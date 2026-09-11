"""Interactive and non-interactive SwitchBot hardware test commands."""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

from .switchbot import SwitchBotClient, SwitchBotError


def _build_from_env(
    *, require_device_ids: bool = True
) -> tuple[SwitchBotClient, str, str]:
    load_dotenv()
    values = {
        "SWITCHBOT_TOKEN": os.getenv("SWITCHBOT_TOKEN"),
        "SWITCHBOT_SECRET": os.getenv("SWITCHBOT_SECRET"),
        "SWITCHBOT_INTERCOM_DEVICE_ID": os.getenv("SWITCHBOT_INTERCOM_DEVICE_ID"),
        "SWITCHBOT_UNLOCK_DEVICE_ID": os.getenv("SWITCHBOT_UNLOCK_DEVICE_ID"),
    }
    required_keys = ["SWITCHBOT_TOKEN", "SWITCHBOT_SECRET"]
    if require_device_ids:
        required_keys.extend(
            ["SWITCHBOT_INTERCOM_DEVICE_ID", "SWITCHBOT_UNLOCK_DEVICE_ID"]
        )
    missing = [key for key in required_keys if not values[key]]
    if missing:
        raise SwitchBotError(f".envの設定が不足しています: {', '.join(missing)}")
    configured = {key: str(value) for key, value in values.items() if value}
    return (
        SwitchBotClient(configured["SWITCHBOT_TOKEN"], configured["SWITCHBOT_SECRET"]),
        configured.get("SWITCHBOT_INTERCOM_DEVICE_ID", ""),
        configured.get("SWITCHBOT_UNLOCK_DEVICE_ID", ""),
    )


def _show_status(client: SwitchBotClient, intercom_id: str, unlock_id: str) -> None:
    for label, device_id in (("インターホン", intercom_id), ("玄関解錠", unlock_id)):
        status = client.status(device_id)
        print(f"\n{label} ({device_id})")
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))


def execute(action: str, *, assume_yes: bool = False) -> int:
    try:
        client, intercom_id, unlock_id = _build_from_env(
            require_device_ids=action != "devices"
        )

        if action == "devices":
            print(
                json.dumps(
                    client.devices(), ensure_ascii=False, indent=2, sort_keys=True
                )
            )
        elif action == "status":
            _show_status(client, intercom_id, unlock_id)
        elif action == "intercom-on":
            client.command(intercom_id, "turnOn")
            print("✅ インターホン用SwitchBotをONにしました")
        elif action == "intercom-off":
            client.command(intercom_id, "turnOff")
            print("✅ インターホン用SwitchBotをOFFにしました")
        elif action == "intercom-toggle":
            state = client.toggle(intercom_id)
            print(f"✅ インターホン用SwitchBotを{state}にしました")
        elif action == "unlock":
            if not assume_yes:
                print("⚠️ 解錠テストは玄関のボタンを実際に押します。")
                if (
                    input("実行する場合は unlock と入力してください: ").strip()
                    != "unlock"
                ):
                    print("キャンセルしました")
                    return 1
            client.press(unlock_id)
            print("✅ 玄関解錠用SwitchBotのボタンを押しました")
        else:
            print(f"❌ 未知の操作です: {action}")
            return 2
        return 0
    except (SwitchBotError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nキャンセルしました")
        elif isinstance(exc, EOFError):
            print("❌ 入力を読み取れませんでした")
        else:
            print(f"❌ {exc}")
        return 1


def interactive() -> int:
    menu = """
SwitchBot 動作確認
  1. SwitchBotアカウントのデバイス一覧を確認
  2. 設定した2台の状態を確認
  3. インターホンをON
  4. インターホンをOFF
  5. インターホンをON/OFF切替
  6. 玄関解錠ボタンを押す（確認あり）
  0. 終了
"""
    choices = {
        "1": "devices",
        "2": "status",
        "3": "intercom-on",
        "4": "intercom-off",
        "5": "intercom-toggle",
        "6": "unlock",
    }
    while True:
        print(menu)
        try:
            choice = input("番号を選択してください: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n終了します")
            return 0
        if choice == "0":
            print("終了します")
            return 0
        action = choices.get(choice)
        if action is None:
            print("❌ 0〜6の番号を入力してください")
            continue
        execute(action)
