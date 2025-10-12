#!/usr/bin/env python3
"""
次の大会に備えてシーズン依存データを初期化するスクリプト。

削除対象:
  - data ディレクトリ内の結果ファイル・記事・ログ類
  - logs 配下のファイル／サブディレクトリ

残すもの:
  - daily_temperatures.json や config/, history_data/ など次大会でも使う基礎データ
"""

import argparse
import sys
from pathlib import Path
from typing import Iterable


DATA_DIR = Path("data")
LOGS_DIR = Path("logs")
DAILY_TEMPS_FILE = DATA_DIR / "daily_temperatures.json"
ARCHIVE_DIR = DATA_DIR / "archive"

DATA_FILES_TO_REMOVE = [
    "ekiden_state.json",
    "individual_results.json",
    "rank_history.json",
    "leg_rank_history.json",
    "runner_locations.json",
    "realtime_report.json",
    "realtime_report_previous.json",
    "daily_summary.json",
    "article_history.json",
    "manager_comments.json",
    "intramural_rankings.json",
    "realtime_log.jsonl",
]

DATA_GLOB_PATTERNS = [
    "realtime_log*.jsonl",
]


def collect_targets() -> list[Path]:
    targets: list[Path] = []

    if DAILY_TEMPS_FILE.exists():
        targets.append(DAILY_TEMPS_FILE)

    if ARCHIVE_DIR.exists():
        targets.append(ARCHIVE_DIR)

    for relative in DATA_FILES_TO_REMOVE:
        candidate = DATA_DIR / relative
        if candidate.exists():
            targets.append(candidate)

    for pattern in DATA_GLOB_PATTERNS:
        for candidate in DATA_DIR.glob(pattern):
            if candidate.exists():
                targets.append(candidate)

    if LOGS_DIR.exists():
        for child in LOGS_DIR.iterdir():
            targets.append(child)

    return sorted(set(targets))


def remove_path(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            remove_path(child)
        try:
            path.rmdir()
        except OSError:
            # 何らかの理由で残っている場合は、そのままにする
            pass
    else:
        path.unlink(missing_ok=True)


def print_targets(targets: Iterable[Path]) -> None:
    print("削除予定のファイル／ディレクトリ一覧:")
    for item in targets:
        if item == DAILY_TEMPS_FILE:
            print(f"  - {item}（内容を \"{{}}\" に初期化）")
            continue
        print(f"  - {item}")
    if not targets:
        print("  （削除対象はありません）")


def main() -> int:
    parser = argparse.ArgumentParser(description="次大会用に data/ と logs/ の成果物を初期化します。")
    parser.add_argument(
        "-y",
        "--yes",
        dest="assume_yes",
        action="store_true",
        help="確認プロンプトをスキップして削除を実行します。",
    )
    args = parser.parse_args()

    targets = collect_targets()
    print_targets(targets)
    print()
    print("注意: daily_temperatures.json や config/ 配下の設定ファイルは変更しません。")
    print("     削除後に `python3.9 scripts/rebuild_history.py` を実行すると初期状態を再生成できます。")

    if not targets:
        return 0

    if not args.assume_yes:
        try:
            answer = input("これらを削除してもよろしいですか？ (y/N): ").strip().lower()
        except EOFError:
            print("\n入力がキャンセルされたため中断しました。")
            return 1
        if answer not in {"y", "yes"}:
            print("削除を中止しました。")
            return 0

    for path in targets:
        if path == DAILY_TEMPS_FILE:
            DAILY_TEMPS_FILE.write_text("{}", encoding="utf-8")
            continue
        remove_path(path)

    if LOGS_DIR.exists():
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

    print("✅ 指定した成果物を削除しました。必要に応じて rebuild_history.py を実行してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
