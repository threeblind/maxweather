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

# 4. 状態ファイルに変更があるか確認し、変更があればPush
#    daily_temperatures.json と intramural_rankings.json をコミット対象に追加
if ! git diff --quiet --exit-code ekiden_state.json individual_results.json rank_history.json leg_rank_history.json runner_locations.json daily_temperatures.json intramural_rankings.json; then
    echo "状態ファイル (ekiden_state.json, etc.) に変更を検出しました。GitHubにプッシュします。"
    git add ekiden_state.json individual_results.json rank_history.json leg_rank_history.json runner_locations.json daily_temperatures.json intramural_rankings.json
    git commit -m "Update daily state [bot] $(date +'%Y-%m-%d')"

    # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash)
    STASH_RESULT=$(git stash)

    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    git pull --rebase origin main

    echo "GitHubにプッシュしています..."
    git push origin main

    # 退避していた変更を元に戻す
    if [[ "$STASH_RESULT" != "No local changes to save" ]]; then
        git stash pop
    fi
else
    echo "状態ファイルに変更はありませんでした。コミットをスキップします。"
fi

echo "処理が正常に完了しました。"
echo ""