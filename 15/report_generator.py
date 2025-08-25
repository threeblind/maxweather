import json
import os
from datetime import datetime, timedelta, time
import requests
import shutil
import sys
import argparse
import re
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import unicodedata
from geopy.distance import geodesic

# --- 定数 ---
AMEDAS_STATIONS_FILE = 'amedas_stations.json'
EKIDEN_DATA_FILE = 'ekiden_data.json'
OUTLINE_FILE = 'outline.json'
STATE_FILE = 'ekiden_state.json'
INDIVIDUAL_STATE_FILE = 'individual_results.json'
RANK_HISTORY_FILE = 'rank_history.json'
LEG_RANK_HISTORY_FILE = 'leg_rank_history.json'
EKIDEN_START_DATE = '2025-07-23'
KML_FILE = 'ekiden_map.kml'
RUNNER_LOCATIONS_OUTPUT_FILE = 'runner_locations.json'
COURSE_PATH_FILE = 'course_path.json'

# 5chからスクレイピングする際のリクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
# --- グローバル変数 ---
stations_data = []
ekiden_data = {}

# --- 関数定義 ---

def load_all_data():
    """必要なJSONファイルをすべて読み込む"""
    global stations_data, ekiden_data
    try:
        with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: データファイルが見つかりません。 {e.filename}")
        exit(1)
    except json.JSONDecodeError:
        print(f"エラー: JSONファイルの形式が正しくありません。")
        exit(1)

def find_station_by_name(name):
    """地点名から観測所情報を検索"""
    return next((s for s in stations_data if s['name'] == name), None)

def fetch_max_temperature(pref_code, station_code):
    """Yahoo天気から最高気温を取得"""
    url = f"https://weather.yahoo.co.jp/weather/amedas/{pref_code}/{station_code}.html"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        record_high_li = soup.find('li', class_='recordHigh')
        if not record_high_li or record_high_li.find('dt').text.strip() != '最高':
            return {'temperature': None, 'error': '気温データなし'}

        dd = record_high_li.find('dd')
        if not dd:
            return {'temperature': None, 'error': '気温情報解析失敗'}

        temp_value_str = dd.contents[0].strip()
        temperature = float(temp_value_str)
        return {'temperature': temperature, 'error': None}

    except requests.RequestException as e:
        return {'temperature': None, 'error': f"通信エラー: {e}"}
    except (ValueError, TypeError):
        return {'temperature': None, 'error': '気温が数値でない'}
    except Exception:
        return {'temperature': None, 'error': '不明な解析エラー'}

def load_ekiden_state(file_path):
    """駅伝の現在の状態を読み込む"""
    if not os.path.exists(file_path):
        return [
            {
                "id": team["id"], "name": team["name"],
                "totalDistance": 0, "currentLeg": 1, "overallRank": 0
            } for team in ekiden_data['teams']
        ]
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_individual_results(file_path):
    """選手個人の結果を読み込む"""
    if not os.path.exists(file_path):
        # 初期状態を生成
        runners_state = {}
        for team in ekiden_data['teams']:
            for runner_name in team['runners']:
                # 選手名をキーとして、総距離、チームID、記録配列を保存
                runners_state[runner_name] = {
                    "totalDistance": 0,
                    "teamId": team['id'],
                    "records": []
                }
        return runners_state
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_ekiden_state(state, file_path):
    """駅伝の現在の状態を保存する"""
    data_to_save = [
        {
            "id": s["id"], "name": s["name"], "totalDistance": s["totalDistance"],
            "currentLeg": s["newCurrentLeg"], "overallRank": s["overallRank"]
        } for s in state
    ]
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=2, ensure_ascii=False)

def save_individual_results(runners_state, file_path):
    """選手個人の結果を保存する"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(runners_state, f, indent=2, ensure_ascii=False)

def get_east_asian_width_count(text):
    """全角文字を2、半角文字を1として文字幅をカウント"""
    return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in text)

def pad_str(text, length, char='＿'):
    """指定した文字幅になるように文字列をパディング"""
    padding = length - get_east_asian_width_count(text)
    return text + char * (padding if padding > 0 else 0)

def get_manager_tripcodes(ekiden_data):
    """ekiden_data.jsonから監督のコテハンと公式監督名を抽出し、辞書で返す"""
    managers = {}
    # ◆の後にスペースが任意で入る場合に対応し、トリップ部分をキャプチャ
    trip_pattern = re.compile(r'◆\s?([a-zA-Z0-9./]+)')
    for team in ekiden_data.get('teams', []):
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

def fetch_daytime_manager_comment(ekiden_data):
    """
    日中（7:00-18:59）に投稿された最新の監督コメントを1件取得する。
    """
    now = datetime.now()
    if not (7 <= now.hour < 19):
        return None
    manager_tripcodes = get_manager_tripcodes(ekiden_data)
    thread_url = get_thread_url()
    if not manager_tripcodes or not thread_url:
        return None

    try:
        response = requests.get(thread_url, headers=HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
    except requests.RequestException:
        return None # 通信エラー時は何も返さない

    soup = BeautifulSoup(response.text, 'html.parser')
    posts = soup.find_all('div', class_='post')
    trip_pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')

    # 新しい投稿が下にあるので、逆順にループして最新のものを探す
    for post in reversed(posts):
        username_span = post.find('span', class_='postusername')
        date_span = post.find('span', class_='date')
        content_div = post.find('div', class_='post-content')

        if not (username_span and date_span and content_div):
            continue

        trip_match = trip_pattern.search(username_span.get_text())
        if not trip_match or trip_match.group(1) not in manager_tripcodes:
            continue

        date_match = re.search(r'(\d{4}/\d{2}/\d{2})\(.\)\s*(\d{2}:\d{2}:\d{2})', date_span.text.strip())
        if not date_match:
            continue

        post_datetime = datetime.strptime(f"{date_match.group(1)} {date_match.group(2)}", '%Y/%m/%d %H:%M:%S')
        # 日中(7-19時)かつ、投稿が10分以内であるかチェック
        if time(7, 0) <= post_datetime.time() < time(19, 0) and (now - post_datetime) < timedelta(minutes=10):
            posted_name = username_span.get_text().split('◆')[0].strip()
            content_text = content_div.get_text(separator=' ', strip=True)
            return {'name': posted_name, 'content': content_text}

    return None # 対象時間内のコメントが見つからなかった場合

def save_realtime_report(results, race_day, breaking_news_comment, breaking_news_timestamp, breaking_news_full_text=""):
    """速報用のJSONデータを生成して保存する"""
    now = datetime.now()
    report_data = {
        "updateTime": now.strftime('%Y/%m/%d %H:%M'),
        "raceDay": race_day,
        "breakingNewsComment": breaking_news_comment,
        "breakingNewsTimestamp": breaking_news_timestamp,
        "breakingNewsFullText": breaking_news_full_text,
        "teams": []
    }

    # resultsは既に総合順位でソートされている想定
    for r in results:
        team_info = next(t for t in ekiden_data['teams'] if t['id'] == r['id'])
        next_runner_name = team_info['runners'][r['currentLegNumber']] if r['currentLegNumber'] < len(team_info['runners']) else '----'
        next_runner_str = 'ゴール' if next_runner_name == '----' else f"{r['currentLegNumber'] + 1}{next_runner_name}"

        report_data["teams"].append({
            "id": r["id"],
            "name": r["name"],
            "short_name": team_info.get("short_name", r["name"]),
            "currentLeg": r["currentLegNumber"],
            "runner": f"{r['currentLegNumber']}{r['runner']}",
            "todayDistance": r["todayDistance"],
            "todayRank": r["todayRank"],
            "totalDistance": r["totalDistance"],
            "overallRank": r["overallRank"],
            "previousRank": r["previousRank"],
            "nextRunner": next_runner_str,
            "error": r['rawTempResult']['error']
        })

    with open('realtime_report.json', 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

def update_rank_history(results, race_day, rank_history_file_path):
    """
    Updates the daily rank history file (e.g., rank_history.json).
    - results: List of today's results, sorted by overall rank.
    - race_day: The current day of the race.
    - rank_history_file_path: Path to the rank history file.
    """
    try:
        with open(rank_history_file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # ファイルがない、または不正な場合は初期化
        history = {
            "dates": [],
            "teams": [{"id": t["id"], "name": t["name"], "ranks": [], "distances": []} for t in ekiden_data['teams']]
        }

    today_str = (datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d') + timedelta(days=race_day - 1)).strftime('%Y-%m-%d')

    # 日付のインデックスを取得または新規追加
    try:
        date_index = history["dates"].index(today_str)
    except ValueError:
        history["dates"].append(today_str)
        date_index = len(history["dates"]) - 1
        # 新しい日付の場合、全チームの履歴配列を拡張
        for team_history in history["teams"]:
            team_history["ranks"].append(None)
            team_history["distances"].append(None)

    # チームIDをキーにした辞書を作成して効率化
    history_teams_map = {team['id']: team for team in history['teams']}

    # 今日の結果を履歴に反映
    for result in results:
        team_id = result['id']
        if team_id in history_teams_map:
            team_history = history_teams_map[team_id]
            team_history['ranks'][date_index] = result['overallRank']
            team_history['distances'][date_index] = result['totalDistance']

    # ファイルに保存
    with open(rank_history_file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def update_leg_rank_history(results, previous_day_state, leg_rank_history_file_path, is_commit_mode=False):
    """
    Updates the leg-by-leg rank history file (leg_rank_history.json).
    This function records the overall rank of a team at the moment it completes a leg.

    - results: List of today's results, sorted by overall rank.
    - previous_day_state: The state of the ekiden from the *start* of the day (before today's results).
    - leg_rank_history_file_path: Path to the leg rank history file.
    - is_commit_mode: If True, overwrites any existing rank for a leg completed today.
                      If False (realtime), only records if the rank is not yet set.
    """
    num_legs = len(ekiden_data['leg_boundaries'])

    try:
        with open(leg_rank_history_file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Initialize if file doesn't exist or is invalid
        history = {
            "teams": [
                {
                    "id": t["id"], "name": t["name"],
                    "leg_ranks": [None] * num_legs
                } for t in ekiden_data['teams']
            ]
        }

    # Create maps for efficient lookups
    previous_state_map = {team['id']: team for team in previous_day_state}
    history_teams_map = {team['id']: team for team in history['teams']}

    # Iterate through today's results
    for result in results:
        team_id = result['id']
        prev_state = previous_state_map.get(team_id)
        team_history = history_teams_map.get(team_id)

        if not prev_state or not team_history:
            continue

        # The team started the day in `prev_state['currentLeg']`.
        # It is now in `result['newCurrentLeg']`.
        # We update the ranks for all legs completed today with the current overall rank.
        start_leg_today = prev_state['currentLeg']
        last_completed_leg = result['newCurrentLeg'] - 1

        # Iterate from the leg they started today up to the last leg they completed.
        for leg_number in range(start_leg_today, last_completed_leg + 1):
            leg_index = leg_number - 1
            if 0 <= leg_index < len(team_history['leg_ranks']):
                # In commit mode, always overwrite.
                # In realtime mode, update continuously as requested.
                # The previous logic of only writing once (if None) is removed
                # to allow for continuous updates.
                team_history['leg_ranks'][leg_index] = result['overallRank']

    with open(leg_rank_history_file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def generate_breaking_news_comment(current_results, previous_report_data):
    """前回と今回の結果を比較し、注目すべき変動があれば速報コメントを生成する"""
    now = datetime.now()
    # 夜間（19時以降）と早朝（7時前）は速報を生成しない
    if not (7 <= now.hour < 19):
        return ""

    if not previous_report_data:
        return ""

    # チームIDをキーにしたマップを作成
    current_teams_map = {team['id']: team for team in current_results}
    previous_ranks = {team['id']: team['overallRank'] for team in previous_report_data.get('teams', [])}

    # --- コメント生成ロジック (優先度順) ---

    # 1. 首位交代 (最優先)
    if current_results and previous_report_data.get('teams'):
        current_leader_id = current_results[0]['id']
        previous_leader_id = previous_report_data['teams'][0]['id']
        if current_leader_id != previous_leader_id:
            current_leader_name = current_results[0]['name']
            return f"【速報】首位交代！ {current_leader_name}がトップに浮上しました！"

    previous_distances = {team['id']: team['totalDistance'] for team in previous_report_data.get('teams', [])}
   # 2. 首位争い (0.5km差以内で、差が縮まっている場合)
    if len(current_results) > 1:
        team_1 = current_results[0]
        team_2 = current_results[1]
        current_gap_lead = team_1['totalDistance'] - team_2['totalDistance']

        prev_dist_1 = previous_distances.get(team_1['id'])
        prev_dist_2 = previous_distances.get(team_2['id'])

        if prev_dist_1 is not None and prev_dist_2 is not None:
            previous_gap_lead = prev_dist_1 - prev_dist_2
            if 0 <= current_gap_lead < 1.0: # 差が1.0km未満であれば常に表示
                return f"【首位争い】トップ{team_1['name']}に2位{team_2['name']}が肉薄！その差わずか{current_gap_lead:.1f}km！"


    # 2. 区間走破
    previous_teams_map = {team['id']: team for team in previous_report_data.get('teams', [])}
    previous_distances = {team['id']: team['totalDistance'] for team in previous_report_data.get('teams', [])}
    leg_finishers_by_leg = {}  # {leg_number: [team_name1, team_name2]}

    for team in current_results:
        team_id = team['id']
        if team_id in previous_teams_map:
            previous_team = previous_teams_map[team_id]
            previous_total_distance = previous_distances.get(team_id)

            # チームが前回更新時にいた区間（＝本日担当区間）をチェック対象とする
            leg_to_check_completion = previous_team['currentLeg']

            if leg_to_check_completion <= len(ekiden_data['leg_boundaries']) and previous_total_distance is not None:
                boundary = ekiden_data['leg_boundaries'][leg_to_check_completion - 1]
                # この更新サイクルで、初めて区間の境界線を越えたかを判定
                if team['totalDistance'] >= boundary and previous_total_distance < boundary:
                    completed_leg = leg_to_check_completion
                    if completed_leg not in leg_finishers_by_leg:
                        leg_finishers_by_leg[completed_leg] = []
                    leg_finishers_by_leg[completed_leg].append(team['name'])

    if leg_finishers_by_leg:
        comments = []
        # Sort by leg number to announce earlier legs first
        for leg, teams in sorted(leg_finishers_by_leg.items()):
            team_names_str = '、'.join(teams)
            comments.append(f"{team_names_str}が{leg}区を走りきりました！")
        return "【区間走破】" + " ".join(comments)
    
# 3. Heat wave record (only on record update)
    hottest_runners = []
    # Create a map of previous temperatures keyed by team ID
    previous_temps_map = {team['id']: team.get('todayDistance', 0) for team in previous_report_data.get('teams', [])}

    for r in current_results:
        # Extract runners who are at 40.0km or higher AND have surpassed their previous record for the day
        if r.get('todayDistance', 0) >= 40.0 and r['todayDistance'] > previous_temps_map.get(r['id'], 0):
            hottest_runners.append(r)

    if hottest_runners:
        runner_details = [f"{r['name']}の{r['runner']}選手({r['todayDistance']:.1f}km)" for r in hottest_runners]
        runner_list_str = ', '.join(runner_details)
        return f"【酷暑】{runner_list_str}が脅威の走りで酷暑日超え、これは強烈な走り！！"
        

# 3. Heat wave record (only on record update)
    hotter_runners = []
    # Create a map of previous temperatures keyed by team ID
    previous_temps_map = {team['id']: team.get('todayDistance', 0) for team in previous_report_data.get('teams', [])}

    for r in current_results:
        # Extract runners who are at 39.0km or higher AND have surpassed their previous record for the day
        if r.get('todayDistance', 0) >= 39.0 and r['todayDistance'] > previous_temps_map.get(r['id'], 0):
            hotter_runners.append(r)

    if hotter_runners:
        runner_details = [f"{r['name']}の{r['runner']}選手({r['todayDistance']:.1f}km)" for r in hotter_runners]
        runner_list_str = ', '.join(runner_details)
        return f"【猛暑】{runner_list_str}が39kmを超える走りをみせています！素晴らしい走りです！"
        
    
    # 4. 27度以下の選手への鼓舞 (16時まで、本日初の場合のみ)
    if 13 <=now.hour < 16:
        cold_runners = [r for r in current_results if 0 < r.get('todayDistance', 0) <= 27.0]
        if cold_runners and not previous_report_data.get('breakingNewsComment', '').startswith('【奮起】'):
            runner_details = [f"{r['name']}の{r['runner']}選手({r['todayDistance']:.1f}km)" for r in cold_runners]
            runner_list_str = '、'.join(runner_details)
            return f"【奮起】{runner_list_str}、ここからの追い上げに期待がかかります！"

    # 5. 3ランク以上のジャンプアップ
    jump_up_teams = []
    for team_id, current_rank in {t['id']: t['overallRank'] for t in current_results}.items():
        if team_id in previous_ranks:
            previous_rank = previous_ranks[team_id]
            if previous_rank - current_rank >= 3:
                team_name = current_teams_map[team_id]['name']
                jump_up_teams.append({
                    "name": team_name, "jump": previous_rank - current_rank, "current_rank": current_rank
                })
    if jump_up_teams:
        best_jumper = max(jump_up_teams, key=lambda x: x['jump'])
        return f"【ジャンプアップ】{best_jumper['name']}が{best_jumper['jump']}ランクアップで{best_jumper['current_rank']}位に浮上！"

    # 6. 5ランク以上のランクダウン
    rank_down_teams = []
    for team_id, current_rank in {t['id']: t['overallRank'] for t in current_results}.items():
        if team_id in previous_ranks:
            previous_rank = previous_ranks[team_id]
            if current_rank - previous_rank >= 5:
                team_name = current_teams_map[team_id]['name']
                rank_down_teams.append({
                    "name": team_name, "drop": current_rank - previous_rank
                })
    if rank_down_teams:
        worst_dropper = max(rank_down_teams, key=lambda x: x['drop'])
        return f"【波乱】{worst_dropper['name']}が{worst_dropper['drop']}ランクダウン。厳しい展開です。"

    # 7. 追い上げ
    previous_distances = {team['id']: team['totalDistance'] for team in previous_report_data.get('teams', [])}
    closing_gap_teams = []
    for i in range(1, len(current_results)):
        current_team = current_results[i]
        team_ahead = current_results[i-1]

        current_gap = team_ahead['totalDistance'] - current_team['totalDistance']

        prev_team_dist = previous_distances.get(current_team['id'])
        prev_ahead_dist = previous_distances.get(team_ahead['id'])

        if prev_team_dist is not None and prev_ahead_dist is not None:
            previous_gap = prev_ahead_dist - prev_team_dist
            gap_closed = previous_gap - current_gap
            if gap_closed >= 2.0:
                closing_gap_teams.append({
                    "name": current_team['name'], "gap_closed": gap_closed
                })
    if closing_gap_teams:
        best_closer = max(closing_gap_teams, key=lambda x: x['gap_closed'])
        return f"【追い上げ】{best_closer['name']}が猛追！前のチームとの差を{best_closer['gap_closed']:.1f}km縮めました！"

    # 8. 接戦 (表彰台、トップ5、シード権)

    if len(current_results) > 3:
        team_3 = current_results[2]
        team_4 = current_results[3]
        current_gap_podium = team_3['totalDistance'] - team_4['totalDistance']

        prev_dist_3 = previous_distances.get(team_3['id'])
        prev_dist_4 = previous_distances.get(team_4['id'])

        if prev_dist_3 is not None and prev_dist_4 is not None:
            previous_gap_podium = prev_dist_3 - prev_dist_4
            if 0 <= current_gap_podium < 0.5 and current_gap_podium < previous_gap_podium:
                return f"【表彰台争い】3位{team_3['name']}と4位{team_4['name']}が激しく競り合っています！"

    if len(current_results) > 5:
        team_5 = current_results[4]
        team_6 = current_results[5]
        current_gap_top5 = team_5['totalDistance'] - team_6['totalDistance']

        prev_dist_5 = previous_distances.get(team_5['id'])
        prev_dist_6 = previous_distances.get(team_6['id'])

        if prev_dist_5 is not None and prev_dist_6 is not None:
            previous_gap_top5 = prev_dist_5 - prev_dist_6
            if 0 <= current_gap_top5 < 0.5 and current_gap_top5 < previous_gap_top5:
                return f"【トップ5争い】5位{team_5['name']}と6位{team_6['name']}がデッドヒート！"

    if len(current_results) > 10:
        # シード権争い (10位 vs 11位)
        team_10 = current_results[9] # 10th place
        team_11 = current_results[10] # 11th place
        current_gap_seed = team_10['totalDistance'] - team_11['totalDistance']

        prev_dist_10 = previous_distances.get(team_10['id'])
        prev_dist_11 = previous_distances.get(team_11['id'])

        if prev_dist_10 is not None and prev_dist_11 is not None:
            previous_gap_seed = prev_dist_10 - prev_dist_11
            # Announce only if the gap is now under 0.5km AND it has shrunk since the last update
            if 0 <= current_gap_seed < 0.5 and current_gap_seed < previous_gap_seed:
                return f"【シード権争い】10位{team_10['name']}と11位{team_11['name']}が熾烈な争い！"
    
    # --- 定時速報ロジック (他の速報がない場合に表示) ---
    can_show_timed_report = True
    last_comment = previous_report_data.get('breakingNewsComment', "")
    last_timestamp_str = previous_report_data.get('breakingNewsTimestamp')

    if last_comment and last_timestamp_str:
        try:
            last_timestamp = datetime.fromisoformat(last_timestamp_str)
            if (now - last_timestamp) < timedelta(hours=1):
                # 1時間以内に速報があった場合、それが「定時速報」でなければ、今回の定時速報は表示しない
                if not last_comment.startswith("【定時速報】"):
                    can_show_timed_report = False
        except (ValueError, TypeError):
            pass # タイムスタンプの形式が不正な場合は無視

    if can_show_timed_report:
        # 9. 定時速報 (選手)
        if current_results and now.hour in range(7, 19) and now.minute == 45:
            top_performer_today = max(current_results, key=lambda x: x.get('todayDistance', 0))
            if top_performer_today.get('todayDistance', 0) > 0:
                runner_name = top_performer_today['runner']
                distance = top_performer_today['todayDistance']
                return f"【定時速報】本日のトップは{runner_name}選手！{distance:.1f}kmと素晴らしい走りです！"

        # 10. 定時速報 (チーム)
        if current_results and now.hour in range(7, 19) and now.minute == 15:
            top_team = current_results[0]
            team_name = top_team['name']
            total_distance = top_team['totalDistance']
            return f"【定時速報】現在トップは{team_name}！総合距離{total_distance:.1f}kmです！"

    return "" # 大きな変動がなければ空文字列を返す

def get_leg_number_from_name(name):
    """'第１区'のようなPlacemark名から区間番号を抽出します。"""
    match = re.search(r'第(\d+)区', name)
    if match:
        return int(match.group(1))
    return float('inf') # マッチしない場合は最後にソートされるように大きな数を返す

def calculate_and_save_runner_locations(teams_data):
    """
    course_path.jsonとリアルタイムレポートから、各チームの現在位置（緯度経度）を計算する。
    """
    # 1. 事前に生成されたコースパスファイルを読み込む
    try:
        with open(COURSE_PATH_FILE, 'r', encoding='utf-8') as f:
            all_points = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {COURSE_PATH_FILE} の読み込みに失敗しました: {e}")
        print("ヒント: `python process_kml.py` を実行して、コースファイルを生成してください。")
        return

    if not all_points:
        print(f"エラー: {COURSE_PATH_FILE} にコースの座標データが見つかりませんでした。")
        return

    # 2. 各チームの距離に基づいて座標を特定
    runner_locations = []
    print("各チームの現在位置を計算中...")

    team_info_map = {t['id']: t for t in ekiden_data['teams']}

    for team in teams_data:
        target_distance_km = team.get('totalDistance', 0)
        cumulative_distance_km = 0.0
        # デフォルトはコースのスタート地点に設定
        team_lat, team_lon = all_points[0]['lat'], all_points[0]['lon']
        location_found = False

        for i in range(1, len(all_points)):
            p1 = (all_points[i-1]['lat'], all_points[i-1]['lon'])
            p2 = (all_points[i]['lat'], all_points[i]['lon'])
            segment_distance_km = geodesic(p1, p2).kilometers

            # ターゲット距離が現在のセグメント内にあるかチェック
            if segment_distance_km > 0 and cumulative_distance_km <= target_distance_km < cumulative_distance_km + segment_distance_km:
                distance_into_segment = target_distance_km - cumulative_distance_km
                fraction = distance_into_segment / segment_distance_km
                team_lat = p1[0] + fraction * (p2[0] - p1[0])
                team_lon = p1[1] + fraction * (p2[1] - p1[1])
                location_found = True
                break
            cumulative_distance_km += segment_distance_km
        
        # ループ内で位置が見つからず、かつ総距離がコース長以上の場合（＝完走後）はゴール地点に配置
        if not location_found and target_distance_km >= cumulative_distance_km:
            team_lat, team_lon = all_points[-1]['lat'], all_points[-1]['lon']
        
        team_info = team_info_map.get(team.get('id'))
        short_name = team_info.get('short_name', team.get('name')) if team_info else team.get('name')

        runner_locations.append({
            "rank": team.get('overallRank'), "team_name": team.get('name'),
            "team_short_name": short_name,
            "runner_name": team.get('runner'), "total_distance_km": team.get('totalDistance'),
            "latitude": team_lat, "longitude": team_lon
        })
        print(f"  {team.get('overallRank')}位 {team.get('name'):<10} @ {team.get('totalDistance'):.1f} km -> ({team_lat:.6f}, {team_lon:.6f})")

    # 3. 結果をJSONファイルに保存
    with open(RUNNER_LOCATIONS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(runner_locations, f, indent=2, ensure_ascii=False)

    print(f"\n計算完了: {len(runner_locations)}チームの位置を特定しました。")
    print(f"結果を {RUNNER_LOCATIONS_OUTPUT_FILE} に保存しました。")

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝のレポートを生成します。')
    parser.add_argument('--realtime', action='store_true', help='リアルタイム速報用のJSON (realtime_report.json) を生成します。')
    parser.add_argument('--commit', action='store_true', help='本日の結果を状態ファイル (ekiden_state.json) に保存します。')
    # テスト用のファイルパスを指定するオプションを追加
    parser.add_argument('--state-file', default=STATE_FILE, help=f'チームの状態ファイルパス (デフォルト: {STATE_FILE})')
    parser.add_argument('--individual-state-file', default=INDIVIDUAL_STATE_FILE, help=f'個人の状態ファイルパス (デフォルト: {INDIVIDUAL_STATE_FILE})')
    parser.add_argument('--history-file', default=RANK_HISTORY_FILE, help=f'Daily rank history file path (default: {RANK_HISTORY_FILE})')
    parser.add_argument('--leg-history-file', default=LEG_RANK_HISTORY_FILE, help=f'Leg-by-leg rank history file path (default: {LEG_RANK_HISTORY_FILE})')
    args = parser.parse_args()

    load_all_data()

    # Copy the previous report for comparison
    previous_report_file = 'realtime_report_previous.json'
    realtime_report_file = 'realtime_report.json'
    previous_report_data = None # 変数を初期化
    if os.path.exists(realtime_report_file):
        shutil.copy(realtime_report_file, previous_report_file)
        try:
            with open(previous_report_file, 'r', encoding='utf-8') as f:
                # previous_report_data はこの後の速報コメント生成で利用される
                previous_report_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"警告: {previous_report_file} の読み込みに失敗しました。")
            previous_report_data = None # 読み込み失敗時も変数をNoneに設定

    start_date = datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d')
    race_day = (datetime.now().date() - start_date.date()).days + 1

    current_state = load_ekiden_state(args.state_file)
    previous_rank_map = {s['id']: s['overallRank'] for s in current_state}
    individual_results = load_individual_results(args.individual_state_file)

    results = []
    print("速報を生成中... 全チームの気温データを取得しています。")
    for team_state in current_state:
        team_data = next(t for t in ekiden_data['teams'] if t['id'] == team_state['id'])
        runner_index = team_state['currentLeg'] - 1
        
        print(f"  {team_data['name']} のデータを取得中...")

        # 現在の区間の選手のみを処理対象とする
        if runner_index < len(team_data['runners']):
            runner_name = team_data['runners'][runner_index]
            station = find_station_by_name(runner_name)

            if not station:
                temp_result = {'temperature': 0, 'error': '地点不明'}
            else:
                temp_result = fetch_max_temperature(station['pref_code'], station['code'])

            if temp_result.get('temperature'):
                today_distance = temp_result['temperature']

                runner_info = individual_results.setdefault(runner_name, {
                    "totalDistance": 0, "teamId": team_data['id'], "records": []
                })

                record_for_today = next((r for r in runner_info['records'] if r.get('day') == race_day), None)

                if record_for_today:
                    record_for_today['distance'] = today_distance
                else:
                    runner_info['records'].append({"day": race_day, "leg": team_state["currentLeg"], "distance": today_distance})

                runner_info['totalDistance'] = round(sum(r['distance'] for r in runner_info['records']), 1)
        else:
            runner_name, temp_result = 'ゴール', {'temperature': 0, 'error': None}

        today_distance = temp_result['temperature'] or 0
        new_total_distance = round(team_state['totalDistance'] + today_distance, 1)

        new_current_leg = team_state['currentLeg']
        if team_state['currentLeg'] <= len(ekiden_data['leg_boundaries']):
            boundary = ekiden_data['leg_boundaries'][team_state['currentLeg'] - 1]
            if new_total_distance >= boundary:
                new_current_leg = team_state['currentLeg'] + 1

        results.append({
            "id": team_state["id"], "name": team_state["name"], "runner": runner_name,
            "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": new_current_leg,
            "todayDistance": today_distance, "totalDistance": new_total_distance,
            "previousRank": previous_rank_map.get(team_state["id"], 0),
            "rawTempResult": temp_result
        })

    # 今日の順位を計算 (Standard competition ranking)
    results.sort(key=lambda x: x['todayDistance'], reverse=True)
    last_score = -1
    last_rank = 0
    for i, r in enumerate(results):
        if r['todayDistance'] != last_score:
            last_rank = i + 1
            last_score = r['todayDistance']
        r['todayRank'] = last_rank

    # 総合順位を計算 (Standard competition ranking)
    results.sort(key=lambda x: x['totalDistance'], reverse=True)
    last_score = -1
    last_rank = 0
    for i, r in enumerate(results):
        if r['totalDistance'] != last_score:
            last_rank = i + 1
            last_score = r['totalDistance']
        r['overallRank'] = last_rank
        
    # レポート生成
    now = datetime.now()
    report = []
    report.append(f"{now.month}月{now.day}日　{race_day}日目　 速報（{now.strftime('%H:%M')}現在）\n")
    report.append('　 　 　 　 　 　 　　 　 　　本日　.　.　.　.　.総合')
    report.append('　大学名　.　.　走者　.　距離 . 順位　.　距離　. 　順位　. 次走者　.　被交代選手　')

    for i, r in enumerate(results):
        team_info = next(t for t in ekiden_data['teams'] if t['id'] == r['id'])
        next_runner_name = team_info['runners'][r['currentLegNumber']] if r['currentLegNumber'] < len(team_info['runners']) else '----'
        next_runner_str = 'ゴール' if next_runner_name == '----' else f"{r['currentLegNumber'] + 1}{next_runner_name}"

        # 各パーツをフォーマット
        name_part = pad_str(r['name'], 10)
        runner_part = pad_str(f"{r['currentLegNumber']}{r['runner']}", 9)
        today_dist_part = f"{r['todayDistance']:.1f}".rjust(4) if not r['rawTempResult']['error'] else '----'.rjust(4)
        today_rank_part = f"{r['todayRank']:02d}"
        total_dist_part = f"{r['totalDistance']:05.1f}" # 総合距離をゼロ埋め
        prev_rank_part = f"({r['previousRank']:02d})" if r['previousRank'] > 0 else '(－)'
        overall_rank_part = f"{r['overallRank']:02d}{prev_rank_part}"

        line = (
            f"{name_part}.　{runner_part}　{today_dist_part}　.　"
            f"{today_rank_part}　.　{total_dist_part}　.　"
            f"{overall_rank_part}　{next_runner_str}"
        )
        report.append(line)
        if i == 9:
            report.append('---------------------------------------------------　')

    print("\n--- 速報生成完了 ---")
    print("\n".join(report))

    if args.realtime:
        comment_to_save = ""
        timestamp_to_save = ""
        full_text_to_save = ""

        # 1. 監督の日中コメントを最優先でチェック
        daytime_comment = fetch_daytime_manager_comment(ekiden_data)
        if daytime_comment:
            content_snippet = daytime_comment['content']
            full_text = f"【{daytime_comment['name']}監督コメント】\n\n{daytime_comment['content']}"
            if len(content_snippet) > 50:
                content_snippet = content_snippet[:50] + '…'
            
            formatted_comment = f"【{daytime_comment['name']}監督コメント】{content_snippet}"
            
            # 前回と同じコメントでなければ採用
            if previous_report_file and formatted_comment != previous_report_data.get('breakingNewsComment', ''):
                comment_to_save = formatted_comment
                full_text_to_save = full_text
                timestamp_to_save = datetime.now().isoformat()
                print(f"Generated breaking news from manager comment: '{comment_to_save}'")

        # 2. 監督コメントがない場合、通常の速報生成ロジックを実行
        if not comment_to_save and previous_report_data:
            new_comment_text = generate_breaking_news_comment(results, previous_report_data)
            if new_comment_text:
                comment_to_save = new_comment_text
                full_text_to_save = "" # 通常の速報には全文はない
                timestamp_to_save = datetime.now().isoformat()
                print(f"Generated breaking news: '{comment_to_save}'")

        # 3. 新しい速報がない場合、古いコメントを1時間維持するか検討
        if not comment_to_save and previous_report_data:
            old_comment, old_timestamp = previous_report_data.get('breakingNewsComment', ""), previous_report_data.get('breakingNewsTimestamp', "")
            old_full_text = previous_report_data.get('breakingNewsFullText', "")
            if old_timestamp and (datetime.now() - datetime.fromisoformat(old_timestamp)) < timedelta(hours=1):
                comment_to_save = old_comment
                timestamp_to_save = old_timestamp
                full_text_to_save = old_full_text

        # 各種速報ファイルを保存
        save_realtime_report(results, race_day, comment_to_save, timestamp_to_save, full_text_to_save)
        update_rank_history(results, race_day, args.history_file)
        update_leg_rank_history(results, current_state, args.leg_history_file)
        save_individual_results(individual_results, args.individual_state_file)
        if results:
            calculate_and_save_runner_locations(results)
        print(f"\n--- [Realtime Mode] Saved report data to {realtime_report_file}, {args.history_file}, {args.leg_history_file}, {args.individual_state_file}, and {RUNNER_LOCATIONS_OUTPUT_FILE} ---")

    if args.commit:
        save_ekiden_state(results, args.state_file)
        update_rank_history(results, race_day, args.history_file)
        update_leg_rank_history(results, current_state, args.leg_history_file, is_commit_mode=True)
        save_individual_results(individual_results, args.individual_state_file)
        if results:
            calculate_and_save_runner_locations(results)
        print(f"\n--- [Commit Mode] Saved final results to {args.state_file}, {args.individual_state_file}, {args.history_file}, {args.leg_history_file}, and {RUNNER_LOCATIONS_OUTPUT_FILE} ---")
    elif not args.realtime:
        print("\n--- [Preview Mode] To save results, run `python generate_report.py --commit` ---")

if __name__ == '__main__':
    main()