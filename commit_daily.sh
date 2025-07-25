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

# 2. --commitモードでレポートを生成し、ekiden_state.jsonを更新
echo "generate_report.py --commit を実行中..."
python generate_report.py --commit

# 3. 状態ファイルに変更があるか確認し、変更があればPush
if ! git diff --quiet --exit-code ekiden_state.json individual_results.json; then
    echo "状態ファイル (ekiden_state.json, individual_results.json) に変更を検出しました。GitHubにプッシュします。"
    git add ekiden_state.json individual_results.json
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