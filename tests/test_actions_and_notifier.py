import base64
import hashlib
import hmac
import unittest
from unittest.mock import Mock, patch

from src.action_server import ActionController, verify_line_signature
from src.notifiers import LineNotifier


class LineNotifierTest(unittest.TestCase):
    @patch("src.notifiers.requests.post")
    def test_chime_notification_has_two_postback_buttons(self, post: Mock) -> None:
        post.return_value.raise_for_status.return_value = None

        self.assertTrue(LineNotifier("token", "user").send_chime("チャイム"))

        message = post.call_args.kwargs["json"]["messages"][0]
        actions = message["template"]["actions"]
        self.assertEqual(len(actions), 2)
        self.assertEqual(actions[0]["data"], "action=intercom")
        self.assertEqual(actions[1]["data"], "action=unlock")


class ActionControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.switchbot = Mock()
        self.controller = ActionController(
            self.switchbot, "intercom", "unlock", "line-token", "allowed-user"
        )
        self.controller._reply_text = Mock()

    def event(self, action: str, event_id: str = "event-1") -> dict:
        return {
            "type": "postback",
            "webhookEventId": event_id,
            "replyToken": "reply",
            "source": {"userId": "allowed-user"},
            "postback": {"data": action},
        }

    def test_intercom_presses_and_replies(self) -> None:
        self.controller.handle(self.event("action=intercom"))
        self.switchbot.press.assert_called_once_with("intercom")
        self.controller._reply_text.assert_called_once_with(
            "reply", "🎧 インターホン用ボタンを押しました"
        )

    def test_unlock_presses_and_replies(self) -> None:
        self.controller.handle(self.event("action=unlock"))
        self.switchbot.press.assert_called_once_with("unlock")
        self.controller._reply_text.assert_called_once_with(
            "reply", "🔓 玄関の解錠ボタンを押しました"
        )

    def test_duplicate_unlock_event_is_ignored(self) -> None:
        self.controller.handle(self.event("action=unlock", "same-event"))
        self.controller.handle(self.event("action=unlock", "same-event"))
        self.switchbot.press.assert_called_once_with("unlock")

    def test_other_user_is_rejected(self) -> None:
        event = self.event("action=unlock")
        event["source"]["userId"] = "someone-else"
        self.controller.handle(event)
        self.switchbot.press.assert_not_called()

    def test_signature_verification(self) -> None:
        body = b'{"events":[]}'
        signature = base64.b64encode(
            hmac.new(b"secret", body, hashlib.sha256).digest()
        ).decode()
        self.assertTrue(verify_line_signature(body, signature, "secret"))
        self.assertFalse(verify_line_signature(body + b" ", signature, "secret"))


if __name__ == "__main__":
    unittest.main()
