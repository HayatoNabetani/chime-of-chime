import base64
import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch

from src.switchbot import SwitchBotClient, SwitchBotError


class SwitchBotClientTest(unittest.TestCase):
    @patch("src.switchbot.uuid.uuid4", return_value="nonce")
    @patch("src.switchbot.time.time", return_value=1.234)
    def test_headers_are_signed_for_v11(self, _time: Mock, _uuid: Mock) -> None:
        headers = SwitchBotClient("token", "secret")._headers()
        expected = base64.b64encode(
            hmac.new(b"secret", b"token1234nonce", hashlib.sha256).digest()
        ).decode()
        self.assertEqual(headers["t"], "1234")
        self.assertEqual(headers["nonce"], "nonce")
        self.assertEqual(headers["sign"], expected)

    @patch("src.switchbot.requests.request")
    def test_get_devices(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "statusCode": 100,
            "body": {"deviceList": [{"deviceId": "abc", "deviceName": "Bot"}]},
        }
        request.return_value = response

        result = SwitchBotClient("token", "secret").devices()

        self.assertEqual(result["deviceList"][0]["deviceId"], "abc")
        self.assertTrue(request.call_args.args[1].endswith("/devices"))

    @patch("src.switchbot.requests.request")
    def test_press_sends_press_command(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"statusCode": 100, "message": "success"}
        request.return_value = response

        SwitchBotClient("token", "secret").press("device/id")

        self.assertIn("device%2Fid", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["json"]["command"], "press")

    @patch("src.switchbot.requests.request")
    def test_api_error_raises(self, request: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"statusCode": 190, "message": "system error"}
        request.return_value = response
        with self.assertRaises(SwitchBotError):
            SwitchBotClient("token", "secret").press("device")


if __name__ == "__main__":
    unittest.main()
