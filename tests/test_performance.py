"""No robot is needed: virtual time covers timing, clearance, and failure stops."""

import contextlib
import io
import math
import sys
import unittest
from unittest.mock import Mock, patch

from go2_performance.__main__ import main
from go2_performance.routine import PerformanceError, Plan, run


class VirtualTime:
    def __init__(self, cancel_at=None):
        self.now = 0.0
        self.cancel_at = cancel_at
        self.cancelled = False

    def clock(self):
        return self.now

    def is_set(self):
        return self.cancelled

    def wait(self, seconds):
        target = self.now + seconds
        if self.cancel_at is not None and target >= self.cancel_at:
            self.now = self.cancel_at
            self.cancelled = True
        else:
            self.now = target
        return self.cancelled


class PerformanceTests(unittest.TestCase):
    def sport(self, timer):
        client = Mock()
        client.StandUp.return_value = 0
        client.BalanceStand.return_value = 0
        client.StopMove.return_value = 0
        client.Euler.side_effect = lambda *angles: 0
        return client

    def test_full_three_minutes_finish_neutral_without_locomotion(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        updates = []
        sport.Euler.side_effect = lambda *angles: updates.append((timer.now, angles)) or 0
        plan = Plan()
        result = run(sport, plan, timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(result, 'completed')
        self.assertAlmostEqual(timer.now, plan.SETTLE_SECONDS + 180, places=6)
        self.assertEqual(updates[-1][1], (0.0, 0.0, 0.0))
        nonzero = [(at, pitch) for at, (_, pitch, _) in updates if pitch]
        self.assertTrue(any(pitch > 0 for _, pitch in nonzero))
        self.assertTrue(any(pitch < 0 for _, pitch in nonzero))
        self.assertTrue(all(abs(pitch) <= math.radians(1.5) for _, pitch in nonzero))
        self.assertTrue(all(at < plan.SETTLE_SECONDS + 180 for at, _ in nonzero))
        sport.StopMove.assert_called_once()
        sport.Move.assert_not_called()
        sport.SwitchJoystick.assert_not_called()

    def test_clearance_reduces_amplitude_and_preserves_reserve(self):
        normal = Plan(clearance_cm=10)
        restricted = Plan(clearance_cm=6)
        self.assertLess(restricted.amplitude, normal.amplitude)
        self.assertLessEqual(restricted.displacement_cm + 5, 6 + 1e-9)
        for index in range(18001):
            self.assertLessEqual(abs(restricted.pitch_at(index / 100)), restricted.amplitude)
        self.assertEqual(normal.pitch_at(0), 0)
        self.assertEqual(normal.pitch_at(180), 0)

    def test_invalid_parameters_are_rejected_before_motion(self):
        for parameters in [
            {'clearance_cm': 5}, {'clearance_cm': 5.01},
            {'pitch_deg': 2.1}, {'pitch_deg': 0},
            {'duration': 181}, {'duration': -1}, {'period': 0},
            {'clearance_cm': float('nan')}, {'pitch_deg': float('inf')},
        ]:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                Plan(**parameters)

    def test_cancel_mid_performance_restores_neutral_and_stops(self):
        timer = VirtualTime(cancel_at=8)
        sport = self.sport(timer)
        result = run(sport, Plan(), timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(result, 'cancelled')
        self.assertEqual(timer.now, 8)
        self.assertEqual(sport.Euler.call_args.args, (0.0, 0.0, 0.0))
        sport.StopMove.assert_called_once()

    def test_cancel_during_stand_settle_never_starts_pitch(self):
        timer = VirtualTime(cancel_at=2)
        sport = self.sport(timer)
        result = run(sport, Plan(), timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(result, 'cancelled')
        sport.BalanceStand.assert_not_called()
        sport.Euler.assert_not_called()
        sport.StopMove.assert_called_once()

    def test_rejected_pitch_aborts_without_retrying_motion(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        sport.Euler.side_effect = [0, 3104, 0]
        with self.assertRaisesRegex(PerformanceError, '3104'):
            run(sport, Plan(), timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(sport.Euler.call_count, 3)  # readiness, failed update, neutral cleanup
        sport.StopMove.assert_called_once()
        self.assertEqual(timer.now, Plan.SETTLE_SECONDS)

    def test_failed_stand_never_attempts_balance_or_pitch(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        sport.StandUp.return_value = -1
        with self.assertRaises(PerformanceError):
            run(sport, Plan(), timer, clock=timer.clock, report=lambda message: None)
        sport.BalanceStand.assert_not_called()
        sport.Euler.assert_not_called()
        sport.StopMove.assert_called_once()

    def test_cleanup_failure_is_not_reported_as_success(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        sport.StopMove.return_value = 3104
        with self.assertRaisesRegex(PerformanceError, 'Cleanup not confirmed'):
            run(sport, Plan(duration=1), timer, clock=timer.clock, report=lambda message: None)

    def test_offline_preview_does_not_import_sdk(self):
        with patch.dict(sys.modules, {'unitree_sdk2py': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--dry-run', '--clearance-cm', '10']), 0)
        self.assertIn('DRY RUN', output.getvalue())
        self.assertIn('180', output.getvalue())


if __name__ == '__main__':
    unittest.main()
