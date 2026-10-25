"""No robot is needed: virtual time covers timing, clearance, and failure stops."""

import contextlib
import csv
import io
import math
import sys
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

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
        self.assertLess(timer.now, 20)  # Fade + two periods, then one startup grace period.
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
            self.assertLessEqual(len(feedback.commands), 94)
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
            for index in range(300):
                timer.now = index / 10
                command = plan.pitch_at(timer.now)
                feedback.update(command if timer.now < 12 else 0, 1)
                feedback.observe(timer.now, command)
        self.assertTrue(feedback.confirmed)  # Initial movement was verified first.
        self.assertLess(timer.now, 23)

    def test_unrelated_pitch_variation_is_not_accepted_as_tracking(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        with self.assertRaisesRegex(PerformanceError, 'no sufficient physical pitch response'):
            for index in range(160):
                timer.now = index / 10
                feedback.update(plan.amplitude * (-1 if index % 2 else 1), 1)
                feedback.observe(timer.now, plan.pitch_at(timer.now))

    def test_small_coherent_response_is_not_rejected_for_low_firmware_gain(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        for index in range(170):
            timer.now = index / 10
            feedback.update(math.radians(0.735 / 2) * math.sin(2 * math.pi * timer.now / 4), 1)
            feedback.observe(timer.now, plan.pitch_at(timer.now))
        self.assertTrue(feedback.confirmed)
        self.assertIn('required=0.150deg', feedback.status())

    def test_recorded_robot_response_is_recognized_as_cyclic_motion(self):
        timer = VirtualTime()
        feedback = PitchFeedback(Plan(), clock=timer.clock)
        feedback.update(math.radians(-1.111210), 0)
        feedback.arm()
        fixture = Path(__file__).parent / 'fixtures' / 'pitch_response_small.csv'
        with fixture.open(newline='') as stream:
            for row in csv.DictReader(stream):
                completed = float(row['completed_elapsed_s'])
                timer.now = completed - float(row['telemetry_age_s'])
                feedback.update(math.radians(float(row['measured_pitch_deg'])), int(row['mode']))
                timer.now = completed
                feedback.observe(completed, math.radians(float(row['command_pitch_deg'])),
                                 commanded_at=float(row['command_elapsed_s']))
        feedback.finish()
        self.assertTrue(feedback.confirmed)

    def test_baseline_drift_alone_does_not_verify_motion(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        with self.assertRaises(PerformanceError):
            for index in range(170):
                timer.now = index / 10
                feedback.update(math.radians(timer.now * 0.1), 1)
                feedback.observe(timer.now, plan.pitch_at(timer.now))
        self.assertFalse(feedback.confirmed)

    def test_tiny_periodic_noise_does_not_verify_motion(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        with self.assertRaises(PerformanceError):
            for index in range(170):
                timer.now = index / 10
                feedback.update(plan.pitch_at(timer.now) * 0.01, 1)
                feedback.observe(timer.now, plan.pitch_at(timer.now))

    def test_separated_test_allows_tenfold_command_without_clearance_limiter(self):
        plan = Plan(duration=16, pitch_deg=15, clearance_cm=0, separated_test=True)
        self.assertAlmostEqual(math.degrees(plan.amplitude), 15)
        self.assertFalse(plan.summary()['clearance_limiter_enabled'])
        self.assertIsNone(plan.summary()['measured_clearance_cm'])
        self.assertEqual(plan.measured_pitch_limit_deg, 18)
        with self.assertRaises(ValueError):
            Plan(pitch_deg=15)
        with self.assertRaises(ValueError):
            Plan(pitch_deg=15.1, separated_test=True)
        timer = VirtualTime()
        sport = self.sport(timer)
        feedback = PitchFeedback(plan, clock=timer.clock)
        sport.Euler.side_effect = lambda roll, pitch, yaw: feedback.update(pitch * 0.9, 1) or 0
        self.assertEqual(run(sport, plan, timer, clock=timer.clock, report=lambda message: None,
                             feedback=feedback), 'completed')
        self.assertTrue(feedback.confirmed)
        sport.StopMove.assert_called_once()

    def test_separated_test_stops_excessive_measured_pitch(self):
        timer = VirtualTime()
        feedback = PitchFeedback(Plan(pitch_deg=15, separated_test=True), clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        feedback.update(math.radians(19), 1)
        with self.assertRaisesRegex(PerformanceError, 'more than 18 degrees'):
            feedback.observe(1, 0)

    def test_startup_grace_allows_response_to_settle(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        for index in range(151):
            timer.now = index / 10
            command = plan.pitch_at(timer.now)
            feedback.update(command * (0.1 if timer.now <= 10 else 0.9), 1)
            feedback.observe(timer.now, command)
        self.assertTrue(feedback.confirmed)

    def test_timestamp_alignment_handles_irregular_sdk_cadence_and_lag(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        feedback.update(0, 1)
        feedback.arm()
        index = 0
        while timer.now < 20:
            # The robot applies a previous command, 0.7 s later. Calls take
            # variable amounts of time, so sample-index lags are inaccurate.
            command = plan.pitch_at(timer.now)
            previous = next((value for at, value in reversed(list(zip(feedback.times, feedback.commands)))
                             if at <= timer.now - 0.7), 0)
            feedback.update(previous * 0.9, 1)
            feedback.observe(timer.now, command)
            timer.now += (0.1, 0.35, 0.15, 0.4)[index % 4]
            index += 1
        self.assertTrue(feedback.confirmed)

    def test_trace_retains_failing_update_and_sdk_call_latency(self):
        timer = VirtualTime()
        plan = Plan()
        feedback = PitchFeedback(plan, clock=timer.clock)
        sport = self.sport(timer)
        def update(roll, pitch, yaw):
            timer.wait(0.15)
            feedback.update(0, 1)
            return 0
        sport.Euler.side_effect = update
        rows = []
        with self.assertRaises(PerformanceError):
            run(sport, plan, timer, clock=timer.clock, report=lambda message: None,
                feedback=feedback, trace=lambda *row: rows.append(row))
        self.assertGreater(rows[-1][1], rows[-1][0])
        self.assertGreaterEqual(rows[-1][1], 14)
        sport.StopMove.assert_called_once()

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

    def test_slow_diagnostic_allows_startup_validation_and_fade_out(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--diagnostic', '--period', '20', '--dry-run']), 0)
        self.assertIn('"duration_seconds": 64', output.getvalue())

    def test_separated_diagnostic_preview_preserves_large_amplitude(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--diagnostic', '--separated-test', '--pitch-deg', '15', '--dry-run']), 0)
        self.assertIn('"maximum_pitch_degrees": 15.0', output.getvalue())
        self.assertIn('"clearance_limiter_enabled": false', output.getvalue())
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
