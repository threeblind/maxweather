#!/usr/bin/env python3
"""
監督コメント取得スクリプト（マルチソース対応版）

5ch 本スレ + したらば避難所から監督の夜間コメントを取得し、
マージ・重複除去して data/manager_comments.json に保存する。

設定: config/outline.json の managerCommentSources 配列に URL と種別を列挙。
"""
import json
import os
import re
import hashlib
import requests
from bs4 import BeautifulSoup, Tag
from datetime import datetime, time, timedelta
from pathlib import Path
from time_utils import JST, now_jst, parse_jst_datetime

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')

# --- ファイル定義 ---
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
OUTLINE_FILE = CONFIG_DIR / 'outline.json'
OUTPUT_FILE = DATA_DIR / 'manager_comments.json'
TEST_EKIDEN_DATA_FILE = Path('15/ekiden_data.json')
TEST_MANAGER_COMMENTS_FILE = Path('15/manager_comments.json')
TEST_MODE = os.environ.get('EKIDEN_TEST_MODE') == '1'

# HTTP リクエスト共通ヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# --- 時間帯定数 ---
# 夜間窓: 18:00 〜 翌 07:00 (JST)
# 19時は運用上の取得開始時刻の目安であり、コメント対象日の判定には使わない。
NIGHT_START_HOUR = 18
NIGHT_END_HOUR = 7

# --- 保持期間 ---
# 当日・前日のコメントをsummaryへ渡すため、直近48時間のコメントを保持する。
# 48時間より古いコメントは保存から除外し、AI入力へ流さない。
# 未来の投稿時刻は実在コメントとして扱わない（保持上限は現在時刻）。
RETENTION_HOURS = 48


# ============================================================
# 1. 設定読み込み
# ============================================================

def get_manager_tripcodes():
    """ekiden_data.json から監督のコテハン（トリップコード）→ 公式名 の辞書を返す"""
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {EKIDEN_DATA_FILE} の読み込みに失敗しました: {e}")
        return {}

    managers = {}
    trip_pattern = re.compile(r'◆\s?([a-zA-Z0-9./]+)')
    for team in data.get('teams', []):
        manager_str = team.get('manager', '')
        match = trip_pattern.search(manager_str)
        if match:
            tripcode = normalize_tripcode(f"◆{match.group(1).strip()}")
            official_name = manager_str.split('◆')[0].strip()
            managers[tripcode] = official_name
    return managers


def normalize_source_url(url):
    """取得元URLを正規化（空白トリムのみ。末尾スラッシュは維持）"""
    return url.strip()


def get_comment_sources():
    """
    outline.json からコメント取得元リストを返す。
    [{url: str, kind: str}, ...]

    優先: managerCommentSources 配列
    フォールバック: mainThreadUrl (5ch) + links からしたらばURLを自動検出

    URL重複除去（末尾スラッシュ差異を吸収）・不正要素スキップを行う。
    """
    try:
        with open(OUTLINE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {OUTLINE_FILE} の読み込みに失敗しました: {e}")
        return []

    raw_sources = data.get('managerCommentSources', [])
    if not raw_sources:
        # フォールバック: mainThreadUrl + links スキャン
        url = data.get('mainThreadUrl')
        if url:
            raw_sources.append({'url': url, 'kind': '5ch'})
        for link in data.get('links', []):
            link_url = link.get('url', '')
            if 'shitaraba.net' in link_url:
                raw_sources.append({'url': link_url, 'kind': 'shitaraba'})

    # URL正規化・重複除去（末尾スラッシュ差異を吸収）・不正要素スキップ
    seen = {}
    for src in raw_sources:
        if not isinstance(src, dict):
            continue
        url = src.get('url', '')
        kind = src.get('kind', '')
        if not url or not kind:
            continue
        url = normalize_source_url(url)
        # 重複判定用キー: 末尾スラッシュを除去して比較
        dedup_key = url.rstrip('/')
        if dedup_key in seen:
            continue
        seen[dedup_key] = {'url': url, 'kind': kind}

    return list(seen.values())


def get_night_window():
    """
    実行時刻（JST基準）に基づいて夜間コメントの取得時間枠を返す (start, end)。
    統一枠: 18:00〜翌07:00 (JST)
    GitHub Actions は UTC 環境のため datetime.now() は使わず now_jst() を使用する。
    注: これは後方互換用。実際の取得対象は get_comment_window()（直近48時間）を使う。
    """
    now = now_jst().replace(tzinfo=None)  # JST 基準（タイムゾーンなし=JST として扱う）
    today = now.date()

    if now.hour >= NIGHT_START_HOUR:
        # 夜 → 当日18:00〜翌07:00
        start = datetime.combine(today, time(NIGHT_START_HOUR, 0))
        end = datetime.combine(today + timedelta(days=1), time(NIGHT_END_HOUR, 0))
    elif now.hour < NIGHT_END_HOUR:
        # 早朝 → 前日18:00〜当日07:00
        yesterday = today - timedelta(days=1)
        start = datetime.combine(yesterday, time(NIGHT_START_HOUR, 0))
        end = datetime.combine(today, time(NIGHT_END_HOUR, 0))
    else:
        # 日中 → テストモード: 前夜の枠（前日18:00〜当日07:00）
        yesterday = today - timedelta(days=1)
        start = datetime.combine(yesterday, time(NIGHT_START_HOUR, 0))
        end = datetime.combine(today, time(NIGHT_END_HOUR, 0))
        print(f"[テストモード] 日中のため、前夜 {NIGHT_START_HOUR}:00〜今朝 {NIGHT_END_HOUR}:00 のコメントを取得します。")

    return start, end


def get_comment_window():
    """取得対象の時間窓（rolling window）を返す (start, end)。

    現在時刻から直近 RETENTION_HOURS (48時間) を取得対象とし、前日朝のコメントも
    必ず含める。19時を意味論上の境界にしない。保持期間（保存時の48時間保持）と
    取得対象窓を分離し、投稿timestampのJST比較でフィルタする。
    end は現在時刻（未来の投稿時刻は実在コメントとして扱わない）。
    """
    now = now_jst().replace(tzinfo=None)  # JST 基準
    start = now - timedelta(hours=RETENTION_HOURS)
    return start, now


# ============================================================
# 2. コメント抽出（ソース種別別）
# ============================================================

def normalize_tripcode(tripcode):
    """トリップコードの空白・記号揺れを正規化"""
    # ◆ の後の空白除去、全角/半角統一
    tripcode = tripcode.strip()
    if tripcode.startswith('◆'):
        tripcode = '◆' + tripcode[1:].strip()
    return tripcode


def normalize_post_datetime(dt: datetime) -> datetime:
    """日時を JST 非依存の naive datetime として扱う"""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def extract_tripcode_from_text(text):
    """テキストから ◆tripcode を抽出"""
    pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')
    m = pattern.search(text)
    if m:
        return normalize_tripcode(m.group(1))
    return None


def parse_5ch_date(date_text):
    """
    5ch kizuna の日時文字列をパース。
    "2026/07/24(金) 18:43:30.58" → datetime
    """
    m = re.search(r'(\d{4}/\d{2}/\d{2})\(.\)\s*(\d{2}:\d{2}:\d{2})', date_text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", '%Y/%m/%d %H:%M:%S')
    except ValueError:
        return None


def parse_5ch_page(html, source_url):
    """
    5ch kizuna.5ch.io の HTML から投稿を抽出。
    戻り値: [comment_dict, ...]
    """
    soup = BeautifulSoup(html, 'html.parser')
    posts = soup.find_all('div', class_='post')
    comments = []

    for post in posts:
        post_id = post.get('id') or ''
        username_span = post.find('span', class_='postusername')
        date_span = post.find('span', class_='date')
        content_div = post.find('div', class_='post-content')

        if not (username_span and date_span and content_div):
            continue

        # トリップコード抽出
        username_text = username_span.get_text()
        tripcode = extract_tripcode_from_text(username_text)
        if not tripcode:
            continue

        # 日時
        post_dt = parse_5ch_date(date_span.text)
        if not post_dt:
            continue

        # 投稿名
        posted_name = username_text.split('◆')[0].strip()

        comments.append({
            'source_url': source_url,
            'source_kind': '5ch',
            'post_id': post_id,
            'timestamp': post_dt,
            'posted_name': posted_name,
            'tripcode': tripcode,
            'content_html': str(content_div),
        })

    return comments


def parse_shitaraba_date(date_text):
    """
    したらばの日時文字列をパース。
    "2026/07/25(土) 06:30:09 ID:xxx" → datetime
    または "2021/07/26(月) 22:38:15" → datetime
    """
    m = re.search(r'(\d{4}/\d{2}/\d{2})\(.\)\s*(\d{2}:\d{2}:\d{2})', date_text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", '%Y/%m/%d %H:%M:%S')
    except ValueError:
        return None


def parse_shitaraba_page(html, source_url):
    """
    したらば jbbs.shitaraba.net の HTML から投稿を抽出。
    戻り値: [comment_dict, ...]
    """
    soup = BeautifulSoup(html, 'html.parser')
    dts = soup.find_all('dt', id=re.compile(r'comment_\d+'))
    comments = []

    for dt in dts:
        # 投稿番号
        post_num_a = dt.find('a')
        post_id = post_num_a.get_text().strip() if post_num_a else ''

        # 名前 + トリップコードを含む要素を探す
        # 型安全に: 各 find 結果を Tag に絞る
        name_container: Tag | None = None
        sage_a = dt.find('a', href='mailto:sage')
        if isinstance(sage_a, Tag):
            name_container = sage_a
        if name_container is None:
            font_tag = dt.find('font')
            if isinstance(font_tag, Tag):
                name_container = font_tag
        if name_container is None:
            continue

        b_tag = name_container.find('b')
        posted_name = b_tag.get_text().strip() if isinstance(b_tag, Tag) else ''

        # トリップコード: 名前コンテナ全体のテキストから名前部分を除いた部分
        container_text = name_container.get_text()
        after_name = container_text.replace(posted_name, '', 1).strip()

        # トリップ抽出
        tripcode = extract_tripcode_from_text(after_name)
        if not tripcode:
            continue

        # 日時: dt から投稿番号リンクと名前コンテナを除いたテキスト
        date_text = dt.get_text()
        if isinstance(post_num_a, Tag):
            date_text = date_text.replace(post_num_a.get_text(), '', 1)
        date_text = date_text.replace(container_text, '', 1)
        date_text = date_text.strip().lstrip('：').strip()

        post_dt = parse_shitaraba_date(date_text)
        if not post_dt:
            continue

        # 本文 (次の <dd>)
        dd = dt.find_next_sibling('dd')
        content_html = str(dd) if isinstance(dd, Tag) else '<dd></dd>'

        comments.append({
            'source_url': source_url,
            'source_kind': 'shitaraba',
            'post_id': post_id,
            'timestamp': post_dt,
            'posted_name': posted_name,
            'tripcode': tripcode,
            'content_html': content_html,
        })

    return comments


# ============================================================
# 3. マージ・重複除去
# ============================================================

def strip_html_tags(html):
    """HTMLタグを除去し、空白を正規化してプレーンテキストを返す"""
    if not html:
        return ''
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def make_content_hash(comment):
    """本文のプレーンテキストハッシュ（dedup用 主キー）"""
    html = comment.get('content_html', '')
    text = strip_html_tags(html)
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def make_html_hash(comment):
    """本文のHTML完全一致ハッシュ（dedup用 補助キー）"""
    html = comment.get('content_html', '')
    return hashlib.md5(html.encode('utf-8')).hexdigest()


def dedup_comments(comments):
    """
    コメントリストの重複除去。

    ルール:
    1. 同一ソース内: source_url + post_id が一致 → 後勝ち
    2. 異種ソース間: timestamp + tripcode + 本文テキストハッシュ が一致 → 1件にまとめる
       (5ch と したらばで同一内容の転載、HTMLタグ/改行の違いを吸収)
       補助キーとして HTML完全一致ハッシュも併用（HTML構造が異なるがテキストが同じものを除去）
    """
    # パス1: 同一ソース内の重複除去 (source_url + post_id)
    seen_local = {}
    for c in comments:
        key = (c['source_url'], c['post_id'])
        seen_local[key] = c  # 後勝ち

    unique = list(seen_local.values())

    # パス2: 異種ソース間の重複除去
    #   主キー: (timestamp, tripcode, テキストハッシュ)
    #   補助キー: (timestamp, tripcode, HTMLハッシュ) — テキスト抽出で区別できない稀なケース用
    seen_cross = {}
    seen_html = {}
    result = []
    for c in unique:
        ts = c['timestamp'].isoformat() if isinstance(c['timestamp'], datetime) else c['timestamp']
        text_key = (ts, c['tripcode'], make_content_hash(c))
        html_key = (ts, c['tripcode'], make_html_hash(c))

        if text_key in seen_cross:
            continue  # テキスト内容が同一 → 重複
        if html_key in seen_html:
            continue  # HTMLまで完全一致 → 重複

        seen_cross[text_key] = c
        seen_html[html_key] = c
        result.append(c)

    return result


def format_output_comment(comment, official_name):
    """
    出力用にコメントを整形。
    既存フォーマットを維持しつつ、source_url/source_kind/post_id を追加。
    """
    ts = comment['timestamp']
    if isinstance(ts, datetime):
        ts_str = ts.isoformat()
    else:
        ts_str = ts

    return {
        'timestamp': ts_str,
        'posted_name': comment['posted_name'],
        'official_name': official_name or comment['posted_name'],
        'tripcode': comment['tripcode'],
        'content_html': comment['content_html'],
        'source_url': comment['source_url'],
        'source_kind': comment['source_kind'],
        'post_id': comment['post_id'],
    }


# ============================================================
# 4. メイン処理
# ============================================================

def normalize_manager_comments(entries):
    """互換性: 15回大会の fixture をそのまま通す"""
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict)]


def _comment_timestamp_jst(comment):
    """コメントの timestamp を JST 基準の naive datetime で返す。

    タイムゾーンなしの timestamp 文字列は JST として解釈し、
    タイムゾーン付き（+00:00 等）は JST へ変換する（parse_jst_datetime 共通方針）。
    不正な値は None を返す（呼び出し側でスキップする）。
    """
    ts = comment.get('timestamp') if isinstance(comment, dict) else None
    if not ts:
        return None
    return parse_jst_datetime(ts)


def _valid_comment_record(c):
    """dedup で参照する必須キーの型・内容を検証する。

    dedup_comments は timestamp / tripcode / content_html / source_url / post_id を
    直接参照し、ハッシュ計算（content_html）や日時変換（timestamp）を行うため、
    型が不正だと例外になる。各キーが非空文字列で、timestamp が JST として
    parse 可能であることを確認し、異常レコードは除外して処理全体を止めない。
    """
    if not isinstance(c, dict):
        return False
    for key in ('source_url', 'post_id', 'timestamp', 'tripcode', 'content_html'):
        val = c.get(key)
        if not isinstance(val, str) or not val.strip():
            return False
    return _comment_timestamp_jst(c) is not None


def merge_existing_comments(existing, new_comments):
    """既存JSONと新規取得コメントを統合して保持する。

    - 同一 (source_url, post_id) は1件にする（新規取得が優先）
    - 異種ソースの転載は既存 dedup ルール（dedup_comments）を維持する
    - 直近 RETENTION_HOURS (48時間) より古いコメントは除去し、
      未来時刻の投稿（> now）も除去する
    - 必須フィールド欠落・型不正の壊れた既存レコードは警告して除外し、
      正常コメントの保存を継続する
    - timestamp は JST 換算の日時で降順ソートする（文字列比較はしない）
    """
    valid_existing = [c for c in existing if _valid_comment_record(c)]
    invalid_existing = [c for c in existing if not _valid_comment_record(c)]
    if invalid_existing:
        print(f"警告: 必須フィールド欠落・型不正の既存コメント {len(invalid_existing)}件を除外しました。")
    valid_new = [c for c in new_comments if _valid_comment_record(c)]

    merged = {}
    for c in valid_existing:
        key = (c.get('source_url'), c.get('post_id'))
        merged[key] = c
    for c in valid_new:
        key = (c.get('source_url'), c.get('post_id'))
        merged[key] = c  # 新規優先

    merged_list = dedup_comments(list(merged.values()))

    now_naive = now_jst().replace(tzinfo=None)
    cutoff = now_naive - timedelta(hours=RETENTION_HOURS)
    retained = []
    for c in merged_list:
        dt = _comment_timestamp_jst(c)
        if dt is None or dt < cutoff or dt > now_naive:
            continue  # 不正timestamp・48時間より古い・未来時刻のコメントは除去
        retained.append(c)
    # JST 換算の日時で降順ソート（+00:00 等の offset 付きも正しい順序になる）。
    # 不正値（None）は datetime.min 扱いで末尾へ。
    retained.sort(key=lambda c: _comment_timestamp_jst(c) or datetime.min, reverse=True)
    return retained


def fetch_source(url, kind):
    """
    指定されたソースから HTML を取得し、投稿を抽出する。
    戻り値: (comments, error_message)
    error_message はエラー時のみ文字列、成功時は None
    """
    print(f"  取得中: [{kind}] {url}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
    except requests.RequestException as e:
        msg = f"  エラー: [{kind}] 取得失敗: {e}"
        print(msg)
        return [], msg

    try:
        if kind == 'shitaraba':
            comments = parse_shitaraba_page(response.text, url)
        else:
            # デフォルトは 5ch パーサ
            comments = parse_5ch_page(response.text, url)
    except Exception as e:
        msg = f"  エラー: [{kind}] パース失敗: {e}"
        print(msg)
        return [], msg

    print(f"  抽出: {len(comments)}件")
    return comments, None


def fetch_and_process_comments():
    """メイン処理: 全ソースからコメントを取得・マージ・保存"""
    manager_tripcodes = get_manager_tripcodes()
    if not manager_tripcodes:
        if TEST_MODE and TEST_MANAGER_COMMENTS_FILE.exists():
            print(f"情報: テストモードのため {TEST_MANAGER_COMMENTS_FILE} を使用します。")
            with open(TEST_MANAGER_COMMENTS_FILE, 'r', encoding='utf-8') as f:
                manager_comments = normalize_manager_comments(json.load(f))
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(manager_comments, f, indent=2, ensure_ascii=False)
            print(f"処理完了: {len(manager_comments)}件の監督コメントを {OUTPUT_FILE} に保存しました。")
            return
        print("監督のコテハンが見つかりませんでした。処理を中断します。")
        return

    # --- 時間枠（直近48時間の rolling window。19時を意味論上の境界にしない） ---
    start_time, end_time = get_comment_window()
    print(f"対象時間枠: {start_time} 〜 {end_time} (JST、直近{RETENTION_HOURS}時間)")

    # --- 取得元リスト ---
    sources = get_comment_sources()
    if not sources:
        print("コメント取得元が見つかりませんでした。")
        return

    print(f"取得元: {len(sources)}件")
    for src in sources:
        print(f"  - [{src['kind']}] {src['url']}")

    # --- 各ソースから独立取得 ---
    all_raw = []
    errors = []

    for src in sources:
        comments, err = fetch_source(src['url'], src['kind'])
        all_raw.extend(comments)
        if err:
            errors.append(err)

    if not all_raw:
        if errors:
            print("全ソースで取得失敗のため、既存JSONを維持します。")
            # 既存ファイルが存在する場合は壊さない
            if OUTPUT_FILE.exists():
                print(f"既存ファイル {OUTPUT_FILE} を維持します。")
            return
        print("監督コメントは見つかりませんでした。")
        return

    # --- 監督判定 & 時間枠フィルタ ---
    manager_comments = []
    trip_pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')

    for c in all_raw:
        tripcode = c['tripcode']
        if tripcode not in manager_tripcodes:
            continue

        post_dt = c['timestamp']
        if not start_time <= post_dt < end_time:
            continue

        official_name = manager_tripcodes[tripcode]
        manager_comments.append(format_output_comment(c, official_name))

    # --- 重複除去 ---
    manager_comments = dedup_comments(manager_comments)

    # --- 既存JSONとの統合（48時間保持・同一post_id重複除去） ---
    # 全ソース失敗時は既存ファイルを壊さず維持（上記 early return 済み）。
    # 一部ソース失敗時は取得済み+既存の有効なコメントを統合する。
    existing = []
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                existing = normalize_manager_comments(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告: 既存 {OUTPUT_FILE} の読み込みに失敗しました: {e}")
            existing = []
    manager_comments = merge_existing_comments(existing, manager_comments)

    # --- 保存（原子的に: 取得失敗時も既存ファイルを壊さない） ---
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = OUTPUT_FILE.with_suffix('.json.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(manager_comments, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, OUTPUT_FILE)

    print(f"処理完了: {len(manager_comments)}件の監督コメントを {OUTPUT_FILE} に保存しました。")
    if errors:
        print(f"警告: 一部ソースでエラーが発生しました ({len(errors)}件)")


if __name__ == '__main__':
    fetch_and_process_comments()
