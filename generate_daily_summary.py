import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from bs4 import BeautifulSoup
import shutil
import unicodedata
import re

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

# --- 定数 ---
REALTIME_REPORT_FILE = DATA_DIR / 'realtime_report.json'
MANAGER_COMMENTS_FILE = DATA_DIR / 'manager_comments.json'
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
RANK_HISTORY_FILE = DATA_DIR / 'rank_history.json'
OUTPUT_FILE = DATA_DIR / 'daily_summary.json'
PREVIOUS_SUMMARY_FILE = LOGS_DIR / 'daily_summary_previous.json'

# --- テキスト整形ヘルパー関数 ---

def get_east_asian_width_count(text):
    """全角文字を2、半角文字を1として文字幅をカウント"""
    return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in str(text))

def pad_str(text, length, align='left', char=' '):
    """指定した文字幅になるように文字列をパディング"""
    text_str = str(text)
    padding_size = length - get_east_asian_width_count(text_str)
    if padding_size < 0:
        return text_str
    
    if align == 'right':
        return (char * padding_size) + text_str
    else: # left
        return text_str + (char * padding_size)

# --- データ準備ヘルパー関数 ---

def load_all_data():
    """解説記事の生成に必要なJSONファイルをすべて読み込む。"""
    data = {}
    files_to_load = {
        'realtime_report': REALTIME_REPORT_FILE,
        'manager_comments': MANAGER_COMMENTS_FILE,
        'ekiden_data': EKIDEN_DATA_FILE,
        'rank_history': RANK_HISTORY_FILE,
    }
    try:
        for key, file_path in files_to_load.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                data[key] = json.load(f)
    except FileNotFoundError as e:
        if key != 'manager_comments':
            print(f"エラー: 必須データファイル '{e.filename}' が見つかりません。")
            exit(1)
        else:
            print(f"情報: {e.filename} が見つからないため、監督コメントはスキップされます。")
            data[key] = []
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        exit(1)
    return data

def format_ranking_table(report_data):
    """realtime_report.jsonのデータから整形されたテキストテーブルを生成する"""
    table_lines = []
    teams = report_data.get('teams', [])
    if not teams:
        return "表示するチームデータがありません。"

    top_distance = teams[0]['totalDistance'] if teams else 0

    header = (
        f"{pad_str('順位', 4)} "
        f"{pad_str('大学名', 12)} "
        f"{pad_str('現在走者', 10)} "
        f"{pad_str('本日距離(順位)', 16)} "
        f"{pad_str('総合距離', 10)} "
        f"{pad_str('トップ差', 10)} "
        f"{pad_str('順位変動(前日)', 16)} "
        f"{pad_str('次走者', 10)}"
    )
    table_lines.append(header)

    for team in teams:
        rank_str = pad_str(str(team.get('overallRank', '')), 4)
        name_str = pad_str(team.get('name', ''), 12)
        runner_str = pad_str(team.get('runner', ''), 10)
        
        today_dist_str = f"{team.get('todayDistance', 0.0):.1f}km ({team.get('todayRank', '')})"
        today_dist_str = pad_str(today_dist_str, 16)
        
        total_dist_str = pad_str(f"{team.get('totalDistance', 0.0):.1f}km", 10, align='right')
        
        gap = top_distance - team.get('totalDistance', 0.0)
        gap_str = '----' if team.get('overallRank') == 1 else f"-{gap:.1f}km"
        gap_str = pad_str(gap_str, 10, align='right')

        prev_rank = team.get('previousRank', 0)
        rank_change_str = f"ー (－)" if prev_rank == 0 else f"ー ({prev_rank})"
        rank_change_str = pad_str(rank_change_str, 16)

        next_runner_str = pad_str(team.get('nextRunner', ''), 10)

        line = f"{rank_str} {name_str} {runner_str} {today_dist_str} {total_dist_str} {gap_str} {rank_change_str} {next_runner_str}"
        table_lines.append(line)
    
    return "\n".join(table_lines)

def prepare_manager_comments(manager_comments_data, num_comments=3):
    """監督コメントをプロンプト用に整形する。"""
    if not manager_comments_data:
        return []

    now = datetime.now()
    recent_comments = []
    
    for comment in manager_comments_data:
        if len(recent_comments) >= num_comments:
            break
        try:
            post_time = datetime.fromisoformat(comment['timestamp'])
            if post_time < now - timedelta(days=1, hours=5):
                continue

            soup = BeautifulSoup(comment['content_html'], 'html.parser')
            for a in soup.find_all('a', class_='reply_link'):
                a.decompose()
            clean_text = soup.get_text(separator=' ', strip=True)
            
            if len(clean_text) > 100:
                clean_text = clean_text[:100] + "..."
            
            if "ありがとうございました" in clean_text or "お世話になりました" in clean_text:
                continue

            recent_comments.append(f"- {comment['official_name']}: 「{clean_text}」")
        except (ValueError, TypeError):
            continue
    
    return recent_comments

def format_relay_info(realtime_data, ekiden_data, rank_history):
    """本日タスキリレーが発生したチームの情報をリストで返す"""
    relay_infos = []
    leg_boundaries = ekiden_data.get('leg_boundaries', [])
    
    if not rank_history or not rank_history.get('dates') or len(rank_history['dates']) < 2:
        return []
        
    last_day_index = len(rank_history['dates']) - 2
    
    yesterday_distances = {}
    for team_history in rank_history.get('teams', []):
        if len(team_history.get('distances', [])) > last_day_index:
            yesterday_distances[team_history['id']] = team_history['distances'][last_day_index]

    for team_state in realtime_data.get('teams', []):
        team_id = team_state.get('id')
        yesterday_dist = yesterday_distances.get(team_id, 0.0)
        today_dist = team_state.get('totalDistance', 0.0)

        for i, boundary in enumerate(leg_boundaries):
            if yesterday_dist < boundary <= today_dist:
                from_leg = i + 1
                to_leg = i + 2
                next_runner = team_state.get('nextRunner', '次の走者').replace(str(to_leg), '')
                relay_infos.append(f"- {team_state['name']}が{from_leg}区を走りきり、{to_leg}区・{next_runner}選手へタスキを繋ぎました！")
    return relay_infos

def format_article_with_markdown(article_text, ekiden_data):
    """
    生成された記事テキストにMarkdownの太字を追加する。
    - 見出し (■で始まる行)
    - 大学名
    - 「選手名+選手」
    """
    # 1. 見出しを太字にする
    # 行頭が■で始まる行全体を太字にする
    article_text = re.sub(r'^(■.*)$', r'**\1**', article_text, flags=re.MULTILINE)

    # 2. 大学名と選手名を個別にリストアップ
    university_names = set()
    player_names = set()
    for team in ekiden_data.get('teams', []):
        university_names.add(team['name'])
        player_names.update(team.get('runners', []))
        player_names.update(team.get('substitutes', []))
        player_names.update(team.get('substituted_out', [])) # 交代済みの選手も対象に

    # 選手名から括弧部分を除いた名前も追加 (例: 「川内（鹿児島）」から「川内」)
    plain_player_names = {re.sub(r'（.+）', '', name).strip() for name in player_names}
    player_names.update(plain_player_names)

    # 3. 大学名を太字に置換
    # 長い名前から順にマッチさせることで、部分的な名前（例：「日本」vs「日本大学」）の誤マッチを防ぐ
    sorted_uni_names = sorted(list(university_names), key=len, reverse=True)
    for name in sorted_uni_names:
        # 既に太字になっていない大学名のみを対象にする
        article_text = re.sub(f'(?<!\\*\\*){re.escape(name)}(?!\\*\\*)', f'**{name}**', article_text)

    # 4. 「選手名+選手」を太字に置換
    # 長い名前から順にマッチさせる
    sorted_player_names = sorted(list(player_names), key=len, reverse=True)
    for name in sorted_player_names:
        if not name: continue # 空文字列はスキップ
        # 「〇〇選手」というパターンを探して、`**〇〇選手**` に置換する
        # 選手名の前の数字(区間番号)もマッチさせ、置換時に削除する
        # パターン: (太字でない) (数字が0個以上) (選手名+選手) (太字でない)
        # 置換: **選手名+選手**
        # `\d*` で選手名の前の数字にマッチさせ、キャプチャグループ `({re.escape(name)}選手)` で選手名部分だけを捉える。
        # 置換文字列 `r'**\1**'` でキャプチャした選手名部分のみを太字にする。
        article_text = re.sub(f'(?<!\\*\\*)\\d*({re.escape(name)}選手)(?!\\*\\*)', r'**\1**', article_text)

    return article_text

# --- メイン処理 ---

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝の1日の総括記事を生成します。')
    parser.add_argument('--dry-run', action='store_true', help='Gemini APIを呼び出さずにプロンプトのデバッグ表示のみ行います。')
    args = parser.parse_args()

    # --- 以前のサマリーをバックアップ・読み込み ---
    previous_summary_data = None
    if os.path.exists(OUTPUT_FILE):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy(OUTPUT_FILE, PREVIOUS_SUMMARY_FILE)
        print(f"情報: 以前のサマリーを '{PREVIOUS_SUMMARY_FILE}' にバックアップしました。")
        try:
            with open(PREVIOUS_SUMMARY_FILE, 'r', encoding='utf-8') as f:
                previous_summary_data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"警告: {PREVIOUS_SUMMARY_FILE} の読み込みに失敗しました。")
            previous_summary_data = None

    print("日次振り返り解説の生成を開始します...")

    load_dotenv()


    if not args.dry_run:
        if "GEMINI_API_KEY" not in os.environ:
            print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。")
            exit(1)
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

    all_data = load_all_data()
    realtime_data = all_data.get('realtime_report', {})
    manager_comments = prepare_manager_comments(all_data.get('manager_comments', []))
    relay_infos = format_relay_info(realtime_data, all_data['ekiden_data'], all_data['rank_history'])
    
    race_day = realtime_data.get('raceDay', 'N/A')
    ranking_table_text = format_ranking_table(realtime_data)
    
    # --- プロンプト用に昨日の記事全体を準備 ---
    previous_article_for_prompt = []
    if previous_summary_data and previous_summary_data.get('article'):
        previous_article_text = previous_summary_data['article']
        # Markdownの太字(**)を削除して、AIがテキストとして認識しやすくする
        cleaned_previous_article = previous_article_text.replace('**', '')
        
        previous_article_for_prompt.extend([
            "\n## 【昨日のあなたの解説記事】",
            "あなたは昨日、以下の解説記事を執筆しました。この内容を踏まえ、今日のレースで状況がどう変化したか、あなたの視点で自由に解説してください。",
            "---",
            cleaned_previous_article,
            "---"
        ])

    prompt_parts = [
        "このプロジェクトは、「高温大学駅伝」という架空の駅伝イベントです。最大の特徴は、各選手の走行距離を、その選手が担当するアメダス観測地点の最高気温に見立ててシミュレーションしている点です。",
        "あなたは、連日熱戦が繰り広げられる「第15回 全国大学対抗高温駅伝」の専属スポーツ解説者です。",
        "今日のレースのハイライトを、毎日速報を楽しみにしているファンのために、情熱的でドラマチックな総括記事として生成してください。",
        "以下の【本日のレース状況】、【昨日のあなたの解説記事】、【昨晩の監督コメント】を元に、今日のレースで起きた最も注目すべき展開を深掘りしてください。",
        "なおすべての基本は総合順位です。本日の総合順位に従って言及していってください"
        "各大学の選手名と、その選手が本日走った距離には必ず触れること。言及がない記事はNGとみなします。"
        "【本日の主なタスキリレー】の下に大学名が入っている場合にのみ次走者に言及してください。"
        "",
        "## 記事執筆ルール",
        "- **冒頭**: 今日のレース展開を象徴する熱いキャッチコピー風タイトルを必ず入れること。",
        "- **見出し構成**: 最低5本と、最後に「■ 解説者の熱い総括」を必ず入れること。見出しはレース展開に応じて柔軟に設定すること。",
        "  - **見出しのヒント（これらはあくまで候補であり、展開に合わせて自由に設定してください）**:",
        "    - **首位攻防戦**: 1位と2位が競っている場合。",
        "    - **独走態勢**: 1位が大きく抜け出している場合。",
        "    - **中盤の混戦**: 差が僅差の大学群がある場合。",
        "    - **シード権争い**: 10位前後のボーダーラインで激しい戦いがある場合。",
        "    - **下位の奮闘**: 10位以下のチームで活躍した選手は積極的に言及、それ以外の選手も距離を淡々と記載するなどとにかく全員登場させること",
        "    - **特殊事象**: 39.0km以上の選手が出た場合や、逆に28.0km未満で苦しむ選手が出た場合など。",
        "    - **全選手の言及**: 上の条件に入らない選手がいた場合にはその他の選手動向などして大学、選手名、距離名をただ書くだけでもよい",
        "  - **言葉選びの注意**: 順位差が大きい場合は「攻防」「混戦」ではなく、「独走」「単独走行」など、展開に即した言葉を選ぶこと。",
        "- **本文構成**:",
        "  - **必須条件1**: 各大学の選手名と、その選手が本日走った距離には必ず触れること。言及がない記事はNGとみなします。",
        "  - **必須条件2**: 記事の中心は総合順位です。総合順位に従って記載してください。選手の当日走った距離も第二の重要な要素です",
        "  - **必須条件3**: 【本日の主なタスキリレー】の下に大学名が入っている場合にのみ次走者に言及してください。",
         "  - **文字数**: 上位争いや注目の展開に関わる大学は長め（80文字程度）、それ以外の大学は50文字程度で記述すること。",
        "  - **特殊事象の記述**: 高温・低温、記録更新、注目すべき監督コメントなどがあれば、本文のどこかに盛り込むこと。",
        "- **総括**:",
        "  - 最後に「■ 解説者の熱い総括」を必ず入れること。",
        "  - 今日のレース全体を振り返りつつ、次戦への期待やファンへの呼びかけで熱く締めくくること。",
        "- **禁止事項**: 「高温大学駅伝のルールは～」といった、基本的なルールの説明は絶対に含めないこと。読者はルールを熟知している前提で執筆すること。また、【昨晩の監督コメント】に記載されていない、架空の監督コメントは一切生成しないこと。",
        "---",
        "## 【本日のレース状況】",
        f"- 大会日: {race_day}日目",
        "- 本日の総合順位:",
        ranking_table_text,
    ]

    if relay_infos:
        prompt_parts.append("\n## 【本日の主なタスキリレー】")
        prompt_parts.extend(relay_infos)

    if previous_article_for_prompt:
        prompt_parts.extend(previous_article_for_prompt)

    if manager_comments:
        prompt_parts.append("\n## 【昨晩の監督コメント】")
        prompt_parts.extend(manager_comments)

    prompt_parts.append("---")
    prompt_parts.append("解説記事:")
    prompt = "\n".join(prompt_parts)

    print("------------------------------------")
    print("Geminiへの統合プロンプト:")
    print(prompt)
    print("------------------------------------")
        
    if args.dry_run:
        print("\n--dry-runモードのため、ファイルへの書き込みは行わずに終了します。")
        return

    try:
        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        response = model.generate_content(prompt)
        raw_article_text = response.text.strip()
        
        # 記事をMarkdownでフォーマットする
        print("記事をMarkdownでフォーマットしています...")
        article_text = format_article_with_markdown(raw_article_text, all_data['ekiden_data'])
        print("✅ Geminiによる解説記事の生成に成功しました。")
    except Exception as e:
        print(f"❌ Gemini API呼び出し中にエラーが発生しました: {e}")
        article_text = "本日の解説記事は、システムの問題により生成できませんでした。ご了承ください。"

    output_data = {
        "date": realtime_data.get('updateTime', datetime.now().strftime('%Y/%m/%d %H:%M')).split(' ')[0],
        "article": article_text
    }
    
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"✅ 日次振り返り解説を '{OUTPUT_FILE}' に保存しました。")
    except IOError as e:
        print(f"エラー: ファイルへの書き込みに失敗しました: {e}")

if __name__ == '__main__':
    main()
