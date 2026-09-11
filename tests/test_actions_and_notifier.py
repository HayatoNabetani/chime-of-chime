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
        self.assertEqual(actions[0]["data"], "action=intercom_toggle")
        self.assertEqual(actions[1]["data"], "action=unlock")


class ActionControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.switchbot = Mock()
        self.switchbot.toggle.return_value = "ON"
        self.controller = ActionController(
            self.switchbot, "intercom", "unlock", "line-token", "allowed-user"
        )
        self.controller._reply_text = Mock()
        self.controller._reply_unlock_confirmation = Mock()

    def event(self, action: str, event_id: str = "event-1") -> dict:
        return {
            "type": "postback",
            "webhookEventId": event_id,
            "replyToken": "reply",
            "source": {"userId": "allowed-user"},
            "postback": {"data": action},
        }

    def test_intercom_toggles_and_replies(self) -> None:
        self.controller.handle(self.event("action=intercom_toggle"))
        self.switchbot.toggle.assert_called_once_with("intercom")
        self.controller._reply_text.assert_called_once_with(
            "reply", "🎧 インターホン音声をONにしました"
        )

    def test_unlock_requires_confirmation(self) -> None:
        self.controller.handle(self.event("action=unlock"))
        self.switchbot.press.assert_not_called()
        reply_args = self.controller._reply_unlock_confirmation.call_args.args
        self.assertEqual(reply_args[0], "reply")
        self.assertTrue(reply_args[1])

    def test_confirmed_unlock_token_can_only_be_used_once(self) -> None:
        self.controller.handle(self.event("action=unlock", "request"))
        token = self.controller._reply_unlock_confirmation.call_args.args[1]
        confirmed = f"action=unlock_confirmed&token={token}"
        self.controller.handle(self.event(confirmed, "confirmation"))
        self.controller.handle(self.event(confirmed, "second-confirmation"))
        self.switchbot.press.assert_called_once_with("unlock")

    def test_expired_unlock_token_is_rejected(self) -> None:
        self.controller.handle(self.event("action=unlock", "request"))
        token = self.controller._reply_unlock_confirmation.call_args.args[1]
        self.controller._unlock_confirmations[token] = 0
        confirmed = f"action=unlock_confirmed&token={token}"
        self.controller.handle(self.event(confirmed, "confirmation"))
        self.switchbot.press.assert_not_called()
        self.controller._reply_text.assert_called_once()

    def test_confirmation_contains_one_time_token(self) -> None:
        controller = ActionController(
            self.switchbot, "intercom", "unlock", "line-token", "allowed-user"
        )
        controller._reply = Mock()
        controller._reply_unlock_confirmation("reply", "one-time-token")
        messages = controller._reply.call_args.args[1]
        actions = messages[0]["template"]["actions"]
        self.assertEqual(
            actions[0]["data"],
            "action=unlock_confirmed&token=one-time-token",
        )
        self.assertEqual(
            actions[1]["data"], "action=unlock_cancel&token=one-time-token"
        )

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
