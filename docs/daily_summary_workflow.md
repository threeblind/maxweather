# 日次ダイジェスト 自動確認・編集・公開ワークフロー

## 2層構造

### 第1層: スクリプト（完全自動・機械的チェック）

`scripts/check_and_repair_daily_summary.sh --no-push` を実行し、機械的チェック + 修復 + git add まで行う。

検出項目:
| チェック | 内容 |
|---------|------|
| JSON構文 | パース可能か |
| 日付一致 | 記事の日付と対象日が一致するか |
| 必須項目 | articleが空でないか |
| 壊れた数字 | `39.km` `nullkm` `NaNkm` 等 |
| 未置換テンプレート | `{{TEAM:1}}` 等の残骸 |
| 距離値の整合性 | 実データにない距離値（28.3km等）がないか（スナップショット参照） |
| 存在しないチーム名 | `**架空大学**` が記事にないか |
| git状態 | COMMIT_TARGETS以外の変更がないか（安全チェック） |

合格時: git add まで実行（COMMIT_TARGETSのみステージ）
不合格時: 中止、エラー報告

### 第2層: AI秘書（Hermes Agent）の判断

スクリプト通過後、以下を実施:

1. **事実確認**: 区間混同、距離種別誤り、順位誤り、数値ミスを目視チェック
2. **スタイル編集**: 事実は一切変えず、実況アナウンサー風の熱量・ウィットを追加
3. **commit/push**: `git commit -m "..." && git push origin main`

（スクリプトがCOMMIT_TARGETS以外の変更をブロック済みなので、commit/pushは安全）

### rescue（AI応答ファイルがある場合のみ）

`logs/summary_ai_responses/` に対象日のJSONファイルがあり、`raw_response` が存在する場合のみ救出を試みる。

- `raw_response` から記事を抽出/修正 → `--no-push` で再検証 → 合格 → 第2層へ
- AIがそもそも応答していない場合（ファイルがない/raw_responseが空）は、記事を作成しない

---

## 実行

### cron: 毎日 00:10 JST

```bash
cd /Users/t28k2/prj/weather
source venv/bin/activate
./scripts/check_and_repair_daily_summary.sh --no-push
# → PASS確認 → 事実確認 + スタイル編集 → git commit/push
```

### オプション

| コマンド | 動作 |
|---------|------|
| オプションなし | 確認・修正・commit/pushまで（第1層のみで完結） |
| `--no-push` | 確認・修正・git addまで（第2層と組み合わせる場合） |
| `--dry-run` | 確認のみ。何も変更しない |
| `--date YYYY-MM-DD` | 特定日を対象 |

---

## コミット対象ファイル（COMMIT_TARGETS）

```python
COMMIT_TARGETS = [
    'data/daily_summary.json',
    'data/article_history.json',
    'data/race_narrative_state.json',
]
```

これら以外のファイルに変更があると、スクリプトがFAILになり中止。
`realtime_log.jsonl` は対象外。`logs/summary_ai_responses/` のファイルは救出処理の過程でaddされる。

---

## 結果確認

```bash
cat logs/summary_check.log | python3 -m json.tool
```

`final_status`: `passed` / `recovered` / `failed`

---

## ファイル構成

| パス | 役割 |
|------|------|
| `scripts/check_and_repair_daily_summary.sh` | シェルラッパー |
| `scripts/check_and_repair_daily_summary.py` | 本体（テスト34件） |
| `data/daily_summary.json` | 日次ダイジェスト記事 |
| `data/daily_snapshots/*/individual_results.json` | 各日の確定記録スナップショット |
| `config/ekiden_data.json` | チーム名マスタ |
| `config/outline.json` | 大会概要 |
| `logs/summary_check.log` | チェック結果 |
| `logs/summary_ai_responses/*.json` | AI応答の保存ファイル |
| `docs/daily_summary_workflow.md` | 本ドキュメント |
