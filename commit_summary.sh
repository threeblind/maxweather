#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# このスクリプトは、高温大学駅伝の1日の総括記事を生成し、
# GitHubリポジトリにプッシュするためのものです。
# cronジョブとして1日1回、0時5分に実行されることを想定しています。

# --- 設定 ---
PROJECT_DIR="/Users/t28k2/prj/weather"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$PROJECT_DIR" || { echo "エラー: プロジェクトディレクトリが見つかりません: $PROJECT_DIR"; exit 1; }

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "日次サマリー記事の生成とコミット処理を開始します..."

# 1. Python仮想環境を有効化
source venv/bin/activate || { echo "エラー: Python仮想環境(venv)の有効化に失敗しました。"; exit 1; }

# 2. 日次サマリー生成スクリプトを実行 (パスを修正)
echo "generate_daily_summary.py を実行中..."
python scripts/generate_daily_summary.py

# 3. daily_summary.json に変更があったか確認し、変更があればPush (パスを修正)
SUMMARY_FILE="data/daily_summary.json"
if ! git diff --quiet --exit-code "$SUMMARY_FILE"; then
    echo "$SUMMARY_FILE に変更を検出しました。GitHubにプッシュします。"
    
    git add "$SUMMARY_FILE"
    
    COMMIT_MSG="Generate daily summary article [bot] $(date +'%Y-%m-%d')"
    echo "コミットを実行します: $COMMIT_MSG"
    git commit -m "$COMMIT_MSG"

    # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash)
    STASH_RESULT=$(git stash)

    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    if ! git pull --rebase origin main; then
        echo "エラー: git pull --rebase に失敗しました。"
        if [[ "$STASH_RESULT" != "No local changes to save" ]]; then git stash pop; fi
        exit 1
    fi

    echo "GitHubにプッシュしています (git push)..."
    git push origin main

    # 退避していた変更を元に戻す
    if [[ "$STASH_RESULT" != "No local changes to save" ]]; then git stash pop; fi
else
    echo "$SUMMARY_FILE に変更はありませんでした。コミットをスキップします。"
fi

echo "処理が正常に完了しました。"
echo ""