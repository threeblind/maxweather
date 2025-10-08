**協業メモ:** Aさん（企画・要望の提示）・Cさん（設計と実装および進行管理）・Gさん（分析支援・レビュー・記事生成）の三者で連携する。Aさんは要望や疑問をCさんへ渡し、Cさんが文脈を整理して必要に応じてGさんに質問や調査・レビュー依頼・文章生成を行い、その結果を要約してAさんへフィードバックする。
# Codex リファレンスメモ

## 目的
- Codex や他のアシスタントが、既存コードを変更せずにプロジェクト全体を理解するためのガイド。
- `README.md` や `Gemini.md` に書ききれていない開発者の意図や実運用のニュアンスを補足する。

## コミュニケーション方針
- すべての回答は日本語で行う。
- ソースコードの修正や追加を行う際は、実装前に必ず変更案を提案し承認を得る。

## プロジェクト概要
- 架空大会「高温大学駅伝」の速報サイト。各選手の走行距離 = 担当アメダス地点の最高気温というルールで進行。
- バックエンド（Python + cron + シェル）が Yahoo!天気・5ch をスクレイピングし、JSON を生成・更新。
- フロントエンド（プレーン HTML/JS）が生成済み JSON を読み込み、地図・グラフ・コメント等を表示。
- **現在運用中は第15回大会。来季（第16回）向けの準備ファイルが `index_16.html` / `app_16.js` にある。** 15回大会の本番用ファイルは `index.html`, `app.js`（および `15/` ディレクトリ）に配置。

## 日次オペレーション
1. **リアルタイム更新 (07:00–19:00)**  
   - `update_realtime.sh` → `scripts/generate_report.py --realtime`  
   - 各選手の最高/現在気温を取得し、`data/realtime_report.json`、`data/runner_locations.json`、`data/realtime_log.jsonl` を更新。  
   - 直近10分以内の監督コメントを拾って速報コメントを生成。  
   - 差分があれば自動で git commit & push（シェルスクリプト側で制御）。
2. **夜間コメント取得 (19:00–07:00)**  
   - `update_manager_comments.sh` → `scripts/fetch_manager_comments.py`  
   - 5ch の監督談話を整理し `data/manager_comments.json` へ保存。
3. **1日の締め (23:55 頃)**  
   - `commit_daily.sh` が以下を実行：  
     - `scripts/update_all_records.py` → 全登録選手(補欠含む)の最終最高気温を取得し `data/daily_temperatures.json` と `data/intramural_rankings.json` を更新。  
     - `scripts/generate_report.py --commit` → `data/ekiden_state.json` を確定、区間順位・履歴系 JSON を更新、`data/realtime_log.jsonl` を日付付きファイルへアーカイブ。  
     - Git コミット・ログ整理など。
4. **AI 日次総括**  
   - `scripts/generate_daily_summary.py` が Gemini プロンプトを組み立て `data/daily_summary.json` を出力。  
   - `data/article_history.json` にプロンプトと記事を保存し、物語の連続性を持たせる。

## 主なバックエンドスクリプト
- `scripts/generate_report.py`  
  - リアルタイム/コミット両モードのエントリーポイント。  
  - `config/ekiden_data.json` や `config/shadow_team.json` といった設定、歴史データを一括読み込み。  
  - 正規チームとシャドーチームを順に更新し、走行区間や個人記録、区間通過履歴、地図用座標、速報コメントなどを算出。  
  - Yahoo!天気 HTML を直接スクレイピング（構造変更リスクはあるが、エラーメッセージで吸収）。  
  - Push 通知は `.env` に設定された `PROD_PUSH_API_URL` / `API_SECRET_KEY` を使用（未設定ならスキップ）。
- `scripts/update_all_records.py`  
  - 全登録選手の最終データを揃え、学内ランキング用 JSON を生成。
- `scripts/fetch_manager_comments.py`  
  - 監督談話スレを巡回し、HTML を正規化した上で JSON 化。
- 各種シェル (`update_realtime.sh`, `update_manager_comments.sh`, `commit_daily.sh`)  
  - cron 実行前提でログの整形、git 操作を管理。

## フロントエンド構成
- `index_16.html`  
  - レイアウトとスタイルを全て内包。Chart.js、Leaflet、OMS、date-fns（日本語ロケール）、Google Fonts を CDN から読み込み。  
  - セクション構成：ナビ・速報コメント・マップ・各種ランキング・区間賞・エントリー・AI記事・監督談話・アメダス検索/全国ランキングなど。  
  - 大会固有の文言（タイトル等）は直接埋め込み。
- `app_16.js`  
  - データ取得、テーブル描画、Leaflet マーカー更新、チャート描画、検索系 UI などを一括で制御。  
  - `EKIDEN_START_DATE`, `CURRENT_EDITION` は毎年更新が必要。  
  - ブラウザ側のスクレイピングは allorigins プロキシ経由。
- 15回大会のコードは `15/` 配下。来年も基本的にはコピーして調整する想定。

## 生成／利用されるデータ
- `data/` 以下の主な JSON  
  - `realtime_report.json`, `individual_results.json`, `rank_history.json`, `leg_rank_history.json`, `runner_locations.json`, `daily_summary.json`, `manager_comments.json`, `intramural_rankings.json`, `daily_temperatures.json`, `ekiden_state.json`, `realtime_log*.jsonl` など。  
  - これらをフロントがポーリングまたは読み込みして画面を更新。
- `config/`  
  - チーム情報、シャドーチーム設定、コース、プレイヤープロフィール、概要 URL、AI プロンプトテンプレートなど。
- `history_data/`  
  - 過去大会の記録やストーリー設定。AI のコンテキストやフロントの参考情報に利用。
- `EKIDEN_START_DATE = '2025-09-01'` が複数スクリプトで共有されているため、次回繰り上げ時は一括で更新。

## AI 日次記事生成フロー
- `scripts/generate_daily_summary.py`  
  - `realtime_report.json`, `manager_comments.json`, `rank_history.json`, `config/summary_prompt_template.txt` を読み込み。  
  - `--dry-run` を指定すると Gemini 呼び出しなしでプロンプト確認のみ。  
  - 生成後は大学名・選手名を自動で太字化。  
  - プロンプトと記事を `data/article_history.json` の先頭に追記（最大10件保持）。  
  - 出力 JSON は `{"date": "YYYY/MM/DD", "article": "..."}` のシンプルな形。

## 運用メモ
- `.env` に Gemini キーや Push 通知用エンドポイントを設定する。  
- シェルスクリプトはリポジトリルートでの実行を想定し、git に依存。  
- スクレイピングはレスポンスが遅い場合があるため、`update_all_records.py` では 0.5秒スリープを挟んでいる。  
- Leaflet アイコンなど一部アセットは CDN 依存。  
- `manifest.json`, `sw.js` が存在するので、次年度更新時は表記の調整を忘れずに。

## 開発者の意図・方針
- メンテナは単独。商用ではなく、自分が使いやすいことが最優先。  
- 大規模リファクタより **新機能や改善アイデアの追加** を重視。  
- ファイル名に大会番号を付ける（例: `index_16.html`）のは意図的。多少の複雑さは許容。  
- テストは手動が主体。既存フロー（cron, スクレイピング）を壊さないことが重要。
- ユーザーの大半はスマートフォンで閲覧する（勤務中の休憩時間等）。モバイルでも下位校まで一望できることが重要で、一覧を省略しない方針。

## 運用タスクのメモ

### 1. 大会切り替え時のデータ初期化（例: 第16回開始前）
1. cron の `update_realtime.sh`, `update_manager_comments.sh`, `update_substitutions.sh`, `commit_daily.sh` を一時停止。  
2. 最新の 15回大会データをアーカイブ（例: `mv data data_15_archive && mkdir data`、`mv logs logs_15_archive && mkdir logs`）。  
3. `config/` ディレクトリを第16回仕様に更新（チーム編成、コース、outline、player_profiles など）。  
4. `EKIDEN_START_DATE` を Python / JS の全ファイルで揃える（`scripts/generate_report.py`, `scripts/update_all_records.py`, `app_16.js` 等）。  
5. `data/` 配下は空でも問題なし。初回の `python scripts/generate_report.py --realtime` 実行で `ekiden_state.json`, `individual_results.json`, `rank_history.json`, `leg_rank_history.json`, `runner_locations.json`, `realtime_report.json` などが自動生成される。  
   - 手動でゼロ初期化したい場合は `python scripts/rebuild_history.py` の `initialize_result_files()` を参考にする。  
6. `logs/substitution_log.txt` も新規作成または空ファイルにしておく。  
7. フロント公開用に `index_16.html` / `app_16.js` を `index.html` / `app.js` に差し替えるか、GitHub Pages 側で参照先を更新。  
8. ローカルで `python scripts/generate_report.py --realtime` を1回実行し、生成された JSON を確認。問題なければ cron を再開。

### 2. 監督の交代宣言があったとき
1. 夜間帯（18:00–24:00）に cron の `update_substitutions.sh` が動いていれば自動処理。  
2. 手動で行う場合  
   1. `source venv/bin/activate`  
   2. `python scripts/process_substitutions.py` を実行し、5ch スレを解析させる。  
   3. 成功時は `config/ekiden_data.json` と `logs/substitution_log.txt` が更新されるので、`git status` で確認しコミット＆プッシュ。  
3. 自動解析に失敗した場合は、手動コマンド `python scripts/substitute_runner.py --team-id <ID> --old <交代前選手> --new <交代後選手>` を実行。  
4. 交代処理後に `python scripts/generate_report.py --realtime` を1度回し、`data/realtime_report.json` 等に反映されているかチェックする。

## 次回大会を見据えた軽いアドバイス
- 第16回開始時は上記「データ初期化」手順を参考にし、15回大会の成果物をアーカイブ。  
- 第17回以降に向けては、大会メタ情報を json 化しておくと大会番号の差し替えが楽になる。  
- 新しい JSON や追加仕様を導入した際は、本メモと `README.md` に概要を追記する。  
- Yahoo!天気の DOM 変更が発生した際は、前回値で暫定対応するなど復旧プランを用意しておく。
