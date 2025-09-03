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
echo "generate_daily_summary_bymoment.py を実行中..."
python scripts/generate_daily_summary_bymoment.py

# 3. daily_summary.json に変更があったか確認し、変更があればPush
SUMMARY_FILE="data/daily_summary.json"

# git diffの代わりに、より確実なファイルのハッシュ値を比較する方法で変更を検知します。

# HEAD（最新のコミット）にあるファイル内容のハッシュ値を取得
HASH_BEFORE=""
# git cat-fileはファイルが存在しないとエラーになるため、事前に存在確認
if git cat-file -e HEAD:"$SUMMARY_FILE" 2>/dev/null; then
    HASH_BEFORE=$(git cat-file -p HEAD:"$SUMMARY_FILE" | shasum | awk '{print $1}')
fi

# 現在のワーキングツリーにあるファイル内容のハッシュ値を取得
HASH_AFTER=$(shasum < "$SUMMARY_FILE" | awk '{print $1}')

# ハッシュ値が異なる場合、ファイル内容に変更があったと判断
if [ "$HASH_BEFORE" != "$HASH_AFTER" ]; then
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