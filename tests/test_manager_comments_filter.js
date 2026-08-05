#!/usr/bin/env node
/**
 * js/manager-comment-jst.js（監督コメントのJST暦日キー変換）の回帰テスト。
 *
 * 画面の「監督陣の分析コメント」は JST 基準で「当日＋前日」だけを表示する。
 * このテストは純粋ヘルパーの実動作（表示/非表示判定）を Node で検証する。
 *
 * 実行: node tests/test_manager_comments_filter.js
 * 固定現在時刻: 2026-08-05 12:00 JST (= 2026-08-05T03:00:00Z)
 */
'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const helpers = require('../js/manager-comment-jst.js');
const { getCommentJstDateKey, getJstDateKeys, formatJstDateKey, getCommentJstTimeLabel } = helpers;

// 2026-08-05 12:00 JST
const NOW_MS = Date.UTC(2026, 7, 5, 3, 0, 0);

// アプリのフィルタと同じ判定（allowedDates = {今日JST, 昨日JST}）
function isVisible(timestamp, nowMs) {
    const keys = getJstDateKeys(nowMs);
    const key = getCommentJstDateKey(timestamp);
    return key !== null && (key === keys.today || key === keys.yesterday);
}

let passed = 0;
let failed = 0;
function test(name, fn) {
    try {
        fn();
        console.log(`  ✓ ${name}`);
        passed++;
    } catch (e) {
        console.log(`  ✗ ${name}: ${e.message}`);
        failed++;
    }
}

// --- 日付キー ---
test('getJstDateKeys: 2026-08-05 12:00 JST → today=08-05, yesterday=08-04', () => {
    const keys = getJstDateKeys(NOW_MS);
    assert.strictEqual(keys.today, '2026-08-05');
    assert.strictEqual(keys.yesterday, '2026-08-04');
});

test('getJstDateKeys: 日付境界 00:00 JST ちょうどでも前日が正しい', () => {
    // 2026-08-05 00:00 JST = 2026-08-04T15:00:00Z
    const keys = getJstDateKeys(Date.UTC(2026, 7, 4, 15, 0, 0));
    assert.strictEqual(keys.today, '2026-08-05');
    assert.strictEqual(keys.yesterday, '2026-08-04');
});

// --- 当日/前日/前々日 ---
test('2026-08-05 のコメントは表示（当日）', () => {
    assert.strictEqual(isVisible('2026-08-05T10:00:00', NOW_MS), true);
});

test('2026-08-04 のコメントは表示（前日）', () => {
    assert.strictEqual(isVisible('2026-08-04T10:00:00', NOW_MS), true);
});

test('2026-08-03 のコメントは非表示', () => {
    assert.strictEqual(isVisible('2026-08-03T10:00:00', NOW_MS), false);
});

// --- naive JST timestamp ---
test('naive JST 2026-08-04T23:59:00 は表示（ブラウザTZに依存しない）', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-04T23:59:00'), '2026-08-04');
    assert.strictEqual(isVisible('2026-08-04T23:59:00', NOW_MS), true);
});

test('naive JST 日付境界 23:59:59 は前日として表示', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-04T23:59:59'), '2026-08-04');
});

test('naive JST 日付境界 00:00:00 は当日として表示', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-05T00:00:00'), '2026-08-05');
    assert.strictEqual(isVisible('2026-08-05T00:00:00', NOW_MS), true);
});

// --- timezone 付き ISO ---
test('2026-08-04T15:00:00+00:00（JST 2026-08-05 00:00）は表示', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-04T15:00:00+00:00'), '2026-08-05');
    assert.strictEqual(isVisible('2026-08-04T15:00:00+00:00', NOW_MS), true);
});

test('2026-08-03T15:00:00+00:00（JST 2026-08-04 00:00）は表示', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-03T15:00:00+00:00'), '2026-08-04');
    assert.strictEqual(isVisible('2026-08-03T15:00:00+00:00', NOW_MS), true);
});

test('2026-08-05T02:59:00+09:00 と Z 形式の JST 変換が一致', () => {
    assert.strictEqual(getCommentJstDateKey('2026-08-04T17:59:00Z'), '2026-08-05');
    assert.strictEqual(getCommentJstDateKey('2026-08-04T18:00:00+05:00'), '2026-08-04'); // JST 22:00
});

// --- invalid/null/missing ---
test('invalid/null/missing timestamp は null を返し非表示', () => {
    assert.strictEqual(getCommentJstDateKey(null), null);
    assert.strictEqual(getCommentJstDateKey(undefined), null);
    assert.strictEqual(getCommentJstDateKey(''), null);
    assert.strictEqual(getCommentJstDateKey('不正な日時'), null);
    assert.strictEqual(isVisible(null, NOW_MS), false);
    assert.strictEqual(isVisible(undefined, NOW_MS), false);
    assert.strictEqual(isVisible('', NOW_MS), false);
});

test('invalid が混在しても正常コメントの表示は継続する', () => {
    const comments = [
        { timestamp: '2026-08-05T10:00:00' },  // 当日 → 表示
        { timestamp: '2026-08-04T10:00:00' },  // 前日 → 表示
        { timestamp: '2026-08-03T10:00:00' },  // 前々日 → 非表示
        { timestamp: null },                   // 非表示
        { timestamp: '不正' },                 // 非表示
        {},                                   // missing → 非表示
    ];
    const keys = getJstDateKeys(NOW_MS);
    const allowed = new Set(Object.values(keys));
    const visible = comments.filter((c) => {
        const k = getCommentJstDateKey(c.timestamp);
        return k !== null && allowed.has(k);
    });
    assert.strictEqual(visible.length, 2);
    // 元配列は破壊しない
    assert.strictEqual(comments.length, 6);
});

// --- ブラウザTZ/UTC環境の模擬 ---
test('Intl の Asia/Tokyo 変換はホストTZに依存しない（UTC インスタント → JST キー）', () => {
    // 2026-08-04T15:00:00Z は JST 2026-08-05 00:00
    assert.strictEqual(formatJstDateKey(new Date('2026-08-04T15:00:00Z')), '2026-08-05');
    // 2026-08-04T23:59:59Z は JST 2026-08-05 08:59:59
    assert.strictEqual(formatJstDateKey(new Date('2026-08-04T23:59:59Z')), '2026-08-05');
});

// --- 表示時刻のJST固定（P1） ---
test('naive JST 23:00 はどのTZ環境でも 23:00 と表示される', () => {
    assert.strictEqual(getCommentJstTimeLabel('2026-08-04T23:00:00'), '23:00');
});

test('2026-08-04T15:00:00Z は JST 00:00 と表示される', () => {
    assert.strictEqual(getCommentJstTimeLabel('2026-08-04T15:00:00Z'), '00:00');
});

test('2026-08-04T15:00:00+00:00 も JST 00:00 と表示される', () => {
    assert.strictEqual(getCommentJstTimeLabel('2026-08-04T15:00:00+00:00'), '00:00');
});

test('getCommentJstTimeLabel は不正値を null で返す', () => {
    assert.strictEqual(getCommentJstTimeLabel(null), null);
    assert.strictEqual(getCommentJstTimeLabel(''), null);
    assert.strictEqual(getCommentJstTimeLabel('不正'), null);
});

// --- キャッシュバスト（P1） ---
test('index.html は app.js の新しいキャッシュバスト version を参照している', () => {
    const indexPath = path.join(__dirname, '..', 'index.html');
    const html = fs.readFileSync(indexPath, 'utf-8');
    assert.ok(html.includes('app.js?v=20260805-1'),
        `index.html に app.js?v=20260805-1 が必要 (実際: ${html.match(/app\.js\?v=[^" ]+/g)})`);
    assert.ok(html.includes('js/manager-comment-jst.js'), 'helper の script タグが必要');
});

console.log(`\n結果: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
