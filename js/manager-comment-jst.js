/**
 * 監督コメントの JST 暦日キー変換ヘルパー。
 *
 * 画面の「監督陣の分析コメント」は、取得データ（直近48時間保持）全体ではなく、
 * JST 基準で「当日」または「前日」のコメントだけを表示するための純粋関数群。
 * ブラウザのローカルタイムゾーン・DST に依存しない（Asia/Tokyo 固定 + UTC 基準演算）。
 *
 * - getCommentJstDateKey(timestamp): 投稿時刻 → JST 暦日キー 'YYYY-MM-DD'（不正・空は null）
 *   - タイムゾーン付き ISO（+00:00 / Z / +05:00 等）は Date として解釈し Asia/Tokyo で暦日化
 *   - タイムゾーンなし（例: 2026-08-04T23:59:00）は JST として解釈（解析前に +09:00 を補う）
 * - getJstDateKeys(nowMs): 現在日時（JST）の暦日キーと前日の暦日キーを返す
 *
 * ブラウザ（window.ManagerCommentJst）と Node（module.exports）の両方で使える。
 */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) {
        module.exports = factory();
    } else {
        root.ManagerCommentJst = factory();
    }
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';

    var JST_OFFSET_MS = 9 * 60 * 60 * 1000; // Asia/Tokyo = UTC+9（日本はDSTなし）

    /** タイムゾーン付きか判定（末尾の Z または ±HH:MM / ±HHMM） */
    function hasTimezone(s) {
        return /(Z|[+-]\d{2}:?\d{2})$/i.test(s);
    }

    /** Date を Asia/Tokyo の 'YYYY-MM-DD' に変換（Intl、ブラウザTZ非依存） */
    function formatJstDateKey(date) {
        var parts = new Intl.DateTimeFormat('en-US', {
            timeZone: 'Asia/Tokyo',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
        }).formatToParts(date);
        function get(type) {
            for (var i = 0; i < parts.length; i++) {
                if (parts[i].type === type) return parts[i].value;
            }
            return '';
        }
        return get('year') + '-' + get('month') + '-' + get('day');
    }

    /**
     * 投稿時刻を JST 暦日キー 'YYYY-MM-DD' に変換する。
     * 不正値・空値・parse不能は null を返す（呼び出し側で除外する）。
     */
    function getCommentJstDateKey(timestamp) {
        if (timestamp === null || timestamp === undefined) return null;
        var s = String(timestamp).trim();
        if (s === '') return null;
        // タイムゾーンなし（naive）は JST として解釈するため +09:00 を補う
        var iso = s;
        if (!hasTimezone(s)) {
            iso = /^\d{4}-\d{2}-\d{2}$/.test(s) ? s + 'T00:00:00+09:00' : s + '+09:00';
        }
        var d = new Date(iso);
        if (isNaN(d.getTime())) return null;
        return formatJstDateKey(d);
    }

    /**
     * 現在日時（JST）の暦日キーと前日の暦日キーを返す。
     * UTC 基準の日付演算でブラウザTZ/DST に依存しない。
     */
    function getJstDateKeys(nowMs) {
        var ms = (nowMs === undefined) ? Date.now() : Number(nowMs);
        function pad(n) { return String(n).padStart(2, '0'); }
        // JST = UTC+9。nowMs に9時間加算した時刻の UTC 暦日 = JST 暦日
        var jst = new Date(ms + JST_OFFSET_MS);
        var today = jst.getUTCFullYear() + '-' + pad(jst.getUTCMonth() + 1) + '-' + pad(jst.getUTCDate());
        // 前日 = JST 暦日の 0:00 から24時間引いた日（UTC 基準で日付演算）
        var prev = new Date(Date.UTC(jst.getUTCFullYear(), jst.getUTCMonth(), jst.getUTCDate()) - 86400000);
        var yesterday = prev.getUTCFullYear() + '-' + pad(prev.getUTCMonth() + 1) + '-' + pad(prev.getUTCDate());
        return { today: today, yesterday: yesterday };
    }

    /**
     * 投稿時刻を JST 固定の時刻ラベル（例: "23:00"）に変換する。
     * naive（タイムゾーンなし）は JST として +09:00 を補い、aware はそのまま Date 化して
     * Asia/Tokyo で表示する（ブラウザTZに依存しない）。不正値は null。
     */
    function getCommentJstTimeLabel(timestamp) {
        if (timestamp === null || timestamp === undefined) return null;
        var s = String(timestamp).trim();
        if (s === '') return null;
        var iso = s;
        if (!hasTimezone(s)) {
            iso = /^\d{4}-\d{2}-\d{2}$/.test(s) ? s + 'T00:00:00+09:00' : s + '+09:00';
        }
        var d = new Date(iso);
        if (isNaN(d.getTime())) return null;
        return new Intl.DateTimeFormat('ja-JP', {
            timeZone: 'Asia/Tokyo',
            hour: '2-digit',
            minute: '2-digit',
            hourCycle: 'h23', // 00:00 を "00:00" と表示（"24:00" にしない）
        }).format(d);
    }

    return {
        getCommentJstDateKey: getCommentJstDateKey,
        formatJstDateKey: formatJstDateKey,
        getJstDateKeys: getJstDateKeys,
        getCommentJstTimeLabel: getCommentJstTimeLabel,
    };
});
