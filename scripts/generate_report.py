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
from collections import defaultdict
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

def load_start_date_from_outline():
    """outline.json から大会開始日を取得してグローバル定数を更新する"""
    global EKIDEN_START_DATE
    try:
        with open(OUTLINE_FILE, 'r', encoding='utf-8') as f:
            outline = json.load(f)
        metadata = outline.get('metadata', {})
        start_date = metadata.get('startDate')
        if start_date:
            EKIDEN_START_DATE = start_date
    except FileNotFoundError:
        print(f"情報: {OUTLINE_FILE} が見つからないため、開始日は既定値 {EKIDEN_START_DATE} を使用します。")
    except json.JSONDecodeError:
        print(f"情報: {OUTLINE_FILE} の解析に失敗したため、開始日は既定値 {EKIDEN_START_DATE} を使用します。")

load_start_date_from_outline()

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

def get_manager_tripcodes(ekiden_data):
    """ekiden_data.jsonから監督のコテハンと公式監督名を抽出し、辞書で返す"""
    managers = {}
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
    """日中（7:00-18:59）に投稿された最新の監督コメントを1件取得する。"""
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
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    posts = soup.find_all('div', class_='post')
    trip_pattern = re.compile(r'(◆[a-zA-Z0-9./]+)')

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
        if time(7, 0) <= post_datetime.time() < time(19, 0) and (now - post_datetime) < timedelta(minutes=10):
            posted_name = username_span.get_text().split('◆')[0].strip()
            content_text = content_div.get_text(separator=' ', strip=True)
            return {'name': posted_name, 'content': content_text}

    return None

def _generate_lead_change_comment(current_results, previous_report_data):
    """首位交代のコメントを生成"""
    if current_results and previous_report_data.get('teams'):
        current_leader_id = current_results[0]['id']
        previous_leader_id = previous_report_data['teams'][0]['id']
        if current_leader_id != previous_leader_id:
            current_leader_name = current_results[0]['name']
            return f"【首位交代】{current_leader_name}がトップに浮上！レースが大きく動きました！"
    return None

def _generate_leg_finish_comment(current_results, previous_report_data):
    """区間走破のコメントを生成"""
    previous_teams_map = {team['id']: team for team in previous_report_data.get('teams', [])}
    previous_distances = {team['id']: team['totalDistance'] for team in previous_report_data.get('teams', [])}
    leg_finishers_by_leg = {}

    for team in current_results:
        team_id = team['id']
        if team_id in previous_teams_map:
            previous_team = previous_teams_map[team_id]
            previous_total_distance = previous_distances.get(team_id)
            leg_to_check_completion = previous_team['currentLeg']

            if leg_to_check_completion <= len(ekiden_data['leg_boundaries']) and previous_total_distance is not None:
                boundary = ekiden_data['leg_boundaries'][leg_to_check_completion - 1]
                if team['totalDistance'] >= boundary and previous_total_distance < boundary:
                    completed_leg = leg_to_check_completion
                    if completed_leg not in leg_finishers_by_leg:
                        leg_finishers_by_leg[completed_leg] = []
                    leg_finishers_by_leg[completed_leg].append(team['name'])

    if leg_finishers_by_leg:
        comments = [f"{'、'.join(teams)}が{leg}区を走りきりました！" for leg, teams in sorted(leg_finishers_by_leg.items())]
        return "【区間走破】" + " ".join(comments)
    return None

def _generate_heat_wave_comment(current_results, previous_report_data):
    """猛暑・酷暑に関するコメントを生成"""
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

def _generate_closing_gap_comment(current_results, previous_report_data):
    """追い上げに関するコメントを生成"""
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
                closing_gap_teams.append({"name": current_team['name'], "gap_closed": gap_closed})
    
    if closing_gap_teams:
        best_closer = max(closing_gap_teams, key=lambda x: x['gap_closed'])
        return f"【追い上げ】{best_closer['name']}が猛追！前のチームとの差を{best_closer['gap_closed']:.1f}km縮めました！"
    return None

def _generate_rank_change_comment(current_results, previous_ranks):
    """順位変動に関するコメントを生成"""
    current_teams_map = {team['id']: team for team in current_results}
    
    jump_up_teams = [
        {"name": current_teams_map[team_id]['name'], "jump": previous_ranks[team_id] - rank, "current_rank": rank}
        for team_id, rank in {t['id']: t['overallRank'] for t in current_results if t.get('overallRank')}.items()
        if team_id in previous_ranks and previous_ranks[team_id] is not None and previous_ranks[team_id] - rank >= 3
    ]
    if jump_up_teams:
        best_jumper = max(jump_up_teams, key=lambda x: x['jump'])
        return f"【ジャンプアップ】{best_jumper['name']}が{best_jumper['jump']}ランクアップで{best_jumper['current_rank']}位に浮上！"

    rank_down_teams = [
        {"name": current_teams_map[team_id]['name'], "drop": rank - previous_ranks[team_id]}
        for team_id, rank in {t['id']: t['overallRank'] for t in current_results if t.get('overallRank')}.items()
        if team_id in previous_ranks and previous_ranks[team_id] is not None and rank - previous_ranks[team_id] >= 5
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
    can_show_timed_report = True
    last_comment = previous_report_data.get('breakingNewsComment', "")
    last_timestamp_str = previous_report_data.get('breakingNewsTimestamp')

    if last_comment and last_timestamp_str:
        try:
            last_timestamp = datetime.fromisoformat(last_timestamp_str)
            if (now - last_timestamp) < timedelta(hours=1) and not last_comment.startswith("【定時速報】"):
                can_show_timed_report = False
        except (ValueError, TypeError):
            pass

    if can_show_timed_report:
        # 定時速報の対象は、区間記録連合を除いた正規チームのみ
        active_teams = [r for r in current_results if not r.get('is_shadow_confederation')]

        if active_teams and now.minute == 45:
            # 本日の走行距離が最も長い選手
            top_performer = max(active_teams, key=lambda x: x.get('todayDistance', 0))
            if top_performer.get('todayDistance', 0) > 0:
                return f"【定時速報】本日のトップは{top_performer['runner']}選手！{top_performer['todayDistance']:.1f}kmと素晴らしい走りです！"
        if active_teams and now.minute == 15:
            # all_resultsは総合順位でソート済みなので、active_teamsの先頭が正規チームのトップ
            top_team = active_teams[0]
            return f"【定時速報】現在トップは{top_team['name']}！総合距離{top_team['totalDistance']:.1f}kmです！"
    return None

def generate_breaking_news_comment(current_results, previous_report_data):
    """前回と今回の結果を比較し、注目すべき変動があれば速報コメントを生成する"""
    now = datetime.now()
    if not (7 <= now.hour < 19) or not previous_report_data:
        return ""

    previous_ranks = {team['id']: team['overallRank'] for team in previous_report_data.get('teams', []) if team.get('overallRank') is not None}

    comment_generators = [
        _generate_lead_change_comment,
        _generate_leg_finish_comment,
        _generate_heat_wave_comment,
        _generate_rank_change_comment,
        _generate_closing_gap_comment,
        _generate_close_race_comment,
        _generate_timed_report_comment,
    ]

    for generator in comment_generators:
        if generator in [_generate_rank_change_comment]:
             comment = generator(current_results, previous_ranks)
        else:
            comment = generator(current_results, previous_report_data)
        
        if comment:
            return comment

    return ""

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
                runners_state[runner_name] = {
                    "totalDistance": 0,
                    "teamId": team['id'],
                    "records": [],
                    "legSummaries": {}
                }
        return runners_state
    with open(file_path, 'r', encoding='utf-8') as f:
        runners_state = json.load(f)

    # 旧フォーマットとの互換性維持
    for runner_name, runner_data in runners_state.items():
        if not isinstance(runner_data, dict):
            runners_state[runner_name] = {
                "totalDistance": 0,
                "teamId": None,
                "records": [],
                "legSummaries": {}
            }
            continue
        runner_data.setdefault("records", [])
        runner_data.setdefault("legSummaries", {})
        runner_data.setdefault("totalDistance", 0)
        runner_data.setdefault("teamId", None)
    return runners_state

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
    """リアルタイムログファイルに現在の走行データを追記する"""
    now_iso = datetime.now().isoformat()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(REALTIME_LOG_FILE, 'a', encoding='utf-8') as f:
            for r in results:
                # 走行中の正規チームのみログに記録
                if r['runner'] == 'ゴール' or r.get('is_shadow_confederation') or r.get('currentTempForLog') is None:
                    continue
                
                runner_name_with_leg = f"{r['currentLegNumber']}{r['runner']}"
                log_entry = {
                    "timestamp": now_iso, "team_id": r['id'],
                    "runner_name": runner_name_with_leg,
                    "distance": r.get('currentTempForLog'),
                    "total_distance": r.get('totalDistance')
                }
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        print(f"✅ リアルタイムログを '{REALTIME_LOG_FILE}' に追記しました。")
    except IOError as e:
        print(f"エラー: '{REALTIME_LOG_FILE}' への書き込みに失敗しました: {e}")

def update_leg_rank_history(results, previous_data, leg_rank_history_file_path, is_commit_mode=False):
    """区間通過順位の履歴を更新する。
    - is_commit_mode=False (リアルタイム): 前回の速報データと比較し、この瞬間に区間を通過したチームの順位を記録する。
    - is_commit_mode=True (コミット時): その日の開始時点のデータと比較し、その日に完了した全区間の最終順位を記録する。
    """
    num_legs = len(ekiden_data['leg_boundaries'])

    try:
        with open(leg_rank_history_file_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {"teams": [{"id": t["id"], "name": t["name"], "leg_ranks": [None] * num_legs} for t in all_teams_data]}

    history_teams_map = {team['id']: team for team in history['teams']}

    if is_commit_mode:
        # --- コミットモード: その日1日で完了した全区間の最終順位を記録 ---
        previous_state_map = {team['id']: team for team in previous_data}
        for result in results:
            team_id = result['id']
            prev_state = previous_state_map.get(team_id)
            team_history = history_teams_map.get(team_id)
            if not prev_state or not team_history: continue

            start_leg_today = prev_state['currentLeg']
            last_completed_leg = result['newCurrentLeg'] - 1
            for leg_number in range(start_leg_today, last_completed_leg + 1):
                leg_index = leg_number - 1
                if 0 <= leg_index < len(team_history['leg_ranks']):
                    team_history['leg_ranks'][leg_index] = result['overallRank']
    else:
        # --- リアルタイムモード: この瞬間に区間を通過したチームのみ記録 ---
        if not previous_data or not previous_data.get('teams'): return
        previous_teams_map = {team['id']: team for team in previous_data.get('teams', [])}
        for result in results:
            team_id = result['id']
            prev_team_data = previous_teams_map.get(team_id)
            team_history = history_teams_map.get(team_id)
            if not prev_team_data or not team_history: continue

            leg_to_check = prev_team_data['currentLeg']
            if leg_to_check <= len(ekiden_data['leg_boundaries']):
                boundary = ekiden_data['leg_boundaries'][leg_to_check - 1]
                if result['totalDistance'] >= boundary and prev_team_data['totalDistance'] < boundary:
                    leg_index = leg_to_check - 1
                    if 0 <= leg_index < len(team_history['leg_ranks']):
                        team_history['leg_ranks'][leg_index] = result['overallRank']

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(leg_rank_history_file_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

# .envファイルから環境変数を読み込む
from dotenv import load_dotenv
# スクリプトの場所を基準に .env ファイルのパスを解決
dotenv_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=dotenv_path)

# Render上のAPIサーバーのURLとシークレットキーを.envから読み込む
PUSH_API_URL = os.getenv("PROD_PUSH_API_URL")
API_SECRET_KEY = os.getenv("API_SECRET_KEY")

def send_push_notification(title, body):
    """Render上のAPIサーバーに通知送信を依頼する"""
    if not PUSH_API_URL or not API_SECRET_KEY:
        print("警告: .envにPROD_PUSH_API_URLまたはAPI_SECRET_KEYが設定されていません。")
        return

    api_endpoint = f"{PUSH_API_URL}/api/send-notification"
    headers = {
        'Content-Type': 'application/json',
        'X-API-Secret': API_SECRET_KEY
    }
    # サーバー側で badge_count を付与するため、ここでは title/body のみ送る
    payload = {
        "title": title,
        "body": body
    }

    try:
        response = requests.post(api_endpoint, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        print(f"APIサーバーへの通知リクエスト成功: {response.json().get('message')}")
    except requests.RequestException as e:
        print(f"APIサーバーへの通知リクエスト失敗: {e}")

def send_hourly_ranking_notification(results):
    """9時〜18時の毎時5分に総合順位を通知する"""
    now = datetime.now()
    
    # テスト通知オプションが指定されているか確認
    is_test_mode = '--test-notification' in sys.argv

    # 9時から18時、かつ毎時5分から9分の間、またはテストモードの場合のみ通知
    if not (is_test_mode or (9 <= now.hour <= 18 and 5 <= now.minute < 10)):
        return

    notification_title = f"【総合順位速報】({now.strftime('%H:%M')}現在)"
    body_lines = []
    # 上位10チームに絞り、区間記録連合と完走済みチームを除外
    ranked_teams = [
        t for t in results
        if not t.get('is_shadow_confederation') and t.get('finishDay') is None
    ]

    if not ranked_teams:
        return
    for team in ranked_teams[:5]:
        rank = team.get('overallRank', '-')
        name = team.get('name', 'N/A')
        runner = team.get('runner', '-')
        today_dist = team.get('todayDistance', 0.0)
        total_dist = team.get('totalDistance', 0.0)
        
        # 選手名に区間番号を付与
        if runner != 'ゴール' and not team.get('is_shadow_confederation'):
             runner_display = f"{team.get('currentLegNumber', '')}{runner}"
        else:
             runner_display = runner

        line = f"{rank}位 {name} ({runner_display}) 本日:{today_dist:.1f}km / 総合:{total_dist:.1f}km"
        body_lines.append(line)
    
    # チームが5チーム以上存在する場合のみ追記
    if len(ranked_teams) > 5:
        body_lines.append("\n以降は速報サイトでご確認ください。")

    notification_body = "\n".join(body_lines)
    print(f"定時順位通知を送信します:\nTitle: {notification_title}\nBody:\n{notification_body}")
    send_push_notification(notification_title, notification_body)

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝のレポートを生成します。')
    parser.add_argument('--realtime', action='store_true', help='リアルタイム速報用のJSONを生成します。')
    parser.add_argument('--commit', action='store_true', help='本日の結果を状態ファイルに保存します。')
    parser.add_argument('--test-notification', action='store_true', help='定時順位通知を強制的に送信してテストします。')
    parser.add_argument('--state-file', default=STATE_FILE, help=f'チームの状態ファイルパス (デフォルト: {STATE_FILE})')
    parser.add_argument('--individual-state-file', default=INDIVIDUAL_STATE_FILE, help=f'個人の状態ファイルパス (デフォルト: {INDIVIDUAL_STATE_FILE})')
    parser.add_argument('--history-file', default=RANK_HISTORY_FILE, help=f'日次順位履歴ファイルパス (デフォルト: {RANK_HISTORY_FILE})')
    args = parser.parse_args()  

    # --- 前回レポートの読み込み ---
    previous_report_file = DATA_DIR / 'realtime_report_previous.json'
    realtime_report_file = REALTIME_REPORT_FILE
    previous_report_data = None
    if realtime_report_file.exists():
        shutil.copy(realtime_report_file, previous_report_file)
        try:
            with open(previous_report_file, 'r', encoding='utf-8') as f:
                previous_report_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"警告: {previous_report_file} の読み込みに失敗しました。")
            previous_report_data = None

    load_all_data()

    start_date = datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d')
    race_day = (datetime.now().date() - start_date.date()).days + 1

    current_state = load_ekiden_state(args.state_file)
    previous_rank_map = {s['id']: s['overallRank'] for s in current_state}
    individual_results = load_individual_results(args.individual_state_file)
    
    today_leg_records = defaultdict(list)  # leg -> list of record dicts updated today
    legs_completed_today = []  # list of (runner_name, leg_number)

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
                finished_leg_number = team_state["currentLeg"]
                if runner_name != "ゴール":
                    legs_completed_today.append((runner_name, finished_leg_number))
                if new_current_leg > len(ekiden_data['leg_boundaries']) and finish_day_today is None:
                    finish_day_today = race_day

        # 個人記録を、その日に実際に走った選手に紐付ける
        if today_distance > 0:
            # ★★★ 修正点: 記録は常にその日に走った選手(runner_name)と、その選手が走っていた区間(team_state["currentLeg"])に紐付ける
            leg_to_record = team_state["currentLeg"]
            runner_info = individual_results.setdefault(
                runner_name,
                {"totalDistance": 0, "teamId": team_data['id'], "records": [], "legSummaries": {}}
            )
            runner_info.setdefault("teamId", team_data['id'])
            runner_info.setdefault("records", [])
            runner_info.setdefault("legSummaries", {})

            record_for_today = next((r for r in runner_info['records'] if r.get('day') == race_day), None)
            previous_distance = record_for_today.get('distance', 0.0) if record_for_today else 0.0
            is_new_record = record_for_today is None

            if record_for_today:
                record_for_today['distance'] = today_distance
            else:
                record_for_today = {"day": race_day, "leg": leg_to_record, "distance": today_distance}
                runner_info['records'].append(record_for_today)

            leg_summaries = runner_info.setdefault("legSummaries", {})
            summary = leg_summaries.setdefault(str(leg_to_record), {
                "totalDistance": 0.0,
                "days": 0,
                "averageDistance": 0.0,
                "rank": None,
                "status": "provisional",
                "finalRank": None,
                "finalDay": None,
                "lastUpdatedDay": None
            })

            # 前回の値を差し引いてから今日の距離を加算する
            summary_total = (summary.get("totalDistance", 0.0) or 0.0) - previous_distance + today_distance
            summary['totalDistance'] = round(summary_total, 1)
            current_days = summary.get('days', 0)
            if is_new_record:
                current_days += 1
            summary['days'] = current_days
            summary['averageDistance'] = round(summary['totalDistance'] / current_days, 3) if current_days else 0.0
            summary['lastUpdatedDay'] = race_day
            # 途中で復旧した場合に備えて final の解除は行わない（後段で最終決定）

            today_leg_records[leg_to_record].append({
                "runner_name": runner_name,
                "record": record_for_today,
                "summary": summary
            })

            runner_info['totalDistance'] = round(sum(r['distance'] for r in runner_info['records']), 1)

        regular_team_results.append({
            "id": team_state["id"], "name": team_data["name"], "runner": runner_name,
            "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": new_current_leg,
            "todayDistance": today_distance, "totalDistance": new_total_distance,
            "previousRank": previous_rank_map.get(team_state["id"], 0),
            "rawTempResult": max_temp_result, "finishDay": finish_day_today,
            "group_id": 0, "currentTempForLog": current_temp_for_log
        })

    # 区間ごとの平均距離・順位を更新
    if individual_results:
        leg_performance_map = defaultdict(list)
        for runner_name, runner_data in individual_results.items():
            leg_summaries = runner_data.get('legSummaries', {})
            for leg_key, summary in leg_summaries.items():
                try:
                    leg_number = int(leg_key)
                except (TypeError, ValueError):
                    continue
                if summary.get('days', 0) == 0:
                    continue
                leg_performance_map[leg_number].append((runner_name, summary))

        for leg_number, performances in leg_performance_map.items():
            if not performances:
                continue
            performances.sort(key=lambda item: item[1].get('averageDistance', 0.0), reverse=True)
            last_avg = None
            current_rank = 0
            for index, (_, summary) in enumerate(performances):
                avg = summary.get('averageDistance', 0.0)
                rounded_avg = round(avg, 3)
                if last_avg is None or rounded_avg != last_avg:
                    current_rank = index + 1
                    last_avg = rounded_avg
                summary['rank'] = current_rank

    # ゲーム内で当日区間を走破した選手を確定扱いに変更
    for runner_name, leg_number in legs_completed_today:
        runner_data = individual_results.get(runner_name)
        if not runner_data:
            continue
        leg_summary = runner_data.get('legSummaries', {}).get(str(leg_number))
        if not leg_summary:
            continue
        leg_summary['status'] = 'final'
        leg_summary['finalRank'] = leg_summary.get('rank')
        leg_summary['finalDay'] = race_day

    # 当日の記録に順位と平均距離を付与
    for leg_number, entries in today_leg_records.items():
        for entry in entries:
            summary = entry.get('summary') or {}
            record = entry.get('record') or {}
            average_distance = summary.get('averageDistance')
            record['legAverageDistance'] = round(average_distance, 3) if average_distance is not None else None
            record['legRank'] = summary.get('rank')
            final_day = summary.get('finalDay')
            is_final_today = summary.get('status') == 'final' and final_day == race_day
            record['legAverageStatus'] = 'final' if is_final_today else 'provisional'
            record['legRankStatus'] = 'final' if is_final_today else 'provisional'

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

        comment_to_save, timestamp_to_save, full_text_to_save = "", "", ""

        # 1. 監督の日中コメントをチェック
        daytime_comment = fetch_daytime_manager_comment(ekiden_data)
        if daytime_comment:
            content_snippet = daytime_comment['content']
            full_text = f"【{daytime_comment['name']}監督コメント】\n\n{daytime_comment['content']}"
            if len(content_snippet) > 50:
                content_snippet = content_snippet[:50] + '…'
            formatted_comment = f"【{daytime_comment['name']}監督コメント】{content_snippet}"
            
            if not previous_report_data or formatted_comment != previous_report_data.get('breakingNewsComment', ''):
                comment_to_save = formatted_comment
                full_text_to_save = full_text
                timestamp_to_save = datetime.now().isoformat()

                # --- 監督コメントのプッシュ通知を送信 ---
                notification_title = f"【{daytime_comment['name']}監督コメント】"
                notification_body = daytime_comment['content']
                # 本文が長すぎる場合は省略
                if len(notification_body) > 100:
                    notification_body = notification_body[:100] + '…'
                send_push_notification(notification_title, notification_body)
                print(f"Generated manager comment breaking news: '{comment_to_save}'")

        # 2. 通常の速報生成ロジック
        if not comment_to_save and previous_report_data:
            new_comment_text = generate_breaking_news_comment(all_results, previous_report_data)
            if new_comment_text:
                comment_to_save = new_comment_text
                full_text_to_save = "" # 通常の速報には全文はない
                timestamp_to_save = datetime.now().isoformat()
                # --- プッシュ通知を送信 ---
                if comment_to_save:
                    notification_title = comment_to_save.split('】')[0] + '】' if '】' in comment_to_save else ''
                    
                    # 通知を送信する速報の種類を限定
                    allowed_notifications = ["【首位交代】", "【首位争い】", "【酷暑】"]
                    if notification_title in allowed_notifications:
                        notification_body = comment_to_save.replace(notification_title, '').strip()
                        send_push_notification(notification_title, notification_body)
                print(f"Generated breaking news: '{comment_to_save}'")

        send_hourly_ranking_notification(all_results)
        
        # 3. 古いコメントの維持
        if not comment_to_save and previous_report_data:
            old_comment, old_timestamp, old_full_text = previous_report_data.get('breakingNewsComment', ""), previous_report_data.get('breakingNewsTimestamp', ""), previous_report_data.get('breakingNewsFullText', "")
            if old_timestamp and (datetime.now() - datetime.fromisoformat(old_timestamp)) < timedelta(hours=1):
                comment_to_save, timestamp_to_save, full_text_to_save = old_comment, old_timestamp, old_full_text

        save_realtime_report(all_results, race_day, comment_to_save, timestamp_to_save, full_text_to_save)
        update_rank_history(all_results, race_day, args.history_file)
        update_leg_rank_history(all_results, previous_report_data, LEG_RANK_HISTORY_FILE, is_commit_mode=False)
        save_individual_results(individual_results, args.individual_state_file)
        if all_results:
            calculate_and_save_runner_locations(all_results)
        print(f"\n--- [Realtime Mode] 各種速報ファイルを保存しました ---")

    if args.commit:
        # コミットモードでは、`current_state`（その日の開始時点の状態）を比較対象として渡す
        save_ekiden_state(all_results, args.state_file)
        update_rank_history(all_results, race_day, args.history_file)
        update_leg_rank_history(all_results, current_state, LEG_RANK_HISTORY_FILE, is_commit_mode=True)
        save_individual_results(individual_results, args.individual_state_file)
        if all_results:
            calculate_and_save_runner_locations(all_results)
        print(f"\n--- [Commit Mode] 最終結果を保存しました ---")
    
    if not args.realtime and not args.commit:
        print("\n--- [Preview Mode] 結果を保存するには --realtime または --commit オプションを使用してください ---")


if __name__ == '__main__':
    main()
