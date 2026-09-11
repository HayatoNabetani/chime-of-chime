import unittest
from unittest.mock import Mock, patch

from src.switchbot_tester import execute


class SwitchBotTesterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.devices = (self.client, "intercom-id", "unlock-id")

    @patch("src.switchbot_tester._build_from_env")
    def test_intercom_on(self, build: Mock) -> None:
        build.return_value = self.devices
        self.assertEqual(execute("intercom-on"), 0)
        self.client.command.assert_called_once_with("intercom-id", "turnOn")
        build.assert_called_once_with(require_device_ids=True)

    @patch("src.switchbot_tester._build_from_env")
    def test_devices_only_requires_credentials(self, build: Mock) -> None:
        build.return_value = (self.client, "", "")
        self.client.devices.return_value = {"deviceList": []}
        self.assertEqual(execute("devices"), 0)
        self.client.devices.assert_called_once_with()
        build.assert_called_once_with(require_device_ids=False)

    @patch("builtins.input", return_value="cancel")
    @patch("src.switchbot_tester._build_from_env")
    def test_unlock_can_be_cancelled(self, build: Mock, _input: Mock) -> None:
        build.return_value = self.devices
        self.assertEqual(execute("unlock"), 1)
        self.client.press.assert_not_called()

    @patch("src.switchbot_tester._build_from_env")
    def test_unlock_yes_presses_device(self, build: Mock) -> None:
        build.return_value = self.devices
        self.assertEqual(execute("unlock", assume_yes=True), 0)
        self.client.press.assert_called_once_with("unlock-id")


if __name__ == "__main__":
    unittest.main()
