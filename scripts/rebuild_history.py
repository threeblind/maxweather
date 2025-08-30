import json
import os
from datetime import datetime, timedelta
import shutil
from pathlib import Path

# --- 定数 ---
# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

# 入力ファイル (Source of Truth)
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
DAILY_TEMP_FILE = DATA_DIR / 'daily_temperatures.json'
COURSE_PATH_FILE = DATA_DIR / 'course_path.json'

# 出力/上書きされるファイル
STATE_FILE = LOGS_DIR / 'ekiden_state.json'
INDIVIDUAL_STATE_FILE = DATA_DIR / 'individual_results.json'
RANK_HISTORY_FILE = DATA_DIR / 'rank_history.json'
LEG_RANK_HISTORY_FILE = DATA_DIR / 'leg_rank_history.json'
RUNNER_LOCATIONS_OUTPUT_FILE = DATA_DIR / 'runner_locations.json'

# 設定
EKIDEN_START_DATE = '2025-07-23'

# --- グローバル変数 ---
ekiden_data = {}
daily_temperatures = {}

def load_source_data():
    """再計算の元となるデータを読み込む"""
    global ekiden_data, daily_temperatures
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        with open(DAILY_TEMP_FILE, 'r', encoding='utf-8') as f:
            daily_temperatures = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: データファイルが見つかりません。 {e.filename}")
        print(f"ヒント: {DAILY_TEMP_FILE} は update_all_records.py を実行すると生成されます。")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        exit(1)

def initialize_result_files():
    """再計算のために、すべての結果ファイルを初期化する"""
    print("結果ファイルを初期化しています...")

    # チームの初期状態
    initial_team_state = [
        {
            "id": team["id"], "name": team["name"],
            "totalDistance": 0, "currentLeg": 1, "overallRank": 0, "finishDay": None
        } for team in ekiden_data['teams']
    ]

    # 個人の初期状態
    initial_individual_results = {}
    for team in ekiden_data['teams']:
        # 選手名とコメントを持つオブジェクトのリストに対応
        all_team_members_obj = team.get('runners', []) + team.get('substitutes', [])
        for runner_obj in all_team_members_obj:
            runner_name = runner_obj.get('name')
            if not runner_name:
                continue
            if runner_name not in initial_individual_results:
                initial_individual_results[runner_name] = {
                    "totalDistance": 0,
                    "teamId": team['id'],
                    "records": []
                }

    # 履歴の初期状態
    initial_rank_history = {
        "dates": [],
        "teams": [{"id": t["id"], "name": t["name"], "ranks": [], "distances": []} for t in ekiden_data['teams']]
    }
    initial_leg_rank_history = {
        "teams": [
            {
                "id": t["id"], "name": t["name"],
                "leg_ranks": [None] * len(ekiden_data['leg_boundaries'])
            } for t in ekiden_data['teams']
        ]
    }

    # ディレクトリが存在しない場合は作成
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ファイルに書き込み
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial_team_state, f, indent=2, ensure_ascii=False)
    with open(INDIVIDUAL_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial_individual_results, f, indent=2, ensure_ascii=False)
    with open(RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial_rank_history, f, indent=2, ensure_ascii=False)
    with open(LEG_RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial_leg_rank_history, f, indent=2, ensure_ascii=False)
    with open(RUNNER_LOCATIONS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f, indent=2, ensure_ascii=False)

    print("✅ 初期化完了")
    return initial_team_state, initial_individual_results

def rebuild_history():
    """
    `daily_temperatures.json` を元に、大会初日から最終日まで一日ずつシミュレーションを実行し、
    すべての状態・履歴ファイルを再構築する。
    """
    # --- 準備 ---
    load_source_data()
    
    # ユーザーに最終確認
    confirm = input(f"警告: 以下のファイルが上書きされます:\n"
                    f" - {STATE_FILE}\n"
                    f" - {INDIVIDUAL_STATE_FILE}\n"
                    f" - {RANK_HISTORY_FILE}\n"
                    f" - {LEG_RANK_HISTORY_FILE}\n"
                    f" - {RUNNER_LOCATIONS_OUTPUT_FILE}\n"
                    f"本当に実行しますか？ (y/n): ")
    if confirm.lower() != 'y':
        print("処理を中断しました。")
        return

    current_state, individual_results = initialize_result_files()

    # 日付順にソートしてループ
    sorted_dates = sorted(daily_temperatures.keys())
    start_date_obj = datetime.strptime(EKIDEN_START_DATE, '%Y-%m-%d').date()

    # --- 再計算ループ ---
    print("\n--- 履歴の再計算を開始します ---")
    for date_str in sorted_dates:
        current_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        race_day = (current_date_obj - start_date_obj).days + 1
        print(f"🔄 {race_day}日目 ({date_str}) の記録を計算中...")

        # generate_report.pyから計算ロジックを拝借
        # -----------------------------------------------------------------
        # この日の気温データを取得
        temps_for_today = daily_temperatures[date_str]
        
        # この日の計算結果を格納するリスト
        results_for_today = []
        
        # 前日の状態を保持
        previous_day_state = json.loads(json.dumps(current_state))

        for team_state in current_state:
            team_data = next(t for t in ekiden_data['teams'] if t['id'] == team_state['id'])
            
            finish_day = team_state.get("finishDay")
            is_finished_yesterday = finish_day is not None and finish_day < race_day

            if is_finished_yesterday:
                # 既にゴール済みのチームは、状態をそのまま引き継ぐ
                results_for_today.append({
                    **team_state,
                    "newCurrentLeg": team_state["currentLeg"],
                    "todayDistance": 0.0,
                    "group_id": 1 # 順位確定グループ
                })
                continue

            # --- 走行中または本日ゴールのチーム ---
            runner_index = team_state['currentLeg'] - 1
            runner_name = "ゴール"
            today_distance = 0.0

            if runner_index < len(team_data['runners']):
                # 選手オブジェクトから名前を取得
                runner_name = team_data['runners'][runner_index].get('name')
                # 日々の気温データから今日の距離を取得
                today_distance = temps_for_today.get(runner_name, 0.0)

                if today_distance > 0:
                    runner_info = individual_results.setdefault(runner_name, {"totalDistance": 0, "teamId": team_data['id'], "records": []})
                    # 既に同じ日の記録があれば更新、なければ追加
                    record_for_today = next((r for r in runner_info['records'] if r.get('day') == race_day), None)
                    if record_for_today:
                        record_for_today['distance'] = today_distance
                    else:
                        runner_info['records'].append({"day": race_day, "leg": team_state["currentLeg"], "distance": today_distance})
                    # 合計距離を再計算
                    runner_info['totalDistance'] = round(sum(r['distance'] for r in runner_info['records']), 1)

            new_total_distance = round(team_state['totalDistance'] + today_distance, 1)
            new_current_leg = team_state['currentLeg']
            finish_day_today = finish_day

            # 区間境界を越えたかチェック
            if new_current_leg <= len(ekiden_data['leg_boundaries']):
                boundary = ekiden_data['leg_boundaries'][new_current_leg - 1]
                if new_total_distance >= boundary:
                    new_current_leg += 1
                    # ゴールした瞬間を記録
                    if new_current_leg > len(ekiden_data['leg_boundaries']) and finish_day_today is None:
                        finish_day_today = race_day

            results_for_today.append({
                "id": team_state["id"], "name": team_state["name"], "runner": runner_name,
                "currentLegNumber": team_state["currentLeg"], "newCurrentLeg": new_current_leg,
                "todayDistance": today_distance, "totalDistance": new_total_distance,
                "finishDay": finish_day_today,
                "group_id": 0 # 順位変動グループ
            })

        # --- 順位計算 (generate_report.pyからロジックを拝借) ---
        finished_teams = [r for r in results_for_today if r.get('group_id') == 1]
        running_teams = [r for r in results_for_today if r.get('group_id') == 0]

        final_goal_distance = ekiden_data['leg_boundaries'][-1]
        for team in finished_teams:
            team['finishScore'] = team['finishDay'] - (team['totalDistance'] - final_goal_distance) / 100

        finished_teams.sort(key=lambda x: x.get('finishScore', float('inf')))
        running_teams.sort(key=lambda x: x['totalDistance'], reverse=True)
        
        final_results_for_day = finished_teams + running_teams

        last_key_val, last_rank = None, 0
        for i, r in enumerate(final_results_for_day):
            key_val = r.get('finishScore') if r.get('group_id') == 1 else r.get('totalDistance')
            if key_val != last_key_val:
                last_rank = i + 1
                last_key_val = key_val
            r['overallRank'] = last_rank

        # --- 履歴ファイルと状態ファイルの更新 ---
        # 1. generate_report.pyから必要な関数をインポートまたはコピーしてくる
        from generate_report import update_rank_history, update_leg_rank_history, save_ekiden_state

        # 2. 履歴を更新
        update_rank_history(final_results_for_day, race_day, RANK_HISTORY_FILE)
        update_leg_rank_history(final_results_for_day, previous_day_state, LEG_RANK_HISTORY_FILE, is_commit_mode=True)

        # 3. この日の最終状態を次の日の入力とする
        current_state = [
            {
                "id": s["id"], "name": s["name"], "totalDistance": s["totalDistance"],
                "currentLeg": s["newCurrentLeg"], "overallRank": s["overallRank"],
                "finishDay": s.get("finishDay")
            } for s in final_results_for_day
        ]
        # -----------------------------------------------------------------

    # --- 最終結果の保存 ---
    print("\n--- 全日程の再計算が完了しました ---")
    from generate_report import save_individual_results, calculate_and_save_runner_locations
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(current_state, f, indent=2, ensure_ascii=False)
    save_individual_results(individual_results, INDIVIDUAL_STATE_FILE)
    calculate_and_save_runner_locations(current_state)
    
    print(f"✅ 最終状態を {STATE_FILE} に保存しました。")
    print(f"✅ 個人記録を {INDIVIDUAL_STATE_FILE} に保存しました。")
    print(f"✅ チーム位置情報を {RUNNER_LOCATIONS_OUTPUT_FILE} に保存しました。")
    print("\nすべての処理が正常に完了しました。")

if __name__ == '__main__':
    rebuild_history()