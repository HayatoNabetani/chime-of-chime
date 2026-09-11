"""argparseベースのCLIエントリーポイント。

  python main.py record          プロファイル作成
  python main.py detect          検知ループ開始
  python main.py test-notify     通知先の疎通確認
  python main.py switchbot-test  SwitchBotの動作確認
"""

import argparse
import sys

from .notifiers import build_notifier_from_env
from .profile import DEFAULT_PROFILE_PATH


def _cmd_record(args: argparse.Namespace) -> int:
    from .recorder import ProfileRecorder

    profile = ProfileRecorder().run(args.output)
    return 0 if profile is not None else 1


def _cmd_detect(args: argparse.Namespace) -> int:
    from .detector import run

    run(args.profile)
    return 0


def _cmd_test_notify(args: argparse.Namespace) -> int:
    notifier = build_notifier_from_env()
    ok = notifier.send_chime(args.message)
    return 0 if ok else 1


def _cmd_serve_actions(args: argparse.Namespace) -> int:
    from .action_server import serve_from_env

    serve_from_env()
    return 0


def _cmd_switchbot_test(args: argparse.Namespace) -> int:
    from .switchbot_tester import execute, interactive

    if args.action is None:
        return interactive()
    return execute(args.action, assume_yes=args.yes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chime-detector",
        description="チャイム音を検知して通知するCLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_record = sub.add_parser("record", help="チャイム音のプロファイルを作成")
    p_record.add_argument(
        "-o",
        "--output",
        default=str(DEFAULT_PROFILE_PATH),
        help=f"プロファイル出力先 (default: {DEFAULT_PROFILE_PATH})",
    )
    p_record.set_defaults(func=_cmd_record)

    p_detect = sub.add_parser("detect", help="検知ループを開始")
    p_detect.add_argument(
        "-p",
        "--profile",
        default=str(DEFAULT_PROFILE_PATH),
        help=f"プロファイルファイル (default: {DEFAULT_PROFILE_PATH})",
    )
    p_detect.set_defaults(func=_cmd_detect)

    p_test = sub.add_parser("test-notify", help="通知先の疎通確認")
    p_test.add_argument(
        "-m",
        "--message",
        default="🔔 テスト通知: チャイム検知システム疎通確認",
        help="送信するメッセージ",
    )
    p_test.set_defaults(func=_cmd_test_notify)

    p_actions = sub.add_parser("serve-actions", help="LINE操作Webhookサーバーを開始")
    p_actions.set_defaults(func=_cmd_serve_actions)

    p_switchbot = sub.add_parser("switchbot-test", help="SwitchBot 2台の動作確認")
    p_switchbot.add_argument(
        "action",
        nargs="?",
        choices=(
            "devices",
            "status",
            "intercom-on",
            "intercom-off",
            "intercom-toggle",
            "unlock",
        ),
        help="省略すると対話メニューを表示",
    )
    p_switchbot.add_argument(
        "--yes",
        action="store_true",
        help="unlockの確認を省略（自動実行用途）",
    )
    p_switchbot.set_defaults(func=_cmd_switchbot_test)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
