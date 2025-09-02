import json
import os
import glob
from pathlib import Path
import re

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
HISTORY_DATA_DIR = Path('history_data')

# --- 入力ファイル定義 ---
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
AMEDAS_STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
LEG_AWARD_HISTORY_FILE = HISTORY_DATA_DIR / 'leg_award_history.json'

OUTPUT_FILE = CONFIG_DIR / 'player_profiles.json'

CURRENT_EDITION = 16

# 都道府県コードと都道府県名のマッピング
PREFECTURE_MAP = {
    '1': '北海道', '2': '青森県', '3': '岩手県', '4': '宮城県', '5': '秋田県',
    '6': '山形県', '7': '福島県', '8': '茨城県', '9': '栃木県', '10': '群馬県',
    '11': '埼玉県', '12': '千葉県', '13': '東京都', '14': '神奈川県', '15': '新潟県',
    '16': '富山県', '17': '石川県', '18': '福井県', '19': '山梨県', '20': '長野県',
    '21': '岐阜県', '22': '静岡県', '23': '愛知県', '24': '三重県', '25': '滋賀県',
    '26': '京都府', '27': '大阪府', '28': '兵庫県', '29': '奈良県', '30': '和歌山県',
    '31': '鳥取県', '32': '島根県', '33': '岡山県', '34': '広島県', '35': '山口県',
    '36': '徳島県', '37': '香川県', '38': '愛媛県', '39': '高知県', '40': '福岡県',
    '41': '佐賀県', '42': '長崎県', '43': '熊本県', '44': '大分県', '45': '宮崎県',
    '46': '鹿児島県', '47': '沖縄県'
}

def load_json(file_path, default=None):
    """JSONファイルを読み込む。ファイルがない場合はデフォルト値を返す。"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"情報: '{file_path}' が見つからないか、形式が不正です。スキップします。")
        return default

def get_prefecture_name(pref_code):
    """都道府県コードから都道府県名を取得する。北海道の特殊コードにも対応。"""
    if not pref_code:
        return '未設定'
    # '1a' -> '1' のように、pref_codeからアルファベットを除去して数字部分だけを取得
    code = re.sub(r'[a-zA-Z]', '', str(pref_code))
    return PREFECTURE_MAP.get(code, '不明')

def main():
    """選手名鑑用のJSONデータを生成するメイン関数"""
    print("選手名鑑データ (player_profiles.json) の生成を開始します...")

    # --- 1. データの読み込み ---
    ekiden_data = load_json(EKIDEN_DATA_FILE, {})
    amedas_stations = load_json(AMEDAS_STATIONS_FILE, [])
    leg_award_history = load_json(LEG_AWARD_HISTORY_FILE, [])

    if not ekiden_data or not amedas_stations:
        print("エラー: 'ekiden_data.json' または 'amedas_stations.json' が読み込めませんでした。処理を中断します。")
        return

    # --- 2. データの前処理 ---
    # 地点名で検索しやすいように辞書に変換
    stations_map = {s['name']: s for s in amedas_stations}
    
    # 選手名で区間賞履歴を検索しやすいように辞書に変換
    personal_best_map = {}
    for edition_data in leg_award_history:
        for award in edition_data.get('awards', []):
            runner_name = award.get('runner_name')
            if runner_name:
                if runner_name not in personal_best_map:
                    personal_best_map[runner_name] = []
                
                # 必要な情報だけを抽出して追加
                personal_best_map[runner_name].append({
                    "edition": edition_data.get('edition'),
                    "leg": award.get('leg'),
                    "record": award.get('record'),
                    "team_name_at_the_time": award.get('team_name'),
                    "notes": award.get('notes', [])
                })

    # 大会ごとの個人記録データを読み込む
    performance_data = {}
    # 過去大会の記録 (例: '15/individual_results.json')
    past_edition_dirs = glob.glob('[0-9]*/') # '15/' のようなディレクトリを探す
    for dir_path in past_edition_dirs:
        edition = Path(dir_path).name.replace('/', '')
        past_results_file = Path(dir_path) / 'individual_results.json'
        past_results = load_json(past_results_file)
        if past_results:
            performance_data[edition] = past_results

    # --- 3. 大会ごと・区間ごとの全記録を収集し、順位計算の準備 ---
    all_leg_performances = {} # {edition: {leg: [dist1, dist2, ...]}}
    for edition, results in performance_data.items():
        all_leg_performances[edition] = {}
        for runner_name, runner_data in results.items():
            for record in runner_data.get('records', []):
                leg = record.get('leg')
                distance = record.get('distance')
                if leg and distance is not None:
                    if leg not in all_leg_performances[edition]:
                        all_leg_performances[edition][leg] = []
                    all_leg_performances[edition][leg].append(distance)

    # 各区間の記録を降順（距離が大きい方が上位）にソート
    for edition, legs in all_leg_performances.items():
        for leg, distances in legs.items():
            distances.sort(reverse=True)

    # --- 3.5. 大会ごと・区間ごとの「選手別平均走行距離」ランキングを作成 ---
    leg_average_rankings = {} # {edition: {leg: [{'runner_name': str, 'avg_dist': float}, ...]}}
    for edition, results in performance_data.items():
        leg_average_rankings[edition] = {}
        # まず、選手ごと・区間ごとに走行距離を集計
        runner_leg_stats = {} # {runner_name: {leg: [dist1, dist2, ...]}}
        for runner_name, runner_data in results.items():
            runner_leg_stats[runner_name] = {}
            for record in runner_data.get('records', []):
                leg = record.get('leg')
                distance = record.get('distance')
                if leg and distance is not None:
                    if leg not in runner_leg_stats[runner_name]:
                        runner_leg_stats[runner_name][leg] = []
                    runner_leg_stats[runner_name][leg].append(distance)

        # 次に、区間ごとに選手とその平均距離をリスト化
        leg_performances_for_ranking = {}
        for runner_name, leg_data in runner_leg_stats.items():
            for leg, distances in leg_data.items():
                if not distances: continue
                avg_dist = sum(distances) / len(distances)
                if leg not in leg_performances_for_ranking:
                    leg_performances_for_ranking[leg] = []
                leg_performances_for_ranking[leg].append({'runner_name': runner_name, 'avg_dist': avg_dist})
        
        for leg, performances in leg_performances_for_ranking.items():
            performances.sort(key=lambda x: x['avg_dist'], reverse=True)
            leg_average_rankings[edition][leg] = performances

    # --- 4. 選手プロファイルの生成 ---
    player_profiles = {}
    all_teams = ekiden_data.get('teams', [])

    for team in all_teams:
        team_id = team.get('id')
        team_name = team.get('name')

        # 選手名とコメントを一緒に扱うように変更
        all_runners_with_comments = team.get('runners', []) + team.get('substitutes', [])

        # 選手名でコメントを引けるように辞書を作成
        runner_comment_map = {runner.get('name'): runner.get('comment', '') for runner in all_runners_with_comments if runner.get('name')}

        # 選手名のセットを作成（重複除外）
        all_runner_names = set(runner_comment_map.keys())

        for runner_name in all_runner_names:

            station_info = stations_map.get(runner_name)
            if not station_info:
                print(f"警告: 選手 '{runner_name}' のアメダス情報が見つかりません。スキップします。")
                continue

            # 都道府県名を取得
            prefecture_name = get_prefecture_name(station_info.get('pref_code'))

            # 基本情報の構築
            profile = {
                "name": runner_name,
                "code": station_info.get('code'),
                "prefecture": prefecture_name,
                "team_id": team_id,
                "team_name": team_name,
                "image_url": f"amedas/jpg/{station_info.get('code')}.jpg",
                "address": station_info.get('address'),
                "start_date": station_info.get('start_date'),
                "elevation": station_info.get('elevation'),
                # チームの紹介文ではなく、選手個人のコメントを使用
                "comment": runner_comment_map.get(runner_name, '')
            }

            # 大会ごとのパフォーマンス情報の構築
            profile['performance'] = {}
            for edition, results in performance_data.items():
                runner_perf = results.get(runner_name)
                if runner_perf and runner_perf.get('records'):
                    records = runner_perf.get('records', []) # オリジナルのrecordsをコピーして変更

                    # --- 区間順位を計算して records に追加 ---
                    for record in records:
                        leg = record.get('leg')
                        distance = record.get('distance')
                        if leg and distance is not None and edition in all_leg_performances and leg in all_leg_performances[edition]:
                            leg_distances = all_leg_performances[edition][leg]
                            # 同順位を考慮した順位計算 (list.indexは最初に見つかったインデックスを返す)
                            try:
                                rank = leg_distances.index(distance) + 1
                                record['legRank'] = rank
                            except ValueError:
                                record['legRank'] = None # 万が一見つからない場合

                    total_distance = runner_perf.get('totalDistance', 0)
                    average_distance = total_distance / len(records) if records else 0
                    legs_run = sorted(list(set([r.get('leg') for r in records if r.get('leg') is not None])))
                    
                    # 新しいロジックでサマリー用の区間順位を計算
                    summary_leg_ranks = []
                    for leg in legs_run:
                        if edition in leg_average_rankings and leg in leg_average_rankings[edition]:
                            ranking_list = leg_average_rankings[edition][leg]
                            try:
                                my_avg_dist = next(p['avg_dist'] for p in ranking_list if p['runner_name'] == runner_name)
                                rank = next(i for i, p in enumerate(ranking_list) if p['avg_dist'] == my_avg_dist) + 1
                                summary_leg_ranks.append(rank)
                            except StopIteration:
                                pass # 自分の記録が見つからない場合は何もしない
                    best_leg_rank = min(summary_leg_ranks) if summary_leg_ranks else None

                    profile['performance'][edition] = {
                        "summary": {
                            "total_distance": round(total_distance, 1),
                            "average_distance": round(average_distance, 3),
                            "best_leg_rank": best_leg_rank,
                            "legs_run": legs_run
                        },
                        "records": records
                    }

            # 保持区間記録（自己ベスト）の構築
            profile['personal_best'] = personal_best_map.get(runner_name, [])

            player_profiles[runner_name] = profile

    # --- 4. ファイル出力 ---
    try:
        # 出力先ディレクトリが存在しない場合は作成
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(player_profiles, f, indent=2, ensure_ascii=False)
        print(f"✅ 選手名鑑データ (全 {len(player_profiles)} 件) を '{OUTPUT_FILE}' に保存しました。")
    except IOError as e:
        print(f"エラー: ファイルへの書き込みに失敗しました: {e}")

if __name__ == '__main__':
    main()
