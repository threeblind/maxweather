#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# このスクリプトは、5chスレッドを監視し、監督による選手交代の宣言を処理するためのものです。
# 単一ロックオーケストレーション:
#   1. fcntlロックを取得（update_realtime.sh との競合を回避）
#   2. process_substitutions.py で交代を検証・適用（成功時のみ config 更新）
#   3. generate_report.py --realtime で速報JSONを再生成（交代を反映）
#   4. 変更があれば config + ログ + 速報ファイルを明示指定で commit / push
# 独立した git stash は行わない（コミット対象を明示指定する）。

# --- 設定 ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$PROJECT_DIR/logs/update_substitutions.log"
LOCK_FILE="$PROJECT_DIR/logs/substitution.lock"

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
    if [ ! -d "venv" ]; then
        echo "エラー: Python仮想環境 'venv' が見つかりません。"
        exit 1
    fi
    source venv/bin/activate
    echo "Python仮想環境を有効化しました。"

    # 2. 単一ロックでオーケストレーション
    #    process_substitutions → realtime再生成 → commit/push をロック下で実行
    echo "単一ロックを取得します ($LOCK_FILE)..."
    python scripts/with_lock.py "$LOCK_FILE" -- bash -c '
        set -euo pipefail
        echo "process_substitutions.py を実行中..."
        python scripts/process_substitutions.py

        echo "generate_report.py --realtime を実行中..."
        python scripts/generate_report.py --realtime

        # 変更があれば commit / push（対象を明示指定。git stash は行わない）
        # 未追跡の新規ログ（初回の review/audit JSONL）も差分検知対象にするため
        # intent-to-add を行う。
        for f in logs/substitution_review.jsonl logs/substitution_audit.jsonl; do
            if [[ -f "$f" ]]; then
                git add -f -N "$f" || true
            fi
        done

        if ! git diff --quiet --exit-code \
            config/ekiden_data.json \
            logs/substitution_log.txt \
            logs/substitution_review.jsonl \
            logs/substitution_audit.jsonl \
            data/realtime_report.json \
            data/individual_results.json \
            data/rank_history.json \
            data/leg_rank_history.json \
            data/runner_locations.json \
            data/realtime_log.jsonl; then
            echo "交代または速報の変更を検出しました。GitHubにプッシュします。"

            git add config/ekiden_data.json \
                logs/substitution_log.txt \
                logs/substitution_review.jsonl \
                logs/substitution_audit.jsonl \
                data/realtime_report.json \
                data/individual_results.json \
                data/rank_history.json \
                data/leg_rank_history.json \
                data/runner_locations.json \
                data/realtime_log.jsonl

            COMMIT_MSG="Apply player substitution [bot] $(date +'%Y-%m-%d %H:%M')"
            echo "コミットを実行します: $COMMIT_MSG"
            git commit -m "$COMMIT_MSG"

            echo "リモートの変更を取り込んでいます (git pull --rebase)..."
            git pull --rebase origin main

            echo "GitHubにプッシュしています (git push)..."
            git push origin main
        else
            echo "新規の有効な交代はありませんでした。コミットをスキップします。"
        fi
    '
    echo "単一ロックを解放しました。"

    echo "処理が正常に完了しました。"
    echo ""

} 2>&1 | tee -a "$LOG_FILE"
