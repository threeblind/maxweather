import json
from pathlib import Path

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
HISTORY_DATA_DIR = Path('history_data')

# --- ファイルパス定義 ---
SHADOW_TEAM_FILE = CONFIG_DIR / 'shadow_team.json'
STATE_FILE = Path('data') / 'ekiden_state.json'
LEG_BEST_RECORDS_FILE = HISTORY_DATA_DIR / 'leg_best_records.json'

# --- 定数 ---
SHADOW_TEAM_ID = 99
SHADOW_TEAM_NAME = "区間記録連合"

def setup_shadow_team():
    """
    config/shadow_team.json に「区間記録連合」チームをセットアップする。
    - leg_best_records.json から各区間の記録保持者を読み込む。
    - shadow_team.json を生成または上書きする。
    """
    print(f"シャドーチーム「{SHADOW_TEAM_NAME}」のセットアップを開始します...")

    # --- 1. 必要なファイルの読み込み ---
    try:
        with open(LEG_BEST_RECORDS_FILE, 'r', encoding='utf-8') as f:
            leg_best_records = json.load(f)
    except FileNotFoundError as e:
        print(f"エラー: 必須ファイルが見つかりません: {e.filename}")
        return
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        return

    # --- 2. シャドーランナーのリストを生成 ---
    shadow_runners = []
    print("各区間の歴代記録保持者を読み込んでいます...")
    for leg_record in sorted(leg_best_records.get('leg_records', []), key=lambda x: x['leg']):
        leg_num = leg_record.get('leg')
        top_records = leg_record.get('top10', [])

        if not leg_num or not top_records:
            continue

        top_record = top_records[0]
        runner_name = top_record.get("runner_name")
        if not runner_name:
            print(f"警告: {leg_num}区の記録保持者名が見つかりません。スキップします。")
            continue

        shadow_runners.append({
            "leg": leg_num,
            "name": runner_name,
            "team_name": top_record.get("team_name"),
            "edition": top_record.get("edition"),
            "record": top_record.get("record")
        })
        edition_str = f"第{top_record.get('edition')}回" if top_record.get('edition') else "(記録大会不明)"
        print(f"  > {leg_num}区: {runner_name} ({top_record.get('team_name')}, {edition_str})")

    # --- 3. 「区間記録連合」チームのデータを作成 ---
    shadow_team_data = {
        "id": SHADOW_TEAM_ID,
        "name": SHADOW_TEAM_NAME,
        "short_name": "区間記録",
        "is_shadow_confederation": True,
        "runners": shadow_runners
    }

    # --- 4. shadow_team.json を保存 ---
    CONFIG_DIR.mkdir(exist_ok=True)
    with open(SHADOW_TEAM_FILE, 'w', encoding='utf-8') as f:
        json.dump(shadow_team_data, f, indent=2, ensure_ascii=False)

    print(f"\nセットアップ完了: {SHADOW_TEAM_FILE} に「{SHADOW_TEAM_NAME}」の定義を保存しました。")

    # --- 5. ekiden_state.json にチームが存在しない場合、安全に初期状態を追加 ---
    add_shadow_team_to_state_if_not_exists(shadow_team_data)


def add_shadow_team_to_state_if_not_exists(shadow_team_data):
    """
    data/ekiden_state.json を確認し、シャドーチームが存在しない場合のみ、
    現在のトップチームの状態に合わせて安全にチームを追加する。
    """
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            ekiden_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"\n情報: '{STATE_FILE}' が見つからないか不正なため、シャドーチームの自動追加はスキップされました。")
        print("ヒント: `generate_report.py --commit` を一度実行すると、状態ファイルが生成されます。")
        return

    shadow_team_id = shadow_team_data.get('id')

    if any(team.get('id') == shadow_team_id for team in ekiden_state):
        print(f"情報: 「{SHADOW_TEAM_NAME}」は既に '{STATE_FILE}' に存在するため、更新は不要です。")
    else:
        print(f"情報: 「{SHADOW_TEAM_NAME}」を '{STATE_FILE}' に安全に追加します...")

        # 現在のトップチームを探し、その状態に同期する
        leader_team = None
        regular_teams = [t for t in ekiden_state if not t.get('is_shadow_confederation') and t.get('id') != shadow_team_id]
        if regular_teams:
            leader_team = max(regular_teams, key=lambda x: x.get('totalDistance', 0))

        initial_distance = leader_team.get('totalDistance', 0.0) if leader_team else 0.0
        initial_leg = leader_team.get('currentLeg', 1) if leader_team else 1
        print(f"情報: トップチームの状態に合わせ、初期位置を {initial_distance:.1f}km (第{initial_leg}区) に設定します。")

        initial_shadow_state = {
            "id": shadow_team_id,
            "name": shadow_team_data.get('name'),
            "totalDistance": initial_distance,
            "currentLeg": initial_leg,
            "overallRank": 0, # この値は generate_report.py 実行時に再計算されます
            "finishDay": None
        }
        ekiden_state.append(initial_shadow_state)
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(ekiden_state, f, indent=2, ensure_ascii=False)
        print(f"完了: 「{SHADOW_TEAM_NAME}」を初期状態で '{STATE_FILE}' に追加しました。")


if __name__ == '__main__':
    setup_shadow_team()
