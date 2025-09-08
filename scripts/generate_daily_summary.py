import json
import os
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
import google.generativeai as genai
from bs4 import BeautifulSoup
import unicodedata

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
DATA_DIR = Path('data')
LOGS_DIR = Path('logs')

# --- 定数 ---
REALTIME_REPORT_FILE = DATA_DIR / 'realtime_report.json'
MANAGER_COMMENTS_FILE = DATA_DIR / 'manager_comments.json'
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
RANK_HISTORY_FILE = DATA_DIR / 'rank_history.json'
ARTICLE_HISTORY_FILE = DATA_DIR / 'article_history.json'
SUMMARY_PROMPT_TEMPLATE_FILE = CONFIG_DIR / 'summary_prompt_template.txt'
OUTPUT_FILE = DATA_DIR / 'daily_summary.json'

class DailySummaryGenerator:
    """
    Generates a daily summary article for the Ekiden race using Gemini,
    with conversation history managed by Momento Cache for context.
    """

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.all_data = {}
        self.gemini_model = None

        load_dotenv()
        self._setup_clients()

    def _setup_clients(self):
        """Initializes Gemini API client."""
        # --- Gemini Setup ---
        if not self.dry_run:
            gemini_api_key = os.getenv("GEMINI_API_KEY")
            if not gemini_api_key:
                print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。")
                exit(1)
            genai.configure(api_key=gemini_api_key)
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            print("✅ Geminiクライアントを初期化しました。")

    def _get_article_history(self, num_articles=2):
        """Fetches the last N articles and prompts from the local history file."""
        if not ARTICLE_HISTORY_FILE.exists():
            return []

        print(f"ローカルファイルから過去の記事履歴を取得しています ({ARTICLE_HISTORY_FILE})...")
        try:
            with open(ARTICLE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                history = json.load(f)
            print(f"✅ {len(history)}件の記事履歴を発見。最新の{num_articles}件を利用します。")
            return history[:num_articles]
        except (json.JSONDecodeError, IOError) as e:
            print(f"❌ 記事履歴の読み込み中にエラーが発生しました: {e}")
            return []

    def _save_article_to_history(self, prompt_text, article_text):
        """Saves the newly generated article and its prompt to the local history file."""
        if not prompt_text or not article_text:
            return

        print(f"ローカルファイルに新しい記事とプロンプトを保存しています ({ARTICLE_HISTORY_FILE})...")
        history = []
        if ARTICLE_HISTORY_FILE.exists():
            try:
                with open(ARTICLE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except (json.JSONDecodeError, IOError):
                print(f"警告: 既存の履歴ファイル '{ARTICLE_HISTORY_FILE}' が読み取れないため、上書きします。")
                pass

        new_entry = {
            "date": self.all_data.get('realtime_report', {}).get('updateTime', datetime.now().strftime('%Y/%m/%d %H:%M')).split(' ')[0],
            "prompt": prompt_text,
            "article": article_text
        }

        # Add new entry to the front and keep the last 10
        updated_history = [new_entry] + history
        updated_history = updated_history[:10]

        try:
            with open(ARTICLE_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(updated_history, f, indent=2, ensure_ascii=False)
            print("✅ 新しい記事とプロンプトを履歴に保存しました。")
        except IOError as e:
            print(f"❌ 記事履歴の保存中にエラーが発生しました: {e}")

    @staticmethod
    def get_east_asian_width_count(text):
        return sum(2 if unicodedata.east_asian_width(c) in 'FWA' else 1 for c in str(text))

    @staticmethod
    def pad_str(text, length, align='left', char=' '):
        text_str = str(text)
        padding_size = length - DailySummaryGenerator.get_east_asian_width_count(text_str)
        if padding_size < 0: return text_str
        return (char * padding_size) + text_str if align == 'right' else text_str + (char * padding_size)

    def load_all_data(self):
        data = {}
        files_to_load = {
            'realtime_report': REALTIME_REPORT_FILE, 'manager_comments': MANAGER_COMMENTS_FILE,
            'ekiden_data': EKIDEN_DATA_FILE, 'rank_history': RANK_HISTORY_FILE,
        }
        for key, file_path in files_to_load.items():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data[key] = json.load(f)
            except FileNotFoundError:
                if key == 'manager_comments':
                    print(f"情報: {file_path} が見つからないため、監督コメントはスキップされます。")
                    data[key] = []
                else:
                    print(f"エラー: 必須データファイル '{file_path}' が見つかりません。")
                    exit(1)
            except json.JSONDecodeError as e:
                print(f"エラー: JSONファイルの形式が正しくありません: {file_path} - {e}")
                exit(1)
        self.all_data = data

    def format_ranking_table(self):
        report_data = self.all_data.get('realtime_report', {})
        table_lines = []
        # is_shadow_confederationがtrueのチーム（区間記録連合）を除外する
        teams = [t for t in report_data.get('teams', []) if not t.get('is_shadow_confederation')]
        if not teams: return "表示するチームデータがありません。"
        top_distance = teams[0]['totalDistance'] if teams else 0
        header = (
            f"{self.pad_str('順位', 4)} {self.pad_str('大学名', 12)} {self.pad_str('現在走者', 10)} "
            f"{self.pad_str('本日距離(順位)', 16)} {self.pad_str('総合距離', 10)} {self.pad_str('トップ差', 10)} "
            f"{self.pad_str('順位変動(前日)', 16)} "
        )
        table_lines.append(header)
        for team in teams:
            gap = top_distance - team.get('totalDistance', 0.0)

            rank_str = self.pad_str(str(team.get('overallRank', '')), 4)
            name_str = self.pad_str(team.get('name', ''), 12)
            runner_str = self.pad_str(team.get('runner', ''), 10)

            today_dist_inner_str = f"{team.get('todayDistance', 0.0):.1f}km ({team.get('todayRank', '')})"
            today_dist_str = self.pad_str(today_dist_inner_str, 16)

            total_dist_str = self.pad_str(f"{team.get('totalDistance', 0.0):.1f}km", 10, align='right')

            gap_inner_str = '----' if team.get('overallRank') == 1 else f'-{gap:.1f}km'
            gap_str = self.pad_str(gap_inner_str, 10, align='right')

            prev_rank = team.get("previousRank", 0)
            rank_change_inner_str = f"ー (－)" if prev_rank == 0 else f"ー ({prev_rank})"
            rank_change_str = self.pad_str(rank_change_inner_str, 16)

            line = f"{rank_str} {name_str} {runner_str} {today_dist_str} {total_dist_str} {gap_str} {rank_change_str}"
            table_lines.append(line)
        return "\n".join(table_lines)

    def prepare_manager_comments(self, num_comments=3):
        manager_comments_data = self.all_data.get('manager_comments', [])
        if not manager_comments_data: return []
        now, recent_comments = datetime.now(), []
        for comment in manager_comments_data:
            if len(recent_comments) >= num_comments: break
            try:
                if datetime.fromisoformat(comment['timestamp']) < now - timedelta(days=1, hours=5): continue
                soup = BeautifulSoup(comment['content_html'], 'html.parser')
                for a in soup.find_all('a', class_='reply_link'): a.decompose()
                clean_text = soup.get_text(separator=' ', strip=True)
                if len(clean_text) > 100: clean_text = clean_text[:100] + "..."
                if "ありがとうございました" in clean_text or "お世話になりました" in clean_text: continue
                recent_comments.append(f"- {comment['official_name']}: 「{clean_text}」")
            except (ValueError, TypeError): continue
        return recent_comments

    def format_relay_info(self):
        realtime_data = self.all_data.get('realtime_report', {})
        ekiden_data = self.all_data.get('ekiden_data', {})
        rank_history = self.all_data.get('rank_history', {})
        relay_infos, leg_boundaries = [], ekiden_data.get('leg_boundaries', [])
        if not rank_history or not rank_history.get('dates') or len(rank_history['dates']) < 2: return []
        last_day_index, yesterday_distances = len(rank_history['dates']) - 2, {}
        for team_history in rank_history.get('teams', []):
            if len(team_history.get('distances', [])) > last_day_index:
                yesterday_distances[team_history['id']] = team_history['distances'][last_day_index]
        # is_shadow_confederationがtrueのチーム（区間記録連合）を除外する
        teams_to_check = [t for t in realtime_data.get('teams', []) if not t.get('is_shadow_confederation')]
        for team_state in teams_to_check:
            yesterday_dist = yesterday_distances.get(team_state.get('id'), 0.0)
            today_dist = team_state.get('totalDistance', 0.0)
            for i, boundary in enumerate(leg_boundaries):
                if yesterday_dist < boundary <= today_dist:
                    from_leg, to_leg = i + 1, i + 2
                    next_runner = team_state.get('nextRunner', '次の走者').replace(str(to_leg), '')
                    relay_infos.append(f"- {team_state['name']}が{from_leg}区を走りきり、{to_leg}区・{next_runner}選手へタスキを繋ぎました！")
        return relay_infos

    def format_article_with_markdown(self, article_text):
        ekiden_data = self.all_data.get('ekiden_data', {})
        article_text = re.sub(r'^(■.*)$', r'**\1**', article_text, flags=re.MULTILINE)
        university_names, player_names = set(), set()
        for team in ekiden_data.get('teams', []):
            university_names.add(team['name'])
            for member_type in ['runners', 'substitutes', 'substituted_out']:
                player_names.update(p.get('name') for p in team.get(member_type, []) if isinstance(p, dict) and p.get('name'))
        plain_player_names = {re.sub(r'（.+）', '', name).strip() for name in player_names if name}
        player_names.update(plain_player_names)
        sorted_uni_names = sorted(list(university_names), key=len, reverse=True)
        for name in sorted_uni_names:
            article_text = re.sub(f'(?<!\\*\\*){re.escape(name)}(?!\\*\\*)', f'**{name}**', article_text)
        sorted_player_names = sorted(list(player_names), key=len, reverse=True)
        for name in sorted_player_names:
            if not name: continue
            article_text = re.sub(f'(?<!\\*\\*)\\d*({re.escape(name)}選手)(?!\\*\\*)', r'**\1**', article_text)
        return article_text

    def _build_prompt(self):
        """Builds the complete prompt for the Gemini API call."""
        realtime_data = self.all_data.get('realtime_report', {})
        ekiden_data = self.all_data.get('ekiden_data', {})
        race_day = realtime_data.get('raceDay', 'N/A')
        race_status_summary = "レース集計中"
        if realtime_data.get('teams'):
            top_team = realtime_data['teams'][0]
            race_status_summary = "トップチームはゴールしました" if top_team.get('runner') == 'ゴール' else f"トップは第{top_team.get('currentLeg', 'N/A')}区を走行中"

        # 大学と都道府県のリストを作成
        team_prefecture_list = []
        if ekiden_data.get('teams'):
            for team in ekiden_data['teams']:
                team_name = team.get('name', '不明')
                prefectures = team.get('prefectures', '')
                team_prefecture_list.append(f"- {team_name}: {prefectures}")
        
        team_prefecture_text = "\n".join(team_prefecture_list)

        # プロンプトテンプレートを読み込む
        try:
            with open(SUMMARY_PROMPT_TEMPLATE_FILE, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
        except FileNotFoundError:
            print(f"エラー: プロンプトテンプレートファイル '{SUMMARY_PROMPT_TEMPLATE_FILE}' が見つかりません。")
            return ""

        # テンプレートに動的データを埋め込む
        base_prompt = prompt_template.format(team_prefecture_list=team_prefecture_text)
        
        prompt_parts = [base_prompt]

        # 過去のプロンプトと記事を文脈に追加
        history_items = self._get_article_history(num_articles=2)
        if history_items:
            history_section = ["\n## 【これまでのレース展開（過去のあなたの解説）】", "過去のプロンプトとそれに対するあなたの解説を踏まえて、今日のレース展開の連続性や特筆すべき変化を解説に含めてください。"]
            for item in history_items:
                try:
                    date_obj = datetime.strptime(item['date'], '%Y/%m/%d')
                    day_str = date_obj.strftime('%-m月%-d日').replace(' 0', ' ') # for Windows compatibility
                except (ValueError, KeyError):
                    day_str = item.get('date', '過去')
                history_section.append(f"\n### 【{day_str}のプロンプト】\n---\n{item.get('prompt', '（プロンプト記録なし）')}\n---")
                history_section.append(f"\n### 【{day_str}のあなたの解説】\n---\n{item.get('article', '（記事記録なし）')}\n---")
            prompt_parts.extend(history_section)

        prompt_parts.append("\n## 【本日のレース状況】")
        prompt_parts.append(f"- 大会日: {race_day}日目")
        prompt_parts.append(f"- 現在のレース状況: {race_status_summary}")
        prompt_parts.append("- 本日の総合順位:")
        prompt_parts.append(self.format_ranking_table())

        relay_infos = self.format_relay_info()
        if relay_infos:
            prompt_parts.append("\n## 【本日の主なタスキリレー】")
            prompt_parts.extend(relay_infos)

        manager_comments = self.prepare_manager_comments()
        if manager_comments:
            prompt_parts.append("\n## 【昨晩の監督コメント】")
            prompt_parts.extend(manager_comments)

        prompt_parts.append("\n---\n解説記事:")
        return "\n".join(prompt_parts)

    def run(self):
        """Main execution logic."""
        print("日次振り返り解説の生成を開始します...")
        self.load_all_data()
        prompt = self._build_prompt()

        print("------------------------------------")
        print("Geminiへの統合プロンプト:")
        print(prompt)
        print("------------------------------------")

        if self.dry_run:
            print("\n--dry-runモードのため、ファイルへの書き込みは行わずに終了します。")
            return

        try:
            response = self.gemini_model.generate_content(prompt)
            raw_article_text = response.text.strip()
            print("記事をMarkdownでフォーマットしています...")
            article_text = self.format_article_with_markdown(raw_article_text)
            print("✅ Geminiによる解説記事の生成に成功しました。")
            self._save_article_to_history(prompt, raw_article_text)
        except Exception as e:
            print(f"❌ Gemini API呼び出し中にエラーが発生しました: {e}")
            article_text = "本日の解説記事は、システムの問題により生成できませんでした。ご了承ください。"

        output_data = {
            "date": self.all_data.get('realtime_report', {}).get('updateTime', datetime.now().strftime('%Y/%m/%d %H:%M')).split(' ')[0],
            "article": article_text
        }

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            print(f"✅ 日次振り返り解説を '{OUTPUT_FILE}' に保存しました。")
        except IOError as e:
            print(f"エラー: ファイルへの書き込みに失敗しました: {e}")

def main():
    """Parses arguments and runs the generator."""
    parser = argparse.ArgumentParser(description='高温大学駅伝の1日の総括記事を生成します（履歴機能付き）。')
    parser.add_argument('--dry-run', action='store_true', help='Gemini APIを呼び出さずにプロンプトのデバッグ表示のみ行います。')
    args = parser.parse_args()

    generator = DailySummaryGenerator(dry_run=args.dry_run)
    generator.run()

if __name__ == '__main__':
    main()
