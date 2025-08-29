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
source venv/bin/activate

# 2. 日次サマリー生成スクリプトを実行
echo "generate_daily_summary.py を実行中..."
python3.9 generate_daily_summary.py

# 3. daily_summary.json に変更があったか確認し、変更があればPush
if ! git diff --quiet --exit-code daily_summary.json; then
    echo "daily_summary.json に変更を検出しました。GitHubにプッシュします。"
    
    git add daily_summary.json
    
    COMMIT_MSG="Generate daily summary article [bot] $(date +'%Y-%m-%d')"
    echo "コミットを実行します: $COMMIT_MSG"
    git commit -m "$COMMIT_MSG"

    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    git pull --rebase origin main

    echo "GitHubにプッシュしています (git push)..."
    git push origin main
else
    echo "daily_summary.json に変更はありませんでした。コミットをスキップします。"
fi

echo "処理が正常に完了しました。"
echo ""