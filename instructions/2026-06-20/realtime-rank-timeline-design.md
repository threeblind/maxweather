# リアルタイム順位変動タイムライン 詳細設計

- 作成日: 2026-06-20
- 対象: 第16回大会フロントエンド
- 対象ファイル: `index_16.html`, `app_16.js`
- 主データ: `data/realtime_log.jsonl`
- 目的: 現在順位だけでは分からない「いつ、どの大学が、何位から何位へ動いたか」を実況ログ形式で表示する

## 1. 完成時の仕様

速報マップの直下、総合順位の直前に「順位変動タイムライン」を追加する。

PCでは最新3件を初期表示し、「すべて見る」で当日分を展開する。スマートフォンでは最新1件を初期表示し、同じボタンで展開する。イベントは新しい順に並べる。

```text
順位変動タイムライン                         08:35更新
[すべて] [順位変動] [記録更新]

08:35  ▲ 熊本学園大  12位 → 10位
       甲佐が28.1kmを記録。2校を逆転

08:25  ▲ 福岡大       3位 → 2位
       総合87.8km。名古屋大との差は2.7km

08:15  👑 名古屋大が首位
       総合90.5km

                         [すべて見る（12件）]
```

## 2. 配置とメニュー

### 2.1 セクション配置

`index_16.html` の速報マップセクションの終了直後かつ `#section-overall-ranking` の直前に、次のセクションを追加する。

```html
<section id="section-rank-timeline" class="ekiden-section-wrapper rank-timeline-section" aria-labelledby="rank-timeline-title">
    <div class="section-header rank-timeline-header">
        <div>
            <h2 id="rank-timeline-title">順位変動タイムライン</h2>
            <p id="rank-timeline-update-time" class="update-time" aria-live="polite"></p>
        </div>
    </div>

    <div class="rank-timeline-filters" role="group" aria-label="タイムラインの表示種別">
        <button type="button" class="rank-timeline-filter active" data-filter="all" aria-pressed="true">すべて</button>
        <button type="button" class="rank-timeline-filter" data-filter="rank" aria-pressed="false">順位変動</button>
        <button type="button" class="rank-timeline-filter" data-filter="record" aria-pressed="false">記録更新</button>
    </div>

    <p id="rank-timeline-status" class="status-message" aria-live="polite">タイムラインを読み込んでいます…</p>
    <ol id="rank-timeline-list" class="rank-timeline-list" aria-live="polite"></ol>
    <button type="button" id="rank-timeline-toggle" class="rank-timeline-toggle" aria-expanded="false" hidden></button>
</section>
```

### 2.2 グローバルメニュー

`#main-nav-list` の「速報」系ドロップダウンに以下を追加する。該当ドロップダウンがない構造なら「速報マップ」の直後に独立項目として追加する。

```html
<li><a href="#section-rank-timeline">順位変動</a></li>
```

表示名は短く「順位変動」とする。リンク先見出しは内容が明確になるよう「順位変動タイムライン」とする。

既存の `.page-nav a[href]` のスムーススクロール処理を利用し、新しい専用クリック処理は追加しない。

## 3. 初期リリースのイベント種別

| type | 表示 | 発生条件 | category |
| --- | --- | --- | --- |
| `leader_change` | 👑 首位交代 | 直前スナップショットと首位チームが異なる | `rank` |
| `rank_up` | ▲ 順位上昇 | チーム順位の数値が小さくなる | `rank` |
| `rank_down` | ▼ 順位下降 | チーム順位の数値が大きくなる | `rank` |
| `daily_record` | 🔥 本日最高記録を更新 | 当日中の全選手の `distance` 最大値を更新 | `record` |

順位変動は、同一時刻に動いた全チームについてイベントを生成する。ただし首位になったチームは `leader_change` のみとし、同時刻の `rank_up` を重複生成しない。

順位下降は生成するが、初期表示の優先度を低くする。大量にイベントが発生した場合でも「すべて」には残す。

## 4. 入力データ

### 4.1 `data/realtime_log.jsonl`

1行1レコードで次の値を使用する。

```json
{"timestamp":"2026-06-20T00:15:10.165564","team_id":7,"runner_name":"1久留米","distance":25.4,"total_distance":87.0}
```

必須項目:

- `timestamp`: スナップショット時刻
- `team_id`: チームID
- `runner_name`: 当時の走者名
- `distance`: 当日の選手記録
- `total_distance`: チーム総合距離

### 4.2 `config/ekiden_data.json`

`team_id` から以下を取得する。

- 大学正式名
- 短縮名
- チームカラー

既存の `ekidenDataCache` と `teamColorMap` を利用し、同じマスタを再取得しない。

### 4.3 時刻の扱い

ログの `timestamp` は現在の生成処理ではUTC相当の値がタイムゾーンなしで記録されている。画面上では日本時間として9時間加算する必要がある。

実装時は既存ログ生成側の実態を確認し、次の関数に変換を集約する。

```js
function parseRealtimeLogTimestamp(value) {
    // 現行ログがUTCのnaive datetimeである間は末尾にZを付けて解釈する。
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
    return new Date(normalized);
}
```

表示は `toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' })` を使う。

## 5. ログ解析仕様

### 5.1 スナップショット作成

1. JSONLを改行で分割する。
2. 空行を除外する。
3. 各行を個別に `JSON.parse` する。壊れた行はその行だけ無視する。
4. `timestamp` が同一のレコードを1スナップショットとしてグループ化する。
5. スナップショットを時刻の昇順に並べる。
6. 同じスナップショット内で `team_id` が重複した場合は後に出現したレコードを採用する。

### 5.2 順位計算

各スナップショットを `total_distance` の降順で並べる。同距離は次の順で安定化する。

1. `total_distance` 降順
2. 直前スナップショットの順位昇順
3. `team_id` 昇順

同距離は同順位にせず、表示上の総合順位表と同じく一意な順位を付ける。前回順位を第2ソート条件にすることで、数値が同じだけの不必要な順位入れ替えを防ぐ。

チーム数が不足するスナップショットは以下のように扱う。

- 最初の完全なスナップショットが現れるまではイベントを生成しない。
- 完全性の基準は、現在の `realtime_report.json` で `overallRank != null` の通常チーム数とする。
- 一度完全になった後に一部チームが欠けたスナップショットは、そのスナップショット全体を順位イベント計算から除外する。
- `daily_record` は有効な行だけで判定できるため、スナップショットが不完全でも生成してよい。

### 5.3 イベント生成

直前の有効スナップショットと現在の有効スナップショットを比較する。

イベント内部形式:

```js
{
    id: '2026-06-20T00:35:09.301308-rank_up-7',
    timestamp: Date,
    type: 'rank_up',
    category: 'rank',
    teamId: 7,
    runnerName: '1久留米',
    oldRank: 3,
    newRank: 2,
    rankDelta: 1,
    distance: 25.4,
    totalDistance: 87.1,
    leaderGap: 3.4
}
```

`rankDelta` は上昇時に正数、下降時に負数とする。`leaderGap` は同じスナップショットの首位総距離との差で、首位の場合は0。

同じチーム・同じ種類・同じ新順位のイベントが連続2スナップショットで発生したように見える場合は、先の1件のみ残す。通常は起きないが、欠損復帰時の重複を防ぐために実施する。

### 5.4 本日最高記録

時刻昇順で走査し、その時点までの最大 `distance` を保持する。

- 初回スナップショットは基準値として扱い、イベントを生成しない。
- 以降、従来最大値を0.1km以上更新した場合に生成する。
- 同一スナップショットで同値の新記録が複数ある場合は全員分を生成する。
- 選手名の区間番号接頭辞は表示時に既存 `formatRunnerName()` で整形する。

### 5.5 並び順と優先度

最終表示は次でソートする。

1. `timestamp` 降順
2. 同時刻では `leader_change`
3. `daily_record`
4. `rank_up`（上昇幅の大きい順）
5. `rank_down`（下降幅の大きい順）
6. `teamId` 昇順

最大保持件数は当日200件とする。200件を超えた古いイベントは表示対象外にする。

## 6. 表示文言

### 6.1 首位交代

- 見出し: `名古屋大学が首位へ`
- 詳細: `3位 → 1位、総合90.5km`
- アイコン: `👑`

### 6.2 順位上昇

- 見出し: `福岡大学 3位 → 2位`
- 詳細: 1つ上昇なら `1ランクアップ。首位との差は2.7km`
- 詳細: 複数上昇なら `2ランクアップ。首位との差は2.7km`
- アイコン: `▲`

### 6.3 順位下降

- 見出し: `鳥取大学 3位 → 4位`
- 詳細: `1ランクダウン、総合86.5km`
- アイコン: `▼`

### 6.4 本日最高記録

- 見出し: `甲佐が本日最高を更新`
- 詳細: `28.1km（熊本学園大学）`
- アイコン: `🔥`

距離はすべて小数第1位まで表示する。差が0の場合は「首位と同距離」とする。

## 7. DOM描画

各イベントは `<li>` で生成する。文字列連結による `innerHTML` へ入力データを直接渡さず、原則として `textContent` を使用する。

```html
<li class="rank-timeline-item rank-timeline-item--up" data-team-id="7">
    <time class="rank-timeline-time" datetime="2026-06-20T00:35:09.301Z">09:35</time>
    <span class="rank-timeline-icon" aria-hidden="true">▲</span>
    <div class="rank-timeline-content">
        <button type="button" class="rank-timeline-team">福岡大学 3位 → 2位</button>
        <p class="rank-timeline-detail">1ランクアップ。首位との差は3.4km</p>
    </div>
</li>
```

大学名のボタン押下時:

1. `runnerLocations` のキャッシュから対象チームを取得する。
2. 取得できれば既存マップの対象マーカーへ移動し、ポップアップを開く。
3. マップ情報がない場合は `showTeamDetailsModal()` 相当のチーム詳細を開く。
4. どちらも利用できない場合でもボタン操作でエラーを出さない。

マップ連携が既存関数へ安全に接続できない場合、初期実装ではボタンを通常テキストにしてよい。その場合でも `data-team-id` は付与して次フェーズで接続可能にする。

## 8. 展開・フィルター動作

状態変数:

```js
let rankTimelineEvents = [];
let rankTimelineFilter = 'all';
let isRankTimelineExpanded = false;
```

初期表示件数:

- 幅768px超: 3件
- 幅768px以下: 1件
- 展開時: フィルターに一致する全件（最大200件）

フィルター変更時:

- `all`: 全種別
- `rank`: `leader_change`, `rank_up`, `rank_down`
- `record`: `daily_record`
- フィルター変更後も展開状態は維持する。
- ボタンの `.active` と `aria-pressed` を同期する。
- 表示件数ゼロなら「該当する順位変動はまだありません。」を表示する。

展開ボタン文言:

- 閉じた状態: `すべて見る（12件）`
- 開いた状態: `折りたたむ`
- 対象件数が初期表示件数以下なら `hidden = true`
- `aria-expanded` を必ず同期する。

ウィンドウ幅変更時は現在の展開状態を維持し、閉じている場合のみ表示件数を1件/3件に切り替える。

## 9. 更新処理への組み込み

### 9.1 初期ロード

`fetchEkidenData()` で取得済みの `logFileRes` を存在確認だけで捨てず、本文を読み取ってタイムライン生成へ渡す。

ただし同じResponseは複数回読めないため、次のどちらかに統一する。

- 推奨: `logFileRes.ok ? await logFileRes.text() : ''` とし、プロフィール側で必要な場合は従来どおり個別fetchする。
- 代案: タイムライン専用の `loadRankTimeline()` が個別fetchする。

推奨構成:

```js
async function loadRankTimeline({ force = false } = {})
function parseRealtimeLogJsonl(text)
function buildRankSnapshots(records)
function calculateSnapshotRanks(snapshots, expectedTeamIds)
function generateRankTimelineEvents(rankedSnapshots)
function renderRankTimeline()
```

### 9.2 定期更新

既存 `refreshRealtimeData()` の成功後に `loadRankTimeline({ force: true })` を呼ぶ。タイムライン取得失敗で総合順位・マップ更新まで失敗扱いにしないよう、別の `try/catch` に分離する。

既存の更新間隔に追従し、タイムライン独自の `setInterval` は作らない。

### 9.3 通信

```js
fetch(`data/realtime_log.jsonl?_=${Date.now()}`, { cache: 'no-store' })
```

HTTP 404は「大会開始前またはログ未生成」として空状態を表示し、コンソールエラーにはしない。その他の非2xxは警告を出し、直前に表示済みのイベントがあれば消さずに維持する。

## 10. 空・エラー・大会終了状態

| 状態 | 表示 |
| --- | --- |
| 読込中 | `タイムラインを読み込んでいます…` |
| ログなし/404 | `本日の順位変動はまだありません。` |
| 有効スナップショット1件のみ | `比較できる次回更新を待っています。` |
| フィルター結果0件 | `該当する順位変動はまだありません。` |
| 更新失敗・過去表示あり | 過去表示を維持し、更新時刻の横に `更新に失敗しました` |
| 更新失敗・表示なし | `タイムラインを取得できませんでした。` と再読み込みボタン |
| 全チーム終了後 | 当日イベントをそのまま表示。特別に非表示にしない |

再読み込みボタンは `loadRankTimeline({ force: true })` を呼ぶ。

## 11. CSS要件

既存の色変数を優先して使用する。固定色を使う場合もライト・ダーク双方で読めるコントラストを確保する。

主要クラス:

- `.rank-timeline-section`: 通常セクションと同じ余白
- `.rank-timeline-header`: 見出しと更新時刻を横並び、スマホでは折返し可
- `.rank-timeline-filters`: ボタン横並び、画面幅不足時は横スクロール可
- `.rank-timeline-list`: `list-style: none; padding: 0; margin: 0;`
- `.rank-timeline-item`: 時刻、アイコン、本文の3列グリッド
- `.rank-timeline-item--leader`: 左線またはアイコンを金系
- `.rank-timeline-item--up`: 上昇を赤系（現行順位表の上昇色に合わせる）
- `.rank-timeline-item--down`: 下降を青系（現行順位表の下降色に合わせる）
- `.rank-timeline-item--record`: 記録更新をオレンジ系
- `.rank-timeline-team`: リンク風ボタン。44px以上のタップ領域
- `.rank-timeline-detail`: muted色、本文より小さく

PCの推奨グリッド:

```css
.rank-timeline-item {
    display: grid;
    grid-template-columns: 3.5rem 1.75rem minmax(0, 1fr);
    gap: 0.75rem;
    padding: 0.9rem 0;
    border-bottom: 1px solid var(--border-color);
}
```

スマートフォンでは時刻を3rem、間隔を0.5rem程度に縮める。横スクロールは発生させない。大学名・説明は折り返す。

`prefers-reduced-motion: reduce` の場合は、新着ハイライトなどのアニメーションを無効化する。初期リリースではアニメーション自体を付けなくてもよい。

## 12. アクセシビリティ

- セクション見出しを `aria-labelledby` で関連付ける。
- 更新時刻と状態表示は `aria-live="polite"`。
- 一覧更新時にリスト全体へフォーカスを移動しない。
- 色だけで種別を表現せず、アイコン・文言を併用する。
- アイコンは装飾なので `aria-hidden="true"`。
- フィルターは `aria-pressed`、展開は `aria-expanded` を同期する。
- キーボードだけでフィルター、大学リンク、展開ボタンを操作可能にする。

## 13. 実装上の注意

- シャドーチームなど `overallRank == null` のチームは順位計算から除外する。
- ログ内の未知 `team_id` は無視する。
- `distance` または `total_distance` が有限数でない行は無視する。
- ログは更新途中で末尾行だけ不完全になる可能性がある。行単位で例外処理し、全体を失敗させない。
- 大会日をまたいだデータが混在した場合は、最新の `realtime_report.raceDay` に対応する当日ログだけを使用する。現状ファイルが日次リセットされる前提でも、タイムスタンプの日付単位で最新日だけに絞る。
- 初回ロード時にイベントを「新着」として通知しない。これは画面内表示機能であり、既存Push通知処理とは接続しない。
- `innerHTML` を使って大学名や選手名を埋め込まない。

## 14. テスト項目

### 14.1 ロジック単体確認

1. 18チームの距離順から1〜18位が生成される。
2. 2チームの距離が逆転すると上昇・下降イベントが各1件生成される。
3. 3位から1位になったチームは首位交代1件だけで、順位上昇が重複しない。
4. 同距離時は前回順位を維持する。
5. スナップショット欠損時に誤った大量順位変動を生成しない。
6. JSONL末尾が壊れていても、それ以前の行から表示できる。
7. 最高記録の初期値ではイベントを出さず、0.1km更新時だけ出す。
8. 未知チームと順位対象外チームを除外する。
9. UTC相当の `00:35` が画面上で日本時間 `09:35` になる。
10. イベントIDが再取得後も同じになり、重複表示されない。

### 14.2 UI確認

1. PC初期表示が3件、スマホ初期表示が1件。
2. 「すべて見る」と「折りたたむ」が正しく切り替わる。
3. 各フィルターの件数と内容が正しい。
4. メニューの「順位変動」からセクションへ移動できる。
5. スマホで横スクロールが発生しない。
6. ダークモードでも文字・罫線・種別が判別できる。
7. キーボード操作とスクリーンリーダー用状態値が正しい。
8. 60秒更新後に新イベントが先頭へ追加される。
9. ログ取得失敗時もマップと総合順位の更新が継続する。

### 14.3 実データ確認

`data/realtime_log.jsonl` を使い、画面に出た順位変動を同時刻の `total_distance` 降順と照合する。最低でも以下を確認する。

- 最初の完全スナップショットではイベントが出ていない。
- 2回目以降の順位が手計算と一致する。
- 時刻が日本時間表示になっている。
- 現在の総合順位と最新スナップショットの順位が一致する。

## 15. 受入条件

- 速報マップ直下、総合順位直前にタイムラインが表示される。
- グローバルメニューの「順位変動」から移動できる。
- 当日の順位上昇、順位下降、首位交代、本日最高記録更新が実ログから自動生成される。
- PCは3件、スマホは1件が初期表示され、全件展開できる。
- 「すべて」「順位変動」「記録更新」で絞り込める。
- 既存リアルタイム更新に追従し、ページ再読込なしで内容が更新される。
- ログ欠損・壊れた末尾行・HTTP 404でページ全体が停止しない。
- マップ、総合順位、プロフィール、Push通知など既存機能の動作を妨げない。
- PC/スマホ、ライト/ダークモード、キーボード操作で利用できる。

## 16. レビュー反映メモ

実装時に以下を必須扱いとする。

- `timestamp` の解釈を一箇所に集約する。現行ログはタイムゾーンなしの UTC 相当として扱う前提だが、`new Date(value)` と `new Date(value + 'Z')` で結果が変わるため、変換ルールを固定する。
- タイムライン項目のクリックから詳細モーダルを開く場合は、`showTeamDetailsModal()` に数値の `teamId` を直接渡さない。既存関数がチームオブジェクトを要求するなら、`ekidenDataCache.teams.find(...)` で実体を解決してから渡すか、別の薄いラッパーを用意する。
- タイムラインからマップ追跡に連携できない実装にするなら、無理に追跡ボタンへ寄せず、項目は詳細表示だけに限定してもよい。安全性と分かりやすさを優先する。
- 表示文言は「何が起きたか」と「どれだけ動いたか」を分離する。
- 「本日最高記録」は曖昧なので、画面表示では「本日の最高移動距離を更新」と明示する。
- 表示文言の最終案として「本日最高記録を更新」は採用可能だが、実装では「記録更新」の対象が本日の走行距離であることを詳細文で補う。
- 「首位へ」は自然だがやや抽象的なので、見出しは「首位に浮上」または「首位交代」に寄せると意味が伝わりやすい。
- フィルターの「順位変動」は、総合順位の変化であることが伝わるよう、説明文や補助テキストを必要に応じて追加する。
- 過去区間最高記録を更新した場合は、通常の記録更新よりも目立つ見せ方にする。例えば金系/祝福系の装飾、短い称賛文、必要なら一時的な強調アニメーションを付ける。

## 17. 実装順序

1. `index_16.html` にメニュー項目、セクションDOM、CSSを追加する。
2. JSONLパーサーとタイムスタンプ変換を実装する。
3. スナップショット化と順位計算を実装する。
4. イベント生成とソートを実装する。
5. DOM描画、フィルター、展開処理を実装する。
6. 初期ロードと `refreshRealtimeData()` に接続する。
7. 空状態・取得失敗・不完全行を確認する。
8. 実データで順位と表示時刻を照合する。
9. PC/スマホと既存機能の回帰確認を行う。

## 18. 将来拡張（初期実装には含めない）

- 中継所通過、区間切り替えイベント
- 首位との差が一定値以下になった接戦イベント
- 過去区間最高記録の祝福演出と恒常バッジ表示
- 注目チームだけを表示するフィルター
- 過去日のタイムライン切り替え
- タイムライン選択時のマップ再生
- SNS共有カード生成

将来拡張は初期実装へ混ぜず、まず順位変動の正確性と見やすさを完成条件とする。
