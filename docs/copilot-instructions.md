## 目的
このリポジトリで自動化エージェント（Copilot など）が素早く有用な編集/提案をできるよう、実務に即した最小限かつ具体的なガイダンスをまとめます。

## ビッグピクチャ（アーキテクチャ）
- データ構成: 設定は `config/`、実行時データは `data/`、履歴は `history_data/` に保存。
- 中心スクリプト: `scripts/generate_report.py` が主要な集約処理（スクレイピング、順位計算、JSON出力、通知）を行う。
- 外部連携: Yahoo 天気ページのスクレイピング（`requests` + `BeautifulSoup`）、位置計算は `geopy`、通知は外部 API（`PROD_PUSH_API_URL` + `API_SECRET_KEY`）へ HTTP POST。

## 重要ファイルと役割（すぐ参照する場所）
- `scripts/generate_report.py` — コアロジック（レース状態読み込み、気温取得、順位算出、JSON保存、通知）。多くのドメイン固有ルールはここにある。
- `config/ekiden_data.json` — チーム定義や `leg_boundaries`（区間境界）を含む。順位・区間判定はこれを基準にする。
- `config/outline.json` — `startDate`（`EKIDEN_START_DATE`）と `mainThreadUrl`（監督コメントスクレイピング先）を含む。スクリプト開始時に読み込み補正される。
- `config/shadow_team.json` — 区間記録連合（シャドーチーム）の定義。シャドーは `group_id=2` / `is_shadow_confederation=True` で順位計算対象外。
- `data/realtime_report.json` と `data/realtime_report_previous.json` — フロントに出す速報データ。フィールド例: `breakingNewsComment`, `breakingNewsTimestamp`, `teams` (各チームに `id,name,currentLeg,runner,todayDistance,totalDistance,overallRank,previousRank,is_shadow_confederation` を含む)

## プロジェクト固有の慣習と注意点
- 言語は日本語中心。文字幅は全角=2、半角=1 を扱うヘルパー `get_east_asian_width_count` / `pad_str` が存在。
- 保存される日時は ISO 文字列（`datetime.now().isoformat()`）で `breakingNewsTimestamp` に入る。
- 区間遷移に関しては `currentLeg`（現在区間）と `newCurrentLeg`（計算後の区間）が併存する。`save_ekiden_state` では `newCurrentLeg` を `currentLeg` 化して保存している点に注意。
- シャドーチームは順位算出の集合に含めないが、位置表示など別の出力に含める（`is_shadow_confederation` フラグ）。

## 実行・デバッグの具体的手順
1. 仮想環境と依存関係
   - Python 仮想環境を作って依存を入れる: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
2. リアルタイム実行（ローカルで速報 JSON を作る）
   - 例: `python scripts/generate_report.py --realtime`
   - 比較用に `data/realtime_report.json` を `data/realtime_report_previous.json` にコピーしておくと挙動確認しやすい。
3. 通知テスト
   - `.env` はリポジトリルート（`Path(__file__).resolve().parent.parent / '.env'`）に置く。
   - 必要な環境変数: `PROD_PUSH_API_URL`, `API_SECRET_KEY`。
   - 通知を強制するテスト: `python scripts/generate_report.py --realtime --test-notification`
4. コミット（当日確定保存）
   - `python scripts/generate_report.py --commit`（スクリプトは `--commit` 時に `save_ekiden_state` / leg 履歴更新 / 個人記録保存 を行う）
5. テスト
   - 既存のテスト例: `15/test_generate_report.py` がある。実行: `pytest -q 15/test_generate_report.py`

## 外部依存と統合ポイント（要注意）
- Web スクレイピング先: Yahoo 天気 (`fetch_max_temperature`, `fetch_current_temperature`)。通信エラーや DOM 変化で壊れやすい。
- 掲示板スクレイピング: `outline.json` の `mainThreadUrl` を使って監督コメントを収集。HTML 構造変更に注意。
- 通知: `send_push_notification` が `PUSH_API_URL/api/send-notification` に POST するため、受け側 API の仕様変更に注意。

## 典型的な修正パターンとサンプル箇所
- 「速報コメント」ロジックは `generate_breaking_news_comment` と複数の `_generate_*_comment` 関数に分かれている。新しい速報ルールを追加するならここを拡張。
- 区間完了判定は `ekiden_data['leg_boundaries']` と `totalDistance` を比較する実装。新しい区間ルールはここに集約される。
- 個人記録の更新は `individual_results` と `legSummaries` を操作する箇所に実装されている（`today_leg_records` と `legs_completed_today` の使い方を踏襲する）。

## 出力検証の短いチェックリスト
- `data/realtime_report.json` が存在し、`teams` 配列に `overallRank` が入っているか。
- `breakingNewsTimestamp` が ISO 形式で入っているか。
- 通知を期待する場合、`PROD_PUSH_API_URL` が設定され `send_push_notification` のエラーが出ていないかログを確認。

---
レビューお願いします: 不明瞭な内部ルール（例: 特定フィールド名の由来、サーバー側 API の細かい挙動）があれば教えてください。必要なら具体的なコード例（小さな修正パッチ）を追加します。
