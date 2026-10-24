"""No robot is needed: virtual time covers timing, clearance, and failure stops."""

import contextlib
import io
import math
import sys
import unittest
from unittest.mock import Mock, patch

from go2_performance.__main__ import main
from go2_performance.routine import PerformanceError, Plan, run
from go2_performance.feedback import PitchFeedback


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

    def test_full_ten_minutes_finish_neutral_without_locomotion(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        updates = []
        sport.Euler.side_effect = lambda *angles: updates.append((timer.now, angles)) or 0
        plan = Plan()
        result = run(sport, plan, timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(result, 'completed')
        self.assertAlmostEqual(timer.now, plan.SETTLE_SECONDS + 600, places=6)
        self.assertEqual(updates[-1][1], (0.0, 0.0, 0.0))
        nonzero = [(at, pitch) for at, (_, pitch, _) in updates if pitch]
        self.assertTrue(any(pitch > 0 for _, pitch in nonzero))
        self.assertTrue(any(pitch < 0 for _, pitch in nonzero))
        self.assertTrue(all(abs(pitch) <= math.radians(1.5) for _, pitch in nonzero))
        self.assertTrue(all(at < plan.SETTLE_SECONDS + 600 for at, _ in nonzero))
        sport.StopMove.assert_called_once()
        sport.Move.assert_not_called()
        sport.SwitchJoystick.assert_not_called()
        calls = sport.mock_calls
        for index, call in enumerate(calls):
            if call[0] == 'Euler' and call.args[1] != 0:
                self.assertEqual(calls[index + 1][0], 'BalanceStand')

    def test_clearance_reduces_amplitude_and_preserves_reserve(self):
        normal = Plan(clearance_cm=10)
        restricted = Plan(clearance_cm=6)
        self.assertLess(restricted.amplitude, normal.amplitude)
        self.assertLessEqual(restricted.displacement_cm + 5, 6 + 1e-9)
        for index in range(60001):
            self.assertLessEqual(abs(restricted.pitch_at(index / 100)), restricted.amplitude)
        self.assertEqual(normal.pitch_at(0), 0)
        self.assertEqual(normal.pitch_at(600), 0)

    def test_invalid_parameters_are_rejected_before_motion(self):
        for parameters in [
            {'clearance_cm': 5}, {'clearance_cm': 5.01},
            {'pitch_deg': 2.1}, {'pitch_deg': 0},
            {'duration': 601}, {'duration': -1}, {'period': 0},
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

    def test_balance_apply_failure_aborts_and_stops(self):
        timer = VirtualTime()
        sport = self.sport(timer)
        sport.BalanceStand.side_effect = [0, -1]
        with self.assertRaisesRegex(PerformanceError, 'apply standing pitch'):
            run(sport, Plan(), timer, clock=timer.clock, report=lambda message: None)
        self.assertEqual(sport.BalanceStand.call_count, 2)
        sport.StopMove.assert_called_once()

    def test_accepted_commands_with_no_measured_motion_abort(self):
        timer = VirtualTime()
        plan = Plan(duration=16)
        feedback = PitchFeedback(plan, clock=timer.clock)
        sport = self.sport(timer)
        sport.Euler.side_effect = lambda *angles: feedback.update(0, 1) or 0
        with self.assertRaisesRegex(PerformanceError, 'no sufficient physical pitch response'):
            run(sport, plan, timer, clock=timer.clock, report=lambda message: None, feedback=feedback)
        self.assertLess(timer.now, 14)
        self.assertEqual(sport.Euler.call_args.args, (0.0, 0.0, 0.0))
        sport.StopMove.assert_called_once()

    def test_measured_response_completes_short_diagnostic(self):
        timer = VirtualTime()
        plan = Plan(duration=16)
        feedback = PitchFeedback(plan, clock=timer.clock)
        sport = self.sport(timer)
        sport.Euler.side_effect = lambda roll, pitch, yaw: feedback.update(pitch * 0.9, 1) or 0
        result = run(sport, plan, timer, clock=timer.clock, report=lambda message: None, feedback=feedback)
        self.assertEqual(result, 'completed')
        self.assertTrue(feedback.confirmed)

    def test_feedback_remains_bounded_over_ten_minutes(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        for index in range(6001):
            timer.now = index / 10
            command = plan.pitch_at(timer.now)
            feedback.update(command * 0.9, 1)
            feedback.observe(timer.now, command)
            self.assertLessEqual(len(feedback.commands), 82)
        feedback.finish()
        self.assertTrue(feedback.confirmed)

    def test_stale_or_damping_telemetry_is_rejected(self):
        timer = VirtualTime()
        feedback = PitchFeedback(Plan(), clock=timer.clock)
        feedback.update(0, 1)
        timer.now = 2
        with self.assertRaisesRegex(PerformanceError, 'stale'):
            feedback.latest()
        feedback.update(0, 7)
        with self.assertRaisesRegex(PerformanceError, 'damping'):
            feedback.latest()

    def test_motion_loss_after_initial_response_is_detected(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        with self.assertRaisesRegex(PerformanceError, 'no sufficient physical pitch response'):
            for index in range(200):
                timer.now = index / 10
                command = plan.pitch_at(timer.now)
                feedback.update(command if timer.now < 9 else 0, 1)
                feedback.observe(timer.now, command)
        self.assertTrue(feedback.confirmed)  # Initial movement was verified first.
        self.assertLess(timer.now, 19)

    def test_unrelated_pitch_variation_is_not_accepted_as_tracking(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        with self.assertRaisesRegex(PerformanceError, 'no sufficient physical pitch response'):
            for index in range(100):
                timer.now = index / 10
                feedback.update(plan.amplitude * (-1 if index % 2 else 1), 1)
                feedback.observe(timer.now, plan.pitch_at(timer.now))

    def test_excessive_measured_pitch_stops_test(self):
        timer = VirtualTime()
        feedback = PitchFeedback(Plan(), clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        feedback.update(math.radians(4), 1)
        with self.assertRaisesRegex(PerformanceError, 'more than 3 degrees'):
            feedback.observe(1, 0)

    def test_offline_diagnostic_is_short_and_does_not_load_sdk(self):
        with patch.dict(sys.modules, {'unitree_sdk2py': None}), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--diagnostic', '--dry-run']), 0)
        self.assertIn('"duration_seconds": 16', output.getvalue())

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
        self.assertIn('"duration_seconds": 600', output.getvalue())


if __name__ == '__main__':
    unittest.main()
