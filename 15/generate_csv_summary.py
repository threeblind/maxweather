import json
import csv
import os

# --- 定数 ---
EKIDEN_DATA_FILE = 'ekiden_data.json'
INDIVIDUAL_RESULTS_FILE = 'individual_results.json'
RANK_HISTORY_FILE = 'rank_history.json'
LEG_RANK_HISTORY_FILE = 'leg_rank_history.json'
OUTPUT_CSV_FILE = 'ekiden_summary_all_teams.csv'

def get_last_valid_value(data_list):
    """
    リストを逆順に探索し、Noneでない最初の値を返します。
    見つからない場合はNoneを返します。
    """
    if not data_list:
        return None
    for value in reversed(data_list):
        if value is not None:
            return value
    return None

def generate_csv_summary():
    """
    全チームの駅伝結果をまとめたCSVファイルを生成します。
    """
    # 1. 必要なデータを読み込む
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        with open(INDIVIDUAL_RESULTS_FILE, 'r', encoding='utf-8') as f:
            individual_results = json.load(f)
        with open(RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
            rank_history = json.load(f)
        with open(LEG_RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
            leg_rank_history = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: データファイルが見つかりません。 {e.filename}")
        print("CSVを生成するには、すべてのレースデータファイルが必要です。")
        return
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        return

    # 2. データを扱いやすいようにMap形式に変換
    rank_history_map = {team['id']: team for team in rank_history['teams']}
    leg_rank_history_map = {team['id']: team for team in leg_rank_history['teams']}

    # 3. CSVに書き込むデータ行を準備するリスト
    csv_rows = []
    header = [
        'team_id', 'team_name', 'final_rank', 'total_team_distance',
        'leg_number', 'runner_name', 'leg_rank', 'day', 'daily_distance'
    ]
    csv_rows.append(header)

    # 4. 各チームのデータを処理してCSVの行を作成
    for team in ekiden_data['teams']:
        team_id = team['id']
        team_name = team['name']

        # チームの全体成績を取得
        team_final_data = rank_history_map.get(team_id)

        # 履歴にNoneが含まれる場合があるため、Noneでない最後の有効な値を取得する
        ranks_history = team_final_data.get('ranks', []) if team_final_data else []
        last_valid_rank = get_last_valid_value(ranks_history)
        final_rank = last_valid_rank if last_valid_rank is not None else ''

        distances_history = team_final_data.get('distances', []) if team_final_data else []
        last_valid_distance = get_last_valid_value(distances_history)
        total_distance = last_valid_distance if last_valid_distance is not None else 0.0

        # チームの区間通過順位を取得
        team_leg_ranks_data = leg_rank_history_map.get(team_id)
        leg_ranks = team_leg_ranks_data.get('leg_ranks', []) if team_leg_ranks_data else []

        # 区間ごとのループ
        for i, runner_name in enumerate(team['runners']):
            leg_number = i + 1
            leg_rank = leg_ranks[i] if i < len(leg_ranks) else ''

            # 選手個人の日別記録を取得
            runner_data = individual_results.get(runner_name)
            if runner_data and runner_data.get('records'):
                # 日ごとのループ
                for record in runner_data['records']:
                    row = [
                        team_id, team_name, final_rank, f"{total_distance:.1f}",
                        leg_number, runner_name, leg_rank,
                        record.get('day', ''), record.get('distance', '')
                    ]
                    csv_rows.append(row)

    # 5. CSVファイルに書き出し
    try:
        with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerows(csv_rows)
        print(f"CSVファイルの生成が完了しました: {OUTPUT_CSV_FILE}")
    except IOError as e:
        print(f"エラー: CSVファイルへの書き込みに失敗しました: {e}")

if __name__ == '__main__':
    generate_csv_summary()