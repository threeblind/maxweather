import json
import os
from datetime import datetime, timedelta
import requests
import shutil
from bs4 import BeautifulSoup
import unicodedata
import sys
import argparse

# --- 定数 ---
AMEDAS_STATIONS_FILE = 'amedas_stations.json'
EKIDEN_DATA_FILE = 'ekiden_data.json'
STATE_FILE = 'ekiden_state.json'
INDIVIDUAL_STATE_FILE = 'individual_results.json'
RANK_HISTORY_FILE = 'rank_history.json'
LEG_RANK_HISTORY_FILE = 'leg_rank_history.json'
EKIDEN_START_DATE = '2025-07-23'

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

def save_realtime_report(results, race_day, breaking_news_comment, breaking_news_timestamp):
    """速報用のJSONデータを生成して保存する"""
    now = datetime.now()
    report_data = {
        "updateTime": now.strftime('%Y/%m/%d %H:%M'),
        "raceDay": race_day,
        "breakingNewsComment": breaking_news_comment,
        "breakingNewsTimestamp": breaking_news_timestamp,
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

def generate_breaking_news_comment(current_results, previous_results_file):
    """前回と今回の結果を比較し、注目すべき変動があれば速報コメントを生成する"""
    if not os.path.exists(previous_results_file):
        return ""

    try:
        with open(previous_results_file, 'r', encoding='utf-8') as f:
            previous_data = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return ""

    # チームIDをキーにしたマップを作成
    current_teams_map = {team['id']: team for team in current_results}
    previous_ranks = {team['id']: team['overallRank'] for team in previous_data.get('teams', [])}

    # --- コメント生成ロジック (優先度順) ---

    # 1. 首位交代
    if current_results and previous_data.get('teams'):
        current_leader_id = current_results[0]['id']
        previous_leader_id = previous_data['teams'][0]['id']
        if current_leader_id != previous_leader_id:
            current_leader_name = current_results[0]['name']
            return f"【速報】首位交代！ {current_leader_name}がトップに浮上しました！"

    # 2. 区間走破（本日初）
    previous_teams_map = {team['id']: team for team in previous_data.get('teams', [])}
    previous_distances = {team['id']: team['totalDistance'] for team in previous_data.get('teams', [])}
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

    # 2. 39度以上の猛暑日記録
    hot_runners = [r for r in current_results if r.get('todayDistance', 0) >= 39.0]
    if hot_runners:
        hottest_runner = max(hot_runners, key=lambda x: x['todayDistance'])
        team_name = hottest_runner['name']
        runner_name = hottest_runner['runner']
        temp = hottest_runner['todayDistance']
        return f"【猛暑】{team_name}の{runner_name}選手が本日{temp:.1f}℃を記録！素晴らしい走りです！"

    # 3. 3ランク以上のジャンプアップ
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

    # 4. 5ランク以上のランクダウン
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

    # 4.5. 追い上げ
    previous_distances = {team['id']: team['totalDistance'] for team in previous_data.get('teams', [])}
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

    # 4.8. 表彰台争い、トップ5争い
    if len(current_results) > 3:
        team_3 = current_results[2]
        team_4 = current_results[3]
        gap_podium = team_3['totalDistance'] - team_4['totalDistance']
        if 0 <= gap_podium < 0.5:
            return f"【表彰台争い】3位{team_3['name']}と4位{team_4['name']}が激しく競り合っています！"

    if len(current_results) > 5:
        team_5 = current_results[4]
        team_6 = current_results[5]
        gap_top5 = team_5['totalDistance'] - team_6['totalDistance']
        if 0 <= gap_top5 < 0.5:
            return f"【トップ5争い】5位{team_5['name']}と6位{team_6['name']}がデッドヒート！"

    # 5. 壮絶な競り合い
    if len(current_results) > 10:
        # シード権争い (10位 vs 11位)
        team_10 = current_results[9]
        team_11 = current_results[10]
        gap = team_10['totalDistance'] - team_11['totalDistance']
        if 0 <= gap < 0.5:
            return f"【シード権争い】10位{team_10['name']}と11位{team_11['name']}が熾烈な争い！"

    # 6. 27度以下の選手への鼓舞 (15時まで)
    if datetime.now().hour < 15:
        cold_runners = [r for r in current_results if 0 < r.get('todayDistance', 0) <= 27.0]
        if cold_runners:
            coldest_runner = min(cold_runners, key=lambda x: x['todayDistance'])
            team_name = coldest_runner['name']
            runner_name = coldest_runner['runner']
            temp = coldest_runner['todayDistance']
            return f"【奮起】{team_name}の{runner_name}選手(現在{temp:.1f}℃)、ここからの追い上げに期待がかかります！"
    
    # 7. 本日トップの選手名を紹介
    if current_results:
        now = datetime.now()
        if now.hour in [12, 13, 14, 15] and now.minute == 5:
            # Find the team with the highest distance today
            top_performer_today = max(current_results, key=lambda x: x.get('todayDistance', 0))
            # Ensure there's some distance to report
            if top_performer_today.get('todayDistance', 0) > 0:
                runner_name = top_performer_today['runner']
                distance = top_performer_today['todayDistance']
                return f"【定時速報】本日のトップは{runner_name}選手！{distance:.1f}kmと素晴らしい走りです！"

    return "" # 大きな変動がなければ空文字列を返す

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
    if os.path.exists(realtime_report_file):
        shutil.copy(realtime_report_file, previous_report_file)
        with open(previous_report_file, 'r', encoding='utf-8') as f:
            previous_report_data = json.load(f)
    else:
        previous_report_file = ''

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
        # Generate breaking news comment
        new_comment_text = ""
        if previous_report_file:
            new_comment_text = generate_breaking_news_comment(results, previous_report_file)

        if new_comment_text:
            comment_to_save = new_comment_text
            timestamp_to_save = datetime.now().isoformat()
            print(f"Generated breaking news: '{comment_to_save}'")
        else:
            # No new comment, check if we should keep the old one
            old_comment, old_timestamp = previous_report_data.get('breakingNewsComment', ""), previous_report_data.get('breakingNewsTimestamp', "")
            if old_timestamp and (datetime.now() - datetime.fromisoformat(old_timestamp)) < timedelta(hours=1):
                comment_to_save = old_comment
                timestamp_to_save = old_timestamp
            else:
                comment_to_save, timestamp_to_save = "", ""

        # 各種速報ファイルを保存
        save_realtime_report(results, race_day, comment_to_save, timestamp_to_save)
        update_rank_history(results, race_day, args.history_file)
        update_leg_rank_history(results, current_state, args.leg_history_file)
        save_individual_results(individual_results, args.individual_state_file)
        print(f"\n--- [Realtime Mode] Saved report data to {realtime_report_file}, {args.history_file}, {args.leg_history_file}, and {args.individual_state_file} ---")

    if args.commit:
        save_ekiden_state(results, args.state_file)
        update_rank_history(results, race_day, args.history_file)
        update_leg_rank_history(results, current_state, args.leg_history_file, is_commit_mode=True)
        save_individual_results(individual_results, args.individual_state_file)
        print(f"\n--- [Commit Mode] Saved final results to {args.state_file}, {args.individual_state_file}, {args.history_file}, and {args.leg_history_file} ---")
    elif not args.realtime:
        print("\n--- [Preview Mode] To save results, run `python generate_report.py --commit` ---")

if __name__ == '__main__':
    main()