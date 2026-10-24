"""SDK-independent checks that accepted pitch commands produce real movement."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from .routine import PerformanceError, Plan


@dataclass(frozen=True)
class Reading:
    timestamp: float
    pitch: float
    mode: int


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
        self.check_at = 2 * plan.period
        self.confirmed = False
        self.last_command = 0.0
        self.last_reading: Reading | None = None

    def update(self, pitch: float, mode: int):
        if not math.isfinite(pitch):
            return
        with self.lock:
            self.reading = Reading(self.clock(), pitch, int(mode))
        self.ready.set()

    def latest(self) -> Reading:
        with self.lock:
            reading = self.reading
        if reading is None or self.clock() - reading.timestamp > 1.0:
            raise PerformanceError("Robot pitch telemetry is missing or stale; routine stopped")
        if reading.mode == 7:
            raise PerformanceError("Robot entered damping mode; routine stopped")
        return reading

    def arm(self):
        self.baseline = self.latest().pitch
        self.commands.clear()
        self.measured.clear()
        self.times.clear()
        self.check_at = 2 * self.plan.period
        self.confirmed = False

    def observe(self, elapsed: float, command: float):
        reading = self.latest()
        if self.baseline is None:
            raise PerformanceError("Pitch monitor was not armed")
        if abs(reading.pitch - self.baseline) > math.radians(3):
            raise PerformanceError("Measured pitch changed by more than 3 degrees; routine stopped")
        self.last_command = command
        self.last_reading = reading
        self.commands.append(command)
        self.measured.append(reading.pitch)
        self.times.append(elapsed)
        while self.times and self.times[0] < elapsed - 2 * self.plan.period:
            self.times.pop(0)
            self.commands.pop(0)
            self.measured.pop(0)
        if elapsed >= self.check_at:
            observed_span = max(self.measured) - min(self.measured)
            minimum_span = max(math.radians(0.05), self.plan.amplitude * 0.5)
            # Allow up to one second of lag at the nominal 10 Hz update rate.
            correlations = [self.correlation(self.commands, self.measured)]
            for lag in range(1, min(10, len(self.commands) // 4) + 1):
                correlations.append(self.correlation(self.commands[:-lag], self.measured[lag:]))
            correlation = max(correlations)
            if observed_span < minimum_span or correlation < 0.3:
                raise PerformanceError(
                    "SDK accepted pitch commands but no sufficient physical pitch response was measured "
                    f"(range {math.degrees(observed_span):.3f} degrees, correlation {correlation:.2f}). "
                    "Check robot mode, firmware compatibility and competing remote/app input."
                )
            self.confirmed = True
            self.check_at = elapsed + self.plan.period / 2

    @staticmethod
    def correlation(commands, measured) -> float:
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
            f"measured={math.degrees(reading.pitch):+.3f}deg mode={reading.mode} "
            f"response={'measured' if self.confirmed else 'awaiting measurement'}"
        )
