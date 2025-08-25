#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# このスクリプトは、5chスレッドを監視し、監督による選手交代の宣言を処理するためのものです。
# cronジョブとして夜間（18:00-23:59）に定期的に実行されることを想定しています。

# --- 設定 ---
PROJECT_DIR="/Users/t28k2/prj/weather"
LOG_FILE="$PROJECT_DIR/logs/update_substitutions.log"

# --- スクリプト本体 ---

# ログディレクトリの存在を確認し、なければ作成
mkdir -p "$(dirname "$LOG_FILE")"

# メイン処理をブロックで囲み、標準出力と標準エラーの両方をログファイルに追記しつつ、コンソールにも表示する
{
    # スクリプトの実行場所をプロジェクトディレクトリに移動
    cd "$PROJECT_DIR" || { echo "エラー: プロジェクトディレクトリが見つかりません: $PROJECT_DIR"; exit 1; }

    echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
    echo "選手交代処理を開始します..."

    # 1. Python仮想環境を有効化
    # venvの存在を確認
    if [ ! -d "venv" ]; then
        echo "エラー: Python仮想環境 'venv' が見つかりません。"
        exit 1
    fi
    source venv/bin/activate
    echo "Python仮想環境を有効化しました。"

    # 2. 選手交代処理スクリプトを実行
    echo "process_substitutions.py を実行中..."
    python3.9 process_substitutions.py

    # 3. ekiden_data.json または substitution_log.txt に変更があったか確認し、変更があればPush
    if ! git diff --quiet --exit-code ekiden_data.json substitution_log.txt; then
        echo "選手交代または新規ログを検出しました。GitHubにプッシュします。"
        
        echo "変更されたファイル:"
        git status --short ekiden_data.json substitution_log.txt

        git add ekiden_data.json substitution_log.txt
        
        COMMIT_MSG="Apply player substitution [bot] $(date +'%Y-%m-%d %H:%M')"
        echo "コミットを実行します: $COMMIT_MSG"
        git commit -m "$COMMIT_MSG"

        # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash)
        echo "他の変更を一時退避します (git stash)..."
        STASH_RESULT=$(git stash)
        echo "Stash result: $STASH_RESULT"

        echo "リモートの変更を取り込んでいます (git pull --rebase)..."
        git pull --rebase origin main

        echo "GitHubにプッシュしています (git push)..."
        git push origin main

        # 退避していた変更を元に戻す
        if [[ "$STASH_RESULT" != "No local changes to save" ]]; then
            echo "一時退避した変更を元に戻します (git stash pop)..."
            git stash pop
        fi
    else
        echo "新規の選手交代はありませんでした。コミットをスキップします。"
    fi

    echo "処理が正常に完了しました。"
    echo ""

} 2>&1 | tee -a "$LOG_FILE"
