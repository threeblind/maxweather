import json
import argparse
import os

EKIDEN_DATA_FILE = 'ekiden_data.json'
INDIVIDUAL_RESULTS_FILE = 'individual_results.json'

def substitute_runner(team_id, old_runner, new_runner):
    """
    ekiden_data.json と individual_results.json を更新して選手を交代させる。
    """
    # --- 1. ekiden_data.json の更新 ---
    try:
        with open(EKIDEN_DATA_FILE, 'r+', encoding='utf-8') as f:
            ekiden_data = json.load(f)
            team_to_update = next((t for t in ekiden_data['teams'] if t['id'] == team_id), None)

            if not team_to_update:
                print(f"エラー: チームID {team_id} が見つかりません。")
                return False

            if old_runner not in team_to_update.get('runners', []):
                print(f"エラー: {team_to_update['name']} の runners に {old_runner} が見つかりません。")
                return False

            # runnersリストの選手を交代
            runner_index = team_to_update['runners'].index(old_runner)
            team_to_update['runners'][runner_index] = new_runner

            # substitutesリストから交代で出場する選手を削除
            if new_runner in team_to_update.get('substitutes', []):
                team_to_update['substitutes'].remove(new_runner)

            # 交代前の選手を記録するリストに追加
            team_to_update.setdefault('substituted_out', []).append(old_runner)
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
        print(f"エラー: {INDIVIDUAL_RESULTS_FILE} が見つかりません。")
        return False

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