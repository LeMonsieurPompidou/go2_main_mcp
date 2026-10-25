"""SDK-independent checks that accepted pitch commands produce real movement."""

from __future__ import annotations

import math
from bisect import bisect_right
import threading
import time
from dataclasses import dataclass

from .routine import PerformanceError, Plan


@dataclass(frozen=True)
class Reading:
    timestamp: float
    pitch: float
    mode: int
    error_code: int = 0


class PitchFeedback:
    def __init__(self, plan: Plan, *, clock=time.monotonic):
        self.plan = plan
        self.clock = clock
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.reading: Reading | None = None
        self.baseline: float | None = None
        self.commands: list[float] = []
        self.measured: list[float] = []
        self.times: list[float] = []
        self.measurement_times: list[float] = []
        self.started_at = 0.0
        self.check_at = 2 + 2 * plan.period
        self.startup_deadline = self.check_at + plan.period
        self.confirmed = False
        self.last_check = "awaiting measurement"
        self.last_command = 0.0
        self.last_reading: Reading | None = None

    def update(self, pitch: float, mode: int, error_code: int = 0):
        if not math.isfinite(pitch):
            return
        with self.lock:
            self.reading = Reading(self.clock(), pitch, int(mode), int(error_code))
        self.ready.set()

    def snapshot(self) -> Reading | None:
        with self.lock:
            return self.reading

    def latest(self) -> Reading:
        reading = self.snapshot()
        if reading is None or self.clock() - reading.timestamp > 1.0:
            raise PerformanceError("Robot pitch telemetry is missing or stale; routine stopped")
        if reading.mode == 7:
            raise PerformanceError("Robot entered damping mode; routine stopped")
        if reading.error_code:
            raise PerformanceError(f"Robot telemetry reports error_code={reading.error_code} (0x{reading.error_code:08x}); routine stopped")
        return reading

    def arm(self, *, started_at=None):
        self.baseline = self.latest().pitch
        self.commands.clear()
        self.measured.clear()
        self.times.clear()
        self.measurement_times.clear()
        self.started_at = self.clock() if started_at is None else started_at
        self.check_at = 2 + 2 * self.plan.period
        self.startup_deadline = self.check_at + self.plan.period
        self.confirmed = False
        self.last_check = "awaiting measurement"

    def observe(self, elapsed: float, command: float, *, commanded_at=None):
        reading = self.latest()
        if self.baseline is None:
            raise PerformanceError("Pitch monitor was not armed")
        if abs(reading.pitch - self.baseline) > math.radians(self.plan.measured_pitch_limit_deg):
            raise PerformanceError(f"Measured pitch changed by more than {self.plan.measured_pitch_limit_deg:g} degrees; routine stopped")
        self.last_command = command
        self.last_reading = reading
        self.commands.append(command)
        self.measured.append(reading.pitch)
        self.times.append(elapsed if commanded_at is None else commanded_at)
        self.measurement_times.append(reading.timestamp - self.started_at)
        # Retain an extra second to align delayed measurements with commands.
        while len(self.times) > 1 and self.times[1] < elapsed - 2 * self.plan.period - 1:
            self.times.pop(0)
            self.commands.pop(0)
            self.measured.pop(0)
            self.measurement_times.pop(0)
        if elapsed >= self.check_at:
            # Exclude the two-second startup fade and duplicate DDS readings.
            samples = {}
            for at, measured in zip(self.measurement_times, self.measured):
                if at >= max(2, elapsed - 2 * self.plan.period):
                    samples[at] = measured
            sample_times = sorted(samples)
            values = [samples[at] for at in sample_times]
            observed_span = max(values) - min(values) if values else 0.0
            # Detect actual cyclic movement, without assuming the firmware's
            # command-to-body gain is 1:1. A recorded run had gain about 0.09.
            minimum_span = max(math.radians(0.05), min(math.radians(0.15), self.plan.amplitude * 0.5))
            # SDK calls can block: ten samples need not equal one second.
            # Compare actual command/telemetry timestamps with 0-1 s of lag.
            correlations = []
            for step in range(21):
                aligned_commands, aligned_values, aligned_times = [], [], []
                for at in sample_times:
                    index = bisect_right(self.times, at - step * 0.05) - 1
                    if index >= 0:
                        aligned_commands.append(self.commands[index])
                        aligned_values.append(samples[at])
                        aligned_times.append(at)
                # Settling drift is not evidence of the requested nod cycle.
                commands = self.detrend(aligned_commands, aligned_times)
                measured = self.detrend(aligned_values, aligned_times)
                energy = sum(value * value for value in commands)
                gain = sum(a * b for a, b in zip(commands, measured)) / energy if energy > 1e-12 else 0.0
                span = max(measured) - min(measured) if measured else 0.0
                correlations.append((self.correlation(commands, measured), gain, span))
            correlation, gain, cyclic_span = max(correlations, key=lambda result: result[0])
            fitted_span = 2 * abs(gain) * self.plan.amplitude
            coverage = sample_times[-1] - sample_times[0] if sample_times else 0.0
            sufficient_samples = len(values) >= 6 and coverage >= 1.5 * self.plan.period
            self.last_check = (
                f"range={math.degrees(observed_span):.3f}deg "
                f"required={math.degrees(minimum_span):.3f}deg "
                f"correlation={correlation:.2f} gain={gain:+.3f} "
                f"cyclic_range={math.degrees(fitted_span):.3f}deg samples={len(values)}"
            )
            self.check_at = elapsed + self.plan.period / 2
            if not sufficient_samples or min(cyclic_span, fitted_span) < minimum_span or correlation < 0.6:
                if not self.confirmed and elapsed < self.startup_deadline:
                    self.last_check = "startup check pending: " + self.last_check
                    return
                raise PerformanceError(
                    "SDK accepted pitch commands but no sufficient physical pitch response was measured "
                    f"({self.last_check}). "
                    "Check robot mode, firmware compatibility and competing remote/app input."
                )
            self.confirmed = True

    @staticmethod
    def detrend(values, times):
        if not values:
            return []
        mean_time = sum(times) / len(times)
        mean_value = sum(values) / len(values)
        energy = sum((at - mean_time) ** 2 for at in times)
        slope = sum((at - mean_time) * (value - mean_value) for at, value in zip(times, values)) / energy if energy > 1e-12 else 0.0
        return [value - mean_value - slope * (at - mean_time) for at, value in zip(times, values)]

    @staticmethod
    def correlation(commands, measured) -> float:
        if len(commands) < 2:
            return 0.0
        command_mean = sum(commands) / len(commands)
        measured_mean = sum(measured) / len(measured)
        commands = [value - command_mean for value in commands]
        measured = [value - measured_mean for value in measured]
        denominator = math.sqrt(sum(value * value for value in commands) * sum(value * value for value in measured))
        if denominator < 1e-12:
            return 0.0
        return abs(sum(a * b for a, b in zip(commands, measured)) / denominator)

    def finish(self):
        if not self.confirmed:
            raise PerformanceError("Test ended before physical pitch response could be verified")

    def status(self) -> str:
        reading = self.last_reading or self.latest()
        return (
            f"command={math.degrees(self.last_command):+.3f}deg "
            f"measured={math.degrees(reading.pitch):+.3f}deg mode={reading.mode} error_code={reading.error_code} "
            f"response={'measured' if self.confirmed else 'unconfirmed'} {self.last_check}"
        )
