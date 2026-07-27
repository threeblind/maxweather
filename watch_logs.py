#!/usr/bin/env python3
"""
高温大学駅伝 ログ監視スクリプト (Log Watchdog)

logs/*.log を監視し、新規発生したエラーを検出して報告する。
cron で定期実行し、no_agent=True で stdout がそのまま Slack に配信される想定。
エラーがなければ何も出力しない（サイレント）。
"""

import json
import os
import re
import sys
from datetime import datetime

# CWD がプロジェクトルート (workdir) であることを前提とする
PROJECT_DIR = os.getcwd()
LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
STATE_FILE = os.path.join(PROJECT_DIR, ".watchdog_state.json")

# エラー検出パターン（1行に1つでも該当すればエラーとする）
ERROR_PATTERNS = [
    re.compile(r'エラー'),
    re.compile(r'Traceback \(most recent call last\)'),
    re.compile(r'fatal:\s'),
    re.compile(r'失敗'),
    re.compile(r'❌'),
    re.compile(r'UnboundLocalError'),
    re.compile(r'FileNotFoundError'),
    re.compile(r'PermissionError'),
    re.compile(r'ConnectionError'),
    re.compile(r'TimeoutError'),
    re.compile(r'Exception\b'),
    re.compile(r'exit code \d+'),
]

# エラーとして扱わないパターン（ホワイトリスト）
IGNORE_PATTERNS = [
    re.compile(r'処理が正常に完了'),
    re.compile(r'エラーは発生して'),
    re.compile(r'エラーが発生しました \(0 件\)'),
    re.compile(r'エラーはありません'),
    re.compile(r'スキップ'),
    re.compile(r'一部ソースでエラーが発生しました'),
    re.compile(r'は正常に終了'),
]


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_error_line(line: str) -> bool:
    """1行がエラー行かどうかを判定する。IGNORE_PATTERNS に合致するものは除外。"""
    for ip in IGNORE_PATTERNS:
        if ip.search(line):
            return False
    for ep in ERROR_PATTERNS:
        if ep.search(line):
            return True
    return False


def scan_log(filepath: str, last_size: int):
    """
    ファイルの last_size 以降からエラー行を抽出する。
    戻り値: (new_file_size, [error_lines])
    ファイルが truncate されていた場合は最初から読み直す。
    """
    if not os.path.exists(filepath):
        return 0, []

    current_size = os.path.getsize(filepath)

    # ファイルが小さくなっている = ローテート/truncate → 先頭から再スキャン
    if current_size < last_size:
        last_size = 0

    if current_size == last_size:
        return current_size, []  # 新規データなし

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            f.seek(last_size)
            content = f.read()
    except Exception as exc:
        return current_size, [f"[watchdog] ファイル読み込みエラー: {exc}"]

    errors = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and is_error_line(stripped):
            errors.append(stripped)

    return current_size, errors


# 初回実行時などの出力制限
MAX_ERRORS_PER_FILE = 5       # 1ファイルあたり最大表示数
MAX_TOTAL_LINES = 40          # 全体の最大行数（超過は「...他N件省略」）


def format_report(errors_by_file: dict) -> str:
    """エラー報告メッセージを整形する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_errors = sum(len(v) for v in errors_by_file.values())
    lines = [f"🚨 ログにエラーを検出しました ({now})"]
    lines.append(f"合計 {total_errors} 件")
    lines.append("=" * 60)
    line_count = 0

    for fname, errs in errors_by_file.items():
        if line_count >= MAX_TOTAL_LINES:
            remaining = total_errors - sum(
                len(v) for fn, v in errors_by_file.items()
                if list(errors_by_file.keys()).index(fn) < list(errors_by_file.keys()).index(fname)
            )
            lines.append(f"\n... 他 {remaining} 件のエラー（打ち切り）")
            break

        display = errs[-MAX_ERRORS_PER_FILE:]
        hidden = len(errs) - len(display)
        label = f"\n📄 {fname}"
        if hidden > 0:
            label += f"（最新{len(display)}件 / 計{len(errs)}件）"
        else:
            label += f"（{len(errs)} 件）"
        lines.append(label)

        for err in display:
            if line_count >= MAX_TOTAL_LINES:
                break
            trimmed = err[:300]
            lines.append(f"  ❌ {trimmed}")
            line_count += 1

    lines.append("\n" + "-" * 60)
    lines.append("📌 最終確認: watchdog 自動検出")
    return "\n".join(lines)


def main():
    state = load_state()
    errors_by_file: dict[str, list[str]] = {}

    if not os.path.isdir(LOGS_DIR):
        print(f"[watchdog] logs/ ディレクトリが見つかりません: {LOGS_DIR}", file=sys.stderr)
        sys.exit(0)

    for fname in sorted(os.listdir(LOGS_DIR)):
        if not fname.endswith(".log"):
            continue
        fpath = os.path.join(LOGS_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        last_size = state.get(fname, 0)
        new_size, errors = scan_log(fpath, last_size)
        state[fname] = new_size

        if errors:
            errors_by_file[fname] = errors

    save_state(state)

    if not errors_by_file:
        return  # エラーなし → サイレント終了（何も配信されない）

    # 標準出力に出せば cron が Slack に配信する
    print(format_report(errors_by_file))


if __name__ == "__main__":
    main()
