# 日次確定処理（`commit_daily.sh`）運用・復旧手順

更新日: 2026-08-01

## 1. スクリプト名と実行環境

このリポジトリに `update_daily.sh` はありません。日次の確定・snapshot保存・commit/pushを行う実体は `commit_daily.sh` です。

| 用途 | 実体 | 現在の実行方法 |
| --- | --- | --- |
| 日中の速報更新 | `update_realtime.sh` | ローカルcron、10分間隔 |
| 日次の確定・公開 | `commit_daily.sh` | ローカルcron、毎日23:56 JST |
| 夜間コメント取得 | `update_manager_comments.sh` | ローカルcron |

現在のローカルcron設定は次のとおりです。

```cron
56 23 * * * /Users/t28k2/prj/weather/commit_daily.sh >> /Users/t28k2/prj/weather/logs/cron_commit.log 2>&1
```

`.github/workflows/weather-cron.yml`にも実行定義は残っていますが、現在の運用確認対象はローカルcronです。

## 2. 正常時の処理フロー

```text
update_all_records.py
  ├─ daily_temperatures.json
  ├─ intramural_rankings.json
  └─ fetch_status.json
        ↓
generate_report.py --commit --best-effort
  ├─ ekiden_state.json
  ├─ individual_results.json
  ├─ rank_history.json
  ├─ leg_rank_history.json
  ├─ runner_locations.json
  ├─ realtime_report.json
  └─ commit_status.json
        ↓
validate_race_state.py
        ↓
daily_snapshots/YYYY-MM-DD/ を保存
沿道向けレポート生成・realtime logアーカイブ
        ↓
対象ファイルをgit add → commit → pull --rebase → push
```

### 生成ファイル

- `data/daily_temperatures.json`: 選手ごとの日次最高気温。距離として利用する。
- `data/intramural_rankings.json`: 学内ランキング。
- `data/fetch_status.json`: 取得数、欠損選手、activeフラグ、欠損理由。
- `data/ekiden_state.json`: チーム状態。
- `data/individual_results.json`: 選手別の累積・日別記録。
- `data/rank_history.json`、`data/leg_rank_history.json`: 順位履歴。
- `data/runner_locations.json`、`data/realtime_report.json`: 地図・速報表示用データ。
- `data/commit_status.json`: 当日の公開状態、検証結果、quarantine対象、公開ファイル。
- `data/daily_snapshots/YYYY-MM-DD/`: 上記確定データと`manifest.json`の保存先。

## 3. 検証結果と公開方針

`validate_race_state.py`は終了コードを3段階で返します。

| 終了コード | 状態 | `commit_daily.sh`の動作 |
| ---: | --- | --- |
| 0 | 正常 | 通常commit/push。`commit_status.status=ok` |
| 2 | 局所警告 | 更新・snapshot・commit/pushを継続。`status=degraded` |
| 1 | 致命的エラー | 候補6ファイルを復元し、snapshot・commit/pushを停止 |

1〜2大学の`totalDistance`差、currentLeg差、区間境界差、取得欠損は局所警告として扱います。警告対象は`commit_status.json`の`errors`または`quarantinedTeams`で確認し、後から手動修正します。

JSON破損、必須構造の欠落、未知のteamIdなど全体を計算できない状態は致命的エラーです。

`--best-effort`は`commit_daily.sh`だけが使用します。手動でstrict動作を確認したい場合は、オプションなしの`--commit`を使用してください。

## 4. 日次実行の確認

プロジェクトルートで確認します。

```bash
cd /Users/t28k2/prj/weather
tail -n 160 logs/cron_commit.log
git log -5 --oneline --decorate
git status --short
```

成功または警告付き継続の場合は、次を確認します。

```bash
python -m json.tool data/commit_status.json >/dev/null
python -m json.tool data/fetch_status.json >/dev/null
python scripts/validate_race_state.py
```

`commit_status.json`の`status`は`ok`または`degraded`、`publishedFiles`には当日公開対象が列挙されます。検証コード2は警告付きの正常継続です。

## 5. 失敗時の切り分け

### 5.1 最初に確認するもの

1. `logs/cron_commit.log`の失敗箇所と終了コード。
2. `data/commit_status.json`と`data/fetch_status.json`。
3. `git status --short`。未commitの生成物が残っていても、内容を確認するまで手動commitしない。
4. `data/diagnostics/`に診断が作られている場合は、`validation_output.txt`とmanifest。

### 5.2 警告（exit 2）の場合

原則として復元しません。全大学の更新・snapshot・公開を優先します。

- `commit_status.json`で警告大学と理由を記録する。
- `quarantinedTeams`がある大学は、当日分のstate・個人記録を前回値のまま保持する。
- 公開後に対象大学だけを手動修正し、次回の確定処理または専用の修復作業で検証する。

### 5.3 致命的エラー（exit 1）の場合

`generate_report.py`がバックアップから次の6ファイルを復元して停止します。

```text
ekiden_state.json
individual_results.json
rank_history.json
leg_rank_history.json
runner_locations.json
realtime_report.json
```

診断を確認し、原因を直してから同日再実行します。同日再実行では日別記録の上書きロジックが働くため、二重加算を避けられます。通常は`commit_daily.sh`を再実行します。

## 6. snapshotからの復旧

snapshotが存在する場合は、まず現在の`data/`を退避してから復元します。復元対象日は必ず確認してください。

```bash
cd /Users/t28k2/prj/weather
RECOVERY_DATE=YYYY-MM-DD
BACKUP_DIR="/tmp/weather-recovery-${RECOVERY_DATE}"
mkdir -p "$BACKUP_DIR"

for f in realtime_report.json ekiden_state.json individual_results.json \
  rank_history.json leg_rank_history.json runner_locations.json \
  daily_temperatures.json intramural_rankings.json fetch_status.json commit_status.json; do
  [ -f "data/$f" ] && cp -p "data/$f" "$BACKUP_DIR/$f"
  [ -f "data/daily_snapshots/$RECOVERY_DATE/$f" ] && \
    cp -p "data/daily_snapshots/$RECOVERY_DATE/$f" "data/$f"
done

python scripts/validate_race_state.py
git diff -- data
```

検証結果と差分を確認してから、通常のcommit/pushを行います。snapshotにないファイルは無理に作成しません。

## 7. 保存済み気温だけでの再生成に関する注意

`update_all_records.py`はWebから再取得するスクリプトです。過去日の`daily_temperatures.json`だけを使って学内ランキングを再生成したい場合、これを実行してはいけません。

現状、選択した過去日を指定して`intramural_rankings.json`だけを再生成する正式な専用コマンドはありません。snapshotがあればsnapshotを優先し、snapshotがない場合は対象日・対象ファイル・期待するcurrentLegを確認したうえで、レビュー済みの一時再生成スクリプトを使用します。

## 8. 運用上の禁止事項

- `validate_race_state.py`の警告を無条件に削除して公開しない。
- `daily_temperatures.json`があるからといって、過去日の復旧で`update_all_records.py`を実行しない。
- 診断ファイル、scratch、dry-runスクリプトを公開対象へ追加しない。
- `ekiden_state.json`と`individual_results.json`を片方だけ手編集しない。
- cron実行中に同じ`commit_daily.sh`を並行起動しない。

