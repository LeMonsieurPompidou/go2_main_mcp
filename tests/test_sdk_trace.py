"""Request/reply recording tests; no DDS participant or robot is created."""

import io
import json
import math
import unittest

from go2_performance.feedback import PitchFeedback
from go2_performance.routine import Plan
from go2_performance.sdk_trace import jsonl_recorder, recorded_client


class SdkTraceTests(unittest.TestCase):
    def test_failure_response_and_robot_flags_are_preserved(self):
        class Client:
            def _Call(self, api_id, parameter):
                return 401001, '{"detail":"robot refused"}'
        feedback = PitchFeedback(Plan())
        feedback.update(math.radians(-8.7), 0, 16)
        stream = io.StringIO()
        client = recorded_client(Client, jsonl_recorder(stream), feedback)
        result = client._Call(1007, '{"x":0,"y":-0.26,"z":0}')
        self.assertEqual(result, (401001, '{"detail":"robot refused"}'))
        event = json.loads(stream.getvalue())
        self.assertEqual(event['api_id'], 1007)
        self.assertEqual(event['code'], 401001)
        self.assertEqual(event['robot']['error_code'], 16)
        self.assertAlmostEqual(event['robot']['pitch_deg'], -8.7)
        self.assertGreaterEqual(event['duration_s'], 0)

    def test_transport_exception_is_recorded_and_not_retried(self):
        calls = []
        class Client:
            def _Call(self, api_id, parameter):
                calls.append(api_id)
                raise RuntimeError('connection lost')
        events = []
        client = recorded_client(Client, events.append, PitchFeedback(Plan()))
        with self.assertRaisesRegex(RuntimeError, 'connection lost'):
            client._Call(1007, '{}')
        self.assertEqual(calls, [1007])
        self.assertIn('connection lost', events[0]['exception'])

    def test_installed_sdk_euler_serialization_through_recording_hook(self):
        try:
            from unitree_sdk2py.go2.sport.sport_client import SportClient
        except ImportError:
            self.skipTest('Unitree SDK is only installed in the WSL runtime')
        class OfflineClient(SportClient):
            def __init__(self):
                pass  # Bypass DDS construction; inherit the real Euler wrapper.

            def _Call(self, api_id, parameter):
                return 0, 'accepted'
        events = []
        client = recorded_client(OfflineClient, events.append, PitchFeedback(Plan()))
        self.assertEqual(client.Euler(0, math.radians(6), 0), 0)
        self.assertEqual(events[0]['api_id'], 1007)
        self.assertAlmostEqual(json.loads(events[0]['request'])['y'], math.radians(6))
        self.assertEqual(events[0]['response'], 'accepted')


if __name__ == '__main__':
    unittest.main()
