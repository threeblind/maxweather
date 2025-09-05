import json
import os
from pathlib import Path
from datetime import datetime, timedelta, time
import requests
import shutil
import sys
import argparse
import re
import unicodedata
from bs4 import BeautifulSoup
from geopy.distance import geodesic

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')
HISTORY_DATA_DIR = Path('history_data')

# --- ファイルパス定義 ---
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
SHADOW_TEAM_FILE = CONFIG_DIR / 'shadow_team.json'
AMEDAS_STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
OUTLINE_FILE = CONFIG_DIR / 'outline.json'
COURSE_PATH_FILE = CONFIG_DIR / 'course_path.json'
STORY_SETTINGS_FILE = HISTORY_DATA_DIR / 'ekiden_story_settings.json'
PAST_RESULTS_FILE = HISTORY_DATA_DIR / 'past_results.json'
LEG_AWARD_HISTORY_FILE = HISTORY_DATA_DIR / 'leg_award_history.json'
TOURNAMENT_RECORDS_FILE = HISTORY_DATA_DIR / 'tournament_records.json'
LEG_BEST_RECORDS_FILE = HISTORY_DATA_DIR / 'leg_best_records.json'
REALTIME_REPORT_FILE = DATA_DIR / 'realtime_report.json'
INDIVIDUAL_STATE_FILE = DATA_DIR / 'individual_results.json'
RANK_HISTORY_FILE = DATA_DIR / 'rank_history.json'
LEG_RANK_HISTORY_FILE = DATA_DIR / 'leg_rank_history.json'
RUNNER_LOCATIONS_OUTPUT_FILE = DATA_DIR / 'runner_locations.json'
INTRAMURAL_RANKINGS_FILE = DATA_DIR / 'intramural_rankings.json'
STATE_FILE = DATA_DIR / 'ekiden_state.json'
REALTIME_LOG_FILE = DATA_DIR / 'realtime_log.jsonl'

# --- 定数 ---
EKIDEN_START_DATE = '2025-09-01'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

# --- グローバル変数 ---
stations_data = []
all_teams_data = [] # 正規チームとシャドーチームを結合したデータ
ekiden_data = {}
story_settings = {}
past_results = []
leg_award_history = []
tournament_records = []
leg_best_records = {}
intramural_rankings = {}

def load_all_data():
    """必要なJSONファイルをすべて読み込む"""
    global stations_data, all_teams_data, ekiden_data, story_settings, past_results, leg_award_history, tournament_records, leg_best_records, intramural_rankings
    try:
        with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        
        # シャドーチームの定義を読み込む
        try:
            with open(SHADOW_TEAM_FILE, 'r', encoding='utf-8') as f:
                shadow_team_data = json.load(f)
            # 正規チームとシャドーチームの情報を結合
            all_teams_data = ekiden_data.get('teams', []) + [shadow_team_data]
        except FileNotFoundError:
            print(f"情報: '{SHADOW_TEAM_FILE}' が見つかりません。シャドーチームなしで処理を続行します。")
            all_teams_data = ekiden_data.get('teams', [])

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
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        sys.exit(1)

    # 学内ランキングは任意ファイルとして読み込む
    try:
        with open(INTRAMURAL_RANKINGS_FILE, 'r', encoding='utf-8') as f:
            intramural_rankings = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"情報: '{INTRAMURAL_RANKINGS_FILE}' が見つからないか不正なため、学内ランキング関連の機能はスキップされます。")
        intramural_rankings = {}

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

def fetch_current_temperature(pref_code, station_code):
    """Yahoo天気から現在の気温を取得"""
    url = f"https://weather.yahoo.co.jp/weather/amedas/{pref_code}/{station_code}.html?m=temp"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        main_data = soup.find('p', class_='mainData')
        if not main_data:
            return {'temperature': None, 'error': '現在気温データなし'}
        temp_span = main_data.find('span')
        if not temp_span or not temp_span.contents:
            return {'temperature': None, 'error': '現在気温情報解析失敗'}
        temp_value_str = temp_span.contents[0].strip()
        temperature = float(temp_value_str)
        return {'temperature': temperature, 'error': None}
    except requests.RequestException as e:
        return {'temperature': None, 'error': f"通信エラー: {e}"}
    except (ValueError, TypeError, IndexError):
        return {'temperature': None, 'error': '現在気温が数値でない'}
    except Exception:
        return {'temperature': None, 'error': '不明な解析エラー'}

def load_ekiden_state(file_path):
    """駅伝の現在の状態を読み込む。ファイルがなければ全チームの初期状態を生成。"""
    if not os.path.exists(file_path):
        print(f"情報: '{file_path}' が見つかりません。全チームの初期状態を生成します。")
        return [
            {
                "id": team["id"], "name": team["name"],
                "totalDistance": 0.0, "currentLeg": 1, "overallRank": 0, "finishDay": None
            } for team in all_teams_data
        ]
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_individual_results(file_path):
    """選手個人の結果を読み込む。ファイルがなければ初期状態を生成。"""
    if not os.path.exists(file_path):
        runners_state = {}
        for team in all_teams_data:
            for runner_obj in team.get('runners', []):
                runner_name = runner_obj.get('name')
                if not runner_name: continue
                runners_state[runner_name] = {"totalDistance": 0, "teamId": team['id'], "records": []}
        return runners_state
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_ekiden_state(state, file_path):
    """駅伝の現在の状態を保存する"""
    data_to_save = []
    for s in state:
        team_state = {
            "id": s["id"], "name": s["name"], "totalDistance": s["totalDistance"],
            "currentLeg": s["newCurrentLeg"], "overallRank": s["overallRank"],
            "finishDay": s.get("finishDay")
        }
        data_to_save.append(team_state)
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_to_save, f, indent=2, ensure_ascii=False)

def save_individual_results(runners_state, file_path):
    """選手個人の結果を保存する"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(runners_state, f, indent=2, ensure_ascii=False)

def get_east_asian_width_count(text):
    """全角文字を2、半角文字を1として文字幅をカウント"""
    return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in text)

def pad_str(text, length, char='＿'):
    """指定した文字幅になるように文字列をパディング"""
    return text + char * (length - get_east_asian_width_count(text))

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

    team_info_map = {t['id']: t for t in all_teams_data}

    for r in results:
        team_info = team_info_map.get(r['id'])
        if not team_info: continue

        runner_display = "ゴール"
        if r['runner'] != 'ゴール':
            if r.get('is_shadow_confederation'):
                runner_display = r['runner']
            else:
                runner_display = f"{r['currentLegNumber']}{r['runner']}"

        next_runner_name = '----'
        if r['currentLegNumber'] < len(team_info.get('runners', [])):
            next_runner_name = team_info['runners'][r['currentLegNumber']]['name']
        
        next_runner_str = 'ゴール' if next_runner_name == '----' else f"{r['currentLegNumber'] + 1}{next_runner_name}"

        report_data["teams"].append({
            "id": r["id"], "name": r["name"],
            "short_name": team_info.get("short_name", r["name"]),
            "currentLeg": r["currentLegNumber"], "runner": runner_display,
            "todayDistance": r["todayDistance"], "todayRank": r["todayRank"],
            "totalDistance": r["totalDistance"], "overallRank": r["overallRank"],
            "previousRank": r["previousRank"], "nextRunner": next_runner_str,
            "error": r['rawTempResult']['error'], "finishDay": r.get("finishDay"),
            "is_shadow_confederation": r.get("is_shadow_confederation", False)
        })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(REALTIME_REPORT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

def update_rank_history(results, race_day, rank_history_file_path):
    """日々の総合順位と距離の履歴を更新する"""
    try:
        with open(rank_history_file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {
            "dates": [],
            "teams": [{"id": t["id"], "name": t["name"], "ranks": [], "distances": []} for t in all_teams_data]
        }

    today_str = (datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d') + timedelta(days=race_day - 1)).strftime('%Y-%m-%d')

    try:
        date_index = history["dates"].index(today_str)
    except ValueError:
        history["dates"].append(today_str)
        date_index = len(history["dates"]) - 1
        for team_history in history["teams"]:
            team_history["ranks"].append(None)
            team_history["distances"].append(None)

    history_teams_map = {team['id']: team for team in history['teams']}
    for result in results:
        team_id = result['id']
        if team_id in history_teams_map:
            team_history = history_teams_map[team_id]
            team_history['ranks'][date_index] = result['overallRank']
            team_history['distances'][date_index] = result['totalDistance']

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(rank_history_file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def calculate_and_save_runner_locations(teams_data):
    """各チームの現在位置（緯度経度）を計算して保存する"""
    try:
        with open(COURSE_PATH_FILE, 'r', encoding='utf-8') as f:
            all_points = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {COURSE_PATH_FILE} の読み込みに失敗: {e}")
        return

    if not all_points:
        print(f"エラー: {COURSE_PATH_FILE} にコースデータがありません。")
        return

    runner_locations = []
    print("各チームの現在位置を計算中...")
    team_info_map = {t['id']: t for t in all_teams_data}

    for team in teams_data:
        target_distance_km = team.get('totalDistance', 0)
        cumulative_distance_km = 0.0
        team_lat, team_lon = all_points[0]['lat'], all_points[0]['lon']
        location_found = False

        for i in range(1, len(all_points)):
            p1 = (all_points[i-1]['lat'], all_points[i-1]['lon'])
            p2 = (all_points[i]['lat'], all_points[i]['lon'])
            segment_distance_km = geodesic(p1, p2).kilometers

            if segment_distance_km > 0 and cumulative_distance_km <= target_distance_km < cumulative_distance_km + segment_distance_km:
                distance_into_segment = target_distance_km - cumulative_distance_km
                fraction = distance_into_segment / segment_distance_km
                team_lat = p1[0] + fraction * (p2[0] - p1[0])
                team_lon = p1[1] + fraction * (p2[1] - p1[1])
                location_found = True
                break
            cumulative_distance_km += segment_distance_km
        
        if not location_found and target_distance_km >= cumulative_distance_km:
            team_lat, team_lon = all_points[-1]['lat'], all_points[-1]['lon']
        
        team_info = team_info_map.get(team.get('id'))
        short_name = team_info.get('short_name', team.get('name')) if team_info else team.get('name')

        runner_locations.append({
            "rank": team.get('overallRank'), "team_name": team.get('name'),
            "team_short_name": short_name,
            "runner_name": team.get('runner'), "total_distance_km": team.get('totalDistance'),
            "latitude": team_lat, "longitude": team_lon,
            "is_shadow_confederation": team.get("is_shadow_confederation", False)
        })
        if not team.get("is_shadow_confederation", False):
            print(f"  {str(team.get('overallRank')) or 'N/A':>3}位 {team.get('name'):<10} @ {team.get('totalDistance'):.1f} km -> ({team_lat:.6f}, {team_lon:.6f})")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUNNER_LOCATIONS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(runner_locations, f, indent=2, ensure_ascii=False)
    print(f"\n計算完了: {len(runner_locations)}チームの位置を {RUNNER_LOCATIONS_OUTPUT_FILE} に保存しました。")

def append_to_realtime_log(results):
    """リアルタイムログファイルに現在の走行データ（現在気温）を追記する"""
    now_iso = datetime.now().isoformat()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(REALTIME_LOG_FILE, 'a', encoding='utf-8') as f:
            for r in results:
                if r['runner'] == 'ゴール' or r.get('currentTempForLog') is None:
                    continue
                
                runner_name_with_leg = f"{r['currentLegNumber']}{r['runner']}"
                log_entry = {
                    "timestamp": now_iso, "team_id": r['id'],
                    "runner_name": runner_name_with_leg,
                    "distance": r.get('currentTempForLog')
                }
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        print(f"✅ リアルタイムログを '{REALTIME_LOG_FILE}' に追記しました。")
    except IOError as e:
        print(f"エラー: '{REALTIME_LOG_FILE}' への書き込みに失敗しました: {e}")

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝のレポートを生成します。')
    parser.add_argument('--realtime', action='store_true', help='リアルタイム速報用のJSONを生成します。')
    parser.add_argument('--commit', action='store_true', help='本日の結果を状態ファイルに保存します。')
    parser.add_argument('--state-file', default=STATE_FILE, help=f'チームの状態ファイルパス (デフォルト: {STATE_FILE})')
    parser.add_argument('--individual-state-file', default=INDIVIDUAL_STATE_FILE, help=f'個人の状態ファイルパス (デフォルト: {INDIVIDUAL_STATE_FILE})')
    parser.add_argument('--history-file', default=RANK_HISTORY_FILE, help=f'順位履歴ファイルパス (デフォルト: {RANK_HISTORY_FILE})')
    args = parser.parse_args()

    load_all_data()

    start_date = datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d')
    race_day = (datetime.now().date() - start_date.date()).days + 1

    current_state = load_ekiden_state(args.state_file)
    previous_rank_map = {s['id']: s['overallRank'] for s in current_state}
    individual_results = load_individual_results(args.individual_state_file)
    
    team_info_map = {t['id']: t for t in all_teams_data}

    # --- Step 1: 正規チームの結果を計算 ---
    regular_team_results = []
    shadow_team_states = []
    print("Step 1: 正規チームの走行結果を計算中...")
    for team_state in current_state:
        team_data = team_info_map.get(team_state['id'])
        if not team_data:
            print(f"警告: ID {team_state['id']} のチーム定義が見つかりません。スキップします。")
            continue
        
        if team_data.get("is_shadow_confederation"):
            shadow_team_states.append(team_state)
            continue

        finish_day = team_state.get("finishDay")
        is_finished_yesterday = finish_day is not None and finish_day < race_day

        if is_finished_yesterday:
            print(f"  {team_data['name']} (順位確定済み)")
            regular_team_results.append({
                "id": team_state["id"], "name": team_data["name"], "runner": "ゴール",
                "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": team_state["currentLeg"],
                "todayDistance": 0.0, "totalDistance": team_state["totalDistance"],
                "previousRank": previous_rank_map.get(team_state["id"], 0),
                "rawTempResult": {'temperature': 0, 'error': None},
                "finishDay": finish_day, "group_id": 1
            })
            continue

        print(f"  {team_data['name']} のデータを取得中...")
        runner_index = team_state['currentLeg'] - 1
        runner_name, max_temp_result, current_temp_for_log, today_distance = "ゴール", {'temperature': 0, 'error': None}, None, 0.0

        if runner_index < len(team_data.get('runners', [])):
            runner_name = team_data['runners'][runner_index]['name']
            station = find_station_by_name(runner_name)
            if station:
                max_temp_result = fetch_max_temperature(station['pref_code'], station['code'])
                current_temp_result = fetch_current_temperature(station['pref_code'], station['code'])
                current_temp_for_log = current_temp_result.get('temperature')
            else:
                max_temp_result = {'temperature': 0, 'error': '地点不明'}

            today_distance = max_temp_result.get('temperature') or 0.0

        new_total_distance = round(team_state['totalDistance'] + today_distance, 1)
        new_current_leg = team_state['currentLeg']
        finish_day_today = finish_day

        is_leg_change = False
        if new_current_leg <= len(ekiden_data['leg_boundaries']):
            boundary = ekiden_data['leg_boundaries'][new_current_leg - 1]
            if new_total_distance >= boundary:
                new_current_leg += 1
                is_leg_change = True
                if new_current_leg > len(ekiden_data['leg_boundaries']) and finish_day_today is None:
                    finish_day_today = race_day

        # 個人記録を、その日に実際に走った選手に紐付ける
        if today_distance > 0:
            # ★★★ 修正点: 記録は常にその日に走った選手(runner_name)と、その選手が走っていた区間(team_state["currentLeg"])に紐付ける
            leg_to_record = team_state["currentLeg"]
            runner_info = individual_results.setdefault(runner_name, {"totalDistance": 0, "teamId": team_data['id'], "records": []})

            record_for_today = next((r for r in runner_info['records'] if r.get('day') == race_day), None)
            if record_for_today:
                record_for_today['distance'] = today_distance
            else:
                runner_info['records'].append({"day": race_day, "leg": leg_to_record, "distance": today_distance})
            runner_info['totalDistance'] = round(sum(r['distance'] for r in runner_info['records']), 1)

        regular_team_results.append({
            "id": team_state["id"], "name": team_data["name"], "runner": runner_name,
            "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": new_current_leg,
            "todayDistance": today_distance, "totalDistance": new_total_distance,
            "previousRank": previous_rank_map.get(team_state["id"], 0),
            "rawTempResult": max_temp_result, "finishDay": finish_day_today,
            "group_id": 0, "currentTempForLog": current_temp_for_log
        })

    # --- Step 2: 区間記録連合の結果を計算 ---
    shadow_team_results = []
    print("\nStep 2: 区間記録連合の走行結果を計算中...")
    if shadow_team_states:
        shadow_team_data = team_info_map.get(shadow_team_states[0]['id'])
        shadow_state = shadow_team_states[0]
        
        # 正規チームの区間ごとの状況を整理
        teams_by_leg = {}
        for team_result in regular_team_results:
            leg = team_result.get('newCurrentLeg')
            if leg not in teams_by_leg:
                teams_by_leg[leg] = []
            teams_by_leg[leg].append(team_result)

        # シャドーチームの現在のランナーを特定
        shadow_leg_num = shadow_state['currentLeg']
        runner_index = shadow_leg_num - 1
        
        shadow_runner_name, today_distance, max_temp_result = "ゴール", 0.0, {'temperature': 0, 'error': None}
        
        if runner_index < len(shadow_team_data.get('runners', [])):
            shadow_runner_info = shadow_team_data['runners'][runner_index]
            shadow_runner_name = shadow_runner_info['name']
            
            # シャドーランナーの状態を判断 (waiting, running, finished)
            status = 'waiting'
            # 誰かが次の区間(shadow_leg_num + 1)に到達していたら、この区間のシャドーは 'finished'
            if any(team.get('newCurrentLeg') > shadow_leg_num for team in regular_team_results):
                status = 'finished'
            # 誰かがこの区間(shadow_leg_num)を走っていたら 'running'
            elif any(team.get('newCurrentLeg') == shadow_leg_num for team in regular_team_results):
                status = 'running'

            print(f"  {shadow_leg_num}区担当 {shadow_runner_name}選手、現在の状態: {status}")

            # 正規チームが同区間を走行中の場合、毎日記録分の距離を加算する
            if status == 'running':
                # その日の気温ではなく、歴代記録（1日あたりの平均走行距離）を今日の距離とする
                today_distance = shadow_runner_info.get('record', 0.0)
                print(f"  > {shadow_leg_num}区の記録 {today_distance:.1f}km を加算しました。")
            else:
                print(f"  > {shadow_leg_num}区は走行開始前か完了済みのため、本日の距離加算はスキップします。")

        new_total_distance = round(shadow_state['totalDistance'] + today_distance, 1)
        new_current_leg = shadow_state['currentLeg']

        # タスキ渡し（次の区間への移行）判定
        if new_current_leg <= len(ekiden_data['leg_boundaries']):
            # 正規チームの誰かが次の区間に到達したら、シャドーも次の区間に進む
            if any(team.get('newCurrentLeg') > new_current_leg for team in regular_team_results):
                new_current_leg += 1
                # ワープ処理: 次の区間に入った正規チームのトップの距離に合わせる
                teams_in_next_leg = [t for t in regular_team_results if t.get('newCurrentLeg') == new_current_leg]
                if teams_in_next_leg:
                    leader_in_next_leg = max(teams_in_next_leg, key=lambda x: x['totalDistance'])
                    new_total_distance = leader_in_next_leg['totalDistance']
                    print(f"  区間記録連合が {new_current_leg}区へタスキ渡し。トップの {leader_in_next_leg['name']} に合わせてワープします。")

        shadow_team_results.append({
            "id": shadow_state["id"], "name": shadow_team_data["name"], "runner": shadow_runner_name,
            "currentLegNumber": shadow_state["currentLeg"], "newCurrentLeg": new_current_leg,
            "todayDistance": today_distance, "totalDistance": new_total_distance,
            "previousRank": None, "rawTempResult": max_temp_result, "finishDay": None,
            "group_id": 2, # 順位計算対象外グループ
            "is_shadow_confederation": True
        })

    # --- Step 3: 結果の結合と順位計算 ---
    print("\nStep 3: 順位計算とレポート生成...")
    all_results = regular_team_results + shadow_team_results

    # 日間順位の計算 (正規チームのみ)
    ranked_teams_today = sorted([r for r in all_results if not r.get('is_shadow_confederation')], key=lambda x: x['todayDistance'], reverse=True)
    for i, team in enumerate(ranked_teams_today):
        team['todayRank'] = i + 1
    for team in all_results:
        if team.get('is_shadow_confederation'):
            team['todayRank'] = None

    # 総合順位の計算 (正規チームのみ)
    # 順位計算対象のチーム（正規チーム）のみを抽出
    teams_for_ranking = [r for r in all_results if not r.get('is_shadow_confederation')]

    # 1. ゴール済みチームの順位付け (ゴール日、ゴール時の距離でソート)
    finished_teams = sorted([r for r in teams_for_ranking if r.get('group_id') == 1], key=lambda x: (x.get('finishDay', float('inf')), -x.get('totalDistance', 0)))
    # 2. 走行中チームの順位付け (総距離でソート)
    running_teams = sorted([r for r in teams_for_ranking if r.get('group_id') == 0], key=lambda x: x.get('totalDistance', 0), reverse=True)

    # 3. 結合して最終的な順位を割り振る (同順位を考慮)
    ranked_teams = finished_teams + running_teams
    last_rank, last_key_val = 0, None
    for i, team in enumerate(ranked_teams):
        key_val = (team.get('finishDay', float('inf')), -team.get('totalDistance', 0)) if team.get('group_id') == 1 else -team.get('totalDistance', 0)
        if key_val != last_key_val:
            last_rank = i + 1
        team['overallRank'] = last_rank
        last_key_val = key_val

    for team in all_results:
        if team.get('is_shadow_confederation'):
            team['overallRank'] = None
    
    # 最終的な表示のために、総合順位でソートし直す (シャドーは最後尾)
    all_results.sort(key=lambda x: (x.get('overallRank') is None, x.get('overallRank', float('inf'))))

    print("\n--- 速報生成完了 ---")

    if args.realtime:
        append_to_realtime_log(all_results)
        save_realtime_report(all_results, race_day, "", "", "")
        update_rank_history(all_results, race_day, args.history_file)
        save_individual_results(individual_results, args.individual_state_file)
        if all_results:
            calculate_and_save_runner_locations(all_results)
        print(f"\n--- [Realtime Mode] 各種速報ファイルを保存しました ---")

    if args.commit:
        save_ekiden_state(all_results, args.state_file)
        update_rank_history(all_results, race_day, args.history_file)
        save_individual_results(individual_results, args.individual_state_file)
        if all_results:
            calculate_and_save_runner_locations(all_results)
        print(f"\n--- [Commit Mode] 最終結果を保存しました ---")
    
    if not args.realtime and not args.commit:
        print("\n--- [Preview Mode] 結果を保存するには --realtime または --commit オプションを使用してください ---")


if __name__ == '__main__':
    main()
