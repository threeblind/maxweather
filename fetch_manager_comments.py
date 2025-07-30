import json
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, time, timedelta

# --- 定数 ---
EKIDEN_DATA_FILE = 'ekiden_data.json'
OUTLINE_FILE = 'outline.json'
OUTPUT_FILE = 'manager_comments.json'

# 5chからスクレイピングする際のリクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def get_manager_tripcodes():
    """ekiden_data.jsonから監督のコテハンと公式監督名を抽出し、辞書で返す"""
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {EKIDEN_DATA_FILE} の読み込みに失敗しました: {e}")
        return {}

    managers = {}
    # ◆の後にスペースが任意で入る場合に対応し、トリップ部分をキャプチャ
    trip_pattern = re.compile(r'◆\s?([a-zA-Z0-9./]+)')
    for team in data.get('teams', []):
        manager_str = team.get('manager', '')
        match = trip_pattern.search(manager_str)
        if match:
            tripcode = f"◆{match.group(1).strip()}"
            official_name = manager_str.split('◆')[0].strip()
            managers[tripcode] = official_name
    return managers

def get_thread_url():
    """outline.jsonからスレッドのURLを取得する"""
    try:
        with open(OUTLINE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('mainThreadUrl')
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {OUTLINE_FILE} の読み込みに失敗しました: {e}")
        return None

def fetch_and_process_comments():
    """5chスレッドから監督の夜間コメントを取得してJSONに保存する"""
    manager_tripcodes = get_manager_tripcodes()
    if not manager_tripcodes:
        print("監督のコテハンが見つかりませんでした。処理を中断します。")
        return

    # --- 取得対象期間の決定 ---
    now = datetime.now()
    today = now.date()

    start_time = None
    end_time = None

    # 実行時刻が夜19時以降の場合 -> 当日19:00から翌日7:00までが対象
    if now.hour >= 19:
        start_time = datetime.combine(today, time(19, 0))
        end_time = datetime.combine(today + timedelta(days=1), time(7, 0))
    # 実行時刻が朝7時より前の場合 -> 前日19:00から当日7:00までが対象
    elif now.hour < 7:
        yesterday = today - timedelta(days=1)
        start_time = datetime.combine(yesterday, time(19, 0))
        end_time = datetime.combine(today, time(7, 0))
    # それ以外の時間帯（7:00〜18:59）は対象外
    else:
        print("対象時間外です。当日のコメントは0件として処理します。")
        # 空のJSONファイルを作成して終了
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        print(f"処理完了: 0件の監督コメントを {OUTPUT_FILE} に保存しました。")
        return

    thread_url = get_thread_url()
    if not thread_url:
        print("スレッドURLが見つかりませんでした。処理を中断します。")
        return

    print(f"スレッドからコメントを取得中: {thread_url}")
    try:
        response = requests.get(thread_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = response.apparent_encoding # 文字化け対策
    except requests.RequestException as e:
        print(f"エラー: スレッドの取得に失敗しました: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')
    posts = soup.find_all('div', class_='post')
    
    manager_comments = []
    trip_pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')

    for post in posts:
        username_span = post.find('span', class_='postusername')
        date_span = post.find('span', class_='date')
        content_div = post.find('div', class_='post-content')

        if not (username_span and date_span and content_div):
            continue

        # コテハンを抽出
        trip_match = trip_pattern.search(username_span.get_text())
        if not trip_match:
            continue
        
        tripcode = trip_match.group(1)
        if tripcode in manager_tripcodes:
            try:
                # 日時をパース: "2025/07/29(火) 23:26:20.45 ID:..." のような文字列から日付と時刻を抽出
                date_text = date_span.text.strip()
                match = re.search(r'(\d{4}/\d{2}/\d{2})\(.\)\s*(\d{2}:\d{2}:\d{2})', date_text)
                if not match:
                    # 想定外のフォーマットの場合はスキップ
                    continue

                date_part = match.group(1)
                time_part = match.group(2)
                post_datetime = datetime.strptime(f"{date_part} {time_part}", '%Y/%m/%d %H:%M:%S')

                # 投稿日時が対象期間内か判定
                if start_time <= post_datetime < end_time:
                    # 投稿で実際に使われた名前を取得
                    posted_name = username_span.get_text().split('◆')[0].strip()
                    # ekiden_data.json から公式の監督名を取得
                    official_name = manager_tripcodes[tripcode]

                    comment_data = {
                        "timestamp": post_datetime.isoformat(),
                        "posted_name": posted_name,
                        "official_name": official_name,
                        "tripcode": tripcode,
                        "content_html": str(content_div)
                    }
                    manager_comments.append(comment_data)
            except (ValueError, IndexError):
                # strptimeでのエラーなど、予期せぬパース失敗はスキップ
                continue

    # 新しいコメントが上に来るように逆順ソート
    manager_comments.sort(key=lambda x: x['timestamp'], reverse=True)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(manager_comments, f, indent=2, ensure_ascii=False)

    print(f"処理完了: {len(manager_comments)}件の監督コメントを {OUTPUT_FILE} に保存しました。")

if __name__ == '__main__':
    fetch_and_process_comments()