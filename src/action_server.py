"""Receive signed LINE postbacks and operate the two SwitchBot devices."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

import requests
from dotenv import load_dotenv

from .switchbot import SwitchBotClient, SwitchBotError

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"


class ActionController:
    def __init__(
        self,
        switchbot: SwitchBotClient,
        intercom_device_id: str,
        unlock_device_id: str,
        line_access_token: str,
        allowed_user_id: str,
    ) -> None:
        self.switchbot = switchbot
        self.intercom_device_id = intercom_device_id
        self.unlock_device_id = unlock_device_id
        self.line_access_token = line_access_token
        self.allowed_user_id = allowed_user_id
        self._lock = threading.Lock()
        self._seen_ids: deque[str] = deque(maxlen=256)
        self._seen_set: set[str] = set()

    def _mark_once(self, event_id: str) -> bool:
        with self._lock:
            if event_id in self._seen_set:
                return False
            if len(self._seen_ids) == self._seen_ids.maxlen:
                self._seen_set.discard(self._seen_ids[0])
            self._seen_ids.append(event_id)
            self._seen_set.add(event_id)
            return True

    def handle(self, event: dict[str, Any]) -> None:
        if event.get("type") != "postback":
            return
        source = event.get("source")
        if not isinstance(source, dict) or source.get("userId") != self.allowed_user_id:
            print("⚠️ 許可されていないLINEユーザーからの操作を拒否しました")
            return

        postback = event.get("postback")
        if not isinstance(postback, dict) or not isinstance(postback.get("data"), str):
            return
        params = parse_qs(postback["data"], keep_blank_values=True)
        action = params.get("action", [""])[0]
        if action not in {"intercom", "unlock"}:
            return

        event_id = event.get("webhookEventId")
        if not isinstance(event_id, str) or not self._mark_once(event_id):
            return

        reply_token = event.get("replyToken")
        try:
            with self._lock:
                if action == "intercom":
                    self.switchbot.press(self.intercom_device_id)
                    result = "🎧 インターホン用ボタンを押しました"
                elif action == "unlock":
                    self.switchbot.press(self.unlock_device_id)
                    result = "🔓 玄関の解錠ボタンを押しました"
                else:
                    return
            print(f"✅ {result}")
        except SwitchBotError as exc:
            result = f"❌ 操作に失敗しました\n{exc}"
            print(result)

        if isinstance(reply_token, str):
            self._reply_text(reply_token, result)

    def _reply_text(self, reply_token: str, message: str) -> None:
        self._reply(reply_token, [{"type": "text", "text": message}])

    def _reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        try:
            response = requests.post(
                LINE_REPLY_URL,
                headers={
                    "Authorization": f"Bearer {self.line_access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "replyToken": reply_token,
                    "messages": messages,
                },
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"❌ LINE操作結果の返信に失敗しました: {exc}")


def verify_line_signature(body: bytes, signature: str, channel_secret: str) -> bool:
    expected = base64.b64encode(
        hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def make_handler(channel_secret: str, controller: ActionController):
    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            super().setup()
            self.connection.settimeout(10)

        def do_POST(self) -> None:
            if self.path != "/line/webhook":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if length <= 0 or length > 1_000_000:
                self.send_error(400)
                return
            body = self.rfile.read(length)
            signature = self.headers.get("X-Line-Signature", "")
            if not verify_line_signature(body, signature, channel_secret):
                self.send_error(401)
                return
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_error(400)
                return
            if not isinstance(payload, dict) or not isinstance(
                payload.get("events"), list
            ):
                self.send_error(400)
                return

            self.send_response(200)
            self.end_headers()
            for event in payload.get("events", []):
                if isinstance(event, dict):
                    threading.Thread(
                        target=controller.handle, args=(event,), daemon=True
                    ).start()

        def log_message(self, format: str, *args: object) -> None:
            print(f"🌐 LINE webhook: {format % args}")

    return Handler


def build_server_from_env() -> ThreadingHTTPServer | None:
    load_dotenv()
    required = {
        "SWITCHBOT_TOKEN": os.getenv("SWITCHBOT_TOKEN"),
        "SWITCHBOT_SECRET": os.getenv("SWITCHBOT_SECRET"),
        "SWITCHBOT_INTERCOM_DEVICE_ID": os.getenv("SWITCHBOT_INTERCOM_DEVICE_ID"),
        "SWITCHBOT_UNLOCK_DEVICE_ID": os.getenv("SWITCHBOT_UNLOCK_DEVICE_ID"),
        "LINE_CHANNEL_ACCESS_TOKEN": os.getenv("LINE_CHANNEL_ACCESS_TOKEN"),
        "LINE_CHANNEL_SECRET": os.getenv("LINE_CHANNEL_SECRET"),
        "LINE_USER_ID": os.getenv("LINE_USER_ID"),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        print(f"⚠️ 操作サーバーを起動できません。未設定: {', '.join(missing)}")
        return None

    values = {key: str(value) for key, value in required.items()}
    controller = ActionController(
        SwitchBotClient(values["SWITCHBOT_TOKEN"], values["SWITCHBOT_SECRET"]),
        values["SWITCHBOT_INTERCOM_DEVICE_ID"],
        values["SWITCHBOT_UNLOCK_DEVICE_ID"],
        values["LINE_CHANNEL_ACCESS_TOKEN"],
        values["LINE_USER_ID"],
    )
    host = os.getenv("ACTION_SERVER_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("ACTION_SERVER_PORT", "8080"))
    except ValueError as exc:
        raise SystemExit("ACTION_SERVER_PORTには整数を設定してください") from exc
    if not 1 <= port <= 65535:
        raise SystemExit("ACTION_SERVER_PORTは1〜65535で設定してください")
    return ThreadingHTTPServer(
        (host, port), make_handler(values["LINE_CHANNEL_SECRET"], controller)
    )


def serve_from_env() -> None:
    server = build_server_from_env()
    if server is None:
        raise SystemExit(1)
    print(
        f"🎛️ 操作サーバー起動: http://{server.server_address[0]}:{server.server_address[1]}/line/webhook"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 操作サーバーを終了します")
    finally:
        server.server_close()


def start_in_background_from_env() -> ThreadingHTTPServer | None:
    load_dotenv()
    if os.getenv("ACTION_SERVER_ENABLED", "0") != "1":
        return None
    targets = {
        part.strip().lower() for part in os.getenv("NOTIFIER", "console").split(",")
    }
    if "line" not in targets:
        return None
    server = build_server_from_env()
    if server is None:
        raise SystemExit(
            "LINE操作ボタンを有効にする設定が不足しています。"
            "不要な場合はACTION_SERVER_ENABLED=0を設定してください。"
        )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"🎛️ 操作サーバー起動: port={server.server_address[1]} path=/line/webhook")
    return server
