# 技術スタック
更新日: 2025-10-09

## 言語・ランタイム
- **Python 3.11** (想定): バックエンドスクリプト (`scripts/`)。仮想環境 `venv/` を利用。
- **Shell (bash)**: cron 用ラッパースクリプト、Git 自動コミット。
- **JavaScript (ES2020)**: フロントロジック (`app.js`, `app_16.js`)。ブラウザ実行。
- **HTML/CSS**: `index.html`, `index_16.html`。CDN 由来のスタイルを併用。

## 主要ライブラリ
### バックエンド
- `requests`, `beautifulsoup4`: Yahoo!天気/5ch のスクレイピング。
- `pandas`, `numpy`: データ集計・整形。
- `pydantic` (導入検討中): JSON スキーマ検証。
- `google-generativeai` (Gemini API クライアント): AI 記事生成。

### フロントエンド
- **Leaflet.js** + `leaflet-omnivore`: コースマップとマーカー表示。
- **Chart.js**: 順位変動グラフ・距離推移グラフ。
- **date-fns**: 日付フォーマットとローカライズ。
- **Papa Parse** (検討中): CSV インポート処理の簡素化。

## インフラ・外部サービス
- **GitHub Pages**: 静的ホスティング。
- **GitHub Actions (予定)**: 将来的な自動デプロイ/テスト導入を検討。
- **Yahoo!天気 (HTML スクレイピング)**: 気温データの主ソース。
- **5ch スレッド**: 監督コメント取得元。
- **Gemini API**: AI 記事生成および分析支援。
- **Push API サーバ** (`push_server.py`): 外部通知 (任意設定)。

## 開発環境・ツール
- VS Code / Cursor / Codex CLI: 日常開発。
- `requirements.txt`: バックエンド依存関係の管理。
- `commit_daily.sh` 等のシェル: 定期実行と Git 自動操作。
- `logs/`: cron 実行結果の記録。障害時の一次情報。

## 品質・監視
- **テスト**: 現状はスクリプト単体テスト未整備。第16回に向けて `pytest` 導入検討。
- **ロギング**: シェルスクリプト内で `logs/` に日次ログを残し、異常検知に活用。
- **監視案**: GitHub Actions or 外部サービスでの疎通監視を検討。

## 参考ドキュメント
- 運用とデータフロー: `docs/Gemini.md`
- 仕様と要件: `docs/requirements.md`
- タスクボード: `docs/development_tasks.md`
- 最新ドキュメント一覧: `docs/documentation_index.md`

