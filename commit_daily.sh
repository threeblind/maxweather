#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# このスクリプトは、高温大学駅伝の一日の結果を状態ファイル(ekiden_state.json)に保存し、
# GitHubリポジトリにプッシュするためのものです。
# cronジョブとして1日1回、深夜に実行されることを想定しています。

# --- 設定 ---
PROJECT_DIR="/Users/t28k2/prj/weather"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$PROJECT_DIR" || { echo "エラー: プロジェクトディレクトリが見つかりません: $PROJECT_DIR"; exit 1; }

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "デイリーコミット処理を開始します..."

# 1. Python仮想環境を有効化
source venv/bin/activate || { echo "エラー: Python仮想環境(venv)の有効化に失敗しました。"; exit 1; }

# 2. 全選手の最終記録を取得・保存 (スクリプトのパスを修正)
echo "scripts/update_all_records.py を実行中..."
python scripts/update_all_records.py

# 3. --commitモードでレポートを生成し、ekiden_state.jsonなどを更新 (スクリプトのパスを修正)
echo "scripts/generate_report.py --commit を実行中..."
python scripts/generate_report.py --commit

# 4. 本日のログファイルをアーカイブ
LOGS_DIR="logs"
DATA_DIR="data"
ARCHIVE_DIR="$DATA_DIR/archive"
mkdir -p "$ARCHIVE_DIR"

SOURCE_LOG_FILE="$DATA_DIR/realtime_log.jsonl"
if [ -f "$SOURCE_LOG_FILE" ]; then
    TODAY=$(date +'%Y-%m-%d')
    DEST_LOG_FILE="$ARCHIVE_DIR/realtime_log_${TODAY}.jsonl"
    echo "'$SOURCE_LOG_FILE' を '$DEST_LOG_FILE' に移動します。"
    git mv "$SOURCE_LOG_FILE" "$DEST_LOG_FILE"
else
    echo "本日のログファイル '$SOURCE_LOG_FILE' は見つかりませんでした。スキップします。"
fi

# 5. 変更されたファイルをステージング (パスを修正)
git add \
  data/ekiden_state.json \
  data/individual_results.json \
  data/rank_history.json \
  data/leg_rank_history.json \
  data/runner_locations.json \
  data/daily_temperatures.json \
  data/intramural_rankings.json

# 6. ステージングされた変更があるか確認し、コミットとプッシュを実行
if ! git diff --cached --quiet; then
    echo "最終結果ファイルまたはログファイルに変更を検出しました。GitHubにプッシュします。"
    git commit -m "Finalize and archive daily data [bot] $(date +'%Y-%m-%d')"

    # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash)
    STASH_RESULT=$(git stash)

    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    if ! git pull --rebase origin main; then
        echo "エラー: git pull --rebase に失敗しました。"
        if [[ "$STASH_RESULT" != "No local changes to save" ]]; then git stash pop; fi
        exit 1
    fi

    echo "GitHubにプッシュしています..."
    git push origin main

    if [[ "$STASH_RESULT" != "No local changes to save" ]]; then git stash pop; fi
else
    echo "コミット対象の変更はありませんでした。"
fi

echo "処理が正常に完了しました。"
echo ""