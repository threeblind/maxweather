# 注目チーム登録機能 実装計画

## 概要

ユーザーが好きな大学を最大3校登録し、順位表・地図・グラフ・タイムラインで強調表示する機能を追加する。  
サーバー変更なし。`localStorage` のみで完結。通知は将来フェーズ。

## スコープ（今回実装）

- ✅ localStorage 読み書きヘルパー
- ✅ エントリーリスト（`#section-team-directory`）への星ボタン
- ✅ 総合順位表（`#ekidenRankingTable`）への星ボタン  ← ユーザー追加要件
- ✅ 順位表の行ハイライト
- ✅ 地図マーカー強調
- ✅ グラフ強調（モーダルを開いた時のみ）
- ✅ タイムラインに「注目チーム」フィルター追加  ← ユーザー追加要件
- ❌ Push通知連携（将来フェーズ）

---

## Proposed Changes

### app_16.js

#### [MODIFY] [app_16.js](file:///Users/t28k2/prj/maxweather/app_16.js)

**① グローバル状態変数の追加**（L17付近）

```js
// --- 注目チーム用状態変数 ---
let favoriteTeamIds = new Set();          // 注目中の team.id セット
const FAVORITE_TEAMS_KEY = 'favoriteTeams';
const FAVORITE_MAX = 3;
```

**② localStorage ヘルパー関数の追加**（グローバル関数として）

```js
function loadFavoriteTeams()     // localStorage → favoriteTeamIds に読み込む
function saveFavoriteTeams()     // favoriteTeamIds → localStorage に保存
function toggleFavoriteTeam(id) // 登録/解除トグル。戻り値: 'added'|'removed'|'full'
function isFavoriteTeam(id)     // boolean
function applyFavoriteHighlights() // 順位表行・マーカー・タイムラインを再描画せず強調更新
```

**③ updateEkidenRankingTable の行に星ボタンを追加**（L1705付近）

行末の `fragment.appendChild(row)` 前に、各 `row` へ星ボタンセルを追加。

```js
const favCell = document.createElement('td');
const favBtn  = createFavoriteButton(team.id);
favCell.appendChild(favBtn);
row.appendChild(favCell);
```

行ハイライトは `data-team-id` 属性 + CSS クラス `is-favorite` で実現。  
`applyFavoriteHighlights()` で全行を走査してクラス付与/削除するだけなので再描画不要。

**④ displayTeamDetails にヘッダー部の星ボタンを追加**（L3234付近）

`team-details-title` div の隣に注目ボタンを追加。エントリーリスト選択中チームに星が付く。

**⑤ updateRunnerMarkers でマーカー強調**（L578付近）

注目チームのマーカーは `zIndexOffset: 500` + `iconSize` を少し大きく（28→34px）+ 輪郭リングを追加。

```js
const isFav = isFavoriteTeam(teamIdFromName);
// isFav の場合は createFavoriteMarkerIcon(color) を使う
```

**⑥ displayRankHistoryChart でグラフ強調**（L1275付近）

dataset 生成時に注目チームは `borderWidth: 4`、非注目は `borderWidth: 1` + `borderColor` を薄く。

```js
const isFav = isFavoriteTeam(team.id);
borderWidth: isFav ? 4 : (favoriteTeamIds.size > 0 ? 1 : 2),
borderColor: isFav ? color : (favoriteTeamIds.size > 0 ? color + '44' : color),
```

**⑦ renderRankTimeline に「注目チーム」フィルター対応**

- フィルター定数 `'favorites'` を追加
- `favoriteTeamIds.size === 0` の場合はフィルターボタンを非表示
- 注目チーム変更時に `renderRankTimeline()` を呼ぶ

**⑧ initRankTimeline のフィルターイベントに `favorites` を追加**

既存フィルターボタンの処理と同様に接続。

**⑨ DOMContentLoaded で `loadFavoriteTeams()` を呼ぶ**（L3322付近）

---

### index_16.html

#### [MODIFY] [index_16.html](file:///Users/t28k2/prj/maxweather/index_16.html)

**① 注目チーム用 CSS の追加**

```css
/* 注目チームボタン */
.fav-btn { ... }
.fav-btn.is-favorite { color: gold; }

/* 順位表のハイライト行 */
#ekidenRankingBody tr.is-favorite { border-left: 4px solid gold; background: rgba(255,215,0,0.08); }

/* タイムラインの注目フィルターボタン */
/* (既存 .rank-timeline-filter に乗るので CSS 追加不要の可能性あり) */

/* 注目チームカウンター */
.favorite-team-counter { ... }
```

**② タイムライン「注目」フィルターボタンの HTML 追加**

```html
<button type="button" class="rank-timeline-filter" data-filter="favorites" 
        aria-pressed="false" id="rank-timeline-filter-favorites" hidden>★ 注目</button>
```

**③ エントリーリスト説明文の追加**（`#section-team-directory` 内 `team-directory-content` の前）

```html
<p class="favorite-hint">★ を押して注目チームに登録できます（最大3校）</p>
<p id="favorite-team-counter" class="favorite-team-counter"></p>
```

---

## 実装順

1. グローバル変数追加 + localStorage ヘルパー関数
2. `createFavoriteButton()` ヘルパー関数（星ボタン DOM 生成）
3. 総合順位表に星ボタン列を追加
4. エントリーリスト（`displayTeamDetails`）に星ボタンを追加
5. `applyFavoriteHighlights()` 実装（順位表行・マーカー・タイムライン）
6. 地図マーカー強調
7. グラフ強調（`displayRankHistoryChart` 内）
8. タイムライン「注目」フィルター
9. CSS / HTML 調整
10. `loadFavoriteTeams()` を初期化に組み込む

## Verification Plan

### Manual Verification
- エントリーリストで星を押すと登録され、再読込後も保持される
- 3校登録後に4校目の星を押しても登録されない（ボタンが無効になる）
- 順位表の注目チーム行が金色ハイライトされる
- タイムラインの「注目」フィルターで注目チームの変動だけ表示される
- グラフモーダルを開くと注目チームの線が太く、非注目が薄くなる
