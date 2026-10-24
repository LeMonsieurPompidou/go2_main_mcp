"""Bridge failure regressions. Run with python -m unittest discover -s tests."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import zmq
from fastapi.testclient import TestClient

from go2_webapp import __main__ as webapp


class CommandApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(webapp.app)

    def test_bridge_timeout_is_json_and_next_request_can_recover(self):
        success = {"ok": True, "msg": "ok", "data": {"speed_level": 1}}
        with patch.object(webapp, "bridge_command", new_callable=AsyncMock) as command:
            command.side_effect = [zmq.Again(), success]
            response = self.client.post("/api/command", json={"cmd": "status"})
            self.assertEqual(response.status_code, 504)
            self.assertFalse(response.json()["ok"])
            self.assertIn("GO2_BRIDGE_HOST", response.json()["msg"])
            response = self.client.post("/api/command", json={"cmd": "status"})
            self.assertEqual(response.json(), success)

    def test_bridge_transport_and_response_errors_are_json(self):
        for error, status in [(zmq.ZMQError(), 503), (ValueError(), 502)]:
            with self.subTest(status=status), patch.object(webapp, "bridge_command", new_callable=AsyncMock) as command:
                command.side_effect = error
                response = self.client.post("/api/command", json={"cmd": "status"})
                self.assertEqual(response.status_code, status)
                self.assertFalse(response.json()["ok"])

    def test_invalid_request_never_reaches_bridge(self):
        with patch.object(webapp, "bridge_command", new_callable=AsyncMock) as command:
            for body in [[], {}, {"cmd": 1}, {"cmd": " "}, {"cmd": "status", "params": []}]:
                response = self.client.post("/api/command", json=body)
                self.assertEqual(response.status_code, 400)
            response = self.client.post("/api/command", content="{invalid")
            self.assertEqual(response.status_code, 400)
            command.assert_not_awaited()


class BridgeSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_socket_is_discarded_on_success_error_and_cancellation(self):
        cases = [b'{"ok":true,"msg":"ok"}', zmq.Again(), asyncio.CancelledError(), b'not json', b'[]', b'{"ok":true}']
        for outcome in cases:
            with self.subTest(outcome=repr(outcome)):
                sock = MagicMock()
                sock.send = AsyncMock()
                sock.recv = AsyncMock()
                if isinstance(outcome, BaseException):
                    sock.recv.side_effect = outcome
                else:
                    sock.recv.return_value = outcome
                ctx = MagicMock()
                ctx.socket.return_value = sock
                with patch.object(webapp, "get_zmq_ctx", return_value=ctx):
                    if isinstance(outcome, BaseException):
                        with self.assertRaises(type(outcome)):
                            await webapp.bridge_command("status")
                    elif outcome == cases[0]:
                        self.assertTrue((await webapp.bridge_command("status"))["ok"])
                    else:
                        with self.assertRaises(ValueError):
                            await webapp.bridge_command("status")
                sock.close.assert_called_once_with(linger=0)
                sock.setsockopt.assert_any_call(zmq.LINGER, 0)
                sock.setsockopt.assert_any_call(zmq.SNDTIMEO, 5000)


if __name__ == "__main__":
    unittest.main()
