#!/bin/bash

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
source venv/bin/activate

# 2. 速報JSONを生成
echo "generate_report.py を実行中..."
python generate_report.py --realtime

# 3. realtime_report.json に変更があるか確認し、変更があればPush
if ! git diff --quiet --exit-code realtime_report.json; then
    echo "realtime_report.json に変更を検出しました。GitHubにプッシュします。"
    git add realtime_report.json
    git commit -m "Update realtime report [bot] $(date +'%Y-%m-%d %H:%M:%S')"
    git push origin main
    echo "プッシュが完了しました。"
else
    echo "realtime_report.json に変更はありませんでした。コミットをスキップします。"
fi

echo "処理が正常に完了しました。"
echo ""