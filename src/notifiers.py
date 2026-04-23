"""通知先を差し替え可能にするためのNotifier抽象。

環境変数 NOTIFIER で通知先を選ぶ。カンマ区切りで複数指定可能。
  NOTIFIER=line
  NOTIFIER=slack
  NOTIFIER=console
  NOTIFIER=line,slack
"""

import os
from abc import ABC, abstractmethod
from typing import Iterable

import requests
from dotenv import load_dotenv


class Notifier(ABC):
    """通知先の共通インターフェース。"""

    @abstractmethod
    def send(self, message: str) -> bool:
        """メッセージを送信。成功ならTrueを返す。"""


class ConsoleNotifier(Notifier):
    """標準出力に出すだけ。開発/デバッグ用。"""

    def send(self, message: str) -> bool:
        print(f"📣 [console] {message}")
        return True


class LineNotifier(Notifier):
    """LINE Messaging API (push message)."""

    API_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(self, access_token: str, user_id: str) -> None:
        self.access_token = access_token
        self.user_id = user_id

    def send(self, message: str) -> bool:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        payload = {
            "to": self.user_id,
            "messages": [{"type": "text", "text": message}],
        }
        try:
            res = requests.post(self.API_URL, headers=headers, json=payload, timeout=5)
            res.raise_for_status()
            print(f"✅ LINE送信成功: {message}")
            return True
        except requests.RequestException as err:
            print(f"❌ LINE送信失敗: {err}")
            return False


class SlackNotifier(Notifier):
    """Slack Incoming Webhook。

    Slackのアプリ設定で Incoming Webhooks を有効化し、チャンネルごとに発行される
    Webhook URL (https://hooks.slack.com/services/...) を SLACK_WEBHOOK_URL に設定する。
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    def send(self, message: str) -> bool:
        try:
            res = requests.post(
                self.webhook_url, json={"text": message}, timeout=5
            )
            res.raise_for_status()
            print(f"✅ Slack送信成功: {message}")
            return True
        except requests.RequestException as err:
            print(f"❌ Slack送信失敗: {err}")
            return False


class MultiNotifier(Notifier):
    """複数のNotifierにブロードキャスト。1つでも成功すればTrue。"""

    def __init__(self, notifiers: Iterable[Notifier]) -> None:
        self.notifiers = list(notifiers)

    def send(self, message: str) -> bool:
        results = [n.send(message) for n in self.notifiers]
        return any(results)


def _build_single(target: str) -> Notifier | None:
    if target == "console":
        return ConsoleNotifier()
    if target == "line":
        token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        user_id = os.getenv("LINE_USER_ID")
        if not token or not user_id:
            print("⚠️ LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が未設定のためLINEを無効化")
            return None
        return LineNotifier(token, user_id)
    if target == "slack":
        url = os.getenv("SLACK_WEBHOOK_URL")
        if not url:
            print("⚠️ SLACK_WEBHOOK_URL が未設定のためSlackを無効化")
            return None
        return SlackNotifier(url)
    print(f"⚠️ 未知の通知先: {target}")
    return None


def build_notifier_from_env() -> Notifier:
    """環境変数 NOTIFIER から実体を構築する。

    未設定または無効な場合はConsoleNotifierにフォールバック。
    """
    load_dotenv()
    raw = os.getenv("NOTIFIER", "console")
    targets = [t.strip().lower() for t in raw.split(",") if t.strip()]
    notifiers = [n for n in (_build_single(t) for t in targets) if n is not None]

    if not notifiers:
        print("⚠️ 有効な通知先がないためConsoleNotifierを使用します")
        return ConsoleNotifier()

    labels = ",".join(type(n).__name__ for n in notifiers)
    print(f"📮 通知先: {labels}")

    if len(notifiers) == 1:
        return notifiers[0]
    return MultiNotifier(notifiers)
