import json
import csv
import os

# --- 定数 ---
EKIDEN_DATA_FILE = 'ekiden_data.json'
INDIVIDUAL_RESULTS_FILE = 'individual_results.json'
RANK_HISTORY_FILE = 'rank_history.json'
LEG_RANK_HISTORY_FILE = 'leg_rank_history.json'
OUTPUT_CSV_FILE = 'ekiden_summary_all_teams.csv'

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

        # 履歴の最後の値がNoneの場合があるため、取得後にNoneチェックを行う
        last_rank_val = team_final_data['ranks'][-1] if team_final_data and team_final_data.get('ranks') else None
        final_rank = last_rank_val if last_rank_val is not None else ''

        last_dist_val = team_final_data['distances'][-1] if team_final_data and team_final_data.get('distances') else None
        total_distance = last_dist_val if last_dist_val is not None else 0.0

        # チームの区間通過順位を取得
        team_leg_ranks_data = leg_rank_history_map.get(team_id)
        leg_ranks = team_leg_ranks_data.get('leg_ranks', [])

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