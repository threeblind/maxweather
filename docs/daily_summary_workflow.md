# 日次ダイジェスト 自動確認・公開ワークフロー

## 概要

毎日 00:10 JST に、前日のダイジェスト記事の確認・修復・公開を自動実行する。
すべて `scripts/check_and_repair_daily_summary.sh` の1コマンドで完結する。

---

## 実行

```bash
cd /Users/t28k2/prj/weather
source venv/bin/activate
./scripts/check_and_repair_daily_summary.sh
```

オプション:
| オプション | 動作 |
|-----------|------|
| なし | 確認・修正・commit/pushまで実行（通常運用） |
| `--dry-run` | 確認のみ。修正・Git変更なし |
| `--no-push` | 修正とgit addまで行う。commit/pushはしない |
| `--date YYYY-MM-DD` | 特定の日付を対象にする |

---

## スクリプトの処理内容

1. 対象日を決定（デフォルト: 前日、`--date` 指定可）
2. `daily_snapshots/<対象日>/individual_results.json` を検証用データとして使用
3. `daily_summary.json` を読み込み、以下のチェックを実行：

| チェック | 内容 | 結果 |
|---------|------|------|
| JSON構文 | パース可能か | PASS/FAIL |
| 日付一致 | 記事の日付と対象日が一致するか | PASS/FAIL |
| 必須項目 | articleが空でないか | PASS/FAIL |
| 壊れた数字 | `39.km` `nullkm` `NaNkm` `40.km` 等 | PASS/FAIL |
| 未置換テンプレート | `{{TEAM:1}}` `{{UNKNOWN_VAR}}` 等 | PASS/FAIL |
| 距離値の整合性 | 実データにない距離値（28.3km等）がないか | PASS/FAIL |
| 存在しないチーム名 | `**架空大学**` が記事にないか | PASS/FAIL |
| git状態 | COMMIT_TARGETS以外の変更がないか | PASS/FAIL |

4. AI応答の救出処理（`logs/summary_ai_responses/` のファイルを確認）
   - `raw_response` がある場合、パース→検証→修復を試行
   - 修復成功時は `status=recovered`、失敗時は `status=rejected_*` でファイルを保持

5. 全チェック合格時のみ commit/push を実行
6. 結果を `logs/summary_check.log` に保存

---

## コミット対象ファイル（COMMIT_TARGETS）

```python
COMMIT_TARGETS = [
    'data/daily_summary.json',
    'data/article_history.json',
    'data/race_narrative_state.json',
]
```

これら以外のファイルに変更があると、安全のため FAIL になり commit/push しない。
`realtime_log.jsonl` は対象外。`logs/summary_ai_responses/` のファイルは救出処理の過程で add される。

---

## スナップショット参照

`data/daily_snapshots/<対象日>/individual_results.json` を検証用データとして使用する。
スナップショットが存在しない場合は安全停止する。

---

## 結果の見方

```bash
cat logs/summary_check.log | python3 -m json.tool
```

`final_status` の値:
| 値 | 意味 |
|----|------|
| `passed` | 全チェック合格、問題なし |
| `recovered` | 修復後に合格、commit/push成功 |
| `failed` | 致命的エラーあり、commit/pushせず |

---

## エラーハンドリング

| 状況 | 動作 |
|------|------|
| ✅ 全チェック合格 | commit/push実行。戻り値 0 |
| 🔧 軽微な問題（ドット落ち等） | 自動修復→再チェック→commit/push。戻り値 0 |
| 🆘 AI応答ありだが保存失敗 | logs/summary_ai_responses/ から救出を試行。成功→commit/push |
| ❌ AI応答なし（ファイルがない） | 無理に記事を作らない。報告のみ。戻り値 1 |
| 💀 どうしても救済不能 | 報告（failed）。戻り値 1 |

---

## ファイル構成

| パス | 役割 |
|------|------|
| `scripts/check_and_repair_daily_summary.sh` | シェルラッパー（venv活性化） |
| `scripts/check_and_repair_daily_summary.py` | 本体（799行） |
| `tests/test_check_and_repair.py` | テスト（34件） |
| `data/daily_summary.json` | 日次ダイジェスト記事 |
| `data/daily_snapshots/*/individual_results.json` | 各日の確定記録スナップショット |
| `data/individual_results.json` | 最新記録データ（検証はスナップショットを使用） |
| `config/ekiden_data.json` | チーム名マスタ |
| `config/outline.json` | 大会概要（startDate等） |
| `logs/summary_check.log` | チェックスクリプトの実行結果 |
| `logs/summary_ai_responses/*.json` | AI応答の保存ファイル |
| `docs/daily_summary_workflow.md` | 本ドキュメント |

---

## 検証

```bash
cd /Users/t28k2/prj/weather
source venv/bin/activate
python3 -m pytest tests/test_check_and_repair.py -v
```
