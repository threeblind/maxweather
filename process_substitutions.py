import json
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# --- Constants ---
EKIDEN_DATA_FILE = 'ekiden_data.json'
OUTLINE_FILE = 'outline.json'
PROCESSED_LOG_FILE = 'substitution_log.txt'
STATE_FILE = 'ekiden_state.json'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_thread_url():
    """outline.jsonから5chスレッドのURLを取得します。"""
    try:
        with open(OUTLINE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('mainThreadUrl')
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {OUTLINE_FILE} を読み込めませんでした: {e}")
        return None

def get_processed_posts():
    """処理済みの投稿番号のログを読み込みます。"""
    try:
        with open(PROCESSED_LOG_FILE, 'r', encoding='utf-8') as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def log_processed_post(post_id):
    """投稿番号を処理済みログファイルに記録します。"""
    with open(PROCESSED_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{post_id}\n")

def parse_substitution_post(content):
    """選手交代の投稿内容を解析し、詳細を抽出します。
    
    修正点:
    - 選手交代の行を独立して抽出し、その行内で完結するように正規表現を修正。
    - これにより、行末に続く余分なテキストを誤って選手名として認識する問題を解決。
    """
    
    # 選手交代の行を独立して見つけ、その行内の情報を抽出
    sub_line_match = re.search(r'交代:\s*(.+?)\s*→\s*([^\n]+)', content)
    if not sub_line_match:
        return None

    details = {
        'runner_out': sub_line_match.group(1).strip(),
        'runner_in': sub_line_match.group(2).strip()
    }
    
    # 他の情報を抽出するための正規表現パターン
    patterns = {
        'university': r'大学名:\s*(.+)',
        'leg': r'区間:\s*([0-9０-９]+)区',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, content)
        if match:
            details[key] = match.group(1).strip()
    
    if 'university' in details and 'leg' in details and 'runner_out' in details and 'runner_in' in details:
        # 全角数字を半角に変換してから整数に変換
        leg_str = details['leg'].translate(str.maketrans('０１２３４５６７８９', '0123456789'))
        details['leg'] = int(leg_str)
        return details
    return None


def get_manager_tripcodes():
    """ekiden_data.jsonから監督のトリップコードを抽出し、大学名をキーにした辞書で返す"""
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
            managers[team['name']] = f"◆{match.group(1).strip()}"
    return managers

def process_substitutions():
    """選手交代を処理するメイン関数。"""
    # スレッドURLをoutline.jsonから取得します。
    thread_url = get_thread_url()
    if not thread_url:
        return

    print(f"コメントを取得中: {thread_url}")
    try:
        response = requests.get(thread_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
    except requests.RequestException as e:
        print(f"エラー: スレッドの取得に失敗しました: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    posts = soup.find_all('div', class_='post')

    processed_posts = get_processed_posts()
    # 監督のトリップコード情報を読み込む
    manager_tripcodes = get_manager_tripcodes()
    trip_pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')
    
    # 駅伝データを読み込み
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {EKIDEN_DATA_FILE} を読み込めませんでした: {e}")
        return

    teams_map = {team['name']: team for team in ekiden_data['teams']}
    # 短縮名でも照合できるように、短縮名から正式名へのマッピングを作成
    short_name_map = {team['short_name']: team['name'] for team in ekiden_data['teams'] if 'short_name' in team}

    substitution_made = False

    for post in posts:
        post_id = post.get('data-id')
        username_span = post.find('span', class_='postusername')
        content_div = post.find('div', class_='post-content')
        if not post_id or not content_div:
            continue

        # 処理済みの投稿はスキップ
        if post_id in processed_posts:
            continue

        content_text = content_div.get_text(separator='\n', strip=True)
        
        # Find all substitution blocks in the post
        substitution_blocks = re.findall(r'【選手交代】.+?→.+', content_text, re.DOTALL)

        if substitution_blocks:
            print(f"\n投稿#{post_id}に選手交代の可能性を検出しました。")

            # 投稿者のトリップコードを抽出
            posted_trip_match = trip_pattern.search(username_span.get_text()) if username_span else None
            if not posted_trip_match:
                print(f"  - 検証失敗: 投稿#{post_id}にトリップコードがありません。スキップします。")
                continue # トリップがない投稿は無視
            # Process the *last* substitution block found in the post
            last_block = substitution_blocks[-1]
            sub_details = parse_substitution_post(last_block)
            
            if not sub_details:
                print(f"  - 投稿#{post_id}: 解析できませんでした。スキップします。")
                log_processed_post(post_id)
                continue

            # --- 検証 ---
            uni_name = sub_details['university']
            leg_num = sub_details['leg']
            runner_out = sub_details['runner_out']
            runner_in = sub_details['runner_in']

            # 大学名が短縮名で投稿された場合、正式名称に変換する
            if uni_name in short_name_map:
                print(f"  - 短縮名 '{uni_name}' を正式名 '{short_name_map[uni_name]}' に変換しました。")
                uni_name = short_name_map[uni_name]

            if uni_name not in teams_map:
                print(f"  - 検証失敗: 大学 '{uni_name}' が見つかりません。")
                log_processed_post(post_id)
                continue

            # 大学名からチームオブジェクトを先に取得
            team = teams_map[uni_name]

            # ★★★ 監督のトリップコードを検証 ★★★
            official_trip = manager_tripcodes.get(uni_name)
            posted_trip = posted_trip_match.group(1)

            if not official_trip or posted_trip != official_trip:
                print(f"  - 検証失敗: 投稿者({posted_trip})は {uni_name} の正規の監督({official_trip or '未登録'})ではありません。")
                log_processed_post(post_id) # 不正な投稿も処理済みとして記録
                continue

            # 交代対象区間が、そのチームの「次の区間」であるかを検証
            # 現在の区間は ekiden_state.json から取得する必要がある
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                current_state_data = json.load(f)
            team_state = next((s for s in current_state_data if s['id'] == team['id']), None)

            leg_index = leg_num - 1

            if not (0 <= leg_index < len(team['runners'])):
                print(f"  - 検証失敗: {uni_name} の区間番号 '{leg_num}' が不正です。")
                log_processed_post(post_id)
                continue

            if not team_state or leg_num != team_state.get('currentLeg', 0) + 1:
                print(f"  - 検証失敗: {uni_name} の交代対象区間({leg_num}区)が次の区間ではありません。現在の区間: {team_state.get('currentLeg', '不明')}")
                log_processed_post(post_id)
                continue

            # 比較のために、公式の選手名から括弧部分を取り除いて正規化
            official_runner_name = team['runners'][leg_index]
            normalized_official_runner = re.sub(r'（.+）', '', official_runner_name).strip()
            if runner_out != official_runner_name and runner_out != normalized_official_runner:
                print(f"  - 検証失敗: 選手 '{runner_out}' は {uni_name} の {leg_num}区の現在の走者ではありません。正選手: '{team['runners'][leg_index]}'")
                log_processed_post(post_id)
                continue

            if runner_in not in team.get('substitutes', []):
                print(f"  - 検証失敗: 選手 '{runner_in}' は {uni_name} の補欠リストにいません。")
                log_processed_post(post_id)
                continue
            
            # --- 交代処理の実行 ---
            print(f"  - 検証成功: {uni_name} の {leg_num}区で '{runner_out}' を '{runner_in}' に交代します。")
            
            # 補欠リストから削除するためにインデックスを見つける
            sub_index = team['substitutes'].index(runner_in)
            
            # 選手を入れ替え
            team['runners'][leg_index] = runner_in
            # 区間から外れた選手は補欠になる
            team['substitutes'][sub_index] = runner_out
            
            substitution_made = True
            log_processed_post(post_id)

    if substitution_made:
        print(f"\n交代処理が完了しました。更新されたデータを {EKIDEN_DATA_FILE} に保存します。")
        with open(EKIDEN_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(ekiden_data, f, indent=2, ensure_ascii=False)
    else:
        print("\n新規の有効な交代宣言は見つかりませんでした。")

if __name__ == '__main__':
    process_substitutions()