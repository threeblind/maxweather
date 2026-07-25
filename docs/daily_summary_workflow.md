# 日次ダイジェスト 自動確認・編集・公開ワークフロー

## 3層構造

### 第1層: スクリプト（機械チェック + git add）

```bash
./scripts/check_and_repair_daily_summary.sh --no-push
```

チェック内容:
- JSON構文
- 日付一致
- 壊れた距離表記（39.km, nullkm, NaNkm）
- 未置換テンプレート（{{TEAM:1}}等）
- snapshotとの距離照合（daily_snapshots/<対象日>/individual_results.json）
- 存在しないチーム名
- git状態（COMMIT_TARGETS以外の変更はFAIL）
- AI応答の復旧（logs/summary_ai_responses/）

ここではcommit/pushしない。合格ならgit addまで。

### 第2層: AI秘書の内容確認・推敲

確認項目:
1. 第1区・第2区の混同
2. 本日距離・平均距離・累計距離の誤り
3. 順位・順位変動の誤り
4. チーム・選手の対応
5. 文章の自然さ

事実誤認があればsnapshotを根拠に修正。
推測で数値を補完しない。

問題なければスタイル編集（実況アナウンサー調）。
事実（数値・チーム名・順位・区間・日付）は絶対に変更しない。

### 第3層: 最終再検証（ループ）

```bash
./scripts/check_and_repair_daily_summary.sh
```

通常モード（オプションなし）で実行。全チェック通過 + commit/pushまで自動実行。

**FAIL → ログ確認 → 第2層に戻って修正 → 第3層再実行 → 合格するまでループ**

編集ミスがあっても止まらない。直して再実行を繰り返す。

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
realtime_log.jsonl は対象外。

---

## エラーハンドリング

| 状況 | 動作 |
|------|------|
| ✅ 全チェック合格 | 第2層→第3層へ |
| 🔧 AI応答ありだが保存失敗 | 救出試行→第1層再実行 |
| ❌ AI応答なし | 記事を作らない。報告のみ |
| 💀 第3層でFAIL | 編集ミスが原因。修正して再実行 |

---

## ファイル構成

| パス | 役割 |
|------|------|
| `scripts/check_and_repair_daily_summary.sh` | シェルラッパー |
| `scripts/check_and_repair_daily_summary.py` | 本体 |
| `tests/test_check_and_repair.py` | テスト34件 |
| `data/daily_summary.json` | 日次ダイジェスト記事 |
| `data/daily_snapshots/*/individual_results.json` | 各日の確定記録 |
| `config/ekiden_data.json` | チーム名マスタ |
| `config/outline.json` | 大会概要 |
| `logs/summary_check.log` | チェック結果 |
| `logs/summary_ai_responses/*.json` | AI応答の保存 |
| `docs/daily_summary_workflow.md` | 本ドキュメント |
