"""Action results must reflect the robot SDK acknowledgement."""

import json
import unittest
from unittest.mock import Mock

from go2_bridge.command_handler import CommandHandler


class ActionResultTests(unittest.TestCase):
    def setUp(self):
        self.robot = Mock()
        self.handler = CommandHandler(self.robot, Mock(), Mock())

    def test_sit_success_requires_zero_sdk_code(self):
        self.robot.execute_action.return_value = 0
        response = json.loads(self.handler._dispatch("action", {"name": "sit"}))
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["code"], 0)
        self.robot.execute_action.assert_called_once_with("Sit", (), {})

    def test_sdk_errors_never_report_executed(self):
        for code in [3102, 3104, 100, None]:
            with self.subTest(code=code):
                self.robot.execute_action.return_value = code
                response = json.loads(self.handler._dispatch("action", {"name": "sit"}))
                self.assertFalse(response["ok"])
                self.assertEqual(response["data"]["code"], code)
                self.assertIn("sit failed", response["msg"])
                self.assertNotIn("executed", response["msg"])

    def test_exception_is_reported_as_failure(self):
        self.robot.execute_action.side_effect = RuntimeError("disconnected")
        response = json.loads(self.handler._dispatch("action", {"name": "sit"}))
        self.assertFalse(response["ok"])
        self.assertIn("disconnected", response["msg"])

    def test_unknown_action_never_calls_robot(self):
        response = json.loads(self.handler._dispatch("action", {"name": "missing"}))
        self.assertFalse(response["ok"])
        self.robot.execute_action.assert_not_called()
