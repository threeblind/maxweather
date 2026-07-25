#!/bin/bash
#
# 日次ダイジェスト確認・修復スクリプト (shell entry point)
#
# 使用方法:
#   ./scripts/check_and_repair_daily_summary.sh [--date YYYY-MM-DD] [--dry-run] [--no-push]
#
# AI秘書はこのスクリプトを1回実行するだけで、
# 前日ダイジェストのエラー確認・記事整合性チェック・必要な修正・commit/push・結果報告まで行える。
#
# 戻り値:
#   0 = 全チェック合格 (または警告のみ)
#   1 = 致命的エラーあり
#
# 実行結果は logs/summary_check.log に保存される。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=============================================="
echo "日次ダイジェスト確認・修復"
echo "実行時刻: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# --- Python実行環境 ---
if [[ -d "venv" ]]; then
    source venv/bin/activate
    PYTHON_CMD="python"
else
    PYTHON_CMD="${PYTHON_CMD:-python3}"
fi

echo ""
echo "Python: $("$PYTHON_CMD" --version 2>&1)"

# --- 引数をそのまま Python スクリプトへ渡す ---
"$PYTHON_CMD" scripts/check_and_repair_daily_summary.py "$@"
exit $?
