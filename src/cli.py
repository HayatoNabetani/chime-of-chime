"""argparseベースのCLIエントリーポイント。

  python main.py record          プロファイル作成
  python main.py detect          検知ループ開始
  python main.py test-notify     通知先の疎通確認
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
    ok = notifier.send(args.message)
    return 0 if ok else 1


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
