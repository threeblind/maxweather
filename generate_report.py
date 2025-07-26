import json
import os
from datetime import datetime, timedelta
import requests
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

def save_realtime_report(results, race_day):
    """速報用のJSONデータを生成して保存する"""
    now = datetime.now()
    report_data = {
        "updateTime": now.strftime('%Y/%m/%d %H:%M'),
        "raceDay": race_day,
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

def update_rank_history(results, race_day):
    """
    順位履歴ファイル(rank_history.json)を更新する。
    - results: 総合順位でソート済みのその日の結果リスト
    - race_day: レース日
    """
    try:
        with open(RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
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
    with open(RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝のレポートを生成します。')
    parser.add_argument('--realtime', action='store_true', help='リアルタイム速報用のJSON (realtime_report.json) を生成します。')
    parser.add_argument('--commit', action='store_true', help='本日の結果を状態ファイル (ekiden_state.json) に保存します。')
    # テスト用のファイルパスを指定するオプションを追加
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
        save_realtime_report(results, race_day)
        # リアルタイムモードでも個人成績を保存する
        save_individual_results(individual_results, args.individual_state_file)
        print(f"\n--- [速報モード] 速報データを realtime_report.json と {args.individual_state_file} に保存しました ---")

    if args.commit:
        save_ekiden_state(results, args.state_file)
        update_rank_history(results, race_day)
        save_individual_results(individual_results, args.individual_state_file)
        print(f"\n--- [コミットモード] 本日の最終結果を {args.state_file}, {args.individual_state_file}, {args.history_file} に保存しました ---")
    elif not args.realtime:
        print("\n--- [プレビューモード] 結果を保存するには `python generate_report.py --commit` を実行してください ---")

if __name__ == '__main__':
    main()