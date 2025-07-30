#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# --- 設定 ---
PROJECT_DIR="/Users/t28k2/prj/weather"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$(dirname "$0")"

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "監督談話室のコメント更新を開始します..."

# Pythonスクリプトを実行して manager_comments.json を更新
python3.9 fetch_manager_comments.py

# manager_comments.json に変更があったかを確認
if git status --porcelain | grep -q "manager_comments.json"; then
    echo "manager_comments.json に変更を検出しました。コミットしてプッシュします。"

    # 変更をステージング
    git add manager_comments.json

    # コミットメッセージを作成
    COMMIT_MESSAGE="[Auto] Update manager comments - $(date '+%Y-%m-%d %H:%M:%S')"
    git commit -m "$COMMIT_MESSAGE"

    # 他の未コミットの変更があった場合に備えて一時的に退避
    STASH_RESULT=$(git stash)

    # リモートの変更を取り込んでからプッシュ (non-fast-forwardエラー対策)
    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    git pull --rebase origin main

    echo "GitHubにプッシュしています..."
    git push origin main

    # 退避していた変更を元に戻す
    if [[ "$STASH_RESULT" != "No local changes to save" ]]; then
        git stash pop
    fi

    echo "プッシュが完了しました。"
else
    echo "manager_comments.json に変更はありませんでした。"
fi
