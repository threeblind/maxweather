import json
import argparse
import os
from pathlib import Path
from datetime import datetime

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

# --- ファイル定義 ---
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
INDIVIDUAL_RESULTS_FILE = DATA_DIR / 'individual_results.json'
SUBSTITUTION_LOG_FILE = LOGS_DIR / 'substitution_log.txt'

def substitute_runner(team_id, old_runner, new_runner):
    """
    ekiden_data.json と individual_results.json を更新して選手を交代させる。
    """
    # --- 1. ekiden_data.json の更新 ---
    try:
        # configディレクトリがなければエラー
        if not CONFIG_DIR.exists():
            print(f"エラー: 設定ディレクトリ '{CONFIG_DIR}' が見つかりません。")
            return False
        with open(EKIDEN_DATA_FILE, 'r+', encoding='utf-8') as f:
            ekiden_data = json.load(f)
            team_to_update = next((t for t in ekiden_data['teams'] if t['id'] == team_id), None)

            if not team_to_update:
                print(f"エラー: チームID {team_id} が見つかりません。")
                return False

            # 交代前の選手がrunnersにいるか確認 (オブジェクトのリストを検索)
            runner_out_obj = next((r for r in team_to_update.get('runners', []) if r.get('name') == old_runner), None)
            if not runner_out_obj:
                print(f"エラー: {team_to_update['name']} の runners に {old_runner} が見つかりません。")
                return False

            # 交代後の選手がsubstitutesにいるか確認
            runner_in_obj = next((r for r in team_to_update.get('substitutes', []) if r.get('name') == new_runner), None)
            if not runner_in_obj:
                print(f"エラー: {team_to_update['name']} の substitutes に {new_runner} が見つかりません。")
                return False

            # runnersリストの選手を交代
            runner_index = team_to_update['runners'].index(runner_out_obj)
            team_to_update['runners'][runner_index] = runner_in_obj

            # substitutesリストから交代で出場する選手を削除
            team_to_update['substitutes'].remove(runner_in_obj)

            # 交代前の選手を記録するリストに追加
            team_to_update.setdefault('substituted_out', []).append(runner_out_obj)
            print(f"情報: {old_runner} を substituted_out リストに追加しました。")

            # ファイルを更新
            f.seek(0)
            json.dump(ekiden_data, f, indent=2, ensure_ascii=False)
            f.truncate()
            print(f"✅ '{EKIDEN_DATA_FILE}' を更新しました: {team_to_update['name']} の {old_runner} -> {new_runner}")

    except FileNotFoundError:
        print(f"エラー: {EKIDEN_DATA_FILE} が見つかりません。")
        return False

    # --- 2. individual_results.json の更新 ---
    try:
        # dataディレクトリがなければ作成
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(INDIVIDUAL_RESULTS_FILE, 'r+', encoding='utf-8') as f:
            individual_results = json.load(f)

            if old_runner in individual_results and individual_results[old_runner].get('records'):
                print(f"⚠️  警告: 交代前の選手 '{old_runner}' には既に記録が存在します。記録の扱いは手動で確認してください。")

            # 新しい選手のエントリを作成し、古い選手のエントリを削除
            if old_runner in individual_results:
                del individual_results[old_runner]

            individual_results[new_runner] = { "totalDistance": 0, "teamId": team_id, "records": [] }

            f.seek(0)
            json.dump(individual_results, f, indent=2, ensure_ascii=False)
            f.truncate()
            print(f"✅ '{INDIVIDUAL_RESULTS_FILE}' を更新しました: {new_runner} のエントリを追加しました。")

    except FileNotFoundError:
        print(f"情報: '{INDIVIDUAL_RESULTS_FILE}' が見つかりませんでした。新規に作成します。")
        individual_results = { new_runner: { "totalDistance": 0, "teamId": team_id, "records": [] } }
        with open(INDIVIDUAL_RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(individual_results, f, indent=2, ensure_ascii=False)
        print(f"✅ '{INDIVIDUAL_RESULTS_FILE}' を新規作成し、{new_runner} のエントリを追加しました。")

    # --- 3. 交代ログの記録 ---
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(SUBSTITUTION_LOG_FILE, 'a', encoding='utf-8') as f:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            log_message = f"{timestamp}: チームID {team_id} ({team_to_update['name']}) - {old_runner} → {new_runner}\n"
            f.write(log_message)
            print(f"✅ 交代ログを '{SUBSTITUTION_LOG_FILE}' に記録しました。")
    except IOError as e:
        print(f"警告: ログファイルへの書き込みに失敗しました: {e}")

    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='駅伝の選手交代を自動化します。')
    parser.add_argument('--team-id', type=int, required=True, help='交代する選手がいるチームのID')
    parser.add_argument('--old', required=True, help='交代前の選手名')
    parser.add_argument('--new', required=True, help='交代後の選手名')
    args = parser.parse_args()

    if substitute_runner(args.team_id, args.old, args.new):
        print("\n選手交代処理が正常に完了しました。")
    else:
        print("\n選手交代処理に失敗しました。")