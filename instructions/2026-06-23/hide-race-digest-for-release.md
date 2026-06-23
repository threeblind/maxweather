# レースダイジェスト一時非表示 実装指示

- 作成日: 2026-06-23
- 対象: 第16回大会フロントエンド公開前対応
- 対象ファイル: `index_16.html`, `app_16.js`
- 目的: 公開時点では「レースダイジェスト」をメニューと本文から非表示にし、後日すぐ再表示できるようにする
- 前提: `data/daily_summary.json` の生成や既存データは削除しない。表示だけを止める

## 1. 実装方針

レースダイジェストは未完成調整中のため、HTML削除ではなく設定フラグで出し分ける。

- フラグ名は `SHOW_RACE_DIGEST` とする
- 初期値は `false`
- `true` に変えるだけで、メニューとコンテンツが再表示されるようにする
- `daily_summary.json` の fetch は、非表示時には実行しない
- 監督コメント欄も `section-digest` 配下にあるため、今回の非表示対象に含める

## 2. 具体的な変更内容

### 2.1 HTML

`index_16.html` のナビゲーション項目に識別用属性を追加する。

対象:

```html
<li><a href="#section-digest">ダイジェスト</a></li>
```

変更例:

```html
<li data-feature="race-digest"><a href="#section-digest">ダイジェスト</a></li>
```

`section-digest` はHTML上に残す。削除しない。

### 2.2 JavaScript

`app_16.js` の先頭付近に表示切り替えフラグを追加する。

```js
const SHOW_RACE_DIGEST = false;
```

初期化処理の早い段階で、以下を行う関数を追加して呼び出す。

- `data-feature="race-digest"` のナビ項目を `hidden = true` にする
- `#section-digest` を `hidden = true` にする
- `SHOW_RACE_DIGEST === true` の場合は何もしない、または `hidden = false` に戻す

関数名例:

```js
function applyFeatureVisibility() {
    const digestNavItem = document.querySelector('[data-feature="race-digest"]');
    const digestSection = document.getElementById('section-digest');
    const shouldHideDigest = !SHOW_RACE_DIGEST;

    if (digestNavItem) digestNavItem.hidden = shouldHideDigest;
    if (digestSection) digestSection.hidden = shouldHideDigest;
}
```

### 2.3 fetch抑止

`displayDailySummary()` の冒頭で、非表示時は即 return する。

```js
async function displayDailySummary() {
    if (!SHOW_RACE_DIGEST) return;
    ...
}
```

`displayManagerComments()` も同様に、非表示時は即 return する。

```js
async function displayManagerComments() {
    if (!SHOW_RACE_DIGEST) return;
    ...
}
```

これにより、公開時に不要な読み込みやエラー表示が出ない。

## 3. 呼び出し位置

`DOMContentLoaded` または現在の初期化処理の最初のほうで `applyFeatureVisibility()` を呼ぶ。

- ナビやセクションDOMが存在してから実行する
- `displayDailySummary()` / `displayManagerComments()` より前に実行する

## 4. 受け入れ条件

- ページ表示時、上部メニューに「ダイジェスト」が表示されない
- 本文中に「レースダイジェスト」セクションが表示されない
- `data/daily_summary.json` は削除されていない
- `SHOW_RACE_DIGEST = true` に変えるだけで、メニューと本文が再表示される
- 非表示時にコンソールエラーが出ない
- スマホのハンバーガーメニューでも「ダイジェスト」が表示されない

## 5. 注意点

- `section-digest` 配下には監督コメント欄も含まれるため、今回はまとめて非表示にする
- CSSだけで隠すのではなく、JSのフラグで制御する
- 将来の再表示を簡単にするため、該当HTMLや既存描画関数は削除しない
- `index.html` が公開対象の場合は、同じ変更が必要か確認する
