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
        # オブジェクトのリストから 'name' キーの値を取得して更新する
        player_names.update(r.get('name') for r in team.get('runners', []) if isinstance(r, dict) and r.get('name'))
        player_names.update(s.get('name') for s in team.get('substitutes', []) if isinstance(s, dict) and s.get('name'))
        # substituted_out もオブジェクトのリストとして処理
        player_names.update(so.get('name') for so in team.get('substituted_out', []) if isinstance(so, dict) and so.get('name'))

    # 選手名から括弧部分を除いた名前も追加 (例: 「川内（鹿児島）」から「川内」)
    # nameがNoneになる可能性を考慮
    plain_player_names = {re.sub(r'（.+）', '', name).strip() for name in player_names if name}
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
    
    # --- 先頭チームの現在区間を取得し、レース状況サマリーを作成 ---
    race_status_summary = "レース集計中"
    if realtime_data.get('teams'):
        top_team = realtime_data['teams'][0]
        # チームがゴールしているかチェック
        if top_team.get('runner') == 'ゴール':
            race_status_summary = "トップチームはゴールしました"
        else:
            leg = top_team.get('currentLeg', 'N/A')
            race_status_summary = f"トップは第{leg}区を走行中"

    

    prompt_parts = [
        "あなたは、長年にわたり「全国大学対抗高温駅伝」を追い続けてきた、日本で唯一の専門スポーツ解説者です。あなたの解説は、単なる事実の羅列ではなく、レースの裏側にあるドラマや選手の想いを描き出し、多くのファンを熱狂させてきました。これから、その深い知見と情熱を込めて、本日のレースを総括する解説記事を執筆していただきます。",
        "",
        "# 大会設定資料（あなたの知識ベース）",
        "以下の情報は、あなたが解説する上での基礎知識です。記事内でこれらのルールを直接説明する必要はありませんが、この設定を完全に理解した上で、物語を紡いでください。",
        "",
        "## 大会概要",
        "- **正式名称**: 第15回 全国大学対抗高温駅伝",
        "- **スタート日**: 2025年7月23日",
        "- **コース**: (旧)気象庁庁舎前(東京) ～ 下関駅前(山口) 全10区間 1055km",
        "",
        "## 基本ルール: 走行距離と順位",
        "- **走行距離 = 最高気温**: 各選手が1日に進む距離(km)は、その選手に割り当てられたアメダス観測地点の「最高気温(℃)」と等しくなります。35.0℃なら35.0km進みます。",
        "- **総合順位の決定**: チームの総合順位は、大会初日からの「総走行距離」の合計によって決まります。より長く、より遠くへ進んだチームが上位となります。",
        "- **タスキリレー**: チームの総走行距離が下記の区間境界を越えると、次の区間の選手にタスキが渡ります。",
        "",
        "## 区間構成 (区間距離 / 累計距離)",
        "- 第１区: 100km / 100km",
        "- 第２区: 110km / 210km",
        "- 第３区: 100km / 310km",
        "- 第４区:  89km / 399km",
        "- 第５区: 123km / 522km",
        "- 第６区: 117km / 639km",
        "- 第７区:  96km / 735km",
        "- 第８区: 106km / 841km",
        "- 第９区: 101km / 942km",
        "- 第10区: 113km / 1055km",
        "",
        "## チーム編成と特別ルール",
        "- **チーム編成**: 各大学は、指定された都道府県のアメダス観測地点から選手10名と補欠選手を選抜してチームを構成します。",
        "- **学連選抜**: 全大学のエントリーから漏れた有力地点の選手で構成される、夢の混成チームです。その日限りの結束力で強豪校に挑みます。",
        "- **シード権**: 総合10位以内に入ったチームは、次年度大会のシード権を獲得します。終盤の熾烈なシード権争いは、この駅伝の大きな見どころの一つです。",
        "",
        "# あなたの役割（ペルソナ）",
        "あなたは、この駅伝の生き字引です。ファンはあなたの解説で、レースの奥深さを知ることを楽しみにしています。",
        "- **物語の語り部**: あなたの仕事は、順位や数字の裏にある「物語」を紡ぎ出すことです。選手の背景、大学間のライバル関係、監督の采配、過去大会からの因縁などを踏まえ、読者の感情に訴えかける記事を書いてください。",
        "- **情熱的なファン代表**: 選手たちの奮闘を称え、苦しむ選手には寄り添い、ファンと一体となって大会を盛り上げる、熱い視点を持ってください。",
        "- **データ分析官**: 提供される【本日のレース状況】や【昨晩の監督コメント】を鋭く分析し、そのデータが何を意味するのかを分かりやすく解説してください。",
        "",
        "# 記事執筆のマスタープラン",
        "以下の構成と思考プロセスに従って、最高の記事を生成してください。",
        "## 1. 全体像の把握とヘッドライン作成",
        "- **今日のテーマは何か？**: 提供された全データに目を通し、「首位の独走か、それとも熾烈な2位争いか？」「シード権争いが激化した日か？」「記録的な酷暑で波乱が起きた日か？」など、その日を象徴するテーマを見つけ出します。",
        "- **心を掴むタイトル**: 見つけ出したテーマを元に、読者が思わず読みたくなるような、ドラマチックなタイトルを付けてください。",
        "",
        "## 2. 見出しによるストーリー設計",
        "- **記事の骨子**: 最低5つの見出しと、最後の「■ 解説者の熱い総括」で記事の骨格を作ります。見出しは、今日の物語を伝えるための章立てです。",
        "- **見出しの具体例**: 以下のような視点で、レース展開に合わせた魅力的な見出しを立ててください。",
        "  - **首位争い**: 「王者〇〇大、王座死守！」「〇〇大、執念の猛追！」",
        "  - **中位争い**: 「中位グループは大混戦！」※4位から10位ぐらいまでは接戦になることが多い",
        "  - **個人の輝き**: 「〇〇（選手名）、驚異の40km超え！チームを救うエースの走り」※39km以上の個人を讃えて欲しい",
        "  - **波乱・逆境**: 「強豪〇〇大、まさかの失速」「〇〇（選手名）、酷暑に散る。しかし、その襷は繋がった」",
        "  - **伏兵の台頭**: 「ノーマークからの下克上！〇〇大がジャンプアップ！」",
        "",
        "## 3. データに基づく本文執筆",
        "- **必須要素**: 総合順位が全ての本文の出発です、あわせて各大学の「選手名」と「その日の走行距離」には必ず触れてください。これが記事の根幹です。",
        "- **順位と距離の描写**: 総合順位を基本に解説を進めます。トップとの差、前日からの順位変動を具体的に記述し、レースの動きを伝えてください。",
        "- **監督コメントの活用**: 【昨晩の監督コメント】は非常に重要です。監督の言葉が現実になったのか（例：「信じていた」→快走）、ならなかったのか（例：「不安が的中」→苦戦）を関連付けて描写し、物語に深みを与えてください。",
        "- **タスキリレーの描写**: 【本日の主なタスキリレー】に情報がある場合、そのリレーがチームにとってどんな意味を持つのか（例：反撃の狼煙、苦渋のタスキリレーなど）を情景豊かに描いてください。",
        "- **言葉選び**: 順位差が大きい場合は「独走」「盤石の走り」、僅差の場合は「デッドヒート」「息詰まる攻防」など、状況に最適な言葉を選んでください。",
        "",
        "## 4. 文体とトーン",
        "- **情熱的かつ客観的に**: あなたはファンの代表ですが、同時にプロの解説者です。感情的な表現を使いつつも、データに基づいた客観的な視点を忘れないでください。",
        "- **ドラマを演出する**: 「しかし」「だが」「一方」などの接続詞を効果的に使い、レースの展開に起伏を持たせてください。",
        "- **専門用語を使いこなす**: 「デッドヒート」「ジャンプアップ」「シード権争い」「花の2区」など、駅伝ファンに馴染みのある言葉を適切に使い、臨場感を高めてください。",
        "",
        "## 5. 執筆例（このスタイルを参考にしてください）",
        "- **良い例**: 「【王者の貫禄！名古屋大学、独走態勢へ】トップを走る名古屋大学は、2区のエース・美濃選手が38.5kmという驚異的な走りを見せ、2位との差をさらに広げました。監督が『彼の走りには絶対の信頼を置いている』と語っていた通り、その期待に完璧に応える走りでした。このまま独走態勢を築くのか、注目です。」（理由：データ、監督コメント、物語性を連携させているため）",
        "- **悪い例**: 「名古屋大学は1位でした。美濃選手は38.5km走りました。2位は三重大学です。」（理由：単なる事実の羅列であり、解説になっていないため）",
        "",
        "## 6. 熱い総括",
        "- **今日のまとめと明日への展望**: 「■ 解説者の熱い総括」で、記事全体を締めくくります。今日最も印象的だったシーンを振り返り、明日以降の注目ポイントやファンへのメッセージで、読者の期待感を最高潮に高めてください。",
        "",
        "# 禁止事項",
        "- **ルールの説明**: 「この駅伝のルールは〜」のような説明は不要です。読者は全て知っている前提で話を進めてください。",
        "- **架空の情報の創作**: 提供されたデータにない、架空のコメントやエピソード（例：「監督は涙を流した」など）は絶対に創作しないでください。",
        "- **単調なデータの羅列**: 「A大学はXkm、B大学はYkmでした」のような、単なるデータの読み上げは避けてください。必ずあなたの解説と物語を加えてください。",
        "## 【本日のレース状況】",
        f"- 大会日: {race_day}日目",
        f"- 現在のレース状況: {race_status_summary}",
        "- 本日の総合順位:",
        ranking_table_text,
    ]

    if relay_infos:
        prompt_parts.append("\n## 【本日の主なタスキリレー】")
        prompt_parts.extend(relay_infos)

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
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
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
