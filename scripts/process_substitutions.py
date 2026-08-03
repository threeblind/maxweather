#!/usr/bin/env python3
"""5chスレッドの【選手交代】投稿を検証・適用する。

設計方針（leader承認済み 2026-08-03）:
- 本文大学名→チームを確定してから、そのチームの許可トリップ集合（manager文字列抽出 +
  将来のaccepted_tripcodes配列）と投稿トリップを照合する。trip→大学の逆引きはしない。
- 兼任監督に対応するため、チームは複数トリップを許可する。
- 区間判定: leg==currentLeg（走行中）または leg==currentLeg+1（次区間の事前交代）は
  自動適用候補。leg<currentLeg は過去区間なので review。leg>currentLeg+1 は拒否。
- 選手照合: runners/substitutes の文字列/辞書混在を内部正規化し、元の形式と
  station_code を保持する。括弧除去のような曖昧判定は行わず、明示 alias のみ。
- 原子性: temp + os.replace で書き込み。
- ログ: 成功した post_id のみ processed log へ。検証失敗・過去区間・設定不一致は
  logs/substitution_review.jsonl へ reason 付きで記録。監査は
  logs/substitution_audit.jsonl（post_id/source/trip/team/leg/out/in/status/reason/timestamp）。
- 冪等性: post_id 単位。同一投稿内の全ブロックが検証成功した場合のみ一括適用し、
  不正/未確認ブロックが1つでもあれば投稿全体を適用せず review へ回す。

テスト用の環境変数:
- EKIDEN_DATA_FILE / EKIDEN_STATE_FILE / EKIDEN_OUTLINE_FILE: パス上書き
- EKIDEN_LOGS_DIR: ログディレクトリ上書き
- EKIDEN_THREAD_URL: スレッドURL上書き
- EKIDEN_POSTS_HTML: ローカルHTMLファイルから投稿を読み込む（fetchをスキップ）
"""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# --- ファイル定義（環境変数で上書き可能） ---
CONFIG_DIR = Path(os.environ.get('EKIDEN_CONFIG_DIR', 'config'))
LOGS_DIR = Path(os.environ.get('EKIDEN_LOGS_DIR', 'logs'))
DATA_DIR = Path(os.environ.get('EKIDEN_DATA_DIR', 'data'))

EKIDEN_DATA_FILE = Path(os.environ.get('EKIDEN_DATA_FILE', CONFIG_DIR / 'ekiden_data.json'))
OUTLINE_FILE = Path(os.environ.get('EKIDEN_OUTLINE_FILE', CONFIG_DIR / 'outline.json'))
STATE_FILE = Path(os.environ.get('EKIDEN_STATE_FILE', DATA_DIR / 'ekiden_state.json'))
PROCESSED_LOG_FILE = LOGS_DIR / 'substitution_log.txt'
REVIEW_LOG_FILE = LOGS_DIR / 'substitution_review.jsonl'
AUDIT_LOG_FILE = LOGS_DIR / 'substitution_audit.jsonl'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# --- 明示 alias ---
# 投稿側の表記 → config 上の選手名。括弧除去などの曖昧判定は禁止。
# 解決は「解決先が対象チームの runners/substitutes に存在する場合のみ」。
EXPLICIT_RUNNER_ALIASES = {
    '大野': '大野（福井）',
}

# 区間・全角数字の変換テーブル
_FULL_TO_HALF = str.maketrans('０１２３４５６７８９', '0123456789')


def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')


# --- トリップ抽出 ---

def extract_trip(text):
    """名義・manager文字列から ◆トリップを抽出する。◆直後の空白は正規化。

    「◆ CT6iZVF9L」→「◆CT6iZVF9L」（config側の表記ゆれ対策）。
    末尾ドットは追加しない（「◆CT6iZVF9L.」は「◆CT6iZVF9L.」のまま）。
    """
    if not text:
        return None
    m = re.search(r'◆\s*([A-Za-z0-9./]+)', text)
    if not m:
        return None
    return f'◆{m.group(1)}'


def get_allowed_trips(team):
    """チームに許可されたトリップ集合を返す。

    accepted_tripcodes 配列（将来拡張）があれば優先して読み取り、
    manager 文字列からの抽出結果も併用する。
    """
    trips = set()
    for code in team.get('accepted_tripcodes', []) or []:
        c = code.strip()
        if c:
            trips.add(c if c.startswith('◆') else f'◆{c}')
    m = extract_trip(team.get('manager', ''))
    if m:
        trips.add(m)
    return trips


# --- 大学名・選手名の解決 ---

def build_team_lookup(teams):
    """正式名 / short_name / aliases からチームを引く辞書。"""
    lookup = {}
    for t in teams:
        lookup[t['name']] = t
        sn = t.get('short_name')
        if sn:
            lookup[sn] = t
        for alias in t.get('aliases', []) or []:
            lookup[alias] = t
    return lookup


def runner_name(runner):
    """runners/substitutes の要素（文字列 or 辞書）から名前を返す。"""
    if isinstance(runner, dict):
        return runner.get('name', '')
    return runner if isinstance(runner, str) else str(runner)


def resolve_runner_name(team, raw):
    """投稿の選手名をチーム内の名前に解決する。明示 alias のみ。"""
    all_names = {runner_name(r) for r in team.get('runners', []) + team.get('substitutes', [])}
    if raw in all_names:
        return raw
    if raw in EXPLICIT_RUNNER_ALIASES and EXPLICIT_RUNNER_ALIASES[raw] in all_names:
        return EXPLICIT_RUNNER_ALIASES[raw]
    return None


# --- ブロック抽出・パース ---

def extract_blocks(content):
    """投稿本文から【選手交代】ブロックを全抽出する。

    1投稿に複数の【選手交代】があっても独立して抽出する。
    ブロックは「次の【選手交代】」または本文末尾まで。
    """
    parts = content.split('【選手交代】')
    blocks = []
    for part in parts[1:]:
        blocks.append(part)
    return blocks


def parse_block(block):
    """ブロック本文から 大学名/区間/交代（前→後）を抽出する。

    形式（実スレッド実例）:
        【選手交代】
        大学名: 学連選抜
        区間: ５区
        交代: 大栃→嬉野
        後続テキスト（ここは選手名に取り込まない）…
    選手名は「交代: X→Y」の行内（改行まで）で完結させる。
    """
    d = {}
    m = re.search(r'大学名[:：]\s*(.+)', block)
    if m:
        d['university'] = m.group(1).strip()

    m = re.search(r'区間[:：]\s*([0-9０-９]+)\s*区', block)
    if m:
        leg_str = m.group(1).translate(_FULL_TO_HALF)
        d['leg'] = int(leg_str)

    # 交代行: 「交代: A→B」 行内で完結（改行まで）
    m = re.search(r'^交代[:：]\s*(.+)$', block, re.MULTILINE)
    if m:
        sub_line = m.group(1).strip()
        sm = re.match(r'(.+?)\s*[→]\s*(.+)', sub_line)
        if sm:
            d['runner_out'] = sm.group(1).strip()
            d['runner_in'] = sm.group(2).strip()

    return d


# --- 投稿取得 ---

def get_thread_url():
    """outline.json から5chスレッドのURLを取得する。"""
    if os.environ.get('EKIDEN_THREAD_URL'):
        return os.environ['EKIDEN_THREAD_URL']
    try:
        with open(OUTLINE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('mainThreadUrl')
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {OUTLINE_FILE} を読み込めませんでした: {e}")
        return None


def fetch_posts(thread_url):
    """スレッドから投稿一覧 [{id, name, content}] を取得する。

    EKIDEN_POSTS_HTML が設定されていればネットワークを使わずローカルHTMLから読む。
    """
    if os.environ.get('EKIDEN_POSTS_HTML'):
        with open(os.environ['EKIDEN_POSTS_HTML'], 'r', encoding='utf-8') as f:
            html = f.read()
    else:
        print(f"コメントを取得中: {thread_url}")
        try:
            response = requests.get(thread_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            response.encoding = response.apparent_encoding
            html = response.text
        except requests.RequestException as e:
            print(f"エラー: スレッドの取得に失敗しました: {e}")
            return []

    soup = BeautifulSoup(html, 'html.parser')
    posts = []
    for post in soup.find_all('div', class_='post'):
        pid = post.get('data-id')
        name_el = post.find('span', class_='postusername')
        content_el = post.find('div', class_='post-content')
        if pid and content_el:
            posts.append({
                'id': pid,
                'name': name_el.get_text(strip=True) if name_el else '',
                'content': content_el.get_text(separator='\n', strip=True),
            })
    return posts


# --- ログ ---

def get_processed_posts():
    """処理済み（適用成功）post_id の集合。"""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(PROCESSED_LOG_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()


def log_processed_post(post_id):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{post_id}\n")


def read_jsonl(path):
    """既存の JSONL を読み、エントリのリストを返す。"""
    if not path.exists():
        return []
    entries = []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries


def log_entry_key(entry):
    """重複防止キー: post_id + block_index + status + reason。"""
    return (
        entry.get('post_id'),
        entry.get('block_index'),
        entry.get('status'),
        entry.get('reason'),
    )


def append_jsonl(path, entry):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def append_jsonl_dedup(path, entry):
    """既存 JSONL を読み、post_id+block_index+status+reason が既にあれば追記しない。

    同じ投稿が将来適用可能になった場合（例: past_leg → 後に currentLeg が進む）は
    status/reason が変わるため別キーとなり、既存 review を残したまま成功 audit と
    processed へ進めることができる。
    """
    key = log_entry_key(entry)
    for existing in read_jsonl(path):
        if log_entry_key(existing) == key:
            return False
    append_jsonl(path, entry)
    return True


def log_review(entry):
    return append_jsonl_dedup(REVIEW_LOG_FILE, entry)


def log_audit(entry):
    return append_jsonl_dedup(AUDIT_LOG_FILE, entry)


# --- 原子書き込み ---

def atomic_write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.tmp_', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- 検証 ---

def validate_block(block, teams_map, manager_trips, state_map, posted_trip):
    """1ブロックを検証する。戻り値: (status, reason, team, details)

    status: 'ok'（自動適用候補）/ 'review'（要確認）/ 'reject'（拒否）
    """
    uni = block.get('university')
    leg = block.get('leg')
    runner_out = block.get('runner_out')
    runner_in = block.get('runner_in')

    # 必須項目
    if not uni or leg is None or not runner_out or not runner_in:
        return ('review', 'missing_field', None, block)

    # 大学名 → チーム確定（逆引きはしない）
    team = teams_map.get(uni)
    if not team:
        return ('review', f'unknown_team: {uni}', None, block)

    # トリップ照合（チームに許可されたトリップ集合）
    allowed = get_allowed_trips(team)
    if not allowed:
        return ('review', 'no_allowed_trip', team, block)
    if not posted_trip:
        return ('review', 'no_trip', team, block)
    if posted_trip not in allowed:
        return ('review', f'trip_mismatch: {posted_trip} not in {sorted(allowed)}', team, block)

    # 区間の範囲
    if not (1 <= leg <= len(team['runners'])):
        return ('reject', f'invalid_leg: {leg}', team, block)

    # 現在区間（state）
    team_state = state_map.get(team['id'])
    if not team_state:
        return ('review', 'no_state', team, block)
    current_leg = team_state.get('currentLeg')

    # 区間判定
    if leg > current_leg + 1:
        return ('reject', f'leg_too_far: {leg} > currentLeg+1({current_leg + 1})', team, block)
    if leg < current_leg:
        return ('review', f'past_leg: {leg} < currentLeg({current_leg})', team, block)
    # leg == currentLeg または currentLeg+1 → 自動適用候補

    # 交代前 = 指定区間の現走者
    leg_idx = leg - 1
    out_name = resolve_runner_name(team, runner_out)
    current_runner = runner_name(team['runners'][leg_idx])
    if out_name != current_runner:
        return ('review', f'runner_out_mismatch: {runner_out} != 現走者 {current_runner}', team, block)

    # 交代後 = 補欠リストに存在
    in_name = resolve_runner_name(team, runner_in)
    if in_name is None:
        return ('review', f'runner_in_not_found: {runner_in}', team, block)
    subs = {runner_name(r) for r in team.get('substitutes', [])}
    if in_name not in subs:
        return ('review', f'runner_in_not_substitute: {in_name}', team, block)

    return ('ok', '', team, block)


def apply_block(team, block):
    """検証済みブロックを config に適用する。元の形式と station_code を保持する。"""
    leg_idx = block['leg'] - 1
    out_name = resolve_runner_name(team, block['runner_out'])
    in_name = resolve_runner_name(team, block['runner_in'])

    out_obj = team['runners'][leg_idx]  # 文字列 or 辞書（元の形式）
    in_obj = next(r for r in team.get('substitutes', []) if runner_name(r) == in_name)

    team['runners'][leg_idx] = in_obj
    team['substitutes'] = [r for r in team.get('substitutes', []) if runner_name(r) != in_name]
    team.setdefault('substituted_out', []).append(out_obj)


# --- メイン ---

def process_substitutions():
    thread_url = get_thread_url()
    if not thread_url:
        return

    posts = fetch_posts(thread_url)
    if not posts:
        return

    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: データファイルの読み込みに失敗しました: {e}")
        return

    teams_map = build_team_lookup(ekiden_data['teams'])
    state_map = {s['id']: s for s in state_data}

    processed_posts = get_processed_posts()
    substitution_made = False

    for post in posts:
        post_id = post['id']
        if post_id in processed_posts:
            continue

        blocks = extract_blocks(post['content'])
        if not blocks:
            continue

        print(f"\n投稿#{post_id} に【選手交代】ブロックを {len(blocks)} 個検出しました。")

        posted_trip = extract_trip(post['name'])
        results = []
        for block_index, block in enumerate(blocks):
            parsed = parse_block(block)
            status, reason, team, details = validate_block(parsed, teams_map, None, state_map, posted_trip)
            results.append({
                'block': parsed,
                'block_index': block_index,
                'status': status,
                'reason': reason,
                'team': team,
            })
            print(f"  - ブロック[{block_index}]: {parsed.get('university')} {parsed.get('leg')}区 "
                  f"{parsed.get('runner_out')}→{parsed.get('runner_in')} => {status} ({reason})")

        # 冪等性: 全ブロック成功時のみ一括適用（方針B）
        all_ok = all(r['status'] == 'ok' for r in results)
        if all_ok:
            for r in results:
                team = r['team']
                apply_block(team, r['block'])
                substitution_made = True
                print(f"  - 適用: {team['name']} {r['block']['leg']}区 "
                      f"{r['block']['runner_out']}→{r['block']['runner_in']}")
            log_processed_post(post_id)
            # 監査ログ（既存 review があっても status='applied' は別キーのため追記される）
            for r in results:
                b = r['block']
                log_audit({
                    'post_id': post_id,
                    'block_index': r['block_index'],
                    'source': thread_url,
                    'trip': posted_trip,
                    'team': r['team']['name'],
                    'leg': b.get('leg'),
                    'out': b.get('runner_out'),
                    'in': b.get('runner_in'),
                    'status': 'applied',
                    'reason': '',
                    'timestamp': now_iso(),
                })
        else:
            # 1つでも不正/未確認があれば投稿全体を適用せず review へ
            for r in results:
                b = r['block']
                log_review({
                    'post_id': post_id,
                    'block_index': r['block_index'],
                    'source': thread_url,
                    'trip': posted_trip,
                    'team': r['team']['name'] if r['team'] else b.get('university'),
                    'leg': b.get('leg'),
                    'out': b.get('runner_out'),
                    'in': b.get('runner_in'),
                    'status': r['status'],
                    'reason': r['reason'],
                    'timestamp': now_iso(),
                })
                log_audit({
                    'post_id': post_id,
                    'block_index': r['block_index'],
                    'source': thread_url,
                    'trip': posted_trip,
                    'team': r['team']['name'] if r['team'] else b.get('university'),
                    'leg': b.get('leg'),
                    'out': b.get('runner_out'),
                    'in': b.get('runner_in'),
                    'status': r['status'],
                    'reason': r['reason'],
                    'timestamp': now_iso(),
                })

    if substitution_made:
        print(f"\n交代処理が完了しました。更新されたデータを {EKIDEN_DATA_FILE} に保存します。")
        atomic_write_json(EKIDEN_DATA_FILE, ekiden_data)
    else:
        print("\n新規の有効な交代宣言は見つかりませんでした。")


if __name__ == '__main__':
    process_substitutions()
