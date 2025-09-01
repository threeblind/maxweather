import json
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import time
from pathlib import Path

# --- 定数 ---
# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

# --- ファイル定義 ---
AMEDAS_STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
DAILY_TEMP_FILE = DATA_DIR / 'daily_temperatures.json'
EKIDEN_STATE_FILE = DATA_DIR / 'ekiden_state.json'
INTRAMURAL_RANKINGS_FILE = DATA_DIR / 'intramural_rankings.json'
EKIDEN_START_DATE = '2025-09-01' # generate_report.pyと共通

# --- グローバル変数 ---
stations_data = []
ekiden_data = {}

def load_base_data():
    """
    このスクリプトに必要な基本データ（アメダス地点、駅伝チーム情報）を読み込む。
    """
    global stations_data, ekiden_data
    try:
        with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: データファイルが見つかりません。 {e.filename}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        exit(1)

def find_station_by_name(name):
    """地点名から観測所情報を検索"""
    return next((s for s in stations_data if s['name'] == name), None)

def fetch_max_temperature(pref_code, station_code):
    """Yahoo天気から最高気温を取得"""
    url = f"https://weather.yahoo.co.jp/weather/amedas/{pref_code}/{station_code}.html"
    try:
        response = requests.get(url, timeout=15)
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

def update_all_records():
    """
    全チームの全選手（補欠含む）のその日の最終的な最高気温を取得し、
    `daily_temperatures.json` と `intramural_rankings.json` を更新する。
    """
    load_base_data()

    today_str = datetime.now().strftime('%Y-%m-%d')
    all_runners_to_fetch = set()
    for team in ekiden_data['teams']:
        # 選手名とコメントを一緒に扱うように変更
        all_team_members_with_comments = team.get('runners', []) + team.get('substitutes', []) + team.get('substituted_out', [])
        for runner_obj in all_team_members_with_comments:
            if isinstance(runner_obj, dict) and 'name' in runner_obj:
                all_runners_to_fetch.add(runner_obj['name'])
            elif isinstance(runner_obj, str): # 互換性のため
                 all_runners_to_fetch.add(runner_obj)

    fetched_temps_cache = {}
    print(f"全 {len(all_runners_to_fetch)} 選手の最終気温データを取得します...")
    for i, runner_name in enumerate(sorted(list(all_runners_to_fetch))):
        station = find_station_by_name(runner_name)
        if station:
            temp_result = fetch_max_temperature(station['pref_code'], station['code'])
        else:
            temp_result = {'temperature': None, 'error': '地点不明'}
        
        fetched_temps_cache[runner_name] = temp_result
        print(f"  ({i+1}/{len(all_runners_to_fetch)}) {runner_name:<10}: {temp_result.get('temperature', '取得失敗')}")
        time.sleep(0.5) # サーバー負荷軽減のため0.5秒待機

    # --- daily_temperatures.json の更新 ---
    try:
        with open(DAILY_TEMP_FILE, 'r', encoding='utf-8') as f:
            daily_temperatures = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        daily_temperatures = {}
    
    # チームの走行状態を読み込む
    try:
        with open(EKIDEN_STATE_FILE, 'r', encoding='utf-8') as f:
            ekiden_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        ekiden_state = []

    daily_temperatures[today_str] = {}
    for runner_name, result in fetched_temps_cache.items():
        if result.get('temperature') is not None:
            daily_temperatures[today_str][runner_name] = result['temperature']

    # 出力先ディレクトリが存在しない場合は作成
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DAILY_TEMP_FILE, 'w', encoding='utf-8') as f:
        json.dump(daily_temperatures, f, indent=2, ensure_ascii=False)
    print(f"\n✅ 日次気温データを '{DAILY_TEMP_FILE}' に保存しました。")

    # --- intramural_rankings.json の生成 ---
    # チームIDをキーにしたcurrentLegのマップを作成
    team_current_leg_map = {team['id']: team.get('currentLeg', 1) for team in ekiden_state}

    intramural_data = {
        "updateTime": datetime.now().strftime('%Y/%m/%d %H:%M'),
        "teams": []
    }

    for team_data in ekiden_data['teams']:
        # 選手名のみを抽出
        active_runners = [r['name'] for r in team_data.get('runners', []) if 'name' in r]
        substitute_runners = [r['name'] for r in team_data.get('substitutes', []) if 'name' in r]
        substituted_out_runners = [r['name'] for r in team_data.get('substituted_out', []) if 'name' in r]
        current_leg = team_current_leg_map.get(team_data['id'], 1)
        all_team_members = set(active_runners + substitute_runners + substituted_out_runners)
        
        daily_results = []
        for runner_name in all_team_members:
            temp_result = fetched_temps_cache.get(runner_name)
            if temp_result and temp_result.get('temperature') is not None:
                # ステータスを決定 (走行中/走行済/走行前/交代済/補欠)
                status = "補欠" # デフォルト
                if runner_name in substituted_out_runners:
                    status = "交代済"
                elif runner_name in active_runners:
                    runner_leg = active_runners.index(runner_name) + 1
                    if runner_leg < current_leg:
                        status = "走行済"
                    elif runner_leg == current_leg:
                        status = "走行中"
                    else:
                        status = "走行前"

                daily_results.append({
                    "runner_name": runner_name,
                    "distance": temp_result['temperature'],
                    "status": status
                })
        
        daily_results.sort(key=lambda x: x.get('distance', 0), reverse=True)
        intramural_data["teams"].append({
            "id": team_data['id'], "name": team_data['name'],
            "short_name": team_data.get("short_name", team_data['name']),
            "daily_results": daily_results
        })

    # 出力先ディレクトリが存在しない場合は作成
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(INTRAMURAL_RANKINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(intramural_data, f, indent=2, ensure_ascii=False)
    print(f"✅ 学内ランキングデータを '{INTRAMURAL_RANKINGS_FILE}' に保存しました。")

if __name__ == '__main__':
    update_all_records()
    print("\nすべての記録更新処理が完了しました。")
