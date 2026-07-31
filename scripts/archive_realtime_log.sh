#!/bin/bash
# realtime_log.jsonl の日次アーカイブ（冪等）
#
# commit_daily.sh から呼ばれる。以下のルールで動作する:
# - 同日アーカイブが無ければ git mv で移動（従来動作）
# - 同日アーカイブが既にあり同内容ならスキップし、ソースを削除して
#   初回実行後の状態（ソース無し・アーカイブ有り）に揃える（冪等）
# - 同日アーカイブが既にあり内容が異なる場合は既存データを無断上書きせず、
#   明示的にエラー終了する
#
# 使い方: scripts/archive_realtime_log.sh [DATA_DIR]
# 戻り値: 0=成功/スキップ, 1=内容不一致により停止
set -euo pipefail

DATA_DIR="${1:-data}"
SOURCE_LOG_FILE="$DATA_DIR/realtime_log.jsonl"
ARCHIVE_DIR="$DATA_DIR/archive"
TODAY=$(date +'%Y-%m-%d')
DEST_LOG_FILE="$ARCHIVE_DIR/realtime_log_${TODAY}.jsonl"

# ソースが無い場合
if [ ! -f "$SOURCE_LOG_FILE" ]; then
    if [ -f "$DEST_LOG_FILE" ]; then
        echo "既にアーカイブ済みです: $DEST_LOG_FILE (ソースは移動済みのためスキップ)"
    else
        echo "本日のログファイル '$SOURCE_LOG_FILE' は見つかりませんでした。スキップします。"
    fi
    exit 0
fi

mkdir -p "$ARCHIVE_DIR"

# 同日アーカイブが既に存在する場合
if [ -f "$DEST_LOG_FILE" ]; then
    if cmp -s "$SOURCE_LOG_FILE" "$DEST_LOG_FILE"; then
        echo "同日アーカイブ '$DEST_LOG_FILE' は既に存在し内容が同一のため、アーカイブをスキップします。"
        # 冪等化: 初回実行後の状態（ソースはアーカイブ済み）に揃えるためソースを削除
        # 追跡済みなら git rm で削除をステージする。staged/未staged の変更があっても
        # cmp で内容同一を確認済みのため -f で強制削除してよい（データ損失なし）
        if git ls-files --error-unmatch -- "$SOURCE_LOG_FILE" >/dev/null 2>&1; then
            git rm -f -q -- "$SOURCE_LOG_FILE"
        else
            rm -f "$SOURCE_LOG_FILE"
        fi
    else
        echo "❌ 同日アーカイブ '$DEST_LOG_FILE' が既に存在し、内容が異なります。"
        echo "   既存データを無断上書きしないため、処理を中止します。"
        exit 1
    fi
    exit 0
fi

# 通常のアーカイブ（移動）
echo "'$SOURCE_LOG_FILE' を '$DEST_LOG_FILE' に移動します。"
git mv "$SOURCE_LOG_FILE" "$DEST_LOG_FILE"
