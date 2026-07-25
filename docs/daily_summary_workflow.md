# 日次ダイジェスト 自動確認・編集・公開ワークフロー

## 概要

毎日 00:10 JST に、前日のダイジェスト記事の確認・編集・公開を自動実行する。

AI秘書（Hermes Agent）が以下の3ステップを実行する：

1. **機械的チェック** — スクリプトで壊れたデータを検出・修復
2. **内容検証 + スタイル編集** — 事実確認 + スポーツ実況調に改善
3. **commit/push** — 問題なければ自動公開

---

## ワークフロー詳細

### Step 1: 機械的チェック（スクリプト）

**実行:** `./scripts/check_and_repair_daily_summary.sh --no-push`

このスクリプトの役割は「明らかな壊れを検出して修復する」こと。

**検出項目:**
| 項目 | 内容 | 状態 |
|------|------|------|
| JSON構文 | daily_summary.json が正しいJSONか | PASS/FAIL |
| 日付一致 | 記事の日付と対象日が一致するか | PASS/FAIL |
| 必須項目 | article フィールドが空でないか | PASS/FAIL |
| 壊れた数字 | `39.km` `nullkm` `NaNkm` など | PASS/FAIL |
| 未置換テンプレート | `{{TEAM:1}}` が残っていないか | PASS/FAIL |
| 距離値の整合性 | 実データにない距離値（28.3km等）がないか | PASS/FAIL |
| 存在しないチーム名 | `**架空大学**` が記事にないか | PASS/FAIL |
| git状態 | 関係ないファイルが変更されていないか | PASS/FAIL |

**注意:** スクリプトの `check_git_status` は `git status --porcelain` の出力をパースする。
`line[3:].strip()` ではなく `line[2:].lstrip()` でパスを抽出すること（v1形式対応）。
この修正は commit f8aa35bb6e で適用済み。

**修復機能:**
- AI応答の失敗ファイル（`logs/summary_ai_responses/*.json`）があれば、
  `raw_response` から記事を抽出・検証して修復を試みる
- 修復成功時は `status=recovered` でファイルを保持（削除しない）

---

### Step 2: 内容検証 + スタイル編集（AI秘書）

スクリプトが PASS した後、AI秘書が以下を実施：

#### 2a. 事実確認（絶対条件）

以下の誤りがないか、`data/daily_summary.json` と `data/individual_results.json` を照合：

| 確認項目 | 具体例 |
|---------|--------|
| **区間の混同** | 第1区の話なのに「第2区で」と書かれていないか |
| **距離の種別** | 平均距離なのに「本日距離」と書かれていないか |
| **チームと区間の対応** | A大学が走った区間にB大学の名前が出ていないか |
| **順位の正しさ** | 実際は5位なのに「3位」と書かれていないか |
| **数値の正確性** | 距離数値が実データと一致しているか |

**事実誤認があった場合は commit/push しない。**

#### 2b. スタイル編集（推敲）

事実が正しい場合、記事のスタイルを**スポーツ新聞・実況アナウンサー調**に改善：

**基本方針:**
- 事実（数値・チーム名・順位・区間・日付）は絶対に変更しない
- 単なる事実羅列に「熱量」と「臨場感」を加える
- 全区間に一律盛る必要はない。ドラマチックな部分だけスポット的に

**編集テクニック:**
| 方向 | 例 |
|------|-----|
| 歴史的な瞬間を強調 | 「歴史が動いた」「語り継がれるべき一日」 |
| 数字に意味を込める | 「たった1.3km」「0.1km。たかが100m、されど100m」 |
| 読者を巻き込む | 「さあ、明日はどうなる」「噛みしめてほしい」 |
| 対決構図を描く | 「追う側の焦りと、逃げる側の余裕」 |
| 実況感を出す | 「まだ勝負は終わらない！」「ここは一歩も引けない！」 |

**禁止事項:**
- 事実（数値・チーム名・順位・区間・日付）の変更
- 元データで確認できない数値の推測
- 第1区・第2区の混同
- 本日距離・平均距離・累計距離の混同
- 前日順位・本日順位の混同

---

### Step 3: commit/push

全ての検証・編集が完了したら：
```bash
git add data/daily_summary.json data/article_history.json data/race_narrative_state.json
git add logs/summary_ai_responses/*.json 2>/dev/null || true
git diff --cached --quiet || git commit -m "Daily summary YYYY-MM-DD [bot]"
git push origin main
```

**コミットメッセージのルール:**
- 通常: `Daily summary YYYY-MM-DD [bot]`
- スタイル編集あり: `Daily summary YYYY-MM-DD [bot] - <編集内容の簡潔な説明>`
- 救出（rescue）: `Daily summary YYYY-MM-DD [bot] - rescued from failed AI response`
- バグ修正を含む: 上記に追加で説明

---

## ファイル構成

| パス | 役割 | 更新者 |
|------|------|--------|
| `data/daily_summary.json` | 日次ダイジェスト記事（date + article） | AI → スクリプト → AI秘書 |
| `data/daily_snapshots/*/individual_results.json` | 各日の確定記録スナップショット（検証用マスタ） | 毎日23:59に作成 |
| `data/individual_results.json` | 最新記録データ（ライブ。検証にはスナップショットを使用） | データ取得バッチ |
| `config/ekiden_data.json` | チーム名・区間マスタ | 手動管理 |
| `config/outline.json` | 大会概要（startDate等） | 手動管理 |
| `logs/cron_summary.log` | 日次データ取得バッチのログ | データ取得バッチ |
| `logs/summary_ai_responses/*.json` | AI応答の保存（失敗時も保持） | 日次ダイジェスト生成 |
| `logs/summary_check.log` | チェックスクリプトの実行結果 | チェックスクリプト |
| `scripts/check_and_repair_daily_summary.py` | 機械的チェック・修復処理 | 開発者 |
| `scripts/check_and_repair_daily_summary.sh` | シェルラッパー（venv活性化） | 開発者 |

---

## cron job 設定

**名前:** `daily-summary-check`
**スケジュール:** 毎日 00:10 JST (`10 0 * * *`)
**作業ディレクトリ:** `/Users/t28k2/prj/weather`
**有効ツール:** terminal, file（最小構成）
**配信先:** Slack スレッド

**備考:** cronジョブのpromptはAI秘書（Hermes Agent）に対する指示であり、
上記Step 1〜3の全手順をself-containedで記述している。
cron実行時は過去の会話コンテキストがないため、全てをprompt内で完結させる必要がある。

---

## エラーハンドリング

### 基本方針: **できる限り失敗させない**

| 状況 | 対応 |
|------|------|
| ✅ 記事正常、全チェックPASS | スタイル編集 → commit/push |
| 🔧 軽微な問題（ドット落ち等） | 直接修正 → 再チェック → commit/push |
| 🆘 AI応答失敗で記事がない | 元データから記事を書き起こし → commit/push（rescued） |
| ❌ 事実誤認あり | 元データで修正可能なら修正、不可能なら報告 |
| 💀 どうしても救済不能 | 報告（failed）— この状態は原則発生させない |

### rescue（記事再構成）のルール

AI応答が失敗して `daily_summary.json` に有効な記事がない場合：

1. `individual_results.json` から対象日の全記録を抽出
2. `ekiden_data.json` からチーム名情報を取得
3. 事実のみで構成された記事を作成（推測禁止）
4. 各区間の順位・距離・チーム名が実データと合っていることを確認
5. スタイルはスポーツ実況調で書く

---

## 検証とテスト

```bash
# 全テスト実行
cd /Users/t28k2/prj/weather
source venv/bin/activate
python3 -m pytest tests/test_check_and_repair.py -v

# dry-run（実際の変更なし）
./scripts/check_and_repair_daily_summary.sh --date YYYY-MM-DD --dry-run

# 特定日の確認
./scripts/check_and_repair_daily_summary.sh --date YYYY-MM-DD --no-push
```

---

## 補足: スクリプトの既知の制約

- 意味的チェック（区間の混同・距離種別の誤り・順位の誤り）は検出できない
  → これはAI秘書（Hermes Agent）の役割
- `git status --porcelain` のパス解析は `line[2:].lstrip()` が必要
  → `line[3:].strip()` は `M data/...` 形式で誤動作する（fix済み）
- 現在は第1区のみのデータ。第2区以降のデータが追加された場合、
  検証ロジックの拡張が必要
