#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# --- 設定 ---
# Pythonの実行可能ファイルへのフルパスを指定します。
# `which python3.9` コマンドで確認したパスに置き換えてください。
PYTHON_CMD="/Users/t28k2/prj/weather/venv/bin/python"
GIT_BRANCH="main"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$(dirname "$0")"

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "監督談話室のコメント更新を開始します..."

# 1. Pythonスクリプトを実行して manager_comments.json を更新
${PYTHON_CMD} fetch_manager_comments.py

# 2. manager_comments.json に変更があったかを確認
if ! git diff --quiet --exit-code manager_comments.json; then
    echo "manager_comments.json に変更を検出しました。コミットしてプッシュします。"

    # 3. 変更をコミットしてプッシュ
    git add manager_comments.json
    git commit -m "[Auto] Update manager comments - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "GitHubにプッシュしています..."
    git push origin ${GIT_BRANCH}
    echo "プッシュが完了しました。"
else
    echo "manager_comments.json に変更はありませんでした。"
fi
