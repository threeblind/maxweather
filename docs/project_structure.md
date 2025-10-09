# プロジェクト構造・データ構造
更新日: 2025-10-09

## 文書の目的
- リポジトリ内の主要ディレクトリとファイルの役割を俯瞰し、オンボーディングと保守を容易にする。
- 主要な JSON データのスキーマ概要を整理し、バックエンド・フロントエンド間のインターフェースを明確化する。

## ディレクトリ概要
| パス | 役割 | 補足 |
| --- | --- | --- |
| `config/` | 大会設定・コースデータ・AIプロンプト | `ekiden_data.json`, `outline.json`, `shadow_team.json` など |
| `data/` | バックエンド生成の公開データおよびアーカイブ | JSON 群と `archive/` (日次ログ) |
| `docs/` | ドキュメント | `README.md`, `Gemini.md`, `Codex-notes.md`, 本文書など |
| `scripts/` | Python スクリプト本体 | レポート生成・AI記事・コメント取得など |
| `logs/` | cron やスクリプト出力ログ | 失敗時のトラブルシュートで参照 |
| `images/` | フロントで使用する静的画像 | 大会バナーなど |
| `index.html` / `app.js` | 第15回大会のフロントエンド | UI ロジックは `app.js` に集約 |
| `index_16.html` / `app_16.js` | 第16回向け準備版 | 次大会仕様の検証用 |
| `sw.js` | Service Worker | キャッシュ制御・オフライン対策 |
| `scripts/*.sh` | cron 用シェル | 自動実行と Git コミット制御 |

## 実行フロー（概要）
1. **リアルタイム更新 (07:00–19:00)**  
   `update_realtime.sh` → `scripts/generate_report.py --realtime`。  
   - 気象データをスクレイピングし、`realtime_report.json`・`runner_locations.json`・`realtime_log.jsonl` 等を更新。
   - 監督コメントの抽出と速報コメント生成を同時に実行。
2. **夜間コメント取得 (19:00–07:00)**  
   `update_manager_comments.sh` → `scripts/fetch_manager_comments.py`。  
   - 監督談話室ログを `manager_comments.json` に保存。
3. **日次確定処理 (23:55 頃)**  
   `commit_daily.sh` が `scripts/update_all_records.py`・`scripts/generate_report.py --commit` を実行。  
   - 区間順位や学内ランキング (`intramural_rankings.json`) を更新し、`realtime_log.jsonl` を `archive/` に移動。  
4. **AI 日次記事生成**  
   `scripts/generate_daily_summary.py` が Gemini を利用して記事 (`daily_summary.json`) を作成し、履歴 (`article_history.json`) に追記。

詳細な運用メモは `docs/Gemini.md`・`docs/Codex-notes.md` を参照。

## 主なデータ構造
### `data/realtime_report.json`
- `updateTime` (str): 最終更新時刻 (ISO8601)。
- `raceDay` (int): 開催何日目かを示す日数。
- `breakingNewsComment` / `breakingNewsFullText` / `breakingNewsTimestamp`: 速報コメントとタイムスタンプ。
- `teams` (list): 各チームの現在情報。
  - `id`, `name`, `short_name`
  - `currentLeg` (int), `runner` (str), `nextRunner` (str)
  - `todayDistance`, `todayRank`, `totalDistance`, `overallRank`, `previousRank`
  - `finishDay` (int or `null`), `error` (str or `null`)
  - `is_shadow_confederation` (bool)

### `data/runner_locations.json`
- リスト形式。マーカー描画用に以下のフィールドを保持。
  - `rank`, `team_name`, `team_short_name`, `runner_name`
  - `total_distance_km`, `latitude`, `longitude`
  - `is_shadow_confederation`

### `data/rank_history.json`
- `dates` (list[str]): 日次の計測日。フロントの折れ線グラフ横軸。
- `teams` (list[dict]): チームごとの履歴。
  - `id`, `name`
  - `ranks` (list[int]): `dates` に対応する総合順位。
  - `distances` (list[float]): 同日の累積距離。

### `data/leg_rank_history.json`
- `teams` (list[dict]):
  - `id`, `name`
  - `leg_ranks` (list[int]): 区間ごとの順位 (インデックスは区間番号-1)。

### `data/individual_results.json`
- キー: チーム名称。値は `dict`。
  - `teamId`, `totalDistance`
  - `records` (list):
    - `day` (int): 出走日。
    - `leg` (int): 区間番号。
    - `distance` (float): その区間の走行距離 (= 最高気温)。

### `data/intramural_rankings.json`
- `updateTime` (str)
- `teams` (list):
  - `id`, `name`, `short_name`
  - `daily_results` (list):
    - `runner_name`, `distance`, `status` (例: `"走行済"`, `"補欠"`)

### `data/daily_temperatures.json`
- キー: 日付 (`YYYY-MM-DD`)。
- 値: `dict` (キー=観測地点名, 値=最高気温 float)。
- 監督コメント生成や学内ランキングの基礎データとして利用。

### そのほかのファイル
- `data/manager_comments.json`: 監督談話のログ (`timestamp`, `author`, `body`)。  
- `data/daily_summary.json`: AI 記事 (`title`, `body`, `highlights`, `author` など)。  
- `data/article_history.json`: 過去記事の履歴とプロンプトメタ情報。

## フロントエンド構成
- `index.html` / `index_16.html`: UI セクションの HTML 定義。Leaflet/Chart.js/CDN 読み込み。
- `app.js` / `app_16.js`: fetch/描画ロジック、モーダル・チャート管理、アニメーション制御。
- `sw.js`: キャッシュ戦略。最新データの常時取得を優先しつつ、静的アセットのキャッシュを保持。
- `images/`: バナーやチームロゴなどを格納。

## デプロイ・配信
- GitHub Pages (`https://threeblind.github.io/maxweather/`) をホスティングに利用。
- バックエンド生成物は Git コミットを介して公開ブランチへ反映される。
- Push 通知 (`push_server.py`) や外部 API 連携は `.env` による設定で切り替え。

## 参照ドキュメント
- 運用メモ・開発履歴: `docs/Gemini.md`
- 協業フロー・コミュニケーション: `docs/Codex-notes.md`
- 要件・仕様: `docs/requirements.md` (本書とセットで参照)

