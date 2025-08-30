import json
import os
from pathlib import Path
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
AMEDAS_STATIONS_FILE = 'config/amedas_stations.json'
HISTORY_DATA_DIR = 'history_data'
STORY_SETTINGS_FILE = Path(HISTORY_DATA_DIR) / 'ekiden_story_settings.json'
PAST_RESULTS_FILE = Path(HISTORY_DATA_DIR) / 'past_results.json'
LEG_AWARD_HISTORY_FILE = Path(HISTORY_DATA_DIR) / 'leg_award_history.json'
TOURNAMENT_RECORDS_FILE = Path(HISTORY_DATA_DIR) / 'tournament_records.json'
LEG_BEST_RECORDS_FILE = Path(HISTORY_DATA_DIR) / 'leg_best_records.json'

# --- リアルタイム更新ファイル ---
EKIDEN_DATA_FILE = 'config/ekiden_data.json'
OUTLINE_FILE = 'config/outline.json'
STATE_FILE = 'data/ekiden_state.json'
INDIVIDUAL_STATE_FILE = 'data/individual_results.json'
RANK_HISTORY_FILE = 'data/rank_history.json'
LEG_RANK_HISTORY_FILE = 'data/leg_rank_history.json'
REALTIME_REPORT_FILE = 'data/realtime_report.json'
REALTIME_LOG_FILE = 'data/realtime_log.jsonl'
EKIDEN_START_DATE = '2025-07-23'
KML_FILE = 'data/ekiden_map.kml'
RUNNER_LOCATIONS_OUTPUT_FILE = 'data/runner_locations.json'
COURSE_PATH_FILE = 'config/course_path.json'

# 5chからスクレイピングする際のリクエストヘッダー
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
# --- グローバル変数 ---
stations_data = []
ekiden_data = {} # ekiden_data.json
story_settings = {} # ekiden_story_settings.json
past_results = [] # past_results.json
leg_award_history = [] # leg_award_history.json
tournament_records = [] # tournament_records.json
leg_best_records = {} # leg_best_records.json
intramural_rankings = {} # intramural_rankings.json

# --- 関数定義 ---

def load_all_data():
    """必要なJSONファイルをすべて読み込む"""
    global stations_data, ekiden_data, story_settings, past_results, leg_award_history, tournament_records, leg_best_records, intramural_rankings
    try:
        with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        # --- 歴史データを読み込む ---
        with open(STORY_SETTINGS_FILE, 'r', encoding='utf-8') as f:
            story_settings = json.load(f)
        with open(PAST_RESULTS_FILE, 'r', encoding='utf-8') as f:
            past_results = json.load(f)
        with open(LEG_AWARD_HISTORY_FILE, 'r', encoding='utf-8') as f:
            leg_award_history = json.load(f)
        with open(TOURNAMENT_RECORDS_FILE, 'r', encoding='utf-8') as f:
            tournament_records = json.load(f)
        with open(LEG_BEST_RECORDS_FILE, 'r', encoding='utf-8') as f:
            leg_best_records = json.load(f)

    except FileNotFoundError as e:
        print(f"エラー: 必須データファイルが見つかりません。 {e.filename}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        exit(1)

    # 学内ランキングは任意ファイルとして読み込む
    try:
        with open('data/intramural_rankings.json', 'r', encoding='utf-8') as f:
            intramural_rankings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("情報: 'intramural_rankings.json' が見つからないか不正なため、学内ランキング関連の機能はスキップされます。")
        intramural_rankings = {} # 空の辞書をセット

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
                "totalDistance": 0, "currentLeg": 1, "overallRank": 0, "finishDay": None
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
            "currentLeg": s["newCurrentLeg"], "overallRank": s["overallRank"],
            "finishDay": s.get("finishDay")
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
        # ゴール済みの場合は区間番号を付けずに「ゴール」と表示
        runner_display = "ゴール" if r['runner'] == 'ゴール' else f"{r['currentLegNumber']}{r['runner']}"
        next_runner_name = team_info['runners'][r['currentLegNumber']] if r['currentLegNumber'] < len(team_info['runners']) else '----'
        next_runner_str = 'ゴール' if next_runner_name == '----' else f"{r['currentLegNumber'] + 1}{next_runner_name}"

        report_data["teams"].append({
            "id": r["id"],
            "name": r["name"],
            "short_name": team_info.get("short_name", r["name"]),
            "currentLeg": r["currentLegNumber"],
            "runner": runner_display,
            "todayDistance": r["todayDistance"],
            "todayRank": r["todayRank"],
            "totalDistance": r["totalDistance"],
            "overallRank": r["overallRank"],
            "previousRank": r["previousRank"],
            "nextRunner": next_runner_str,
            "error": r['rawTempResult']['error'],
            "finishDay": r.get("finishDay")
        })

    with open(REALTIME_REPORT_FILE, 'w', encoding='utf-8') as f:
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

def _generate_lead_change_comment(current_results, previous_report_data):
    """首位交代のコメントを生成"""
    if current_results and previous_report_data.get('teams'):
        current_leader_id = current_results[0]['id']
        previous_leader_id = previous_report_data['teams'][0]['id']
        if current_leader_id != previous_leader_id:
            current_leader_name = current_results[0]['name']
            return f"【首位交代】{current_leader_name}がトップに浮上！レースが大きく動きました！"
    return None

def _generate_record_challenge_comment(current_results):
    """区間記録や歴代記録への挑戦に関するコメントを生成"""
    for r in current_results:
        if r['todayRank'] == 1 and r['todayDistance'] > 0:
            leg_num = r['currentLegNumber']
            leg_records = next((item for item in leg_best_records.get('leg_records', []) if item['leg'] == leg_num), None)
            if leg_records:
                # 今日の記録が歴代10位以内に入るかチェック
                for i, best_record in enumerate(leg_records['top10']):
                    if r['todayDistance'] >= best_record['record']:
                        rank_in_history = i + 1
                        runner_name = r['runner'].replace(str(r['currentLegNumber']), '')
                        return f"【記録への挑戦】{r['name']}の{runner_name}選手、{leg_num}区で歴代{rank_in_history}位に相当する好タイム！歴史に名を刻むか！"
    return None

def _generate_champion_comeback_comment(current_results, previous_ranks):
    """優勝経験校の走りに関するコメントを生成"""
    champion_teams = story_settings.get('commentary_settings', {}).get('champion_teams', {})
    for team_name, wins in champion_teams.items():
        team_result = next((r for r in current_results if r['name'] == team_name), None)
        if team_result:
            prev_rank = previous_ranks.get(team_result['id'])
            if team_result['overallRank'] <= 3 and prev_rank and team_result['overallRank'] < prev_rank:
                return f"【王者の走り】優勝{wins}回、{team_name}がじわりと順位を上げ現在{team_result['overallRank']}位！さすがの勝負強さです！"
    return None

def _generate_revenge_run_comment(current_results):
    """昨年の雪辱を果たす走りに関するコメントを生成"""
    last_year_results_data = next((r for r in reversed(past_results) if r['year'] == datetime.now().year - 1), None)
    if not last_year_results_data:
        return None
    last_year_ranks = {team['team_name']: team['rank'] for team in last_year_results_data['results']}

    for r in current_results:
        last_year_rank = last_year_ranks.get(r['name'])
        if last_year_rank and (last_year_rank - r['overallRank'] >= 5):
            return f"【昨年の雪辱へ】{r['name']}、昨年の{last_year_rank}位から今年は{r['overallRank']}位と大躍進！このまま上位を維持できるか！"
    return None

def _generate_ace_leg_comment(current_results):
    """エース区間の快走に関するコメントを生成"""
    ace_legs_info = story_settings.get('commentary_settings', {}).get('ace_legs', {})
    ace_legs = ace_legs_info.get('main', []) + ace_legs_info.get('sub', [])
    threshold = story_settings.get('commentary_settings', {}).get('thresholds', {}).get('ace_leg_rank', 3)

    for r in current_results:
        if r['currentLegNumber'] in ace_legs and r['todayRank'] <= threshold:
            runner_name = r['runner'].replace(str(r['currentLegNumber']), '')
            leg_name = "花の" if r['currentLegNumber'] in ace_legs_info.get('main', []) else ""
            return f"【エースの走り】{leg_name}{r['currentLegNumber']}区で{r['name']}・{runner_name}選手が区間{r['todayRank']}位の快走！チームを勢いづけます！"
    return None

def _generate_cinderella_comment(current_results, intramural_rankings):
    """学内ランキング下位選手の活躍（シンデレラボーイ）に関するコメントを生成"""
    if not intramural_rankings or 'teams' not in intramural_rankings:
        return None

    threshold = story_settings.get('commentary_settings', {}).get('thresholds', {}).get('cinderella_rank', 10)
    
    for r in current_results:
        team_ranking = next((t for t in intramural_rankings['teams'] if t['id'] == r['id']), None)
        if not team_ranking:
            continue

        runner_name_only = r['runner'].replace(str(r['currentLegNumber']), '')
        runner_rank_info = next((runner for runner in team_ranking['daily_results'] if runner['runner_name'] == runner_name_only), None)
        
        if runner_rank_info:
            # 学内順位はインデックス+1で計算
            intramural_rank = team_ranking['daily_results'].index(runner_rank_info) + 1
            # 正規メンバー（10人）のうち下位（7位以降）かつ、今日の区間順位が閾値以内
            if intramural_rank >= 7 and r['todayRank'] <= threshold:
                 return f"【シンデレラボーイ登場か！？】学内ランキングでは目立たなかった{r['name']}の{runner_name_only}選手が、この大舞台で区間{r['todayRank']}位の走りを見せています！"
    return None

def _generate_leg_finish_comment(current_results, previous_report_data):
    """区間走破に関するコメントを生成"""
    previous_teams_map = {team['id']: team for team in previous_report_data.get('teams', [])}
    leg_finishers_by_leg = {}

    for team in current_results:
        if team['id'] in previous_teams_map:
            previous_team = previous_teams_map[team['id']]
            if team['newCurrentLeg'] > previous_team['currentLeg']:
                completed_leg = previous_team['currentLeg']
                if completed_leg not in leg_finishers_by_leg:
                    leg_finishers_by_leg[completed_leg] = []
                leg_finishers_by_leg[completed_leg].append(team['name'])

    if leg_finishers_by_leg:
        comments = [f"{'、'.join(teams)}が{leg}区を走りきりました！" for leg, teams in sorted(leg_finishers_by_leg.items())]
        return "【区間走破】" + " ".join(comments)
    return None

def _generate_heatwave_comment(current_results, previous_report_data):
    """酷暑・猛暑に関するコメントを生成"""
    previous_temps_map = {team['id']: team.get('todayDistance', 0) for team in previous_report_data.get('teams', [])}
    
    hottest_runners = [r for r in current_results if r.get('todayDistance', 0) >= 40.0 and r['todayDistance'] > previous_temps_map.get(r['id'], 0)]
    if hottest_runners:
        runner_details = [f"{r['name']}の{r['runner']}選手({r['todayDistance']:.1f}km)" for r in hottest_runners]
        return f"【酷暑】{', '.join(runner_details)}が脅威の走りで酷暑日超え、これは強烈な走り！！"

    hotter_runners = [r for r in current_results if r.get('todayDistance', 0) >= 39.0 and r['todayDistance'] > previous_temps_map.get(r['id'], 0)]
    if hotter_runners:
        runner_details = [f"{r['name']}の{r['runner']}選手({r['todayDistance']:.1f}km)" for r in hotter_runners]
        return f"【猛暑】{', '.join(runner_details)}が39kmを超える走りをみせています！素晴らしい走りです！"
    return None

def _generate_rank_change_comment(current_results, previous_ranks):
    """順位変動に関するコメントを生成"""
    current_teams_map = {team['id']: team for team in current_results}
    
    jump_up_teams = [
        {"name": current_teams_map[team_id]['name'], "jump": previous_ranks[team_id] - rank, "current_rank": rank}
        for team_id, rank in {t['id']: t['overallRank'] for t in current_results}.items()
        if team_id in previous_ranks and previous_ranks[team_id] - rank >= 3
    ]
    if jump_up_teams:
        best_jumper = max(jump_up_teams, key=lambda x: x['jump'])
        return f"【ジャンプアップ】{best_jumper['name']}が{best_jumper['jump']}ランクアップで{best_jumper['current_rank']}位に浮上！"

    rank_down_teams = [
        {"name": current_teams_map[team_id]['name'], "drop": rank - previous_ranks[team_id]}
        for team_id, rank in {t['id']: t['overallRank'] for t in current_results}.items()
        if team_id in previous_ranks and rank - previous_ranks[team_id] >= 5
    ]
    if rank_down_teams:
        worst_dropper = max(rank_down_teams, key=lambda x: x['drop'])
        return f"【波乱】{worst_dropper['name']}が{worst_dropper['drop']}ランクダウン。厳しい展開です。"
    return None

def _generate_close_race_comment(current_results, previous_report_data):
    """接戦に関するコメントを生成"""
    previous_distances = {team['id']: team['totalDistance'] for team in previous_report_data.get('teams', [])}
    
    # 首位争い
    if len(current_results) > 1:
        t1, t2 = current_results[0], current_results[1]
        if 0 <= (t1['totalDistance'] - t2['totalDistance']) < 1.0:
            return f"【首位争い】トップ{t1['name']}に2位{t2['name']}が肉薄！その差わずか{(t1['totalDistance'] - t2['totalDistance']):.1f}km！"

    # シード権争い
    if len(current_results) > 10:
        t10, t11 = current_results[9], current_results[10]
        prev_dist_10, prev_dist_11 = previous_distances.get(t10['id']), previous_distances.get(t11['id'])
        if prev_dist_10 is not None and prev_dist_11 is not None:
            current_gap = t10['totalDistance'] - t11['totalDistance']
            if 0 <= current_gap < 0.5 and current_gap < (prev_dist_10 - prev_dist_11):
                return f"【シード権争い】10位{t10['name']}と11位{t11['name']}が熾烈な争い！"
    return None

def _generate_timed_report_comment(current_results, previous_report_data):
    """定時速報コメントを生成"""
    now = datetime.now()
    last_comment = previous_report_data.get('breakingNewsComment', "")
    last_timestamp_str = previous_report_data.get('breakingNewsTimestamp')
    can_show_timed_report = True

    if last_comment and last_timestamp_str:
        try:
            if (now - datetime.fromisoformat(last_timestamp_str)) < timedelta(hours=1) and not last_comment.startswith("【定時速報】"):
                can_show_timed_report = False
        except (ValueError, TypeError):
            pass

    if can_show_timed_report:
        if now.minute == 15 and current_results:
            top_team = current_results[0]
            return f"【定時速報】現在トップは{top_team['name']}！総合距離{top_team['totalDistance']:.1f}kmです！"
        if now.minute == 45 and current_results:
            top_performer = max(current_results, key=lambda x: x.get('todayDistance', 0))
            if top_performer.get('todayDistance', 0) > 0:
                return f"【定時速報】本日のトップは{top_performer['runner']}選手！{top_performer['todayDistance']:.1f}kmと素晴らしい走りです！"
    return None

def generate_breaking_news_comment(current_results, previous_report_data, individual_results, intramural_rankings):
    """前回と今回の結果を比較し、注目すべき変動があれば速報コメントを生成する"""
    now = datetime.now()
    # 夜間（19時以降）と早朝（7時前）は速報を生成しない
    if not (7 <= now.hour < 19):
        return ""
    if not previous_report_data:
        return ""

    previous_ranks = {team['id']: team['overallRank'] for team in previous_report_data.get('teams', [])}

    comment_generators = [
        _generate_lead_change_comment,
        _generate_record_challenge_comment,
        _generate_champion_comeback_comment,
        _generate_revenge_run_comment,
        _generate_ace_leg_comment,
        _generate_cinderella_comment,
        _generate_leg_finish_comment,
        _generate_heatwave_comment,
        _generate_rank_change_comment,
        _generate_close_race_comment,
        _generate_timed_report_comment,
    ]

    for generator in comment_generators:
        # 各生成関数に必要な引数を渡す
        if generator in [_generate_cinderella_comment]:
             comment = generator(current_results, intramural_rankings)
        elif generator in [_generate_champion_comeback_comment, _generate_rank_change_comment]:
            comment = generator(current_results, previous_ranks)
        elif generator in [_generate_revenge_run_comment, _generate_ace_leg_comment, _generate_record_challenge_comment]:
            comment = generator(current_results)
        else:
            comment = generator(current_results, previous_report_data)
        
        if comment:
            return comment

    return ""

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

def append_to_realtime_log(results):
    """リアルタイムログファイルに現在の走行データを追記する。"""
    now_iso = datetime.now().isoformat()
    try:
        with open(REALTIME_LOG_FILE, 'a', encoding='utf-8') as f:
            for r in results:
                # ゴール済みの選手や、本日走行していない選手はログに記録しない
                if r['runner'] == 'ゴール' or r.get('todayDistance', 0) <= 0:
                    continue
                
                log_entry = {
                    "timestamp": now_iso,
                    "team_id": r['id'],
                    "runner_name": r['runner'], # '1穴吹' のような形式
                    "distance": r['todayDistance']
                }
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        print(f"✅ リアルタイムログを '{REALTIME_LOG_FILE}' に追記しました。")
    except IOError as e:
        print(f"エラー: '{REALTIME_LOG_FILE}' への書き込みに失敗しました: {e}")

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
    previous_report_file = 'data/realtime_report_previous.json'
    realtime_report_file = REALTIME_REPORT_FILE
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

    # intramural_rankings は load_all_data でグローバル変数に読み込まれている
    results = []
    print("速報を生成中... 全チームの気温データを取得しています。")
    for team_state in current_state:
        team_data = next(t for t in ekiden_data['teams'] if t['id'] == team_state['id'])
        
        finish_day = team_state.get("finishDay")
        is_finished_yesterday = finish_day is not None and finish_day < race_day

        if is_finished_yesterday:
            print(f"  {team_data['name']} (順位確定済み)")
            results.append({
                "id": team_state["id"], "name": team_state["name"], "runner": "ゴール",
                "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": team_state["currentLeg"],
                "todayDistance": 0.0, "totalDistance": team_state["totalDistance"],
                "previousRank": previous_rank_map.get(team_state["id"], 0),
                "rawTempResult": {'temperature': 0, 'error': None},
                "finishDay": finish_day,
                "group_id": 1 # 順位確定グループ
            })
            continue

        # --- 走行中または本日ゴールのチーム ---
        print(f"  {team_data['name']} のデータを取得中...")
        runner_index = team_state['currentLeg'] - 1
        runner_name, temp_result, today_distance = "ゴール", {'temperature': 0, 'error': None}, 0.0

        if runner_index < len(team_data['runners']):
            runner_name = team_data['runners'][runner_index]
            station = find_station_by_name(runner_name)
            temp_result = fetch_max_temperature(station['pref_code'], station['code']) if station else {'temperature': 0, 'error': '地点不明'}
            today_distance = temp_result.get('temperature') or 0.0

            if today_distance > 0:
                runner_info = individual_results.setdefault(runner_name, {"totalDistance": 0, "teamId": team_data['id'], "records": []})
                record_for_today = next((r for r in runner_info['records'] if r.get('day') == race_day), None)
                if record_for_today:
                    record_for_today['distance'] = today_distance
                else:
                    runner_info['records'].append({"day": race_day, "leg": team_state["currentLeg"], "distance": today_distance})
                runner_info['totalDistance'] = round(sum(r['distance'] for r in runner_info['records']), 1)

        new_total_distance = round(team_state['totalDistance'] + today_distance, 1)
        new_current_leg = team_state['currentLeg']
        finish_day_today = finish_day # 前日のゴール情報を引き継ぐ

        if new_current_leg <= len(ekiden_data['leg_boundaries']):
            boundary = ekiden_data['leg_boundaries'][new_current_leg - 1]
            if new_total_distance >= boundary:
                new_current_leg += 1
                if new_current_leg > len(ekiden_data['leg_boundaries']) and finish_day_today is None:
                    finish_day_today = race_day

        results.append({
            "id": team_state["id"], "name": team_state["name"], "runner": runner_name,
            "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": new_current_leg,
            "todayDistance": today_distance, "totalDistance": new_total_distance,
            "previousRank": previous_rank_map.get(team_state["id"], 0),
            "rawTempResult": temp_result,
            "finishDay": finish_day_today,
            "group_id": 0 # 順位変動グループ
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

    # 総合順位を計算 (新しいルール)
    results.sort(key=lambda x: (x.get('group_id', 0), x['totalDistance']), reverse=True)
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
            new_comment_text = generate_breaking_news_comment(results, previous_report_data, individual_results, intramural_rankings)
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

        # リアルタイムログに追記
        append_to_realtime_log(results)

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