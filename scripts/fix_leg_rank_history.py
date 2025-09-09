import json
from pathlib import Path

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')

# --- ファイルパス定義 ---
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
RANK_HISTORY_FILE = DATA_DIR / 'rank_history.json'
LEG_RANK_HISTORY_FILE = DATA_DIR / 'leg_rank_history.json'

def fix_leg_rank_history():
    """
    rank_history.json を元に、leg_rank_history.json を再構築します。
    これにより、過去の区間通過順位の記録を修正します。
    """
    print("区間通過順位の履歴ファイル (leg_rank_history.json) の修正を開始します...")

    # --- 1. 必要なデータの読み込み ---
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        with open(RANK_HISTORY_FILE, 'r', encoding='utf-8') as f:
            rank_history = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: 必須ファイルが見つかりません: {e.filename}")
        print(f"ヒント: {RANK_HISTORY_FILE} が存在するか確認してください。")
        return
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        return

    if not rank_history.get("dates"):
        print("情報: rank_history.json に履歴データがないため、処理をスキップします。")
        return

    # --- 2. 新しい区間順位履歴を初期化 ---
    num_legs = len(ekiden_data.get('leg_boundaries', []))
    all_teams_data = ekiden_data.get('teams', [])
    
    # 区間記録連合も考慮に入れる
    try:
        with open(CONFIG_DIR / 'shadow_team.json', 'r', encoding='utf-8') as f:
            shadow_team_data = json.load(f)
        all_teams_data.append(shadow_team_data)
    except FileNotFoundError:
        pass # シャドーチームがなくても問題ない

    new_leg_history = {
        "teams": [
            {"id": t["id"], "name": t["name"], "leg_ranks": [None] * num_legs}
            for t in all_teams_data
        ]
    }
    new_leg_history_map = {team['id']: team for team in new_leg_history['teams']}

    # --- 3. 日々の履歴を元に再計算 ---
    dates = rank_history.get("dates", [])
    rank_history_map = {team['id']: team for team in rank_history.get('teams', [])}
    leg_boundaries = ekiden_data.get('leg_boundaries', [])

    # 各チームについてループ
    for team_id, team_history in rank_history_map.items():
        if team_id not in new_leg_history_map:
            continue

        # 2日目以降のデータをチェック
        for i in range(1, len(dates)):
            prev_dist = team_history["distances"][i - 1]
            today_dist = team_history["distances"][i]
            today_rank = team_history["ranks"][i]

            if prev_dist is None or today_dist is None or today_rank is None:
                continue

            # 各区間境界をチェック
            for leg_index, boundary in enumerate(leg_boundaries):
                # 前日の距離 < 境界 <= 今日の距離 となった最初の日に順位を記録
                if prev_dist < boundary <= today_dist:
                    target_team_history = new_leg_history_map[team_id]
                    # まだその区間の順位が記録されていなければ記録する
                    if target_team_history["leg_ranks"][leg_index] is None:
                        target_team_history["leg_ranks"][leg_index] = today_rank

    # --- 4. 修正したファイルを出力 ---
    try:
        # ユーザーに最終確認
        confirm = input(f"警告: '{LEG_RANK_HISTORY_FILE}' の内容が上書きされます。よろしいですか？ (y/n): ")
        if confirm.lower() != 'y':
            print("処理を中断しました。")
            return

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(LEG_RANK_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_leg_history, f, indent=2, ensure_ascii=False)
        print(f"✅ 修正完了: {LEG_RANK_HISTORY_FILE} を更新しました。")

    except IOError as e:
        print(f"エラー: ファイルへの書き込みに失敗しました: {e}")


if __name__ == '__main__':
    fix_leg_rank_history()
