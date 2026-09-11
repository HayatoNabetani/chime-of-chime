"""SwitchBot OpenAPI v1.1 client."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests


class SwitchBotError(RuntimeError):
    """SwitchBot API request failed."""


@dataclass(frozen=True)
class SwitchBotClient:
    token: str
    secret: str
    base_url: str = "https://api.switch-bot.com/v1.1"
    timeout: float = 5.0

    def _headers(self) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        value = f"{self.token}{timestamp}{nonce}".encode()
        signature = base64.b64encode(
            hmac.new(self.secret.encode(), value, hashlib.sha256).digest()
        ).decode()
        return {
            "Authorization": self.token,
            "Content-Type": "application/json; charset=utf8",
            "sign": signature,
            "t": timestamp,
            "nonce": nonce,
        }

    def _request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SwitchBotError(f"SwitchBot APIへの接続に失敗しました: {exc}") from exc

        if not isinstance(data, dict):
            raise SwitchBotError("SwitchBot APIから不正なレスポンスを受信しました")
        if data.get("statusCode") != 100:
            raise SwitchBotError(
                f"SwitchBot APIエラー: {data.get('statusCode')} {data.get('message', '')}"
            )
        return data

    def command(self, device_id: str, command: str) -> None:
        device = quote(device_id, safe="")
        self._request(
            "POST",
            f"/devices/{device}/commands",
            payload={
                "command": command,
                "parameter": "default",
                "commandType": "command",
            },
        )

    def devices(self) -> dict[str, Any]:
        """Return the devices registered to the SwitchBot account."""
        body = self._request("GET", "/devices").get("body")
        if not isinstance(body, dict):
            raise SwitchBotError("SwitchBotのデバイス一覧を取得できませんでした")
        return body

    def status(self, device_id: str) -> dict[str, Any]:
        """Return the device status body."""
        device = quote(device_id, safe="")
        body = self._request("GET", f"/devices/{device}/status").get("body")
        if not isinstance(body, dict):
            raise SwitchBotError("SwitchBotのデバイス状態を取得できませんでした")
        return body

    def press(self, device_id: str) -> None:
        self.command(device_id, "press")
