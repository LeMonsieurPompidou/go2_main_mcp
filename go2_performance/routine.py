"""A small standing pitch oscillation with timing and clearance limits."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol


class PerformanceError(RuntimeError):
    pass


class SportControl(Protocol):
    def StandUp(self) -> int: ...
    def BalanceStand(self) -> int: ...
    def Euler(self, roll: float, pitch: float, yaw: float) -> int: ...
    def StopMove(self) -> int: ...


@dataclass(frozen=True)
class Plan:
    duration: float = 600.0
    period: float = 4.0
    pitch_deg: float = 1.5
    clearance_cm: float = 10.0

    # A planning allowance for torso points, not a measured collision model.
    BODY_RADIUS_M = 0.75
    CLEARANCE_RESERVE_M = 0.05
    MAX_PITCH_DEG = 2.0
    MAX_DURATION_SECONDS = 600
    SAMPLE_INTERVAL = 0.1
    SETTLE_SECONDS = 5.0

    def __post_init__(self):
        for name in ("duration", "period", "pitch_deg", "clearance_cm"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not 1 <= self.duration <= self.MAX_DURATION_SECONDS:
            raise ValueError("duration must be between 1 and 600 seconds")
        if not 2 <= self.period <= 20:
            raise ValueError("period must be between 2 and 20 seconds")
        if not 0.1 <= self.pitch_deg <= self.MAX_PITCH_DEG:
            raise ValueError("pitch must be between 0.1 and 2 degrees")
        if self.clearance_cm <= self.CLEARANCE_RESERVE_M * 100:
            raise ValueError("clearance must exceed the 5 cm planning reserve")
        if self.amplitude < math.radians(0.1):
            raise ValueError("insufficient clearance for a 0.1 degree nod")

    @property
    def amplitude(self) -> float:
        available = self.clearance_cm / 100 - self.CLEARANCE_RESERVE_M
        # Bound point displacement by 2*r*sin(angle/2), allowing for either sign.
        ratio = max(0.0, min(1.0, available / (2 * self.BODY_RADIUS_M)))
        clearance_angle = 2 * math.asin(ratio)
        return min(math.radians(self.pitch_deg), clearance_angle)

    @property
    def displacement_cm(self) -> float:
        return 200 * self.BODY_RADIUS_M * math.sin(self.amplitude / 2)

    def pitch_at(self, elapsed: float) -> float:
        if elapsed <= 0 or elapsed >= self.duration:
            return 0.0
        fade = min(2.0, self.duration / 2)
        fraction = min(1.0, elapsed / fade, (self.duration - elapsed) / fade)
        envelope = fraction * fraction * (3 - 2 * fraction)
        return self.amplitude * envelope * math.sin(2 * math.pi * elapsed / self.period)

    def summary(self) -> dict:
        return {
            "duration_seconds": self.duration,
            "period_seconds": self.period,
            "maximum_pitch_degrees": round(math.degrees(self.amplitude), 4),
            "measured_clearance_cm": self.clearance_cm,
            "modelled_point_displacement_cm": round(self.displacement_cm, 4),
            "planning_reserve_cm": self.CLEARANCE_RESERVE_M * 100,
            "sample_rate_hz": 1 / self.SAMPLE_INTERVAL,
            "stand_settle_seconds": self.SETTLE_SECONDS,
        }


def require_success(code: int, operation: str) -> None:
    if code != 0:
        raise PerformanceError(f"{operation} failed with SDK code {code}; routine aborted")


def run(
    sport: SportControl,
    plan: Plan,
    cancelled: threading.Event,
    *,
    clock: Callable[[], float] = time.monotonic,
    report: Callable[[str], None] = print,
    feedback=None,
    progress_interval: float = 15.0,
    trace=None,
) -> str:
    """Execute once; never retry a rejected motion or issue locomotion commands.

    Completion and cancellation restore neutral pitch and request StopMove.
    These are best-effort SDK calls, not a hardware emergency stop.
    """
    if cancelled.is_set():
        return "cancelled"

    balancing = False
    failed = False
    try:
        report("Standing up; keep the entire standing transition clear.")
        require_success(sport.StandUp(), "StandUp")
        if cancelled.wait(plan.SETTLE_SECONDS):
            return "cancelled"
        require_success(sport.BalanceStand(), "BalanceStand")
        balancing = True
        if cancelled.is_set():
            return "cancelled"
        require_success(sport.Euler(0.0, 0.0, 0.0), "neutral pose")
        started = clock()
        if feedback is not None:
            feedback.arm(started_at=started)

        progress_at = 0.0
        report("Nodding started. Ctrl+C requests a stop; physical remote controls remain enabled.")
        while not cancelled.is_set():
            elapsed = clock() - started
            if elapsed >= plan.duration:
                if feedback is not None:
                    feedback.finish()
                return "completed"
            if feedback is not None:
                feedback.latest()  # Do not send more motion using stale telemetry.
            pitch = plan.pitch_at(elapsed)
            require_success(sport.Euler(0.0, pitch, 0.0), "pitch update")
            # Unitree's standing-attitude example applies BalanceStand after
            # every Euler setpoint, not just once at startup.
            require_success(sport.BalanceStand(), "apply standing pitch")
            if feedback is not None:
                # Trace even an update that causes the feedback check to abort.
                if trace is not None:
                    reading = feedback.latest()
                    trace(elapsed, clock() - started, pitch, reading)
                feedback.observe(clock() - started, pitch, commanded_at=elapsed)
            # Preserve startup evidence even when validation stops before 15 s.
            interval = min(progress_interval, 1.0) if feedback is not None and not feedback.confirmed else progress_interval
            if elapsed >= progress_at:
                detail = f" | {feedback.status()}" if feedback is not None else ""
                report(f"Performance: {elapsed:.0f}/{plan.duration:.0f} seconds{detail}")
                progress_at = elapsed + interval
            remaining = plan.duration - (clock() - started)
            if remaining > 0:
                cancelled.wait(min(plan.SAMPLE_INTERVAL, remaining))
        return "cancelled"
    except BaseException:
        failed = True
        raise
    finally:
        cleanup_errors = []
        operations = []
        if balancing:
            operations.append(("neutral pose", lambda: sport.Euler(0.0, 0.0, 0.0)))
        operations.append(("StopMove", sport.StopMove))
        for name, operation in operations:
            try:
                require_success(operation(), name)
            except Exception as exc:
                cleanup_errors.append(str(exc))
        if cleanup_errors:
            message = "Cleanup not confirmed: " + "; ".join(cleanup_errors)
            if failed:
                report(message)
            else:
                raise PerformanceError(message)
