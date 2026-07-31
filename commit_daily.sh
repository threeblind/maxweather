#!/bin/bash

# スクリプトが失敗した場合に即座に終了するように設定
set -euo pipefail

# このスクリプトは、高温大学駅伝の一日の結果を状態ファイル(ekiden_state.json)に保存し、
# GitHubリポジトリにプッシュするためのものです。
# cronジョブとして1日1回、深夜に実行されることを想定しています。

# --- 設定 ---
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="data"

# --- スクリプト本体 ---

# スクリプトの実行場所をプロジェクトディレクトリに移動
cd "$PROJECT_DIR" || { echo "エラー: プロジェクトディレクトリが見つかりません: $PROJECT_DIR"; exit 1; }

echo "--- $(date +'%Y-%m-%d %H:%M:%S') ---"
echo "デイリーコミット処理を開始します..."

# 1. Python実行環境を用意
if [[ -d "venv" ]]; then
    source venv/bin/activate || { echo "エラー: Python仮想環境(venv)の有効化に失敗しました。"; exit 1; }
    PYTHON_CMD="python"
else
    PYTHON_CMD="${PYTHON_CMD:-python}"
fi

# 2. 全選手の最終記録を取得・保存 (スクリプトのパスを修正)
echo "scripts/update_all_records.py を実行中..."
"$PYTHON_CMD" scripts/update_all_records.py

# 3. --commit --best-effort モードでレポートを生成し、ekiden_state.jsonなどを更新
#    終了コード: 0=正常, 2=警告付き継続(degraded), 1=致命的停止
DEGRADED=0
echo "scripts/generate_report.py --commit --best-effort を実行中..."
set +e
"$PYTHON_CMD" scripts/generate_report.py --commit --best-effort
COMMIT_RC=$?
set -e
case "$COMMIT_RC" in
  0)
    echo "✅ generate_report.py 正常終了"
    ;;
  2)
    DEGRADED=1
    echo "⚠️ generate_report.py は警告付き継続 (degraded) で終了しました。後続処理を継続します。"
    ;;
  1)
    echo "❌ generate_report.py が致命的エラーで終了しました。処理を停止します。"
    exit 1
    ;;
  *)
    echo "❌ generate_report.py が予期しない終了コード ($COMMIT_RC) で終了しました。処理を停止します。"
    exit 1
    ;;
esac

# 3.5. 状態ファイルの整合性を検証（0=問題なし, 2=警告のみ継続, 1=致命的停止）
echo "scripts/validate_race_state.py を実行中..."
set +e
VALIDATION_OUTPUT=$("$PYTHON_CMD" scripts/validate_race_state.py 2>&1)
VALIDATION_RC=$?
set -e
case "$VALIDATION_RC" in
  0)
    echo "$VALIDATION_OUTPUT"
    echo "✅ 状態ファイルの整合性確認完了"
    ;;
  2)
    DEGRADED=1
    echo "$VALIDATION_OUTPUT"
    echo "⚠️ 状態ファイルに警告があります (degraded)。スナップショット保存・コミットを継続します。"
    ;;
  1)
    echo "$VALIDATION_OUTPUT"
    echo "❌ 状態ファイルの致命的エラーを検出しました。診断成果物を保存します..."
    if ! "$PYTHON_CMD" scripts/save_validation_diagnostics.py --output "$VALIDATION_OUTPUT"; then
        echo "⚠️ 診断成果物の保存に失敗しました（検証の失敗自体は継続）"
    fi
    echo "スナップショット保存・アーカイブ・コミットを中止します。"
    exit 1
    ;;
  *)
    echo "$VALIDATION_OUTPUT"
    echo "❌ validate_race_state.py が予期しない終了コード ($VALIDATION_RC) で終了しました。処理を停止します。"
    exit 1
    ;;
esac

# 4. 確定データを日付付きスナップショットとして永続保存
echo "scripts/save_daily_snapshot.py を実行中..."
SNAPSHOT_DIR=$("$PYTHON_CMD" scripts/save_daily_snapshot.py --print-path)
SNAPSHOT_DATE=$(basename "$SNAPSHOT_DIR")
echo "スナップショット: $SNAPSHOT_DIR"

# 4.5. 沿道様向け速報表を生成（set -e で失敗時は commit/push を中止）
echo "scripts/generate_alongroad_report.py --date $SNAPSHOT_DATE --save を実行中..."
"$PYTHON_CMD" scripts/generate_alongroad_report.py --date "$SNAPSHOT_DATE" --save

# 4.6. manifest.json に alongroad_report.txt を追加
"$PYTHON_CMD" scripts/save_daily_snapshot.py \
  --add-to-manifest alongroad_report.txt \
  --manifest-dir "$SNAPSHOT_DIR"

if [[ "${EKIDEN_DISABLE_GIT_PUSH:-0}" == "1" ]]; then
    echo "テストモードのため、Git commit / push はスキップします。"
    echo "処理が正常に完了しました。"
    echo ""
    exit 0
fi

# 5. 本日のログファイルをアーカイブ（冪等。同日アーカイブが既にあれば同内容スキップ/不一致停止）
echo "scripts/archive_realtime_log.sh を実行中..."
if ! bash scripts/archive_realtime_log.sh "$DATA_DIR"; then
    echo "❌ realtime_log のアーカイブに失敗しました。処理を中止します。"
    exit 1
fi

# 6. 変更されたファイルをステージング (パスを修正)
#    明示リストのみを対象とし、存在しないファイルはスキップする
#    （未想定の変更を巻き込まないための安全策）
STAGE_PATHS=(
  data/realtime_report.json
  data/ekiden_state.json
  data/individual_results.json
  data/rank_history.json
  data/leg_rank_history.json
  data/runner_locations.json
  data/daily_temperatures.json
  data/intramural_rankings.json
  data/fetch_status.json
  data/commit_status.json
  data/daily_snapshots
)
for stage_path in "${STAGE_PATHS[@]}"; do
  [ -e "$stage_path" ] && git add -- "$stage_path"
done

# 7. ステージングされた変更があるか確認し、コミットとプッシュを実行
if ! git diff --cached --quiet; then
    if [ "$DEGRADED" = "1" ]; then
        echo "最終結果ファイルまたはログファイルに変更を検出しました (degraded)。GitHubにプッシュします。"
        git commit -m "Finalize and archive daily data [degraded] [bot] $(date +'%Y-%m-%d')"
    else
        echo "最終結果ファイルまたはログファイルに変更を検出しました。GitHubにプッシュします。"
        git commit -m "Finalize and archive daily data [bot] $(date +'%Y-%m-%d')"
    fi

    # 他の未コミットの変更があった場合に備えて、一時的に退避 (stash)
    # 退避が必要な変更がある場合のみ実行する（ロケール非依存の判定）
    STASHED=0
    if ! git diff --quiet || ! git diff --cached --quiet; then
        git stash push -q || { echo "エラー: 未コミット変更の退避(stash)に失敗しました。"; exit 1; }
        STASHED=1
    fi

    echo "リモートの変更を取り込んでいます (git pull --rebase)..."
    if ! git pull --rebase origin main; then
        echo "エラー: git pull --rebase に失敗しました。"
        # 競合で中断した場合は rebase を中止して元の状態へ復帰させる
        git rebase --abort 2>/dev/null || true
        if [ "$STASHED" = "1" ]; then
            git stash pop || echo "⚠️ 退避した変更の復元に失敗しました (git stash list で確認してください)"
        fi
        exit 1
    fi

    echo "GitHubにプッシュしています..."
    if ! git push origin main; then
        echo "エラー: git push に失敗しました。"
        # 退避した変更が stash に残ったままにならないよう復元する
        if [ "$STASHED" = "1" ]; then
            git stash pop || echo "⚠️ 退避した変更の復元に失敗しました (git stash list で確認してください)"
        fi
        exit 1
    fi

    if [ "$STASHED" = "1" ]; then
        git stash pop || echo "⚠️ 退避した変更の復元に失敗しました (git stash list で確認してください)"
    fi
else
    echo "コミット対象の変更はありませんでした。"
fi

echo "処理が正常に完了しました。"
echo ""
