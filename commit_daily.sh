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
source venv/bin/activate

# 2. 全選手の最終記録を取得・保存
echo "update_all_records.py を実行中..."
python update_all_records.py

# 3. --commitモードでレポートを生成し、ekiden_state.jsonを更新
#    このスクリプトは update_all_records.py が生成した daily_temperatures.json を参照します。
echo "generate_report.py --commit を実行中..."
python generate_report.py --commit

# 4. dataディレクトリを作成し、本日のログファイルを移動
DATA_DIR="data"
mkdir -p "$DATA_DIR"

SOURCE_LOG_FILE="realtime_log.jsonl"
if [ -f "$SOURCE_LOG_FILE" ]; then
    TODAY=$(date +'%Y-%m-%d')
    DEST_LOG_FILE="$DATA_DIR/realtime_log_${TODAY}.jsonl"
    echo "'$SOURCE_LOG_FILE' を '$DEST_LOG_FILE' に移動します。"
    git mv "$SOURCE_LOG_FILE" "$DEST_LOG_FILE"
else
    echo "本日のログファイル '$SOURCE_LOG_FILE' は見つかりませんでした。スキップします。"
fi

# 5. 変更されたファイルをステージング
#    daily_temperatures.json と intramural_rankings.json をコミット対象に追加
#    (git mv で移動したログファイルは既にステージングされている)
git add ekiden_state.json individual_results.json rank_history.json leg_rank_history.json runner_locations.json daily_temperatures.json intramural_rankings.json

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