# 日次ダイジェスト 自動確認・編集・公開ワークフロー

## ループ構造（最大3回）

```
00:10 cron
  │
  ├─ 第1層: ./scripts/check_and_repair_daily_summary.sh --no-push
  │  機械チェック + git add
  │  ├─ FAIL → 修正して再実行
  │  └─ PASS
  │
  ├─ 第2層: AI秘書
  │  事実確認・文章推敲
  │  daily_summary.jsonを更新
  │
  ├─ 第3層: ./scripts/check_and_repair_daily_summary.sh
  │  全チェック + commit/push
  │  ├─ 記事FAIL → 第2層へ戻る（最大3回）
  │  ├─ Git/環境FAIL → 停止・報告
  │  └─ PASS → 完了報告
  │
  └─ 最大3回で打ち切り
```

### 第1層: スクリプト（機械チェック + git add）

チェック内容:
- JSON構文
- 日付一致
- 壊れた距離表記（39.km, nullkm, NaNkm）
- 未置換テンプレート
- snapshotとの距離照合
- 存在しないチーム名
- git状態（COMMIT_TARGETS以外の変更はFAIL）
- AI応答の復旧

### 第2層: AI秘書の内容確認・推敲

確認項目:
1. 第1区・第2区の混同
2. 本日距離・平均距離・累計距離の誤り
3. 順位・順位変動の誤り
4. チーム・選手の対応
5. 文章の自然さ

### 第3層: 最終再検証（ループ）

結果に応じて分岐:
- **PASS** → 完了報告
- **記事FAIL**（壊れた数字・距離不一致等） → 第2層に戻って修正、再実行（最大3回）
- **Git/環境FAIL**（無関係な変更等） → 停止・報告。第2層に戻らない

### コミット対象ファイル（COMMIT_TARGETS）

```python
['data/daily_summary.json', 'data/article_history.json', 'data/race_narrative_state.json']
```

realtime_log.jsonl は対象外。

### ファイル構成

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
