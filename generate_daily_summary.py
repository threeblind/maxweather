import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from bs4 import BeautifulSoup
import unicodedata

# --- 定数 ---
REALTIME_REPORT_FILE = 'realtime_report.json'
MANAGER_COMMENTS_FILE = 'manager_comments.json'
OUTPUT_FILE = 'daily_summary.json'

def get_east_asian_width_count(text):
    """全角文字を2、半角文字を1として文字幅をカウント"""
    return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in text)

def pad_str(text, length, align='left', char=' '):
    """指定した文字幅になるように文字列をパディング"""
    padding_size = length - get_east_asian_width_count(text)
    if padding_size < 0:
        return text
    
    if align == 'right':
        return (char * padding_size) + text
    else: # left
        return text + (char * padding_size)

def format_ranking_table(report_data):
    """realtime_report.jsonのデータから整形されたテキストテーブルを生成する"""
    table_lines = []
    teams = report_data.get('teams', [])
    if not teams:
        return "表示するチームデータがありません。"

    top_distance = teams[0]['totalDistance'] if teams else 0

    # ヘッダー
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

    # テーブルボディ
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

def load_all_data():
    """
    解説記事の生成に必要なJSONファイルをすべて読み込む。
    manager_comments.json は任意ファイルとして扱う。
    """
    data = {}
    files_to_load = {
        'realtime_report': REALTIME_REPORT_FILE,
        'manager_comments': MANAGER_COMMENTS_FILE,
    }
    try:
        for key, file_path in files_to_load.items():
            with open(file_path, 'r', encoding='utf-8') as f:
                data[key] = json.load(f)
    except FileNotFoundError as e:
        if key != 'manager_comments':
            print(f"エラー: 必須データファイルが見つかりません。 {e.filename}")
            exit(1)
        else:
            print(f"情報: {e.filename} が見つからないため、監督コメントはスキップされます。")
            data[key] = []
    except json.JSONDecodeError as e:
        print(f"エラー: JSONファイルの形式が正しくありません: {e}")
        exit(1)
    return data

def prepare_manager_comments(manager_comments_data, num_comments=3):
    """
    監督コメントをプロンプト用に整形する。
    """
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

def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='高温大学駅伝の1日の総括記事を生成します。')
    parser.add_argument('--dry-run', action='store_true', help='Gemini APIを呼び出さずにプロンプトのデバッグ表示のみ行います。')
    args = parser.parse_args()

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
    
    race_day = realtime_data.get('raceDay', 'N/A')
    ranking_table_text = format_ranking_table(realtime_data)
    
    prompt_parts = [
        "あなたは、日本の学生駅伝をこよなく愛する、非常に熱量の高いスポーツ解説者です。",
        "本日の「第15回 全国大学対抗高温駅伝」のレース結果と、昨晩の監督たちのコメントを元に、今日のレースを総括する情熱的でドラマチックなハイライト解説記事を、約800から1000文字で生成してください。",
        "以下の【本日のレース状況】と【昨晩の監督たちの主なコメント】を参考に、特に注目すべき展開（首位争いを含む上位争い、記録的な走り、予想外の躍進や苦戦など）に焦点を当てるとともに、ただし全大学に触れるようにして、視聴者の心を揺さぶるような記事を作成してください。",
        "---",
        "## 【本日のレース状況】",
        f"- 大会日: {race_day}日目",
        "- 本日の総合順位:",
        ranking_table_text,
    ]

    if manager_comments:
        prompt_parts.append("\n## 【昨晩の監督たちの主なコメント】")
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
        article_text = response.text.strip()
        print("✅ Geminiによる解説記事の生成に成功しました。")
    except Exception as e:
        print(f"❌ Gemini API呼び出し中にエラーが発生しました: {e}")
        article_text = "本日の解説記事は、システムの問題により生成できませんでした。ご了承ください。"

    output_data = {
        "date": realtime_data.get('updateTime', datetime.now().strftime('%Y/%m/%d %H:%M')).split(' ')[0],
        "article": article_text
    }
    
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"✅ 日次振り返り解説を '{OUTPUT_FILE}' に保存しました。")
    except IOError as e:
        print(f"エラー: ファイルへの書き込みに失敗しました: {e}")

if __name__ == '__main__':
    main()