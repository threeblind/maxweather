#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
# -e: コマンドが非ゼロのステータスで終了した場合にスクリリプトを終了
# -u: 未定義の変数を参照しようとした場合にスクリプトを終了
# -o pipefail: パイプラインのいずれかのコマンドが失敗した場合、パイプライン全体を失敗とみなす
set -euo pipefail
# このスクリプトは、高温大学駅伝のリアルタイム速報を生成し、
# GitHubリポジトリにプッシュするためのものです。
# cronジョブとして定期的に実行されることを想定しています。

# --- 設定 ---
# プロジェクトのルートディレクトリへの絶対パス
# cronから実行される場合、パスの解決に失敗することがあるため絶対パスを指定します。
PROJECT_DIR="/Users/t28k2/prj/weather"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$PROJECT_DIR" || { echo "エラー: プロジェクトディレクトリが見つかりません: $PROJECT_DIR"; exit 1; }

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "リアルタイム速報の更新を開始します..."

# 1. Python仮想環境を有効化
source venv/bin/activate || { echo "エラー: Python仮想環境(venv)の有効化に失敗しました。"; exit 1; }

# 2. 速報JSONを生成
echo "scripts/generate_report.py を実行中..."
python scripts/generate_report.py --realtime

# 3. 速報ファイルに変更があるか確認し、変更があればPush
if ! git diff --quiet --exit-code \
  data/realtime_report.json \
  data/individual_results.json \
  data/rank_history.json \
  data/leg_rank_history.json \
  data/runner_locations.json \
  logs/realtime_log.jsonl; then
    echo "速報ファイル (realtime_report.json, etc.) に変更を検出しました。GitHubにプッシュします。"
    git add data/realtime_report.json data/individual_results.json data/rank_history.json data/leg_rank_history.json data/runner_locations.json logs/realtime_log.jsonl
    git commit -m "Update realtime report [bot] $(date +'%Y-%m-%d %H:%M:%S')"

    # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash) します。
    # これにより、`git pull --rebase` が安全に実行できます。
    STASH_RESULT=$(git stash)

    # リモートの変更を取り込んでからプッシュする (non-fast-forwardエラー対策)
    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    if ! git pull --rebase origin main; then
        echo "エラー: git pull --rebase に失敗しました。コンフリクトを解決する必要があるかもしれません。"
        # pullに失敗した場合、stashを戻してから終了する
        if [[ "$STASH_RESULT" != "No local changes to save" ]]; then
            git stash pop
        fi
        exit 1
    fi

    echo "GitHubにプッシュしています..."
    git push origin main

    # 退避していた変更を元に戻します。
    if [[ "$STASH_RESULT" != "No local changes to save" ]]; then
        echo "一時退避した変更を元に戻します..."
        git stash pop
    fi
else
    echo "速報ファイルに変更はありませんでした。コミットをスキップします。"
fi

echo "処理が正常に完了しました。"
echo ""