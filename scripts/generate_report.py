import json
import os
import copy
import bisect
import math
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
from time_utils import JST, now_jst, format_jst_iso

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')
HISTORY_DATA_DIR = Path('history_data')
TEST_EKIDEN_DATA_FILE = Path('15/ekiden_data.json')
SNAPSHOT_DIR = DATA_DIR / 'snapshots'  # スナップショットの保存ディレクトリ
TEST_MODE = os.environ.get('EKIDEN_TEST_MODE') == '1'

def determine_leg_from_total_distance(total_distance, leg_boundaries):
    """総合距離から 1-based の区間番号を返す。境界値は次区間扱いにする。"""
    try:
        total_dist = float(total_distance)
    except (ValueError, TypeError):
        return 1

    if total_dist < 0:
        return 1

    for i, boundary in enumerate(leg_boundaries):
        if total_dist < boundary:
            return i + 1

    return len(leg_boundaries) + 1
# --- ファイルパス定義 ---


EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
SHADOW_TEAM_FILE = CONFIG_DIR / 'shadow_team.json'
AMEDAS_STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
OUTLINE_FILE = CONFIG_DIR / 'outline.json'
COURSE_PATH_FILE = CONFIG_DIR / 'course_path.json'
RELAY_POINTS_FILE = CONFIG_DIR / 'relay_points.json'
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
# outline.json が読めない場合の最終フォールバック
EKIDEN_START_DATE = '2026-07-23'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

# --- グローバル変数 ---
stations_data = []
stations_by_code = {}  # code -> station
all_teams_data = [] # 正規チームとシャドーチームを結合したデータ
ekiden_data = {}
story_settings = {}
past_results = []
leg_award_history = []
tournament_records = []
leg_best_records = {}
intramural_rankings = {}
# 通常チームの現行登録選手名 → teamId のマップ (shadow とは別管理)。
# generate_report.py は選手名をキーに individual_results を管理するため、
# shadow_team.json と同名の通常選手が teamId=99 に混入するのを防ぐ。
current_runner_team_map = {}

def load_start_date_from_outline():
    """outline.json の metadata.startDate を正本として大会開始日を取得する"""
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

def normalize_runner_entries(team_data):
    """runners / substitutes が文字列配列でも dict 配列でも扱えるように正規化する"""
    if not isinstance(team_data, dict):
        return team_data

    for key in ('runners', 'substitutes'):
        entries = team_data.get(key, [])
        normalized = []
        for entry in entries:
            if isinstance(entry, str):
                normalized.append({'name': entry})
            else:
                normalized.append(entry)
        team_data[key] = normalized
    return team_data

def build_current_runner_team_map(teams):
    """
    通常チームの現行登録選手 (runners/substitutes/substituted_out、文字列/dict両形式) から
    runner_name → teamId のマップを構築する。シャドーチームは除外する。
    通常チーム同士で同名が重複する場合は (None, メッセージ) を返す (設定エラー)。
    戻り値: (map, error_message_or_None)
    """
    runner_team_map = {}
    for team in teams:
        if team.get('is_shadow_confederation'):
            continue
        team_id = team.get('id')
        for key in ('runners', 'substitutes', 'substituted_out'):
            for runner_obj in team.get(key, []):
                runner_name = runner_obj.get('name') if isinstance(runner_obj, dict) else runner_obj
                if not runner_name:
                    continue
                if runner_name in runner_team_map:
                    prev_team_id = runner_team_map[runner_name]
                    if prev_team_id != team_id:
                        return None, (f"通常チームで選手名 '{runner_name}' が重複登録されています "
                                      f"(teamId {prev_team_id} と {team_id})。設定を確認してください。")
                else:
                    runner_team_map[runner_name] = team_id
    return runner_team_map, None


def load_all_data():
    """必要なJSONファイルをすべて読み込む"""
    global stations_data, stations_by_code, all_teams_data, ekiden_data, story_settings, past_results, leg_award_history, tournament_records, leg_best_records, intramural_rankings, current_runner_team_map
    try:
        with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
        stations_by_code = {s['code']: s for s in stations_data}
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        if TEST_MODE:
            has_runners = any(team.get('runners') for team in ekiden_data.get('teams', []))
            if not has_runners and TEST_EKIDEN_DATA_FILE.exists():
                print(f"情報: テストモードのため {TEST_EKIDEN_DATA_FILE} を選手データとして使用します。")
                with open(TEST_EKIDEN_DATA_FILE, 'r', encoding='utf-8') as tf:
                    ekiden_data = json.load(tf)
        ekiden_data['teams'] = [normalize_runner_entries(team) for team in ekiden_data.get('teams', [])]

        # 通常チームの現行登録選手 (runners/substitutes/substituted_out) から runner_name → teamId を構築。
        # 通常チーム同士で同名が重複する場合は設定エラーとして明示的に検出する。
        current_runner_team_map, map_error = build_current_runner_team_map(ekiden_data.get('teams', []))
        if map_error:
            print(f"エラー: {map_error}")
            sys.exit(1)
        
        # シャドーチームの定義を読み込む
        try:
            with open(SHADOW_TEAM_FILE, 'r', encoding='utf-8') as f:
                shadow_team_data = json.load(f)
            shadow_team_data = normalize_runner_entries(shadow_team_data)
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
    now = now_jst()
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

        # 掲示板の時刻はJST表記で、datetime.strptimeはnaiveになるためJSTを付与する。
        post_datetime = datetime.strptime(
            f"{date_match.group(1)} {date_match.group(2)}", '%Y/%m/%d %H:%M:%S'
        ).replace(tzinfo=JST)
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
        # 区間記録連合（シャドーチーム）は区間走破コメントの対象外。
        # 通常チームIDに依存せず is_shadow_confederation フラグで判定する。
        if team.get('is_shadow_confederation'):
            continue
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

def _comment_contains_shadow_team(comment):
    """コメント文字列にシャドーチーム（区間記録連合）の表示名が含まれるか判定する。

    古いコメントの1時間維持（retention）で、過去の区間記録連合混入コメントを
    次回更新で保持しないためのガード。判定は is_shadow_confederation フラグを持つ
    チームの表示名を all_teams_data から取得し、ハードコードしない。
    """
    if not comment:
        return False
    for team in all_teams_data:
        if team.get('is_shadow_confederation') and team.get('name') and team['name'] in comment:
            return True
    return False

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
    now = now_jst()
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
    now = now_jst()
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

    last_comment = previous_report_data.get('breakingNewsComment', "")

    for generator in comment_generators:
        if generator in [_generate_rank_change_comment]:
             comment = generator(current_results, previous_ranks)
        else:
            comment = generator(current_results, previous_report_data)
        
        if comment:
            if comment == last_comment:
                continue
            return comment

    return ""

def load_ekiden_state(file_path, race_day=None):
    """駅伝の現在の状態を読み込む。ファイルがなければ全チームの初期状態を生成。"""
    if not os.path.exists(file_path):
        print(f"情報: '{file_path}' が見つかりません。全チームの初期状態を生成します。")
        return [
            {
                "id": team["id"], "name": team["name"],
                "totalDistance": 0.0, "currentLeg": 1, "overallRank": 0, "finishDay": None,
                "currentRunnerStartDistance": 0.0, "currentRunnerLegStartDay": 1
            } for team in all_teams_data
        ]
    with open(file_path, 'r', encoding='utf-8') as f:
        states = json.load(f)
    # 既存stateに新フィールドがない場合の補完
    for s in states:
        s.setdefault("currentRunnerStartDistance", s.get("totalDistance", 0.0))
        if "currentRunnerLegStartDay" not in s:
            if s.get("currentLeg", 1) == 1:
                s["currentRunnerLegStartDay"] = 1
            else:
                s["currentRunnerLegStartDay"] = race_day or 1
    return states

def load_individual_results(file_path):
    """選手個人の結果を読み込む。ファイルがなければ初期状態を生成。"""
    if not os.path.exists(file_path):
        runners_state = {}
        for team in all_teams_data:
            # シャドーチーム (is_shadow_confederation) の runners は個人記録DBに投入しない。
            # 区間記録連合の過去記録は shadow_team.json を正とし、通常の個人記録DBへ同名キーで混在させない。
            if team.get('is_shadow_confederation'):
                continue
            for runner_obj in team.get('runners', []):
                # 通常は load_all_data の normalize_runner_entries で dict 化済みだが、
                # 文字列のまま渡された場合にも防御する。
                runner_name = runner_obj.get('name') if isinstance(runner_obj, dict) else runner_obj
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

    # 現行 config の通常登録選手は、既存 teamId が 99 (shadow) や別 ID でも現行 teamId へ正規化する。
    # records / legSummaries / totalDistance は保持したまま自動修復する。
    for runner_name, runner_data in runners_state.items():
        if not isinstance(runner_data, dict):
            continue
        current_team_id = current_runner_team_map.get(runner_name)
        if current_team_id is not None:
            runner_data['teamId'] = current_team_id

    return runners_state

def save_ekiden_state(state, file_path, race_day=None):
    """駅伝の現在の状態を保存する"""
    data_to_save = []
    for s in state:
        team_state = {
            "id": s["id"], "name": s["name"],
            "totalDistance": s["totalDistance"],
            "currentLeg": s["newCurrentLeg"],
            "overallRank": s["overallRank"],
            "finishDay": s.get("finishDay"),
            "currentRunnerStartDistance": s.get("nextRunnerStartDistance", s.get("currentRunnerStartDistance", s["totalDistance"])),
            "currentRunnerLegStartDay": s.get("nextRunnerLegStartDay", s.get("currentRunnerLegStartDay", race_day or 1))
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


COMMIT_STATUS_FILE = DATA_DIR / 'commit_status.json'
COMMIT_PUBLISHED_FILES = [
    "data/ekiden_state.json",
    "data/individual_results.json",
    "data/rank_history.json",
    "data/leg_rank_history.json",
    "data/runner_locations.json",
    "data/realtime_report.json",
    "data/daily_temperatures.json",
    "data/intramural_rankings.json",
    "data/fetch_status.json",
    "data/commit_status.json",
]


def parse_validation_result(stdout):
    """validate_race_state.py の最終行 VALIDATION_RESULT {...} をパースして (issues, validated_teams) を返す。"""
    if not stdout:
        return [], []
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith('VALIDATION_RESULT '):
            try:
                payload = json.loads(line[len('VALIDATION_RESULT '):])
                return payload.get('issues', []), payload.get('validated_teams', [])
            except json.JSONDecodeError:
                return [], []
    return [], []


def write_commit_status(status, validation_severity, issues, quarantined_teams, date_str, validated_teams=None):
    """
    data/commit_status.json を生成する。
    status: ok / degraded / failed
    validation_severity: 0=問題なし, 1=fatal, 2=warning
    date_str: YYYY-MM-DD 形式の文字列
    validated_teams: 実際に検証した全大学 [{team_id, team_name}]
    生成失敗時は例外を送出する（呼び出し側で fatal 扱いにする）。
    """
    from time_utils import format_jst_datetime
    now = now_jst()
    commit_status = {
        "schemaVersion": 1,
        "date": date_str,
        "status": status,
        "generatedAt": format_jst_datetime(now),
        "validationSeverity": validation_severity,
        "validatedTeams": validated_teams if validated_teams is not None else [
            {"team_id": i.get('team_id'), "team_name": i.get('team_name')} for i in issues if i.get('team_name')
        ],
        "quarantinedTeams": quarantined_teams,
        "errors": [i.get('message') for i in issues],
        "publishedFiles": COMMIT_PUBLISHED_FILES,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(COMMIT_STATUS_FILE, 'w', encoding='utf-8') as f:
        json.dump(commit_status, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(f"✅ commit_status.json を保存しました (status={status})")
    return commit_status


def restore_backups(backups):
    """バックアップからファイルを復元する。"""
    for orig, bak in backups.items():
        if Path(bak).exists():
            shutil.move(bak, orig)


def apply_quarantine(all_results, individual_results, current_state, quarantined_teams,
                     pre_commit_state, pre_commit_individual, team_info_map=None):
    """
    quarantine 対象チームを今回実行前のバックアップ値（チーム単位）に戻す。

    - individual_results: quarantine チームの選手を実行前の値に復元
    - current_state: quarantine チームのエントリを実行前の値に復元
    - all_results: save_ekiden_state / rank_history / runner_locations / realtime_report は
      all_results から表示・保存値を再構築するため、quarantine チームのエントリを
      実行前 state (totalDistance / currentLeg / overallRank / finishDay /
      currentRunnerStartDistance / currentRunnerLegStartDay) から完全に再構築する。

    team_info_map: config の team_id → team 定義 (runner 名の解決用)。省略時は runner 名を
    「(quarantine)」に置き換える。

    戻り値: 更新後の (all_results, current_state)
    """
    if not quarantined_teams:
        return all_results, current_state
    q_ids = {q['team_id'] for q in quarantined_teams}
    pre_state_by_id = {s['id']: s for s in pre_commit_state}

    # individual_results: quarantine チームの選手を実行前の値に戻す
    for runner_name, runner_data in list(individual_results.items()):
        if runner_data.get('teamId') in q_ids:
            pre = pre_commit_individual.get(runner_name)
            if pre is not None:
                individual_results[runner_name] = copy.deepcopy(pre)
            else:
                # 実行前になかった選手（今日新規作成された不完全データ）は削除
                del individual_results[runner_name]

    # state: quarantine チームのエントリを実行前の値に戻す
    state_by_id = {s['id']: s for s in current_state}
    for q in quarantined_teams:
        pre = pre_state_by_id.get(q['team_id'])
        if pre is not None:
            state_by_id[q['team_id']] = copy.deepcopy(pre)
    current_state = [state_by_id[s['id']] for s in current_state if s['id'] in state_by_id]

    # all_results: quarantine チームのエントリを実行前 state から完全に再構築する
    for i, result in enumerate(all_results):
        if result.get('id') not in q_ids:
            continue
        pre = pre_state_by_id.get(result.get('id'))
        if pre is None:
            continue
        pre_leg = pre.get('currentLeg', 1)
        pre_total = pre.get('totalDistance', 0.0)
        pre_start = pre.get('currentRunnerStartDistance', pre_total)
        pre_start_day = pre.get('currentRunnerLegStartDay', 1)
        pre_finish = pre.get('finishDay')

        # 実行前の区間に対応するランナー名を解決
        runner_name = '(quarantine)'
        if team_info_map is not None:
            team_data = team_info_map.get(result.get('id'))
            if team_data:
                runners = team_data.get('runners', [])
                idx = pre_leg - 1
                if 0 <= idx < len(runners):
                    r = runners[idx]
                    runner_name = r['name'] if isinstance(r, dict) else str(r)

        all_results[i] = {
            "id": pre.get('id', result.get('id')),
            "name": pre.get('name', result.get('name')),
            "runner": runner_name,
            "currentLegNumber": pre_leg,
            "newCurrentLeg": pre_leg,
            "todayDistance": 0.0,
            "todayRank": None,  # quarantine: 今日の日間順位は未確定 (shadow と同様 None)
            "totalDistance": pre_total,
            "overallRank": pre.get('overallRank', result.get('overallRank', 0)),
            "previousRank": pre.get('overallRank', result.get('previousRank', 0)),
            "rawTempResult": {'temperature': 0, 'error': 'quarantine'},
            "finishDay": pre_finish,
            "group_id": 1 if pre_finish is not None else 0,
            "currentTempForLog": None,
            "currentRunnerStartDistance": pre_start,
            "currentRunnerLegStartDay": pre_start_day,
            "nextRunnerStartDistance": pre_start,
            "nextRunnerLegStartDay": pre_start_day,
            "is_shadow_confederation": False,
        }

    return all_results, current_state

def get_east_asian_width_count(text):
    """全角文字を2、半角文字を1として文字幅をカウント"""
    return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in text)

def pad_str(text, length, char='＿'):
    """指定した文字幅になるように文字列をパディング"""
    return text + char * (length - get_east_asian_width_count(text))

def save_realtime_report(results, race_day, breaking_news_comment, breaking_news_timestamp, breaking_news_full_text=""):
    """速報用のJSONデータを生成して保存する"""
    from time_utils import format_jst_datetime
    now = now_jst()
    report_data = {
        "updateTime": format_jst_datetime(now),
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
            "currentLeg": r["newCurrentLeg"],
            "todayLeg": r["currentLegNumber"],  # 本日実際に走っている区間番号
            "runner": runner_display,
            "todayDistance": r["todayDistance"], "todayRank": r["todayRank"],
            "totalDistance": r["totalDistance"], "overallRank": r["overallRank"],
            "previousRank": r["previousRank"], "nextRunner": next_runner_str,
            "error": r['rawTempResult']['error'], "finishDay": r.get("finishDay"),
            "is_shadow_confederation": r.get("is_shadow_confederation", False),
            "currentRunnerStartDistance": r.get("currentRunnerStartDistance"),
            "currentRunnerLegStartDay": r.get("currentRunnerLegStartDay")
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


# --- マップ距離補正（KMLコース距離 → 設定距離の区間別キャリブレーション） ---
# 速報データ（累積距離・区間判定・順位・記録計算）は変更せず、マップ座標生成のみを補正する。
# 設定距離の正本は ekiden_data['leg_boundaries']。relay_points.json の target_distance_km は補助。
ANCHOR_SEARCH_WINDOW_KM = 20.0    # 中継所アンカーの最近傍course_path頂点を探すKML距離の探索幅
MAX_ANCHOR_DEVIATION_KM = 2.0     # アンカーとcourse_path最近傍点の乖離上限（実データは約30m）
BOUNDARY_SNAP_TOLERANCE_KM = 1e-3  # 設定境界とみなす距離許容（1m）


def _load_relay_points():
    """relay_points.json を読み込む。失敗時は None を返す。"""
    try:
        with open(RELAY_POINTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _warn_calibration_fallback():
    """マップ距離補正の無効化警告を1回だけ出力する（チームごとに繰り返さない）。"""
    print("警告: マップ距離補正を無効化し、従来のcourse_path距離変換を使用します。")


def _valid_latlon(lat, lon):
    """緯度経度を検証し float 化する。欠落・非数値・非有限・範囲外は None を返す。"""
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat_f) and math.isfinite(lon_f)):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        return None
    return (lat_f, lon_f)


def _point_latlon(point):
    """course_path の1点から検証済み (lat, lon) タプルを返す。dictでない・不正なら None。"""
    if not isinstance(point, dict):
        return None
    return _valid_latlon(point.get('lat'), point.get('lon'))


def _safe_course_point(course_points, default_point):
    """異常course_pathでも有効な座標を返す。default_point が有効ならそれ、なければ先頭の有効点、全滅なら (0.0, 0.0)。"""
    latlon = _point_latlon(default_point)
    if latlon is not None:
        return latlon
    for p in course_points:
        latlon = _point_latlon(p)
        if latlon is not None:
            return latlon
    return (0.0, 0.0)


def _legacy_runner_position(target_distance_km, course_points, final_goal_km):
    """従来方式（course_path直走査・geodesic）の距離→座標変換（calibration無効時のフォールバック）。

    - 通常course_pathでは従来と同一の座標を返す。
    - 非有限target（NaN/±Inf）はスタート相当（0km）へ統一し、+Infをゴールへ流さない。
    - 異常course_path（欠落・非数値・非有限・範囲外の点）は該当セグメントをスキップし、
      例外を出さず有効な座標（先頭の有効点・最終点）で安全に扱う。
    - final_goal_km が None の場合はゴールスナップしない（save_snapshot 従来動作）。
    """
    try:
        target = float(target_distance_km)
    except (TypeError, ValueError):
        target = 0.0
    if not math.isfinite(target):
        target = 0.0
    if not course_points:
        return (0.0, 0.0)

    if target <= 0:
        return _safe_course_point(course_points, course_points[0])
    if final_goal_km is not None and target >= final_goal_km:
        return _safe_course_point(course_points, course_points[-1])

    cumulative_distance_km = 0.0
    team_lat, team_lon = _safe_course_point(course_points, course_points[0])
    location_found = False
    for i in range(1, len(course_points)):
        p1 = _point_latlon(course_points[i - 1])
        p2 = _point_latlon(course_points[i])
        if p1 is None or p2 is None:
            continue  # 異常点（欠落・非数値・非有限・範囲外）はスキップ
        segment_distance_km = geodesic(p1, p2).kilometers
        if segment_distance_km > 0 and cumulative_distance_km <= target < cumulative_distance_km + segment_distance_km:
            distance_into_segment = target - cumulative_distance_km
            fraction = distance_into_segment / segment_distance_km
            team_lat = p1[0] + fraction * (p2[0] - p1[0])
            team_lon = p1[1] + fraction * (p2[1] - p1[1])
            location_found = True
            break
        cumulative_distance_km += segment_distance_km
    if not location_found and target >= cumulative_distance_km:
        team_lat, team_lon = _safe_course_point(course_points, course_points[-1])
    return (team_lat, team_lon)


def _build_map_distance_calibration(course_path, relay_points, leg_boundaries):
    """KMLコース距離を設定距離（leg_boundaries）へ区間別に補正するアンカーを構築する。

    戻り値: 以下のキーを持つ dict。データ異常時は None（呼び出し側は従来方式へフォールバック）。
      configured_distances: [0.0] + leg_boundaries（スタート+第1〜第N中継所+ゴールに対応）
      actual_distances:     各アンカーのKML累積距離
      anchor_coordinates:   各アンカーの正確な座標 (lat, lon) タプル
      course_cumulative_distances: course_path 頂点のKML累積距離
      anchor_indices:       各アンカーに対応する course_path 頂点インデックス

    アンカー対応: 0km→スタート、leg_boundaries[i-1]→第i中継所、最終境界→ゴール。
    通常は configured_distances と anchor_coordinates がともに len(leg_boundaries)+1 要素になる。
    """
    if not isinstance(course_path, list) or len(course_path) < 2:
        return None
    if not isinstance(relay_points, list) or len(relay_points) == 0:
        return None
    # course_path の各点を検証して float 化する（欠落・非数値・非有限・範囲外は無効化）。
    # 数値文字列はここで float 化し、以後の累積距離・座標補間をすべて数値として扱う。
    normalized_course_path = []
    for p in course_path:
        if not isinstance(p, dict):
            return None
        latlon = _valid_latlon(p.get('lat'), p.get('lon'))
        if latlon is None:
            return None
        normalized_course_path.append(latlon)
    try:
        boundaries = [float(b) for b in leg_boundaries]
    except (TypeError, ValueError):
        return None
    # NaN/Inf などの非有限境界値は無効（NaN は比較で通過してしまうため明示検証）
    if not all(math.isfinite(b) for b in boundaries):
        return None
    # アンカー数一致: 設定境界数 = 中継所数 + 1（最終境界はゴールに対応）
    if len(boundaries) != len(relay_points) + 1:
        return None
    if boundaries[0] <= 0 or any(boundaries[i] >= boundaries[i + 1] for i in range(len(boundaries) - 1)):
        return None

    configured_distances = [0.0] + boundaries

    # relay_points の要素が dict でない場合は無効（AttributeError を出さない）
    if not all(isinstance(r, dict) for r in relay_points):
        return None
    # relay_points を leg 昇順に整列し、leg が 1..N で欠落・重複がないことを確認
    relays = sorted(relay_points, key=lambda r: r.get('leg', 0))
    if [r.get('leg') for r in relays] != list(range(1, len(relays) + 1)):
        return None

    # アンカー座標: スタート + 第1〜第N中継所 + ゴール。
    # 座標は検証+float化（欠落・非数値・非有限・範囲外は無効化し例外を出さない）。
    anchor_coordinates = [normalized_course_path[0]]
    relay_coords = []
    for r in relays:
        latlon = _valid_latlon(r.get('latitude'), r.get('longitude'))
        if latlon is None:
            return None
        relay_coords.append(latlon)
        anchor_coordinates.append(latlon)
    anchor_coordinates.append(normalized_course_path[-1])

    # course_path 頂点のKML累積距離を一度だけ計算（チームごとに再計算しない）
    course_cumulative_distances = [0.0]
    for i in range(1, len(normalized_course_path)):
        seg = geodesic(normalized_course_path[i - 1], normalized_course_path[i]).kilometers
        course_cumulative_distances.append(course_cumulative_distances[-1] + seg)
    if course_cumulative_distances[-1] <= 0:
        return None

    # 各中継所アンカーを course_path の最近傍頂点へ対応付ける（スタート・ゴールは先頭・末尾）。
    # 探索中心は設定距離の正本 leg_boundaries[i] を使う（relay_points の target_distance_km は
    # 正本ではないため探索には使わない。欠落・古い値でも探索がずれない）。
    anchor_indices = [0]
    for i, r in enumerate(relays):
        approx_km = boundaries[i]
        idx = _find_nearest_course_vertex(
            relay_coords[i][0], relay_coords[i][1], approx_km,
            normalized_course_path, course_cumulative_distances)
        if idx is None:
            return None
        anchor_indices.append(idx)
    anchor_indices.append(len(normalized_course_path) - 1)

    # アンカー探索インデックスが単調増加でなければ無効
    if any(anchor_indices[i] >= anchor_indices[i + 1] for i in range(len(anchor_indices) - 1)):
        return None

    actual_distances = [course_cumulative_distances[i] for i in anchor_indices]
    if any(actual_distances[i] >= actual_distances[i + 1] for i in range(len(actual_distances) - 1)):
        return None

    return {
        "configured_distances": configured_distances,
        "actual_distances": actual_distances,
        "anchor_coordinates": anchor_coordinates,
        "course_cumulative_distances": course_cumulative_distances,
        "anchor_indices": anchor_indices,
        "normalized_course_path": normalized_course_path,
    }


def _find_nearest_course_vertex(lat, lon, approx_km, course_path, course_cumulative_distances):
    """中継所座標に最近傍の course_path 頂点インデックスを返す。見つからなければ None。"""
    lo = bisect.bisect_left(course_cumulative_distances, max(0.0, approx_km - ANCHOR_SEARCH_WINDOW_KM))
    hi = bisect.bisect_right(course_cumulative_distances, approx_km + ANCHOR_SEARCH_WINDOW_KM)
    best_idx, best_dist = None, float('inf')
    for i in range(lo, min(hi, len(course_path))):
        d = geodesic((lat, lon), course_path[i]).kilometers
        if d < best_dist:
            best_dist, best_idx = d, i
    if best_idx is None or best_dist > MAX_ANCHOR_DEVIATION_KM:
        return None
    return best_idx


def _interpolate_on_course(actual_target_km, course_points, course_cumulative_distances):
    """KML累積距離上の位置を course の2点間で距離比例の線形補間により座標(lat, lon)で返す。

    course_points は float 化済みの (lat, lon) タプル配列（calibration の normalized_course_path）。
    """
    cum = course_cumulative_distances
    if actual_target_km <= cum[0]:
        return course_points[0]
    if actual_target_km >= cum[-1]:
        return course_points[-1]

    for i in range(1, len(course_points)):
        seg_len = cum[i] - cum[i - 1]
        if seg_len <= 0:
            continue  # ゼロ長セグメントはスキップ
        if cum[i - 1] <= actual_target_km <= cum[i]:
            fraction = (actual_target_km - cum[i - 1]) / seg_len
            p1 = course_points[i - 1]
            p2 = course_points[i]
            return (p1[0] + fraction * (p2[0] - p1[0]),
                    p1[1] + fraction * (p2[1] - p1[1]))
    return course_points[-1]


def _get_calibrated_runner_position(target_distance_km, course_path, calibration):
    """設定距離(km)をキャリブレーションでKML上の位置へ変換し、座標(lat, lon)を返す。

    - target <= 0 はスタート座標
    - target >= 最終leg_boundary はゴール座標
    - 設定境界と(ほぼ)一致する場合は正確なアンカー座標（中継所の実座標）を返す
    - 区間内は設定距離の比率でKML実距離を補間する（KML距離を速報距離として扱わない）
    - NaN/±Inf などの非有限targetはスタート座標(0km相当)へ統一し、意図せずゴールへ飛ばさない

    course_path 引数はAPI互換のため保持するが、座標補間には calibration の
    normalized_course_path（構築時にfloat化済み）を使用する。
    """
    try:
        target = float(target_distance_km)
    except (TypeError, ValueError):
        target = 0.0
    if not math.isfinite(target):
        return calibration["anchor_coordinates"][0]

    configured = calibration["configured_distances"]
    actual = calibration["actual_distances"]
    anchors = calibration["anchor_coordinates"]
    course_cum = calibration["course_cumulative_distances"]
    norm_course = calibration["normalized_course_path"]

    if target <= 0:
        return anchors[0]
    if target >= configured[-1]:
        return anchors[-1]

    # 設定境界と厳密一致・ほぼ一致する場合は正確なアンカー座標を返す
    for i, boundary in enumerate(configured):
        if abs(target - boundary) <= BOUNDARY_SNAP_TOLERANCE_KM:
            return anchors[i]

    actual_target = None
    for i in range(len(configured) - 1):
        if configured[i] < target < configured[i + 1]:
            span = configured[i + 1] - configured[i]
            ratio = (target - configured[i]) / span if span > 0 else 0.0
            actual_target = actual[i] + ratio * (actual[i + 1] - actual[i])
            break
    if actual_target is None:
        # 上記の範囲判定で必ず到達するはずだが、防御的に target をそのまま使う
        actual_target = target

    return _interpolate_on_course(actual_target, norm_course, course_cum)


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

    # マップ距離補正（KMLコース距離→設定距離）のアンカーを一度だけ構築する。
    # 異常時は None となり、従来の単純course_path距離変換へフォールバックする。
    relay_points = _load_relay_points()
    calibration = _build_map_distance_calibration(all_points, relay_points, ekiden_data.get('leg_boundaries') or [])
    if calibration is None:
        _warn_calibration_fallback()

    runner_locations = []
    print("各チームの現在位置を計算中...")
    team_info_map = {t['id']: t for t in all_teams_data}

    for team in teams_data:
        target_distance_km = team.get('totalDistance', 0)

        if calibration is not None:
            team_lat, team_lon = _get_calibrated_runner_position(target_distance_km, all_points, calibration)
        else:
            # --- 従来方式（フォールバック） ---
            # 最終ゴール距離以上ならコース最終点にスナップ（異常入力でも例外を出さない）
            final_goal_km = (ekiden_data.get('leg_boundaries') or [])[-1] if ekiden_data.get('leg_boundaries') else None
            team_lat, team_lon = _legacy_runner_position(target_distance_km, all_points, final_goal_km)

        team_info = team_info_map.get(team.get('id'))
        short_name = team_info.get('short_name', team.get('name')) if team_info else team.get('name')

        runner_locations.append({
            "rank": team.get('overallRank'), "team_name": team.get('name'),
            "team_short_name": short_name,
            "runner_name": team.get('runner'), "total_distance_km": team.get('totalDistance'),
            "latitude": team_lat, "longitude": team_lon,
            "current_leg": team.get('newCurrentLeg', team.get('currentLegNumber', 1)),
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
    now_iso = now_jst().isoformat()
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

def should_generate_snapshot():
    """スナップショット生成の条件を判定する
    1. 毎時5分のタイミング（24時間）
    2. 大きな状態変化（首位交代、区間完走など）があった場合
    """
    now = now_jst()
    return now.minute == 5  # 24時間毎時5分でスナップショットを生成

def list_snapshots():
    """スナップショットの一覧を取得する
    Returns:
        list: スナップショットファイルのリスト（タイムスタンプ順）
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshots = []
    for file in SNAPSHOT_DIR.glob('realtime_report_*.json'):
        try:
            timestamp_str = file.stem.replace('realtime_report_', '')
            timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M')
            snapshots.append({
                'filename': file.name,
                'path': str(file),
                'timestamp': timestamp,
                'timestamp_str': timestamp_str
            })
        except ValueError:
            continue
    return sorted(snapshots, key=lambda x: x['timestamp'])

def save_snapshot(results, race_day, breaking_news_comment, breaking_news_timestamp, breaking_news_full_text="", individual_results=None):
    """速報データのスナップショットを保存する
    
    スナップショットには以下の情報が含まれます：
    - チーム情報（順位、走者、距離など）
    - ランナーの位置情報（緯度経度）
    - 個人記録
    - 区間記録履歴
    - 速報コメント
    
    また、スナップショット一覧ファイルも自動的に更新します。
    """
    now = now_jst()
    timestamp_str = now.strftime('%Y%m%d_%H%M')
    
    # 位置情報の計算
    runner_locations = []
    try:
        with open(COURSE_PATH_FILE, 'r', encoding='utf-8') as f:
            all_points = json.load(f)

        # calculate_and_save_runner_locations() と同じ共通キャリブレーション/座標ヘルパーを使う。
        # 異常時は None となり従来の単純course_path距離変換へフォールバックする。
        relay_points = _load_relay_points()
        calibration = _build_map_distance_calibration(all_points, relay_points, ekiden_data.get('leg_boundaries') or [])
        if calibration is None:
            _warn_calibration_fallback()

        for team in results:
            target_distance_km = team.get('totalDistance', 0)
            current_leg = team.get('currentLegNumber', 1)

            if calibration is not None:
                team_lat, team_lon = _get_calibrated_runner_position(target_distance_km, all_points, calibration)
            else:
                # --- 従来方式（フォールバック） ---
                # スナップショットは従来どおりゴールスナップしない（異常入力でも例外を出さない）
                team_lat, team_lon = _legacy_runner_position(target_distance_km, all_points, None)

            runner_locations.append({
                "team_id": team["id"],
                "team_name": team.get("name"),
                "leg": current_leg,
                "runner": team.get("runner"),
                "distance": target_distance_km,
                "latitude": team_lat,
                "longitude": team_lon,
                "current_leg": current_leg,
                "is_shadow_confederation": team.get("is_shadow_confederation", False)
            })
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"警告: コース情報の読み込みに失敗しました: {e}")
        runner_locations = []

    snapshot_data = {
        "updateTime": now.strftime('%Y/%m/%d %H:%M'),
        "timestamp": now.isoformat(),
        "raceDay": race_day,
        "breakingNewsComment": breaking_news_comment,
        "breakingNewsTimestamp": breaking_news_timestamp,
        "breakingNewsFullText": breaking_news_full_text,
        "teams": [],
        "runnerLocations": runner_locations
    }

    team_info_map = {t['id']: t for t in all_teams_data}
    for r in results:
        team_info = team_info_map.get(r['id'])
        if not team_info:
            continue

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

        snapshot_data["teams"].append({
            "id": r["id"], "name": r["name"],
            "short_name": team_info.get("short_name", r["name"]),
            "currentLeg": r["newCurrentLeg"],
            "todayLeg": r["currentLegNumber"],  # 本日実際に走っている区間番号
            "runner": runner_display,
            "todayDistance": r["todayDistance"], "todayRank": r["todayRank"],
            "totalDistance": r["totalDistance"], "overallRank": r["overallRank"],
            "previousRank": r["previousRank"], "nextRunner": next_runner_str,
            "error": r['rawTempResult']['error'], "finishDay": r.get("finishDay"),
            "is_shadow_confederation": r.get("is_shadow_confederation", False),
            "currentRunnerStartDistance": r.get("currentRunnerStartDistance"),
            "currentRunnerLegStartDay": r.get("currentRunnerLegStartDay")
        })

    snapshot_path = SNAPSHOT_DIR / f"realtime_report_{timestamp_str}.json"
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot_data, f, indent=2, ensure_ascii=False)
    print(f"✅ スナップショットを '{snapshot_path}' に保存しました。")

    # スナップショット一覧の更新
    snapshots = list_snapshots()
    snapshot_index = {
        'lastUpdated': now.isoformat(),
        'snapshots': [{
            'filename': s['filename'],
            'timestamp': s['timestamp'].isoformat(),
            'timestamp_str': s['timestamp_str']
        } for s in snapshots]
    }
    index_path = SNAPSHOT_DIR / 'snapshot_index.json'
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(snapshot_index, f, indent=2, ensure_ascii=False)
    print(f"✅ スナップショット一覧を更新しました（計 {len(snapshots)} 件）")

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
        print("警告: 環境変数 PROD_PUSH_API_URL または API_SECRET_KEY が設定されていません。")
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
        response = requests.post(api_endpoint, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        print(f"APIサーバーへの通知リクエスト成功: {response.json().get('message')}")
    except requests.RequestException as e:
        print(f"APIサーバーへの通知リクエスト失敗: {e}")

def send_hourly_ranking_notification(results):
    """9時〜18時の毎時5分に総合順位を通知する"""
    now = now_jst()
    
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
    parser.add_argument('--best-effort', action='store_true', dest='best_effort',
                        help='警告(degraded)でも確定・継続します (validator exit 2 を致命的にしません)。')
    parser.add_argument('--test-notification', action='store_true', help='定時順位通知を強制的に送信してテストします。')
    parser.add_argument('--force-snapshot', action='store_true', help='強制的にスナップショットを生成します。')
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
    race_day = (now_jst().date() - start_date.date()).days + 1

    current_state = load_ekiden_state(args.state_file, race_day)
    previous_rank_map = {s['id']: s['overallRank'] for s in current_state}
    individual_results = load_individual_results(args.individual_state_file)
    
    today_leg_records = defaultdict(list)  # leg -> list of record dicts updated today
    legs_completed_today = []  # list of (runner_name, leg_number)

    team_info_map = {t['id']: t for t in all_teams_data}

    # --- best-effort 用: quarantine 管理 ---
    # quarantine 対象チームは state / individual_results を今回実行前のバックアップ値で保持する。
    quarantined_teams = []
    pre_commit_individual = copy.deepcopy(individual_results)
    pre_commit_state = copy.deepcopy(current_state)

    # --- Commitモード: daily_temperatures.json を読み込み、確定値を使用する ---
    cached_temps = {}
    race_day_date = (start_date + timedelta(days=race_day - 1)).strftime('%Y-%m-%d')
    if args.commit:
        try:
            with open(DATA_DIR / 'daily_temperatures.json', 'r', encoding='utf-8') as f:
                all_temps = json.load(f)
            day_temps = all_temps.get(race_day_date, {})
            if not day_temps:
                print(f'❌ daily_temperatures.json に対象日 {race_day_date} のデータがありません')
                sys.exit(1)
            cached_temps = day_temps
            print(f'  📝 daily_temperatures.json から確定値を使用 ({len(day_temps)}件)')
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f'❌ daily_temperatures.json の読み込みに失敗: {e}')
            sys.exit(1)

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
                "finishDay": finish_day, "group_id": 1,
                "currentRunnerStartDistance": team_state.get("currentRunnerStartDistance", team_state["totalDistance"]),
                "currentRunnerLegStartDay": team_state.get("currentRunnerLegStartDay", race_day)
            })
            continue

        print(f"  {team_data['name']} のデータを取得中...")
        runner_index = team_state['currentLeg'] - 1
        runner_name, max_temp_result, current_temp_for_log, today_distance = "ゴール", {'temperature': 0, 'error': None}, None, 0.0

        if runner_index < len(team_data.get('runners', [])):
            runner_name = team_data['runners'][runner_index]['name']
            runner_obj = team_data['runners'][runner_index]
            station = None
            should_skip = False
            if isinstance(runner_obj, dict) and runner_obj.get('station_code'):
                code = runner_obj['station_code']
                station = stations_by_code.get(code)
                if not station:
                    print(f"エラー: 選手 '{runner_name}' の観測所コード {code} が stations_by_code に見つかりません")
                    max_temp_result = {'temperature': 0, 'error': f'コード {code} 不明'}
                    current_temp_for_log = None
                    should_skip = True
            if not station and not should_skip:
                station = find_station_by_name(runner_name)
            if station:
                if args.commit:
                    # Commitモード: daily_temperatures.json の確定値を使用
                    temp = cached_temps.get(runner_name)
                    if temp is None or (isinstance(temp, (int, float)) and temp == 0):
                        if args.best_effort:
                            # best-effort: この大学を quarantine 扱いにして state/individual 更新を保留する
                            quarantined_teams.append({
                                'team_id': team_state['id'],
                                'team_name': team_data['name'],
                                'reason': f'{runner_name} の気温確定値が daily_temperatures.json にありません（値={temp!r}）',
                            })
                            print(f'⚠️ [best-effort] {team_data["name"]} を quarantine します: '
                                  f'{runner_name} の確定気温がありません（値={temp!r}）。state/individual 更新を保留します。')
                            # 今日の距離は 0 扱い（記録追加・距離加算をしない）
                            max_temp_result = {'temperature': 0, 'error': '確定気温なし (quarantine)'}
                            current_temp_for_log = None
                        else:
                            print(f'❌ Commit失敗: {runner_name} の気温確定値が daily_temperatures.json にありません（値={temp!r}）')
                            sys.exit(1)
                    else:
                        max_temp_result = {'temperature': temp, 'error': None}
                        current_temp_for_log = temp
                else:
                    # Realtime/通常モード: 外部サイトから取得
                    max_temp_result = fetch_max_temperature(station['pref_code'], station['code'])
                    current_temp_result = fetch_current_temperature(station['pref_code'], station['code'])
                    current_temp_for_log = current_temp_result.get('temperature')
            else:
                if args.commit:
                    print(f'❌ Commit失敗: {runner_name} の観測所情報が見つかりません')
                    sys.exit(1)
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

        # 現在走者の開始距離と開始日（表示用 = todayLegの走者の値）
        current_runner_start_distance = team_state.get('currentRunnerStartDistance', team_state['totalDistance'])
        current_runner_leg_start_day = team_state.get('currentRunnerLegStartDay', race_day)
        # 次状態保存用（区間交代時は新走者の値に更新、交代なしなら表示用と同じ）
        next_runner_start_distance = current_runner_start_distance
        next_runner_leg_start_day = current_runner_leg_start_day
        if is_leg_change:
            # 新しい走者の開始距離 = 交代時の総距離
            # 開始日は翌日から（交代当日は旧走者が走っているため）
            next_runner_start_distance = new_total_distance
            next_runner_leg_start_day = race_day + 1

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
            "group_id": 0, "currentTempForLog": current_temp_for_log,
            "currentRunnerStartDistance": current_runner_start_distance,
            "currentRunnerLegStartDay": current_runner_leg_start_day,
            "nextRunnerStartDistance": next_runner_start_distance,
            "nextRunnerLegStartDay": next_runner_leg_start_day
        })

    # 区間ごとの平均距離・順位を更新
    if individual_results:
        leg_performance_map = defaultdict(list)
        for runner_name, runner_data in individual_results.items():
            # shadow チーム (teamId=99) の記録は通常の区間平均・順位計算の対象外。
            # 通常登録に戻した選手は load_individual_results で現行 teamId へ正規化済みなので対象に含まれる。
            if runner_data.get('teamId') == 99:
                continue
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

        # 日別順位 (dailyRank): 同日・同一区間内の距離順位 (competition ranking)
        entries.sort(key=lambda e: e['record'].get('distance', 0) or 0, reverse=True)
        last_dist, current_rank = None, 0
        for i, entry in enumerate(entries):
            record = entry['record']
            dist = record.get('distance', 0) or 0
            if dist != last_dist:
                current_rank = i + 1
                last_dist = dist
            record['dailyRank'] = current_rank
            record['dailyRankStatus'] = record.get('legRankStatus', 'provisional')

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
                new_total_distance = round(shadow_state['totalDistance'] + today_distance, 1)
            elif status == 'finished':
                # 誰かが次の区間に到達したため、この区間の走行は完了。距離を境界値に合わせる
                boundary_distance = ekiden_data['leg_boundaries'][shadow_leg_num - 1]
                new_total_distance = max(shadow_state['totalDistance'], boundary_distance)
                today_distance = round(new_total_distance - shadow_state['totalDistance'], 1)
                print(f"  > {shadow_leg_num}区は完了したため、総距離を中継所 ({new_total_distance:.1f}km) に合わせました。本日加算距離: {today_distance:.1f}km")
            else:
                print(f"  > {shadow_leg_num}区は走行開始前のため、本日の距離加算はスキップします。")
                new_total_distance = shadow_state['totalDistance']
        new_current_leg = determine_leg_from_total_distance(new_total_distance, ekiden_data['leg_boundaries'])
        if new_current_leg != shadow_state['currentLeg']:
            print(f"  区間記録連合の区間を {shadow_state['currentLeg']}区 -> {new_current_leg}区 に更新します。")

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

    # 日間順位の計算 (正規チームのみ、同率処理あり)
    ranked_teams_today = sorted([r for r in all_results if not r.get('is_shadow_confederation')], key=lambda x: x['todayDistance'], reverse=True)
    last_today_rank, last_today_dist = 0, None
    for i, team in enumerate(ranked_teams_today):
        if team['todayDistance'] != last_today_dist:
            last_today_rank = i + 1
            last_today_dist = team['todayDistance']
        team['todayRank'] = last_today_rank
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

        # スナップショット生成（毎時5分、重要な状態変化時、または強制指定時）
        if should_generate_snapshot() or args.force_snapshot:
            print("\nスナップショットを生成します...")
            save_snapshot(
                results=all_results,
                race_day=race_day,
                breaking_news_comment=comment_to_save,
                breaking_news_timestamp=timestamp_to_save,
                breaking_news_full_text=full_text_to_save,
                individual_results=individual_results
            )
            print(f"✅ スナップショットを {SNAPSHOT_DIR} に保存しました。")

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
                timestamp_to_save = now_jst().isoformat()

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
                timestamp_to_save = now_jst().isoformat()
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
        # シャドーチーム（区間記録連合）名を含む古いコメントは、過去の混入コメントを
        # 次回更新で保持し続けないよう維持対象から除外する。
        if not comment_to_save and previous_report_data:
            old_comment, old_timestamp, old_full_text = previous_report_data.get('breakingNewsComment', ""), previous_report_data.get('breakingNewsTimestamp', ""), previous_report_data.get('breakingNewsFullText', "")
            if old_timestamp and (now_jst() - datetime.fromisoformat(old_timestamp)) < timedelta(hours=1) \
                    and not _comment_contains_shadow_team(old_comment):
                comment_to_save, timestamp_to_save, full_text_to_save = old_comment, old_timestamp, old_full_text

        save_realtime_report(all_results, race_day, comment_to_save, timestamp_to_save, full_text_to_save)
        update_rank_history(all_results, race_day, args.history_file)
        update_leg_rank_history(all_results, previous_report_data, LEG_RANK_HISTORY_FILE, is_commit_mode=False)
        save_individual_results(individual_results, args.individual_state_file)
        if all_results:
            calculate_and_save_runner_locations(all_results)
        print(f"\n--- [Realtime Mode] 各種速報ファイルを保存しました ---")

    if args.commit:
        # コミットモード: 既存ファイルをバックアップ→保存→検証→不合格時復元
        commit_files = [
            args.state_file,
            args.individual_state_file,
            args.history_file,
            str(LEG_RANK_HISTORY_FILE),
            str(DATA_DIR / 'runner_locations.json'),
            str(REALTIME_REPORT_FILE),
        ]
        backups = {}
        for fp in commit_files:
            fp_str = str(fp)
            if Path(fp_str).exists():
                backups[fp_str] = fp_str + '.bak'
                shutil.copy2(fp_str, backups[fp_str])

        try:
            # quarantine 対象チームは、今回実行前のバックアップ値（チーム単位）を state / individual に保持する
            all_results, current_state = apply_quarantine(
                all_results, individual_results, current_state, quarantined_teams,
                pre_commit_state, pre_commit_individual, team_info_map,
            )

            save_ekiden_state(all_results, args.state_file, race_day)
            update_rank_history(all_results, race_day, args.history_file)
            update_leg_rank_history(all_results, current_state, LEG_RANK_HISTORY_FILE, is_commit_mode=True)
            save_individual_results(individual_results, args.individual_state_file)
            if all_results:
                calculate_and_save_runner_locations(all_results)
            previous_comment = previous_report_data or {}
            save_realtime_report(
                all_results, race_day,
                previous_comment.get("breakingNewsComment", ""),
                previous_comment.get("breakingNewsTimestamp", ""),
                previous_comment.get("breakingNewsFullText", ""),
            )

            # 整合性検証
            print("状態ファイルの整合性を検証中...")
            import subprocess
            result = subprocess.run(
                [sys.executable, "scripts/validate_race_state.py"],
                capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent
            )
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)

            validation_issues, validated_teams = parse_validation_result(result.stdout)
            validation_severity = result.returncode  # 0=問題なし, 2=warning, 1=fatal

            # 想定外の終了コード (0/1/2 以外) は fatal 扱い
            if validation_severity not in (0, 1, 2):
                print(f"❌ validate_race_state.py が予期しない終了コード ({validation_severity}) で終了しました。致命的エラーとして扱います。")
                try:
                    diag = subprocess.run(
                        [sys.executable, "scripts/save_validation_diagnostics.py",
                         "--output", result.stdout],
                        cwd=Path(__file__).resolve().parent.parent
                    )
                    if diag.returncode != 0:
                        print("⚠️ 診断成果物の保存に失敗しました", file=sys.stderr)
                except OSError as e:
                    print(f"⚠️ 診断成果物の保存に失敗しました: {e}", file=sys.stderr)
                restore_backups(backups)
                sys.exit(1)

            # commit_status.json 生成 (失敗時は fatal 扱い)
            # date は YYYY-MM-DD 文字列に統一 (race_day_date)。strict 停止時は failed にする (D4)。
            try:
                if validation_severity == 0:
                    commit_status = 'ok'
                elif validation_severity == 2:
                    commit_status = 'degraded'
                else:
                    commit_status = 'failed'
                write_commit_status(commit_status, validation_severity, validation_issues,
                                    quarantined_teams, race_day_date, validated_teams)
            except Exception as e:
                print(f"❌ commit_status.json の生成に失敗しました: {e}", file=sys.stderr)
                restore_backups(backups)
                sys.exit(1)

            if validation_severity == 1:
                # fatal: 従来通り候補を復元して停止
                print("❌ 状態ファイルの致命的エラー。診断成果物を保存してからバックアップから復元します。")
                # 復元前に不整合状態の診断成果物を保存（復元動作は従来通り維持）
                try:
                    diag = subprocess.run(
                        [sys.executable, "scripts/save_validation_diagnostics.py",
                         "--output", result.stdout],
                        cwd=Path(__file__).resolve().parent.parent
                    )
                    if diag.returncode != 0:
                        print("⚠️ 診断成果物の保存に失敗しました", file=sys.stderr)
                except OSError as e:
                    print(f"⚠️ 診断成果物の保存に失敗しました: {e}", file=sys.stderr)
                restore_backups(backups)
                sys.exit(1)

            if validation_severity == 2 and not args.best_effort:
                # warning だが strict 運用: 従来通り復元して停止
                # (D4) strict 停止時は commit_status を failed に更新してから復元
                print("❌ 状態ファイルに警告があります (strict 運用のため停止)。診断成果物を保存してからバックアップから復元します。")
                try:
                    write_commit_status('failed', validation_severity, validation_issues,
                                        quarantined_teams, race_day_date, validated_teams)
                except Exception as e:
                    print(f"⚠️ commit_status.json の failed 更新に失敗しました: {e}", file=sys.stderr)
                try:
                    diag = subprocess.run(
                        [sys.executable, "scripts/save_validation_diagnostics.py",
                         "--output", result.stdout],
                        cwd=Path(__file__).resolve().parent.parent
                    )
                    if diag.returncode != 0:
                        print("⚠️ 診断成果物の保存に失敗しました", file=sys.stderr)
                except OSError as e:
                    print(f"⚠️ 診断成果物の保存に失敗しました: {e}", file=sys.stderr)
                restore_backups(backups)
                sys.exit(1)

            # 検証合格 (0) または warning 継続 (2 + best-effort): バックアップ削除
            for bak in backups.values():
                Path(bak).unlink(missing_ok=True)
            if validation_severity == 2:
                print("⚠️ 警告付き継続 (degraded)。候補を確定しました。")
                print("✅ 状態ファイルの整合性確認完了 (warning)")
                sys.exit(2)
            print("✅ 状態ファイルの整合性確認完了")

        except SystemExit:
            # Blocker 1: 意図的な sys.exit (2=degraded継続, 1=fatal停止) はバックアップ復元しない。
            # degraded継続時は候補を確定しているため、残存バックアップを復元してはならない。
            raise
        except BaseException:
            # 例外時もバックアップ復元 (SystemExit 以外)
            restore_backups(backups)
            raise

        print(f"\n--- [Commit Mode] 最終結果を保存しました ---")
    
    if not args.realtime and not args.commit:
        print("\n--- [Preview Mode] 結果を保存するには --realtime または --commit オプションを使用してください ---")


if __name__ == '__main__':
    main()
