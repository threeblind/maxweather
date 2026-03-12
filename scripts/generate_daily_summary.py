import json
import os
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import unicodedata
import google.generativeai as genai

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
OUTPUT_FILE = DATA_DIR / 'daily_summary.json'
INDIVIDUAL_RESULTS_FILE = DATA_DIR / 'individual_results.json'
PLAYER_STORY_CONTEXT_FILE = CONFIG_DIR / 'player_story_context.json'
TEAM_STORY_CONTEXT_FILE = CONFIG_DIR / 'team_story_context.json'
LEG_STORY_CONTEXT_FILE = CONFIG_DIR / 'leg_story_context.json'

class DailySummaryGenerator:
    """
    Generates a daily summary article for the Ekiden race using an LLM.
    """
    DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite-preview"

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.all_data = {}
        self.gemini_model = None

        load_dotenv()
        self.model_name = os.getenv("GEMINI_MODEL", self.DEFAULT_GEMINI_MODEL)
        self._setup_clients()

    def _setup_clients(self):
        """Initializes Gemini API client."""
        if not self.dry_run:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                print("エラー: 環境変数 'GEMINI_API_KEY' が設定されていません。")
                exit(1)

            genai.configure(api_key=api_key)
            self.gemini_model = genai.GenerativeModel(
                self.model_name,
                system_instruction=self.build_system_prompt()
            )
            print(f"✅ Geminiクライアントを初期化しました。model={self.model_name}")

    def _switch_gemini_model(self, model_name):
        self.model_name = model_name
        self.gemini_model = genai.GenerativeModel(
            self.model_name,
            system_instruction=self.build_system_prompt()
        )
        print(f"ℹ️ Geminiモデルを切り替えました。model={self.model_name}")

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

        # Add new entry to the front
        updated_history = [new_entry] + history

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

    def _load_outline_data(self):
        """outline.jsonから大会情報を読み込む"""
        outline_file = CONFIG_DIR / 'outline.json'
        try:
            with open(outline_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"警告: {outline_file} が見つかりません。デフォルト値を使用します。")
            return {}
        except json.JSONDecodeError as e:
            print(f"警告: {outline_file} の形式が正しくありません: {e}。デフォルト値を使用します。")
            return {}

    def _format_leg_configuration(self, legs):
        """区間構成を整形する"""
        if not legs:
            # デフォルトの区間構成
            return """- 第１区: 100km / 100km
- 第２区: 110km / 210km
- 第３区: 100km / 310km
- 第４区:  89km / 399km
- 第５区: 123km / 522km
- 第６区: 117km / 639km
- 第７区:  96km / 735km
- 第８区: 106km / 841km
- 第９区: 101km / 942km
- 第10区: 113km / 1055km"""
        
        formatted_legs = []
        for i, leg_info in enumerate(legs, 1):
            # leg_infoは "第１区（100km) 100km" のような形式
            formatted_legs.append(f"- 第{i}区: {leg_info}")
        
        return '\n'.join(formatted_legs)

    def load_all_data(self):
        data = {}
        files_to_load = {
            'realtime_report': REALTIME_REPORT_FILE, 'manager_comments': MANAGER_COMMENTS_FILE,
            'ekiden_data': EKIDEN_DATA_FILE, 'rank_history': RANK_HISTORY_FILE,
            'individual_results': INDIVIDUAL_RESULTS_FILE,
            'player_story_context': PLAYER_STORY_CONTEXT_FILE,
            'team_story_context': TEAM_STORY_CONTEXT_FILE,
            'leg_story_context': LEG_STORY_CONTEXT_FILE,
        }
        for key, file_path in files_to_load.items():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data[key] = json.load(f)
            except FileNotFoundError:
                if key == 'manager_comments':
                    print(f"情報: {file_path} が見つからないため、監督コメントはスキップされます。")
                    data[key] = []
                elif key == 'individual_results':
                    print(f"情報: {file_path} が見つからないため、区間賞集計はスキップされます。")
                    data[key] = {}
                elif key == 'player_story_context':
                    print(f"情報: {file_path} が見つからないため、個人文脈はスキップされます。")
                    data[key] = {}
                elif key == 'team_story_context':
                    print(f"情報: {file_path} が見つからないため、チーム文脈はスキップされます。")
                    data[key] = {}
                elif key == 'leg_story_context':
                    print(f"情報: {file_path} が見つからないため、区間文脈はスキップされます。")
                    data[key] = {}
                else:
                    print(f"エラー: 必須データファイル '{file_path}' が見つかりません。")
                    exit(1)
            except json.JSONDecodeError as e:
                print(f"エラー: JSONファイルの形式が正しくありません: {file_path} - {e}")
                exit(1)
        self.all_data = data

    def format_ranking_table(self):
        """総合順位をMarkdownテーブル形式で整形する。"""
        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return "現在走行中の公式チームはありません。"

        header = "| 順位 | 大学名 | 現在走者 | 本日距離(順位) | 総合距離 | トップ差 | 順位変動(前日) |"
        divider = "|:---|:---|:---|:---|:---|:---|:---|"
        rows = [header, divider]

        top_distance = teams[0].get('totalDistance', 0.0)
        for team in teams:
            total_distance = team.get('totalDistance', 0.0)
            gap = "----" if team.get('overallRank') == 1 else f"-{top_distance - total_distance:.1f}km"
            previous_rank = team.get("previousRank", 0)
            rank_change = self._rank_move_label(previous_rank, team.get('overallRank'))

            row = [
                team.get('overallRank', ''),
                team.get('name', ''),
                team.get('runner', ''),
                f"{team.get('todayDistance', 0.0):.1f}km ({team.get('todayRank', '')})",
                f"{total_distance:.1f}km",
                gap,
                rank_change,
            ]
            rows.append("| " + " | ".join(str(cell) if cell != "" else "-" for cell in row) + " |")

        return "\n".join(rows)

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
        # 走行中チームのみを対象にする（区間記録連合は除外済み）
        teams_to_check = self._get_active_teams()
        for team_state in teams_to_check:
            yesterday_dist = yesterday_distances.get(team_state.get('id'), 0.0)
            today_dist = team_state.get('totalDistance', 0.0)
            for i, boundary in enumerate(leg_boundaries):
                if yesterday_dist < boundary <= today_dist:
                    from_leg, to_leg = i + 1, i + 2
                    next_runner_raw = team_state.get('nextRunner', '次の走者')
                    if to_leg > len(leg_boundaries):
                        relay_infos.append(f"- {team_state['name']}が{from_leg}区を走りきり、フィニッシュテープを切りました！")
                    else:
                        next_runner = next_runner_raw.lstrip(str(to_leg)).replace('ゴール', '').strip()
                        if not next_runner:
                            next_runner = "次の走者"
                        relay_infos.append(f"- {team_state['name']}が{from_leg}区を走りきり、{to_leg}区の{next_runner}選手へタスキを繋ぎました！")
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

    def _get_regular_teams(self):
        realtime_data = self.all_data.get('realtime_report', {})
        return [team for team in realtime_data.get('teams', []) if not team.get('is_shadow_confederation')]

    def _get_active_teams(self):
        """現在も走行中の公式チームのみを抽出。"""
        return [
            team for team in self._get_regular_teams()
            if (team.get('runner') or '').strip() != 'ゴール'
        ]

    @staticmethod
    def _format_team_snapshot(team):
        rank = team.get('overallRank')
        total = team.get('totalDistance', 0.0)
        today = team.get('todayDistance', 0.0)
        runner = team.get('runner') or ''
        rank_str = f"{rank}位" if rank else "順位不明"
        return f"{team.get('name')}（{rank_str} / 累計{total:.1f}km / 本日{today:.1f}km / 走者:{runner}）"

    @staticmethod
    def _describe_gap(gap):
        if gap is None:
            return "差不明"
        if gap <= 1.0:
            return f"{gap:.1f}km差のデッドヒート"
        if gap >= 5.0:
            return f"{gap:.1f}km差で独走態勢"
        return f"{gap:.1f}km差"

    @staticmethod
    def _rank_move_label(previous_rank, current_rank):
        if not previous_rank or not current_rank:
            return "前日比較なし"
        diff = previous_rank - current_rank
        if diff >= 3:
            return f"{diff}ランクアップ"
        if diff >= 1:
            return f"{diff}ランクアップ"
        if diff == 0:
            return "順位維持"
        return f"{abs(diff)}ランクダウン"

    def _build_story_angle(self):
        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return []

        notes = []
        if len(teams) >= 2:
            lead_gap = teams[0].get('totalDistance', 0.0) - teams[1].get('totalDistance', 0.0)
            notes.append(f"- 今日の軸: 首位争いは{teams[0].get('name')}と{teams[1].get('name')}の{self._describe_gap(lead_gap)}。")

        upper_mid = [t for t in teams if t.get('overallRank') and 4 <= t['overallRank'] <= 8]
        if len(upper_mid) >= 2:
            spread = upper_mid[0].get('totalDistance', 0.0) - upper_mid[-1].get('totalDistance', 0.0)
            notes.append(f"- 中位戦線: 4〜8位帯は最大{spread:.1f}km差の混戦。")

        rank10 = next((t for t in teams if t.get('overallRank') == 10), None)
        rank11 = next((t for t in teams if t.get('overallRank') == 11), None)
        race_day = self.all_data.get('realtime_report', {}).get('raceDay')
        try:
            race_day_int = int(race_day)
        except (TypeError, ValueError):
            race_day_int = None
        if rank10 and rank11:
            seed_gap = rank10.get('totalDistance', 0.0) - rank11.get('totalDistance', 0.0)
            if abs(seed_gap) <= 0.5 or (race_day_int is not None and race_day_int >= 3 and abs(seed_gap) <= 1.5):
                notes.append(f"- シード争い: 10位{rank10.get('name')}と11位{rank11.get('name')}は{self._describe_gap(abs(seed_gap))}。")

        risers = []
        fallers = []
        for team in teams:
            previous_rank = team.get('previousRank')
            current_rank = team.get('overallRank')
            if not previous_rank or not current_rank:
                continue
            if current_rank < previous_rank:
                risers.append(f"{team.get('name')}（{previous_rank}位→{current_rank}位）")
            elif current_rank > previous_rank:
                fallers.append(f"{team.get('name')}（{previous_rank}位→{current_rank}位）")

        if risers:
            notes.append("- 順位上昇校: " + "、".join(risers[:4]))
        if fallers:
            notes.append("- 順位後退校: " + "、".join(fallers[:4]))

        return notes

    def _build_continuity_note(self):
        history = self._get_article_history(num_articles=1)
        if not history:
            return []

        latest = history[0]
        article = re.sub(r'\s+', ' ', str(latest.get('article', '') or '')).strip()
        if not article:
            return []

        article = article.replace("**", "")
        article = re.sub(r'^#+\s*', '', article)
        if len(article) > 140:
            article = article[:140].rstrip() + "..."

        date_text = latest.get('date') or '前日'
        return [
            f"- 前回記事（{date_text}）の主題: {article}",
            "- 今日の記事では前日の焦点が継続しているのか、入れ替わったのかを自然に接続すること。"
        ]

    def build_coverage_checklist(self):
        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return ["- 現在走行中の公式チームはありません。"]

        lines = []

        top_cluster = teams[:3]
        if top_cluster:
            lines.append("- トップ集団(上位): " + "、".join(self._format_team_snapshot(t) for t in top_cluster))

        mid_pack = [t for t in teams if t.get('overallRank') and 4 <= t['overallRank'] <= 8]
        if mid_pack:
            lines.append("- 中位混戦ゾーン(4〜8位): " + "、".join(self._format_team_snapshot(t) for t in mid_pack))

        race_day = self.all_data.get('realtime_report', {}).get('raceDay')
        try:
            race_day_int = int(race_day)
        except (TypeError, ValueError):
            race_day_int = None
        rank10 = next((t for t in teams if t.get('overallRank') == 10), None)
        rank11 = next((t for t in teams if t.get('overallRank') == 11), None)
        if rank10 and rank11:
            seed_gap = abs(rank10.get('totalDistance', 0.0) - rank11.get('totalDistance', 0.0))
            if seed_gap <= 0.5 or (race_day_int is not None and race_day_int >= 3 and seed_gap <= 1.5):
                seed_window = [t for t in teams if t.get('overallRank') and 9 <= t['overallRank'] <= 12]
                if seed_window:
                    lines.append("- シード権前後: " + "、".join(self._format_team_snapshot(t) for t in seed_window))

        lower_surge_candidates = sorted(teams, key=lambda te: te.get('overallRank') or 999, reverse=True)
        tail_fighters = [
            t for t in lower_surge_candidates[:4]
            if t.get('todayDistance', 0.0) >= 20.0 or (t.get('overallRank') or 0) >= 13
        ]
        if tail_fighters:
            lines.append("- 下位でも目立ったチーム: " + "、".join(self._format_team_snapshot(t) for t in tail_fighters))

        return lines

    def _load_recent_substitution_logs(self):
        log_file = LOGS_DIR / 'substitution_log.txt'
        if not log_file.exists():
            return []

        recent_entries = []
        now = datetime.now()
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}): チームID (\d+) \((.+?)\) - (.+?) → (.+)$', line)
                if not match:
                    continue
                timestamp_str, team_id, team_name, runner_out, runner_in = match.groups()
                try:
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if now - timestamp <= timedelta(hours=36):
                    recent_entries.append({
                        "timestamp": timestamp_str,
                        "team_name": team_name,
                        "runner_out": runner_out,
                        "runner_in": runner_in
                    })
        return recent_entries

    def _get_leg_awards_for_day(self, race_day):
        try:
            race_day_int = int(race_day)
        except (TypeError, ValueError):
            return []

        individual_results = self.all_data.get('individual_results') or {}
        if not individual_results:
            return []

        realtime_data = self.all_data.get('realtime_report', {})
        active_legs = set()
        for team in realtime_data.get('teams', []):
            if team.get('is_shadow_confederation'):
                continue
            runner_name = (team.get('runner') or '').strip()
            if runner_name == 'ゴール':
                continue
            leg_num = team.get('currentLeg')
            if isinstance(leg_num, int):
                active_legs.add(leg_num)

        if not active_legs:
            return []

        team_lookup = {}
        for team in self.all_data.get('ekiden_data', {}).get('teams', []):
            team_lookup[team.get('id')] = team.get('name')

        leg_best_map = {}
        for runner_name, runner_data in individual_results.items():
            if not isinstance(runner_data, dict):
                continue
            team_id = runner_data.get('teamId')
            leg_summaries = runner_data.get('legSummaries', {})
            if not isinstance(leg_summaries, dict):
                continue
            for leg_key, summary in leg_summaries.items():
                if not isinstance(summary, dict):
                    continue
                try:
                    leg_number = int(leg_key)
                except (TypeError, ValueError):
                    continue
                entry = leg_best_map.setdefault(leg_number, {
                    "performers": [],
                    "average": None,
                    "all_final": True
                })
                status = summary.get('status', 'provisional')
                if status != 'final':
                    entry['all_final'] = False
                    continue

                rank_val = summary.get('rank')
                if rank_val is None:
                    continue
                try:
                    rank_int = int(rank_val)
                except (TypeError, ValueError):
                    continue

                average = summary.get('averageDistance')
                try:
                    average_val = float(average)
                except (TypeError, ValueError):
                    average_val = None
                if average_val is not None:
                    entry['average'] = average_val

                entry['performers'].append({
                    "runner_name": runner_name,
                    "team_name": team_lookup.get(team_id, '所属不明'),
                    "status": status,
                    "average": average_val,
                    "rank": rank_int,
                    "finalDay": summary.get('finalDay'),
                    "lastUpdatedDay": summary.get('lastUpdatedDay')
                })

        awards = []
        for leg_number, data in leg_best_map.items():
            if leg_number not in active_legs:
                continue
            if not data.get('all_final'):
                continue
            top_performers = [p for p in data.get('performers', []) if p.get('rank') == 1]
            if not top_performers:
                continue
            avg_val = top_performers[0].get('average')
            awards.append({
                "leg": leg_number,
                "performers": top_performers,
                "average": avg_val if isinstance(avg_val, (int, float)) else data.get('average')
            })
        awards.sort(key=lambda item: item['leg'])
        return awards

    def _build_leg_award_notes(self, race_day):
        leg_awards = self._get_leg_awards_for_day(race_day)
        if not leg_awards:
            return []

        leg_awards.sort(key=lambda award: award.get('leg'))
        max_display = 3
        segments = []
        for award in leg_awards[:max_display]:
            performers = award.get('performers', [])
            if not performers:
                continue
            status_label = "確定" if all(p.get('status') == 'final' for p in performers) else "暫定"
            average = award.get('average')
            average_text = f"{average:.1f}km/日" if isinstance(average, (int, float)) else "-"
            performer_text = "、".join(f"{p.get('rank')}位 {p['runner_name']}（{p['team_name']}）" for p in performers)
            if performer_text:
                segments.append(f"第{award.get('leg')}区（{status_label}）{performer_text} {average_text}")

        if not segments:
            return []

        remaining = len(leg_awards) - len(segments)
        note_text = "- 区間賞情報: " + " / ".join(segments)
        if remaining > 0:
            note_text += f" / ほか{remaining}区"
        return [note_text]

    def build_daily_notes(self, race_day):
        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return ["- 現在走行中のチーム情報は取得できません。"]

        notes = []
        try:
            race_day_int = int(race_day)
            notes.append(f"- 第{race_day_int}日目の継続走行校は{len(teams)}校。")
        except (TypeError, ValueError):
            pass

        top_team = teams[0]
        if len(teams) > 1:
            runner_up = teams[1]
            gap = top_team.get('totalDistance', 0.0) - runner_up.get('totalDistance', 0.0)
            notes.append(f"- 首位攻防: 1位 {top_team.get('name')} と2位 {runner_up.get('name')} の差は {gap:.1f}km。")
        else:
            notes.append(f"- 首位状況: {top_team.get('name')} が走行中チームの先頭を独走。")

        today_stars = [t for t in sorted(teams, key=lambda tm: tm.get('todayDistance', 0.0), reverse=True) if t.get('todayDistance', 0.0) > 0][:3]
        if today_stars:
            notes.append("- 本日の距離トップ: " + "、".join(f"{t.get('name')} {t.get('todayDistance', 0.0):.1f}km（{t.get('runner')}）" for t in today_stars))

        seed_ten = next((t for t in teams if t.get('overallRank') == 10), None)
        seed_eleven = next((t for t in teams if t.get('overallRank') == 11), None)
        if seed_ten and seed_eleven:
            diff = seed_ten.get('totalDistance', 0.0) - seed_eleven.get('totalDistance', 0.0)
            try:
                race_day_int = int(race_day)
            except (TypeError, ValueError):
                race_day_int = None
            if abs(diff) <= 0.5 or (race_day_int is not None and race_day_int >= 3 and abs(diff) <= 1.5):
                notes.append(f"- シードライン差: 10位 {seed_ten.get('name')} と11位 {seed_eleven.get('name')} の距離差は {diff:.1f}km。")

        substitutions = self._load_recent_substitution_logs()
        if substitutions:
            for entry in substitutions:
                notes.append(f"- 選手交代: {entry['timestamp']} {entry['team_name']}が {entry['runner_out']} → {entry['runner_in']} に交代。")

        leg_award_notes = self._build_leg_award_notes(race_day)
        notes.extend(leg_award_notes)

        return notes

    def build_system_prompt(self):
        return "\n".join([
            "あなたは「高温大学駅伝」の専門解説者です。",
            "出力は日本語のMarkdown記事です。",
            "",
            "必ず守ること:",
            "- 提供されたデータにない情報を創作しない",
            "- 総合順位が上がっていないチームに「浮上」「ジャンプアップ」「逆転」を使わない",
            "- 監督コメントは提供された場合のみ言及する",
            "- 既にゴールしたチームには、当日新規性がある場合を除き重点的に触れない",
            "- 記事は事実優先で書き、数字や順位差は提供データを優先する",
            "",
            "文体:",
            "- 情熱はあるが、実況ではなく解説記事",
            "- 単なるデータ羅列ではなく、レースの構図が伝わるように書く",
            "- 具体的な大学名、選手名、距離差、区間を自然に織り込む",
        ])

    def _get_relevant_player_story_notes(self):
        context_root = self.all_data.get('player_story_context') or {}
        player_map = context_root.get('players', {}) if isinstance(context_root, dict) else {}
        if not player_map:
            return []

        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return []

        selected = []

        def normalize_runner(raw_name):
            return (raw_name or '').lstrip('1234567890').strip()

        def add_runner(raw_name):
            runner_name = normalize_runner(raw_name)
            if not runner_name or runner_name in selected or runner_name not in player_map:
                return
            selected.append(runner_name)

        for team in teams[:5]:
            add_runner(team.get('runner'))

        for team in sorted(teams, key=lambda t: t.get('todayDistance', 0.0), reverse=True)[:5]:
            add_runner(team.get('runner'))

        notes = []
        for runner_name in selected[:5]:
            context = player_map.get(runner_name, {})
            summary = context.get('summary')
            highlights = context.get('highlights') or []
            tags = context.get('tags') or []

            fragments = []
            if summary:
                fragments.append(summary)
            if highlights:
                fragments.append("実績: " + " / ".join(highlights[:2]))
            if tags:
                fragments.append("タグ: " + "、".join(tags[:3]))

            if fragments:
                notes.append(f"- {runner_name}: " + " / ".join(fragments))

        if not notes:
            return []

        notes.insert(0, "- 以下は走者本人の補助文脈。歴代記録保持者や複数回上位入りなどの格付けは、当日の走りを補強する範囲でのみ使うこと。")
        return notes

    def _build_record_break_notes(self, race_day):
        try:
            race_day_int = int(race_day)
        except (TypeError, ValueError):
            return []

        leg_context_root = self.all_data.get('leg_story_context') or {}
        leg_map = leg_context_root.get('legs', {}) if isinstance(leg_context_root, dict) else {}
        individual_results = self.all_data.get('individual_results') or {}
        ekiden_teams = self.all_data.get('ekiden_data', {}).get('teams', [])
        team_lookup = {team.get('id'): team.get('name') for team in ekiden_teams}

        notes = []
        for runner_name, runner_data in individual_results.items():
            if not isinstance(runner_data, dict):
                continue
            leg_summaries = runner_data.get('legSummaries') or {}
            team_name = team_lookup.get(runner_data.get('teamId'), '所属不明')
            for leg_key, summary in leg_summaries.items():
                if not isinstance(summary, dict):
                    continue
                if summary.get('status') != 'final':
                    continue
                if summary.get('finalDay') != race_day_int:
                    continue
                leg_context = leg_map.get(str(leg_key)) or {}
                best_record = leg_context.get('best_record') or {}
                best_distance = best_record.get('distance')
                average_distance = summary.get('averageDistance')
                if not isinstance(best_distance, (int, float)) or not isinstance(average_distance, (int, float)):
                    continue
                if average_distance <= best_distance:
                    continue
                notes.append(
                    f"- 歴代区間記録更新: 第{leg_key}区で{team_name}の{runner_name}が{average_distance:.3f}kmを記録。従来の最高 {best_record.get('team', '不明')} {best_record.get('runner', '不明')} {best_distance:.3f}km（第{best_record.get('edition', '?')}回）を上回った。"
                )

        return notes

    def _get_light_team_story_notes(self):
        context_root = self.all_data.get('team_story_context') or {}
        team_map = context_root.get('teams', {}) if isinstance(context_root, dict) else {}
        if not team_map:
            return []

        teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        spotlight = []

        for team in teams[:3]:
            name = team.get('name')
            if name and name not in spotlight and name in team_map:
                spotlight.append(name)

        upper_mid = [t.get('name') for t in teams if t.get('overallRank') and 4 <= t.get('overallRank') <= 8]
        for name in upper_mid[:2]:
            if name and name not in spotlight and name in team_map:
                spotlight.append(name)

        notes = []
        for team_name in spotlight[:4]:
            context = team_map.get(team_name, {})
            summary = context.get('history_summary')
            rivals = context.get('rival_candidates') or []
            if not summary:
                continue
            line = f"- {team_name}: {summary}"
            if rivals:
                line += f" ライバル候補: {', '.join(rivals[:2])}。"
            notes.append(line)

        if not notes:
            return []

        notes.insert(0, "- 以下はチーム対決の補助文脈。記事の軸は当日の順位差と走りに置き、必要な対立構図だけを薄く使うこと。")
        return notes

    def _get_light_leg_story_notes(self):
        context_root = self.all_data.get('leg_story_context') or {}
        leg_map = context_root.get('legs', {}) if isinstance(context_root, dict) else {}
        if not leg_map:
            return []

        active_legs = []
        for team in sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999):
            leg_num = team.get('currentLeg')
            if isinstance(leg_num, int) and leg_num not in active_legs:
                active_legs.append(leg_num)

        notes = []
        for leg_num in active_legs[:1]:
            context = leg_map.get(str(leg_num))
            if not context:
                continue
            summary = context.get('summary')
            dominant_notes = context.get('dominant_notes') or []
            pieces = []
            if summary:
                pieces.append(summary)
            if dominant_notes:
                pieces.append(dominant_notes[0])
            if pieces:
                notes.append(f"- 第{leg_num}区: " + " ".join(pieces))

        if not notes:
            return []

        notes.insert(0, "- 以下は当日走行区間の補助文脈。区間の性格づけとして短く使うこと。")
        return notes

    def build_user_prompt(self):
        """Builds the complete user prompt for the OpenAI API call."""
        realtime_data = self.all_data.get('realtime_report', {})
        race_day = realtime_data.get('raceDay', 'N/A')
        race_status_summary = "レース集計中"
        active_sorted = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
        if active_sorted:
            top_active = active_sorted[0]
            race_status_summary = f"走行中トップは第{top_active.get('currentLeg', 'N/A')}区、{top_active.get('runner', '走者不明')}がリード中"
        elif realtime_data.get('teams'):
            top_team = realtime_data['teams'][0]
            race_status_summary = "トップチームはゴールしました" if top_team.get('runner') == 'ゴール' else f"トップは第{top_team.get('currentLeg', 'N/A')}区を走行中"

        ekiden_data = self.all_data.get('ekiden_data', {})
        team_prefecture_list = []
        for team in ekiden_data.get('teams', []):
            team_name = team.get('name', '不明')
            prefectures = team.get('prefectures', '')
            team_prefecture_list.append(f"- {team_name}: {prefectures}")
        team_prefecture_text = "\n".join(team_prefecture_list)

        outline_data = self._load_outline_data()
        leg_configuration = self._format_leg_configuration(outline_data.get('legs', []))
        tournament_title = outline_data.get('title')
        details = outline_data.get('details', {}) if isinstance(outline_data, dict) else {}
        metadata = outline_data.get('metadata', {}) if isinstance(outline_data, dict) else {}
        start_date = details.get('startDateLabel') or details.get('startDate') or metadata.get('startDate')
        course_description = details.get('course')

        prompt_parts = [
            "# 大会コンテキスト",
            f"- 大会名: {tournament_title or '大会名称未設定'}",
            f"- スタート日: {start_date or '開始日未設定'}",
            f"- コース概要: {course_description or 'コース情報未設定'}",
            "- 読者は大会ルールを理解している前提で書くこと。",
            "- 走行距離と順位のルール説明は不要。",
            "- 出場校と担当都道府県:",
            team_prefecture_text or "- 情報なし",
            "- 区間構成:",
            leg_configuration,
            "",
            "# 本日の記事方針",
            "- 文字数は500字程度、ただし緊迫した局面では長くなっても良い",
            "- 見出しは4個程度、ただし緊迫した局面では増やしても良い",
            "- その日の最大テーマを最優先で描くこと。候補は首位の独走、上位のデッドヒート、中位混戦、シードライン攻防、大きな順位変動、好走者、交代・タスキリレー。",
            "- 上記のうち、実際に動きが大きいものを3から4点選んで重点的に書くこと。",
            "- 大学名、選手名は太字で扱うこと、選手名に必ず君づけすること(例:上武大学の佐野君、名古屋大の美濃君など)",
            "- 好走者には原則触れること。シード権ラインは接戦または順位変動がある場合に優先して触れること。",
            "- シード権ラインは大会終盤、またはその攻防が当日の主要テーマである場合にのみ大きく扱うこと。",
            "- 交代またはタスキリレーがあれば自然に触れること。",
            "- 監督コメントがある場合は、結果と結びつけて触れること。",
            "- 最後は『今日の総括』として短い締めを必ず入れること。",
            "- 『歴代区間記録の更新』が提示されている場合、その更新には必ず本文で触れること。",
            "",
            "# 本日のレース状況",
        ]
        prompt_parts.append(f"- 大会日: {race_day}日目")
        prompt_parts.append(f"- 現在のレース状況: {race_status_summary}")
        prompt_parts.append("- 本日の総合順位:")
        prompt_parts.append(self.format_ranking_table())

        story_angle = self._build_story_angle()
        if story_angle:
            prompt_parts.append("\n# 今日の焦点")
            prompt_parts.extend(story_angle)

        coverage_checklist = self.build_coverage_checklist()
        if coverage_checklist:
            prompt_parts.append("\n# カバレッジチェック")
            prompt_parts.extend(coverage_checklist)

        daily_notes = self.build_daily_notes(race_day)
        if daily_notes:
            prompt_parts.append("\n# 取材メモ")
            prompt_parts.extend(daily_notes)

        record_break_notes = self._build_record_break_notes(race_day)
        if record_break_notes:
            prompt_parts.append("\n# 歴代区間記録の更新")
            prompt_parts.extend(record_break_notes)

        relay_infos = self.format_relay_info()
        if relay_infos:
            prompt_parts.append("\n# 本日の主なタスキリレー")
            prompt_parts.extend(relay_infos)

        manager_comments = self.prepare_manager_comments()
        if manager_comments:
            prompt_parts.append("\n# 昨晩の監督コメント")
            prompt_parts.extend(manager_comments)

        team_story_notes = self._get_light_team_story_notes()
        if team_story_notes:
            prompt_parts.append("\n# 注目チームの対決文脈")
            prompt_parts.extend(team_story_notes)

        leg_story_notes = self._get_light_leg_story_notes()
        if leg_story_notes:
            prompt_parts.append("\n# 注目区間の文脈")
            prompt_parts.extend(leg_story_notes)

        player_story_notes = self._get_relevant_player_story_notes()
        if player_story_notes:
            prompt_parts.append("\n# 注目走者の個人実績")
            prompt_parts.extend(player_story_notes)

        continuity_notes = self._build_continuity_note()
        if continuity_notes:
            prompt_parts.append("\n# 前日からの文脈")
            prompt_parts.extend(continuity_notes)

        prompt_parts.append(
            "\n---\n"
            "# 出力形式\n"
            "- 1行目はタイトル。\n"
            "- 本文は見出し付きで2〜3章程度。\n"
            "- Markdown見出しは最大3個とし、最後に『■ 今日の総括』を必ず置くこと。\n"
            "- 過剰な箇条書きは使わない。\n"
            "- 熱量のあるスポーツ記事の文体で、350〜550字程度のMarkdown記事を作成すること。\n"
            "- 記事全体を現在走行中のチーム・走者の動きに集中させ、既にゴールしたチームや確定順位の回顧は避けること。\n"
            "- 走行中チーム同士の首位・シードライン・追い上げの構図を具体的な距離差や区間情報とともに描写すること。\n"
            "- 本日の距離が際立った走者・区間での躍動を必ず紹介し、Markdownの見出しや強調を適宜用いること。\n"
            "解説記事:"
        )
        return "\n".join(prompt_parts)

    def run(self):
        """Main execution logic."""
        print("日次振り返り解説の生成を開始します...")
        self.load_all_data()
        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt()

        print("------------------------------------")
        print("Geminiへのsystem prompt:")
        print(system_prompt)
        print("------------------------------------")
        print("Geminiへのuser prompt:")
        print(user_prompt)
        print("------------------------------------")

        if self.dry_run:
            print("\n--dry-runモードのため、ファイルへの書き込みは行わずに終了します。")
            return

        try:
            response = self.gemini_model.generate_content(user_prompt)
            raw_article_text = response.text.strip()
            print("記事をMarkdownでフォーマットしています...")
            article_text = self.format_article_with_markdown(raw_article_text)
            print("✅ Geminiによる解説記事の生成に成功しました。")
            prompt_payload = json.dumps(
                {"system": system_prompt, "user": user_prompt},
                ensure_ascii=False,
                indent=2
            )
            self._save_article_to_history(prompt_payload, raw_article_text)
        except Exception as e:
            error_message = str(e)
            retryable_model_error = (
                "models/" in error_message
                and "is not found" in error_message
                and self.model_name != self.DEFAULT_GEMINI_MODEL
            )
            if retryable_model_error:
                print(f"⚠️ 指定モデル '{self.model_name}' が利用できないため、既定モデルへフォールバックします。")
                try:
                    self._switch_gemini_model(self.DEFAULT_GEMINI_MODEL)
                    response = self.gemini_model.generate_content(user_prompt)
                    raw_article_text = response.text.strip()
                    print("記事をMarkdownでフォーマットしています...")
                    article_text = self.format_article_with_markdown(raw_article_text)
                    print("✅ Geminiによる解説記事の生成に成功しました。")
                    prompt_payload = json.dumps(
                        {"system": system_prompt, "user": user_prompt},
                        ensure_ascii=False,
                        indent=2
                    )
                    self._save_article_to_history(prompt_payload, raw_article_text)
                except Exception as retry_error:
                    print(f"❌ Gemini API呼び出し中にエラーが発生しました: {retry_error}")
                    article_text = "本日の解説記事は、システムの問題により生成できませんでした。ご了承ください。"
            else:
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
