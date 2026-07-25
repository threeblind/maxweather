"""
scripts/fetch_manager_comments.py のテスト。
実サイトアクセスなし、fixture のみ。
"""
import sys
import json
from pathlib import Path
from datetime import datetime, time, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from fetch_manager_comments import (
    get_manager_tripcodes,
    get_comment_sources,
    get_night_window,
    normalize_tripcode,
    normalize_source_url,
    strip_html_tags,
    make_content_hash,
    make_html_hash,
    parse_5ch_date,
    parse_5ch_page,
    parse_shitaraba_date,
    parse_shitaraba_page,
    extract_tripcode_from_text,
    dedup_comments,
    format_output_comment,
    NIGHT_START_HOUR,
    NIGHT_END_HOUR,
)

# ============================================================
# Fixture: 5ch kizuna HTML (監督投稿を含む)
# ============================================================
FIXTURE_5CH_HTML = """<!DOCTYPE html>
<html><body>
<div class="clear post" data-id="1" id="1">
<div class="post-header" open="">
<div>
<span class="postid">1</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">７７４＠沿道</a></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/24(金) 18:01:03.15</span></span>
</div>
<div class="post-content">テスト投稿（非監督）</div>
</div>

<div class="clear post" data-id="100" id="100">
<div class="post-header" open="">
<div>
<span class="postid">100</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">■三重大学監督（風来の試練）</a></b>◆g8a8AxWMVk <b></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/24(金) 20:30:15.27</span></span>
</div>
<div class="post-content"> 三重大学 1区初日 粥見 38.5℃</div>
</div>

<div class="clear post" data-id="101" id="101">
<div class="post-header" open="">
<div>
<span class="postid">101</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">■上武大学監督(前福岡大監督)</a></b>◆1Lye/U2E2I <b></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/24(金) 21:15:45.10</span></span>
</div>
<div class="post-content"> 前橋 35.5℃ やませ強し</div>
</div>

<div class="clear post" data-id="102" id="102">
<div class="post-header" open="">
<div>
<span class="postid">102</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">■名古屋大学監督(ロマン派)</a></b>◆Ai4OO8X72O3b <b></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/25(土) 06:23:18.02</span></span>
</div>
<div class="post-content"> 美濃 40.0km 素晴らしい</div>
</div>

<div class="clear post" data-id="103" id="103">
<div class="post-header" open="">
<div>
<span class="postid">103</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">■駅弁監督（innocent world season7）</a></b>◆rGlpXlZawQ <b></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/25(土) 07:50:33.44</span></span>
</div>
<div class="post-content"> 福島大学 高田 33.8km</div>
</div>

<div class="clear post" data-id="104" id="104">
<div class="post-header" open="">
<div>
<span class="postid">104</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">■全日本学連選抜監督（夏の日の1994)</a></b>◆oIdAWXadP6 <b></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/25(土) 08:30:01.99</span></span>
</div>
<div class="post-content"> 金山選手 39.1km 良い走り</div>
</div>
</body></html>
"""

# ============================================================
# Fixture: したらば HTML (監督投稿を含む)
# ============================================================
FIXTURE_SHITARABA_HTML = """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><meta charset="EUC-JP"/><title>テスト</title></head>
<body>
<div id="thread-body">
<dl>
<dt id="comment_200">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/200" rel="nofollow">200</a>：
<a href="mailto:sage"><b>774</b></a>：
2026/07/24(土) 10:00:01 ID:xxxxx
</dt>
<dd>非監督テスト</dd>

<dt id="comment_201">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/201" rel="nofollow">201</a>：
<a href="mailto:sage"><b>■名古屋大学監督(ロマン派)</b> ◆Ai4OO8X72O3b</a>：
2026/07/24(金) 21:30:15 ID:i6tmgZks0
</dt>
<dd>名古屋大学 美濃 39.8km<br/>良いペース</dd>

<dt id="comment_202">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/202" rel="nofollow">202</a>：
<a href="mailto:sage"><b>■駅弁監督（innocent world season7）</b> ◆rGlpXlZawQ</a>：
2026/07/24(金) 23:53:01 ID:tMfmmPBw0
</dt>
<dd>熊本学園大学 犬飼 35.8km<br/>今日は南隣の宇目君が早々雷雨で</dd>

<dt id="comment_203">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/203" rel="nofollow">203</a>：
<a href="mailto:sage"><b>■上武大学監督(前福岡大監督)</b> ◆1Lye/U2E2I</a>：
2026/07/25(土) 01:15:30 ID:abc123
</dt>
<dd>飯塚 36.1℃ さすがです</dd>

<dt id="comment_204">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/204" rel="nofollow">204</a>：
<font color="#008800"><b>■山梨学院大学監督【帰ってきたベストマン】</b> ◆fPBkcaMyRA</font>：
2026/07/25(土) 06:59:30 ID:niSB5cJE0
</dt>
<dd>佐久間は学内3タテも視野に</dd>

<dt id="comment_205">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/205" rel="nofollow">205</a>：
<a href="mailto:sage"><b>■全日本学連選抜監督（夏の日の1994)</b> ◆oIdAWXadP6</a>：
2026/07/25(土) 08:05:22 ID:def456
</dt>
<dd>今日も期待できそうです</dd>

<dt id="comment_206">
<a href="https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/206" rel="nofollow">206</a>：
<a href="mailto:sage"><b>■三重大学監督（風来の試練）</b> ◆g8a8AxWMVk</a>：
2026/07/25(土) 07:01:00 ID:xuI9OdG60
</dt>
<dd>桑名が40℃を超えました</dd>
</dl>
</div>
</body></html>
"""

# 非監督投稿（トリップなし）
FIXTURE_NO_MANAGER_HTML = """<!DOCTYPE html>
<html><body>
<div class="clear post" data-id="50" id="50">
<div class="post-header" open="">
<div>
<span class="postid">50</span>
<span class="postusername"><b><a href="/cdn-cgi/l/email-protection#abcd">名無しさん</a></b></span>
</div>
<span style="width:100%;"><span class="date">2026/07/24(金) 19:30:00.00</span></span>
</div>
<div class="post-content">ただの雑談</div>
</div>
</body></html>
"""


# ============================================================
# テスト: ユーティリティ関数
# ============================================================

def test_normalize_tripcode():
    assert normalize_tripcode("◆ g8a8AxWMVk") == "◆g8a8AxWMVk"
    assert normalize_tripcode("  ◆Ai4OO8X72O3b  ") == "◆Ai4OO8X72O3b"
    assert normalize_tripcode("◆1Lye/U2E2I") == "◆1Lye/U2E2I"
    assert normalize_tripcode("◆ CT6iZVF9L") == "◆CT6iZVF9L"


def test_extract_tripcode():
    assert extract_tripcode_from_text("◆g8a8AxWMVk") == "◆g8a8AxWMVk"
    assert extract_tripcode_from_text("名前 ◆Ai4OO8X72O3b") == "◆Ai4OO8X72O3b"
    assert extract_tripcode_from_text("トリップなし") is None
    assert extract_tripcode_from_text("二重 ◆A ◆B") == "◆A"


def test_normalize_source_url():
    """末尾スラッシュは維持（URL依存のサイト対策）、空白のみトリム"""
    assert normalize_source_url("https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/") == "https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/"
    assert normalize_source_url("https://kizuna.5ch.io/test/read.cgi/sky/1782726210/") == "https://kizuna.5ch.io/test/read.cgi/sky/1782726210/"
    assert normalize_source_url("https://example.com/path") == "https://example.com/path"
    assert normalize_source_url("  https://example.com/  ") == "https://example.com/"


def test_strip_html_tags():
    assert strip_html_tags("<dd>名古屋大学 美濃 39.8km<br/>良いペース</dd>") == "名古屋大学 美濃 39.8km 良いペース"
    assert strip_html_tags("<p>内容A</p>") == "内容A"
    assert strip_html_tags("") == ""
    assert strip_html_tags("  プレーン  ") == "プレーン"
    assert strip_html_tags("<div class=\"post-content\">  三重大学 1区初日 </div>") == "三重大学 1区初日"


def test_make_content_hash_text_only():
    """テキスト内容が同じならHTML構造が違っても同一ハッシュ"""
    h1 = make_content_hash({'content_html': '<dd>内容<br/>改行</dd>'})
    h2 = make_content_hash({'content_html': '<p>内容<br>改行</p>'})
    assert h1 == h2

    h3 = make_content_hash({'content_html': '<p>内容A</p>'})
    h4 = make_content_hash({'content_html': '<p>内容B</p>'})
    assert h3 != h4


def test_make_html_hash_structure_sensitive():
    """HTMLハッシュはHTML構造に敏感（補助キー用）"""
    h1 = make_html_hash({'content_html': '<p>内容</p>'})
    h2 = make_html_hash({'content_html': '<dd>内容</dd>'})
    assert h1 != h2


def test_parse_5ch_date():
    dt = parse_5ch_date("2026/07/24(金) 20:30:15.27")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 24
    assert dt.hour == 20
    assert dt.minute == 30
    assert dt.second == 15

    assert parse_5ch_date("invalid") is None
    assert parse_5ch_date("") is None


def test_parse_shitaraba_date():
    dt = parse_shitaraba_date("2026/07/24(金) 21:30:15 ID:i6tmgZks0")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 7
    assert dt.day == 24
    assert dt.hour == 21

    dt2 = parse_shitaraba_date("2026/07/25(土) 06:59:30")
    assert dt2 is not None
    assert dt2.hour == 6

    assert parse_shitaraba_date("invalid") is None


# ============================================================
# テスト: 5ch パーサー
# ============================================================

def test_parse_5ch_page():
    url = "https://kizuna.5ch.io/test/read.cgi/sky/1782726210/"
    comments = parse_5ch_page(FIXTURE_5CH_HTML, url)
    assert len(comments) == 5

    c = comments[0]
    assert c['source_kind'] == '5ch'
    assert c['post_id'] == '100'
    assert '三重大学' in c['posted_name']
    assert c['tripcode'] == '◆g8a8AxWMVk'
    assert c['timestamp'].hour == 20
    assert c['timestamp'].minute == 30


def test_parse_5ch_page_no_trip():
    url = "https://kizuna.5ch.io/test/read.cgi/sky/1782726210/"
    comments = parse_5ch_page(FIXTURE_NO_MANAGER_HTML, url)
    assert len(comments) == 0


# ============================================================
# テスト: したらばパーサー
# ============================================================

def test_parse_shitaraba_page():
    url = "https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/"
    comments = parse_shitaraba_page(FIXTURE_SHITARABA_HTML, url)
    assert len(comments) == 6

    c = comments[0]
    assert c['source_kind'] == 'shitaraba'
    assert c['post_id'] == '201'
    assert '名古屋大学' in c['posted_name']
    assert c['tripcode'] == '◆Ai4OO8X72O3b'
    assert c['timestamp'].hour == 21

    c_font = [c for c in comments if c['post_id'] == '204']
    assert len(c_font) == 1
    assert '山梨学院大学' in c_font[0]['posted_name']
    assert c_font[0]['tripcode'] == '◆fPBkcaMyRA'


def test_parse_shitaraba_no_trip():
    url = "https://jbbs.shitaraba.net/bbs/read.cgi/study/13070/1627306695/"
    comments = parse_shitaraba_page(FIXTURE_NO_MANAGER_HTML.replace('div class="clear post"', 'dt id="comment_50"').replace('div class="post-content"', 'dd'), url)
    assert len(comments) == 0


# ============================================================
# テスト: 重複除去
# ============================================================

def test_dedup_same_source_same_post():
    """同一ソース内で同じ post_id の重複は後勝ち"""
    comments = [
        {'source_url': 'https://5ch.test/1', 'source_kind': '5ch', 'post_id': '100',
         'timestamp': datetime(2026, 7, 24, 20, 30, 15), 'tripcode': '◆a', 'content_html': '<p>v1</p>',
         'posted_name': '監督A', 'official_name': 'A'},
        {'source_url': 'https://5ch.test/1', 'source_kind': '5ch', 'post_id': '100',
         'timestamp': datetime(2026, 7, 24, 20, 30, 15), 'tripcode': '◆a', 'content_html': '<p>v2</p>',
         'posted_name': '監督A', 'official_name': 'A'},
    ]
    result = dedup_comments(comments)
    assert len(result) == 1
    assert result[0]['content_html'] == '<p>v2</p>'


def test_dedup_cross_source():
    """異種ソース間で同一内容（timestamp+tripcode+content hash）の重複は除去"""
    same_content = "<dd>名古屋大学 美濃 39.8km<br/>良いペース</dd>"
    comments = [
        {'source_url': 'https://5ch.test/100', 'source_kind': '5ch', 'post_id': '100',
         'timestamp': datetime(2026, 7, 24, 21, 30, 15), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': same_content, 'posted_name': '名古屋大学', 'official_name': ''},
        {'source_url': 'https://shitaraba.test/301', 'source_kind': 'shitaraba', 'post_id': '301',
         'timestamp': datetime(2026, 7, 24, 21, 30, 15), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': same_content, 'posted_name': '名古屋大学', 'official_name': ''},
    ]
    result = dedup_comments(comments)
    assert len(result) == 1


def test_dedup_cross_source_different_html():
    """異種ソース間でHTML構造が異なるがテキスト内容が同じなら重複除去"""
    comments = [
        {'source_url': 'https://5ch.test/100', 'source_kind': '5ch', 'post_id': '100',
         'timestamp': datetime(2026, 7, 24, 21, 30, 15), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': '<div class="post-content"> 名古屋大学 美濃 39.8km 良いペース </div>',
         'posted_name': '監督A', 'official_name': ''},
        {'source_url': 'https://shitaraba.test/301', 'source_kind': 'shitaraba', 'post_id': '301',
         'timestamp': datetime(2026, 7, 24, 21, 30, 15), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': '<dd>名古屋大学 美濃 39.8km<br/>良いペース</dd>',
         'posted_name': '監督A', 'official_name': ''},
    ]
    result = dedup_comments(comments)
    assert len(result) == 1  # テキスト内容が同一なので重複除去


def test_dedup_different_content_kept():
    """異なる内容の場合は両方残す"""
    comments = [
        {'source_url': 'https://5ch.test/100', 'source_kind': '5ch', 'post_id': '100',
         'timestamp': datetime(2026, 7, 24, 21, 30, 15), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': '<p>内容A</p>', 'posted_name': '監督A', 'official_name': ''},
        {'source_url': 'https://5ch.test/101', 'source_kind': '5ch', 'post_id': '101',
         'timestamp': datetime(2026, 7, 24, 22, 0, 0), 'tripcode': '◆Ai4OO8X72O3b',
         'content_html': '<p>内容B</p>', 'posted_name': '監督A', 'official_name': ''},
    ]
    result = dedup_comments(comments)
    assert len(result) == 2


# ============================================================
# テスト: 時間枠
# ============================================================

def test_night_window_basic():
    start, end = get_night_window()
    assert start.hour == NIGHT_START_HOUR
    assert end.hour == NIGHT_END_HOUR
    assert start.minute == 0
    assert end.minute == 0
    assert end > start


# ============================================================
# テスト: フォーマット出力
# ============================================================

def test_format_output_comment():
    c = {
        'source_url': 'https://5ch.test/1',
        'source_kind': '5ch',
        'post_id': '100',
        'timestamp': datetime(2026, 7, 24, 21, 0, 0),
        'posted_name': '■監督A(ロマン派)',
        'tripcode': '◆Ai4OO8X72O3b',
        'content_html': '<p>本文</p>',
    }
    result = format_output_comment(c, '■監督A（公式）')
    assert result['timestamp'] == '2026-07-24T21:00:00'
    assert result['posted_name'] == '■監督A(ロマン派)'
    assert result['official_name'] == '■監督A（公式）'
    assert result['tripcode'] == '◆Ai4OO8X72O3b'
    assert result['content_html'] == '<p>本文</p>'
    assert result['source_url'] == 'https://5ch.test/1'
    assert result['source_kind'] == '5ch'
    assert result['post_id'] == '100'


# ============================================================
# テスト: get_comment_sources (outline.json 読み込み)
# ============================================================

def test_get_comment_sources_returns_list():
    sources = get_comment_sources()
    assert isinstance(sources, list)
    assert len(sources) >= 1
    for src in sources:
        assert 'url' in src
        assert 'kind' in src


# ============================================================
# テストランナー
# ============================================================

if __name__ == '__main__':
    tests = [
        ("normalize_tripcode", test_normalize_tripcode),
        ("extract_tripcode", test_extract_tripcode),
        ("normalize_source_url", test_normalize_source_url),
        ("strip_html_tags", test_strip_html_tags),
        ("make_content_hash_text_only", test_make_content_hash_text_only),
        ("make_html_hash_structure_sensitive", test_make_html_hash_structure_sensitive),
        ("parse_5ch_date", test_parse_5ch_date),
        ("parse_shitaraba_date", test_parse_shitaraba_date),
        ("parse_5ch_page", test_parse_5ch_page),
        ("parse_5ch_page_no_trip", test_parse_5ch_page_no_trip),
        ("parse_shitaraba_page", test_parse_shitaraba_page),
        ("parse_shitaraba_no_trip", test_parse_shitaraba_no_trip),
        ("dedup_same_source_same_post", test_dedup_same_source_same_post),
        ("dedup_cross_source", test_dedup_cross_source),
        ("dedup_cross_source_different_html", test_dedup_cross_source_different_html),
        ("dedup_different_content_kept", test_dedup_different_content_kept),
        ("night_window_basic", test_night_window_basic),
        ("format_output_comment", test_format_output_comment),
        ("get_comment_sources_returns_list", test_get_comment_sources_returns_list),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
