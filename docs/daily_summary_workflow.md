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
- タスキリレー記述で同一走者名が両側に出現していないか（「AからAへ」は誤り）
- git状態（COMMIT_TARGETS以外の変更はFAIL）
- AI応答の復旧

### 第2層: AI秘書の内容確認・推敲＋スタイル編集

確認項目:
1. 第1区・第2区の混同
2. 本日距離・平均距離・累計距離の誤り
3. 順位・順位変動の誤り
4. チーム・選手の対応
5. タスキリレー記述で異なる走者間のリレーになっているか（「AからAへ」は誤り）
6. 文章の自然さ
7. **常にスタイル編集（スポーツ実況者テイストの付加）を適用する**

スタイル編集の内容:
- スポーツ実況・解説者らしい熱量のある文体に整える
- 句読点と「！」「？」などの感嘆符でリズムをつける
- 見出しにキャッチーなフレーズ（例: 「まだ離れない！」「譲らない！」）
- ただし事実（距離・順位・チーム名・選手名）は絶対に変更しない

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

---

## cron job 登録情報

| 項目 | 設定値 |
|------|--------|
| 名前 | `daily-summary-check` |
| ジョブID | `5e84630cdbbc` |
| スケジュール | `10 0 * * *`（毎日 00:10 JST） |
| 作業ディレクトリ | `/Users/t28k2/prj/weather` |
| 有効ツール | terminal, file（最小構成） |
| 配信先 | origin（Slack依頼元スレッド） |
| 状態 | scheduled（有効） |
| 初回実行 | 2026-07-27T00:10:00+09:00 |

### cron prompt（AI秘書への指示文）

cronジョブには以下の指示が登録されている。実行時にこの指示に従って動作する。

```
日次ダイジェストの確認・修復・編集を行い、commit/pushまで持っていってください。
最大3回まで修正ループ。Git/環境エラーは即停止。

基本方針: できる限り失敗させない。AI未応答なら無理に記事を作らない。

第1層: ./scripts/check_and_repair_daily_summary.sh --no-push
  → 機械チェック + git add
第2層: AI秘書が事実確認・推敲 → daily_summary.json更新
第3層: ./scripts/check_and_repair_daily_summary.sh
  → 全チェック + commit/push
  → 記事FAIL → 第2層へ戻る（最大3回）
  → Git/環境FAIL → 停止・報告

制約: 事実変更禁止、推測禁止、.env/.DS_Store/realtime_log.jsonl除外
```

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
