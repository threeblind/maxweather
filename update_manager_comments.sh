#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# --- 設定 ---
# Pythonの実行可能ファイルを解決します。ローカルではvenv、CIではPATH上のpythonを使います。
if [[ -x "venv/bin/python" ]]; then
    PYTHON_CMD="venv/bin/python"
else
    PYTHON_CMD="${PYTHON_CMD:-python}"
fi
GIT_BRANCH="main"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$(dirname "$0")"

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "監督談話室のコメント更新を開始します..."

# データディレクトリを確保
mkdir -p data

# 1. Pythonスクリプトを実行して manager_comments.json を更新
"$PYTHON_CMD" scripts/fetch_manager_comments.py

# 2. manager_comments.json に変更があったかを確認（初回生成／新規追跡対応）
if [ -f data/manager_comments.json ] && [ -n "$(git status --porcelain -- data/manager_comments.json 2>/dev/null)" ]; then
    echo "data/manager_comments.json に変更を検出しました。コミットしてプッシュします。"

    # 3. 変更をコミットしてプッシュ
    git add data/manager_comments.json
    git commit -m "[Auto] Update manager comments - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "GitHubにプッシュしています..."
    git push origin ${GIT_BRANCH}
    echo "プッシュが完了しました。"
else
    echo "manager_comments.json に変更はありませんでした。"
fi
