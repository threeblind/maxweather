import json
import os
import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import unicodedata
from openai import OpenAI

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
NARRATIVE_STATE_FILE = DATA_DIR / 'race_narrative_state.json'

class DailySummaryGenerator:
    """
    Generates a daily summary article for the Ekiden race using an LLM.
    """
    DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.all_data = {}
        self.client = None
        self.narrative_state = {}

        load_dotenv()
        self.model_name = os.getenv("OPENAI_MODEL", self.DEFAULT_OPENAI_MODEL)
        self._setup_clients()
        self.load_narrative_state()

    def load_narrative_state(self):
        """race_narrative_state.jsonを読み込み、存在しない場合はデフォルト状態で初期化します。"""
        if not NARRATIVE_STATE_FILE.exists():
            print(f"情報: {NARRATIVE_STATE_FILE} が存在しないため、デフォルト状態で初期化します。")
            self.narrative_state = {
                "schema_version": 1,
                "updated_day": 0,
                "main_story": {},
                "ongoing_battles": [],
                "momentum": [],
                "runner_threads": [],
                "resolved_stories": []
            }
            return

        try:
            with open(NARRATIVE_STATE_FILE, 'r', encoding='utf-8') as f:
                self.narrative_state = json.load(f)
            print(f"✅ 物語状態をロードしました。updated_day={self.narrative_state.get('updated_day')}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告: {NARRATIVE_STATE_FILE} の読み込み中にエラーが発生しました: {e}。新規に初期化します。")
            self.narrative_state = {
                "schema_version": 1,
                "updated_day": 0,
                "main_story": {},
                "ongoing_battles": [],
                "momentum": [],
                "runner_threads": [],
                "resolved_stories": []
            }

    def save_narrative_state(self):
        """現在の物語状態を race_narrative_state.json に保存します。"""
        if self.dry_run:
            print("[dry-run] 物語状態の保存はスキップします。")
            return
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(NARRATIVE_STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.narrative_state, f, indent=2, ensure_ascii=False)
            print(f"✅ 物語状態を '{NARRATIVE_STATE_FILE}' に保存しました。")
        except IOError as e:
            print(f"エラー: 物語状態の保存に失敗しました: {e}")

    def _setup_clients(self):
        """OpenAI APIクライアントを初期化します。"""
        if not self.dry_run:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                print("エラー: 環境変数 'OPENAI_API_KEY' が設定されていません。")
                exit(1)

            self.client = OpenAI(api_key=api_key)
            print(f"✅ OpenAIクライアントを初期化しました。model={self.model_name}")

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

    def calculate_race_metrics(self):
        """Python側で現在順位、前日順位、首位差、シード差などの数値を計算します。"""
        realtime_data = self.all_data.get('realtime_report', {})
        race_day = realtime_data.get('raceDay')
        try:
            day_idx = int(race_day) - 1
        except (TypeError, ValueError):
            day_idx = 0

        teams = self._get_regular_teams()
        if not teams:
            return {}

        # 順位でソート
        teams_sorted = sorted(teams, key=lambda t: t.get('overallRank') or 999)

        # 1位と2位
        lead_battle = None
        if len(teams_sorted) >= 2:
            t1, t2 = teams_sorted[0], teams_sorted[1]
            gap_current = t1.get('totalDistance', 0.0) - t2.get('totalDistance', 0.0)

            # 前日のgapを取得
            gap_prev = None
            t1_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t1['name']), None)
            t2_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t2['name']), None)
            if t1_hist and t2_hist and day_idx > 0:
                d1_hist_len = len(t1_hist.get('distances', []))
                d2_hist_len = len(t2_hist.get('distances', []))
                if d1_hist_len >= day_idx and d2_hist_len >= day_idx:
                    gap_prev = t1_hist['distances'][day_idx-1] - t2_hist['distances'][day_idx-1]

            lead_battle = {
                "team1": t1['name'],
                "team2": t2['name'],
                "gap_current": gap_current,
                "gap_prev": gap_prev,
                "change": (gap_current - gap_prev) if gap_prev is not None else None
            }

        # シード争い (10位と11位)
        seed_battle = None
        t10 = next((t for t in teams_sorted if t.get('overallRank') == 10), None)
        t11 = next((t for t in teams_sorted if t.get('overallRank') == 11), None)
        if t10 and t11:
            gap_current = t10.get('totalDistance', 0.0) - t11.get('totalDistance', 0.0)
            gap_prev = None
            t10_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t10['name']), None)
            t11_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t11['name']), None)
            if t10_hist and t11_hist and day_idx > 0:
                if len(t10_hist.get('distances', [])) >= day_idx and len(t11_hist.get('distances', [])) >= day_idx:
                    gap_prev = t10_hist['distances'][day_idx-1] - t11_hist['distances'][day_idx-1]

            seed_battle = {
                "team10": t10['name'],
                "team11": t11['name'],
                "gap_current": gap_current,
                "gap_prev": gap_prev,
                "change": (gap_current - gap_prev) if gap_prev is not None else None
            }

        # 各チームの順位変化
        rank_changes = {}
        for t in teams_sorted:
            prev_rank = t.get('previousRank')
            curr_rank = t.get('overallRank')
            if prev_rank and curr_rank:
                rank_changes[t['name']] = {
                    "prev": prev_rank,
                    "curr": curr_rank,
                    "diff": prev_rank - curr_rank # 正の値は上昇、負の値は下降
                }

        return {
            "race_day": int(race_day) if race_day else 1,
            "lead_battle": lead_battle,
            "seed_battle": seed_battle,
            "rank_changes": rank_changes
        }

    def format_ranking_table(self):
        """総合順位をMarkdownテーブル形式で整形する。"""
        teams = sorted(self._get_regular_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return "公式チーム情報はありません。"

        header = "| 順位 | 大学名 | 状態 | 現在走者 | 本日距離(順位) | 総合距離 | トップ差 | 順位変動(前日) |"
        divider = "|:---|:---|:---|:---|:---|:---|:---|:---|"
        rows = [header, divider]

        top_distance = teams[0].get('totalDistance', 0.0)
        for team in teams:
            total_distance = team.get('totalDistance', 0.0)
            gap = "----" if team.get('overallRank') == 1 else f"-{top_distance - total_distance:.1f}km"
            previous_rank = team.get("previousRank", 0)
            rank_change = self._rank_move_label(previous_rank, team.get('overallRank'))
            finish_day = team.get('finishDay')
            status = f"ゴール済み（{finish_day}日目）" if finish_day else "走行中"

            row = [
                team.get('overallRank', ''),
                team.get('name', ''),
                status,
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
        article_text = re.sub(r'^■\s*(.+)$', r'### \1', article_text, flags=re.MULTILINE)
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

    def _build_finish_status_notes(self, race_day):
        teams = sorted(self._get_regular_teams(), key=lambda t: t.get('overallRank') or 999)
        if not teams:
            return []

        try:
            race_day_int = int(race_day)
        except (TypeError, ValueError):
            race_day_int = None

        notes = []
        champion = next((team for team in teams if team.get('overallRank') == 1), None)
        if champion and champion.get('finishDay'):
            notes.append(
                f"- 総合1位は{champion.get('name')}で、{champion.get('finishDay')}日目にフィニッシュ済み。"
                "他大学が後日フィニッシュしても、この事実を覆さない。"
            )

        finished_teams = [team for team in teams if team.get('finishDay')]
        if finished_teams:
            notes.append(
                "- ゴール済み順位: "
                + "、".join(
                    f"{team.get('overallRank')}位 {team.get('name')}（{team.get('finishDay')}日目）"
                    for team in finished_teams[:6]
                )
            )

        if race_day_int is not None:
            today_finishers = [team for team in teams if team.get('finishDay') == race_day_int]
            if today_finishers:
                notes.append(
                    "- 本日フィニッシュ: "
                    + "、".join(
                        f"{team.get('name')}は総合{team.get('overallRank')}位でフィニッシュ"
                        for team in today_finishers
                    )
                    + "。総合1位・優勝・首位フィニッシュとは書かないこと（総合1位の場合を除く）。"
                )

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
            "- ただし前回記事の順位表現は正本ではない。総合順位・ゴール順・優勝表現は必ず本日の総合順位表とゴール済み順位を正とすること。"
        ]

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
        """順位表や今日の焦点に含まれない、当日固有の出来事だけを返す。"""
        notes = []
        substitutions = self._load_recent_substitution_logs()
        if substitutions:
            for entry in substitutions:
                notes.append(f"- 選手交代: {entry['timestamp']} {entry['team_name']}が {entry['runner_out']} → {entry['runner_in']} に交代。")

        leg_award_notes = self._build_leg_award_notes(race_day)
        notes.extend(leg_award_notes)

        return notes

    def build_system_prompt(self):
        return "\n".join([
            "あなたは「高温大学駅伝」の実況アナウンサー兼解説者です。",
            "出力は日本語のMarkdown記事です。",
            "",
            "必ず守ること:",
            "- 提供されたデータにない情報を創作しない",
            "- 総合順位が上がっていないチームに「浮上」「ジャンプアップ」「逆転」を使わない",
            "- 監督コメントは提供された場合のみ言及する",
            "- 既にゴールしたチームには、当日新規性がある場合を除き重点的に触れない",
            "- 当日フィニッシュしたチームが総合1位でない場合、優勝・首位・先頭フィニッシュ・大会を支配した、とは書かない",
            "- ゴール済み順位と走行中トップを混同しない",
            "- 記事は事実優先で書き、数字や順位差は提供データを優先する",
            "",
            "文体:",
            "- テレビのスポーツハイライトのように、興奮と緊迫感を出す",
            "- 各トピックは短い実況調の一文で始め、その後に数字を使った解説を続ける",
            "- 大げさな形容を連発せず、順位や距離差そのものをドラマとして見せる",
            "- 具体的な大学名、選手名、距離差、区間を自然に織り込む",
        ])

    def select_today_themes(self, metrics):
        """Python側でレース状況から複数の『ゾーン候補』を構造化して生成します。
        各候補は排他的ではなく、意味のある順位帯ごとに重複を許容して生成され、
        AIが全体の状況を見て統合・採用を判断します。"""
        zones = []

        realtime_data = self.all_data.get('realtime_report', {})
        teams_data = realtime_data.get('teams', [])

        # 当日フィニッシュしたチームの情報収集
        goal_teams = [
            t for t in teams_data
            if t.get('runner') == 'ゴール'
            and not t.get('is_shadow_confederation')
            and t.get('finishDay') == metrics.get('race_day')
        ]
        if goal_teams:
            names = [t['name'] for t in goal_teams]
            detail_parts = []
            rank_changes = {}
            today_distances = {}
            for t in goal_teams:
                rank_str = f"総合{t.get('overallRank')}位"
                detail_parts.append(f"{t['name']}が{rank_str}でフィニッシュ")
                prev = t.get('previousRank')
                curr = t.get('overallRank')
                if prev and curr:
                    rank_changes[t['name']] = prev - curr
                today_distances[t['name']] = t.get('todayDistance', 0.0)

            min_rank = min(t.get('overallRank', 999) for t in goal_teams)
            max_rank = max(t.get('overallRank', 0) for t in goal_teams)

            zones.append({
                "zone": "ゴール・フィニッシュ",
                "teams": names,
                "rank_range": [min_rank, max_rank],
                "facts": {
                    t['name']: {
                        "totalDistance": t.get('totalDistance', 0.0),
                        "todayDistance": t.get('todayDistance', 0.0),
                        "rank_change": rank_changes.get(t['name'], 0)
                    } for t in goal_teams
                },
                "gaps": {},
                "reason": f"{'、'.join(detail_parts)}。目標のフィニッシュテープを切り、全区間を完走しました。"
            })

        # 歴代記録更新のゾーン候補
        record_breaks = self._build_record_break_notes(metrics.get('race_day'))
        if record_breaks:
            rb_teams = []
            for rb in record_breaks:
                for t in self._get_regular_teams():
                    if t['name'] in rb and t['name'] not in rb_teams:
                        rb_teams.append(t['name'])
            zones.append({
                "zone": "歴代記録更新",
                "teams": rb_teams,
                "rank_range": [],
                "facts": {},
                "gaps": {},
                "reason": " / ".join(record_breaks)
            })

        # 走行中の公式チーム情報を取得
        active_teams = self._get_active_teams()
        active_teams_sorted = sorted(active_teams, key=lambda t: t.get('overallRank') or 999)

        if not active_teams_sorted:
            return zones

        # 共通データ生成用ヘルパー
        def build_facts_and_gaps(teams_list, zone_name):
            facts = {}
            for t in teams_list:
                prev = t.get('previousRank')
                curr = t.get('overallRank')
                facts[t['name']] = {
                    "overallRank": curr,
                    "totalDistance": t.get('totalDistance', 0.0),
                    "todayDistance": t.get('todayDistance', 0.0),
                    "rank_change": (prev - curr) if (prev and curr) else 0
                }

            gaps = {}
            # 首位との差
            leader_team = active_teams_sorted[0]
            gaps["gap_to_leader"] = {
                t['name']: float(f"{leader_team.get('totalDistance', 0.0) - t.get('totalDistance', 0.0):.2f}")
                for t in teams_list if t['name'] != leader_team['name']
            }

            # 帯内での最大差
            distances = [t.get('totalDistance', 0.0) for t in teams_list]
            if distances:
                gaps["max_spread_km"] = float(f"{max(distances) - min(distances):.2f}")
            else:
                gaps["max_spread_km"] = 0.0

            return facts, gaps

        # --- A) 首位状況 (1位と2位) ---
        lead_teams = [t for t in active_teams_sorted if t.get('overallRank') in [1, 2]]
        if len(lead_teams) >= 2:
            facts, gaps = build_facts_and_gaps(lead_teams, "首位状況")
            gap_1to2 = lead_teams[0].get('totalDistance', 0.0) - lead_teams[1].get('totalDistance', 0.0)
            gaps["gap_1st_to_2nd_km"] = float(f"{gap_1to2:.2f}")

            # 前日のgapを取得して拡大・縮小トレンドを計算
            day_idx = metrics.get('race_day', 1) - 1
            gap_prev = None
            t1_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == lead_teams[0]['name']), None)
            t2_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == lead_teams[1]['name']), None)
            if t1_hist and t2_hist and day_idx > 0:
                if len(t1_hist.get('distances', [])) >= day_idx and len(t2_hist.get('distances', [])) >= day_idx:
                    gap_prev = t1_hist['distances'][day_idx-1] - t2_hist['distances'][day_idx-1]

            if gap_prev is not None:
                diff_prev = gap_1to2 - gap_prev
                gaps["gap_trend"] = "拡大" if diff_prev > 0 else "縮小"
                gaps["gap_change_km"] = float(f"{abs(diff_prev):.2f}")
                trend_text = f"（前日差 {gap_prev:.1f}km から首位差が {abs(diff_prev):.1f}km {gaps['gap_trend']}）"
            else:
                trend_text = ""

            reason = f"1位{lead_teams[0]['name']}は累積距離{lead_teams[0]['totalDistance']:.1f}km、2位{lead_teams[1]['name']}は{lead_teams[1]['totalDistance']:.1f}km、差は{gap_1to2:.1f}km{trend_text}。"

            zones.append({
                "zone": "首位状況",
                "teams": [t['name'] for t in lead_teams],
                "rank_range": [1, 2],
                "facts": facts,
                "gaps": gaps,
                "reason": reason
            })

        # --- B) 上位状況 (2位〜5位) ---
        top_chase_teams = [t for t in active_teams_sorted if t.get('overallRank') and 2 <= t['overallRank'] <= 5]
        if top_chase_teams:
            facts, gaps = build_facts_and_gaps(top_chase_teams, "上位状況")
            min_rank = min(t.get('overallRank') for t in top_chase_teams)
            max_rank = max(t.get('overallRank') for t in top_chase_teams)
            reason = f"総合{min_rank}位から{max_rank}位のチーム（{', '.join([t['name'] for t in top_chase_teams])}）の累積距離。集団内の最大差は{gaps['max_spread_km']:.1f}km。"
            zones.append({
                "zone": "上位状況",
                "teams": [t['name'] for t in top_chase_teams],
                "rank_range": [min_rank, max_rank],
                "facts": facts,
                "gaps": gaps,
                "reason": reason
            })

        # --- C) 中位状況 (4位〜8位) ---
        mid_battle_teams = [t for t in active_teams_sorted if t.get('overallRank') and 4 <= t['overallRank'] <= 8]
        if mid_battle_teams:
            facts, gaps = build_facts_and_gaps(mid_battle_teams, "中位状況")
            min_rank = min(t.get('overallRank') for t in mid_battle_teams)
            max_rank = max(t.get('overallRank') for t in mid_battle_teams)
            reason = f"総合{min_rank}位〜{max_rank}位のチーム（{', '.join([t['name'] for t in mid_battle_teams])}）の累積距離。集団内の最大差は{gaps['max_spread_km']:.1f}km。"
            zones.append({
                "zone": "中位状況",
                "teams": [t['name'] for t in mid_battle_teams],
                "rank_range": [min_rank, max_rank],
                "facts": facts,
                "gaps": gaps,
                "reason": reason
            })

        # --- D) シード境界状況 (9位〜12位) ---
        seed_boundary_teams = [t for t in active_teams_sorted if t.get('overallRank') and 9 <= t['overallRank'] <= 12]
        if seed_boundary_teams:
            facts, gaps = build_facts_and_gaps(seed_boundary_teams, "シード境界状況")
            min_rank = min(t.get('overallRank') for t in seed_boundary_teams)
            max_rank = max(t.get('overallRank') for t in seed_boundary_teams)

            # 10位と11位の距離差を明示
            t10 = next((t for t in active_teams_sorted if t.get('overallRank') == 10), None)
            t11 = next((t for t in active_teams_sorted if t.get('overallRank') == 11), None)
            if t10 and t11:
                gap_10_11 = t10.get('totalDistance', 0.0) - t11.get('totalDistance', 0.0)
                gaps["gap_10th_to_11th_km"] = float(f"{gap_10_11:.2f}")

                # 前日差を取得してトレンド計算
                day_idx = metrics.get('race_day', 1) - 1
                gap_prev_10_11 = None
                t10_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t10['name']), None)
                t11_hist = next((t for t in self.all_data.get('rank_history', {}).get('teams', []) if t['name'] == t11['name']), None)
                if t10_hist and t11_hist and day_idx > 0:
                    if len(t10_hist.get('distances', [])) >= day_idx and len(t11_hist.get('distances', [])) >= day_idx:
                        gap_prev_10_11 = t10_hist['distances'][day_idx-1] - t11_hist['distances'][day_idx-1]

                if gap_prev_10_11 is not None:
                    diff_prev_10_11 = gap_10_11 - gap_prev_10_11
                    gaps["gap_10th_to_11th_trend"] = "拡大" if diff_prev_10_11 > 0 else "縮小"
                    gaps["gap_10th_to_11th_change_km"] = float(f"{abs(diff_prev_10_11):.2f}")
                    trend_text = f"（前日差 {gap_prev_10_11:.1f}km から {abs(diff_prev_10_11):.1f}km {gaps['gap_10th_to_11th_trend']}）"
                else:
                    trend_text = ""
                reason = f"10位{t10['name']}と11位{t11['name']}の累積距離の差は{gap_10_11:.1f}km{trend_text}。"
            else:
                reason = f"総合{min_rank}位から{max_rank}位のチーム累積距離。集団内の最大差は{gaps['max_spread_km']:.1f}km。"

            zones.append({
                "zone": "シード境界状況",
                "teams": [t['name'] for t in seed_boundary_teams],
                "rank_range": [min_rank, max_rank],
                "facts": facts,
                "gaps": gaps,
                "reason": reason
            })

        # --- E) シード圏外 (13位以下から特筆校のみ) ---
        lower_teams = [t for t in active_teams_sorted if t.get('overallRank') and t['overallRank'] >= 13]
        if lower_teams:
            # 全体の本日距離から閾値（上位20%の距離、または上位3位の距離）を算出
            all_today_distances = sorted([t.get('todayDistance', 0.0) for t in active_teams], reverse=True)
            dist_threshold = 999.0
            if all_today_distances:
                limit_idx = max(2, len(all_today_distances) // 5)
                dist_threshold = all_today_distances[min(limit_idx, len(all_today_distances)-1)]

            t10 = next((t for t in active_teams_sorted if t.get('overallRank') == 10), None)
            day_idx = metrics.get('race_day', 1) - 1

            notable_lower_teams = []
            for t in lower_teams:
                is_notable = False
                reasons_notable = []

                prev = t.get('previousRank')
                curr = t.get('overallRank')
                if prev and curr and prev - curr >= 3:
                    is_notable = True
                    reasons_notable.append(f"順位上昇（前日比+{prev - curr}）")

                today_dist = t.get('todayDistance', 0.0)
                if today_dist >= dist_threshold and today_dist > 0:
                    is_notable = True
                    reasons_notable.append(f"本日走行距離（{today_dist:.1f}km）")

                if t10 and day_idx > 0:
                    gap_curr = t.get('totalDistance', 0.0) - t10.get('totalDistance', 0.0)
                    t_hist = next((h for h in self.all_data.get('rank_history', {}).get('teams', []) if h['name'] == t['name']), None)
                    t10_hist = next((h for h in self.all_data.get('rank_history', {}).get('teams', []) if h['name'] == t10['name']), None)
                    if t_hist and t10_hist:
                        if len(t_hist.get('distances', [])) >= day_idx and len(t10_hist.get('distances', [])) >= day_idx:
                            gap_prev = t_hist['distances'][day_idx-1] - t10_hist['distances'][day_idx-1]
                            if gap_curr > gap_prev:
                                is_notable = True
                                reasons_notable.append(f"シード差縮小（本日{abs(gap_curr):.1f}km差、{gap_curr - gap_prev:.1f}km縮小）")

                if is_notable:
                    notable_lower_teams.append((t, reasons_notable))

            if notable_lower_teams:
                facts = {}
                for t, _ in notable_lower_teams:
                    prev = t.get('previousRank')
                    curr = t.get('overallRank')
                    facts[t['name']] = {
                        "overallRank": curr,
                        "totalDistance": t.get('totalDistance', 0.0),
                        "todayDistance": t.get('todayDistance', 0.0),
                        "rank_change": (prev - curr) if (prev and curr) else 0
                    }

                gaps = {}
                leader_team = active_teams_sorted[0]
                gaps["gap_to_leader"] = {
                    t['name']: float(f"{leader_team.get('totalDistance', 0.0) - t.get('totalDistance', 0.0):.2f}")
                    for t, _ in notable_lower_teams
                }
                if t10:
                    gaps["gap_to_10th"] = {
                        t['name']: float(f"{t10.get('totalDistance', 0.0) - t.get('totalDistance', 0.0):.2f}")
                        for t, _ in notable_lower_teams
                    }

                reason_parts = [f"{t['name']}の{'/'.join(reasons)}" for t, reasons in notable_lower_teams]
                reason = f"シード圏外（13位以下）における特筆値を持つチーム情報: {', '.join(reason_parts)}。"

                zones.append({
                    "zone": "シード圏外状況",
                    "teams": [t['name'] for t, _ in notable_lower_teams],
                    "rank_range": [min(t.get('overallRank') for t, _ in notable_lower_teams), max(t.get('overallRank') for t, _ in notable_lower_teams)],
                    "facts": facts,
                    "gaps": gaps,
                    "reason": reason
                })

        return zones

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
        for runner_name in selected[:2]:
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

    def _get_light_team_story_notes(self, selected_themes):
        """今日の選定テーマに関係するチームを優先して、チーム文脈（最大2校）を抽出します。"""
        context_root = self.all_data.get('team_story_context') or {}
        team_map = context_root.get('teams', {}) if isinstance(context_root, dict) else {}
        if not team_map:
            return []

        related_teams = []
        for theme in selected_themes:
            details = theme.get('details', '') or theme.get('reason', '')
            for t_name in theme.get('teams', []):
                if t_name not in related_teams:
                    related_teams.append(t_name)
            for t_name in team_map.keys():
                if t_name in details and t_name not in related_teams:
                    related_teams.append(t_name)

        if len(related_teams) < 2:
            teams = sorted(self._get_active_teams(), key=lambda t: t.get('overallRank') or 999)
            for t in teams:
                name = t.get('name')
                if name in team_map and name not in related_teams:
                    related_teams.append(name)
                    if len(related_teams) >= 2:
                        break

        notes = []
        for team_name in related_teams[:2]:
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

        notes.insert(0, "- 以下はチーム対決の補助文脈（最大2校）。記事の軸は当日の順位差と走りに置き、必要な対立構図だけを薄く使うこと。")
        return notes

    def _get_light_leg_story_notes(self):
        """現在走行中の区間（最大1区間）の補助文脈を抽出します。"""
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

        notes.insert(0, "- 以下は当日走行区間の補助文脈（最大1区間）。区間の性格づけとして短く使うこと。")
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

    def build_user_prompt(self, metrics):
        """Builds the complete user prompt for the OpenAI API call using selected themes."""
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

        outline_data = self._load_outline_data()
        tournament_title = outline_data.get('title')
        details = outline_data.get('details', {}) if isinstance(outline_data, dict) else {}
        metadata = outline_data.get('metadata', {}) if isinstance(outline_data, dict) else {}
        start_date = details.get('startDateLabel') or details.get('startDate') or metadata.get('startDate')
        course_description = details.get('course')

        # 今日のテーマ候補ゾーン
        selected_zones = self.select_today_themes(metrics)
        zones_lines = []
        for i, zone in enumerate(selected_zones, 1):
            teams_str = ", ".join(zone["teams"])
            rank_range_str = f"{zone['rank_range'][0]}〜{zone['rank_range'][1]}位" if zone["rank_range"] else "なし"

            # facts から各チームの情報を構築
            facts_lines = []
            for team, f in zone.get("facts", {}).items():
                change = f.get("rank_change", 0)
                change_str = f"{'+' if change > 0 else ''}{change}" if change != 0 else "維持"
                facts_lines.append(
                    f"{team}(順位:{f.get('overallRank', '不明')}位 / 累計:{f.get('totalDistance', 0.0):.1f}km / 本日:{f.get('todayDistance', 0.0):.1f}km / 変動:{change_str})"
                )
            facts_str = ", ".join(facts_lines)

            # gaps から情報を構築
            gaps_list = []
            gaps_dict = zone.get("gaps", {})
            if "max_spread_km" in gaps_dict:
                gaps_list.append(f"集団内最大差: {gaps_dict['max_spread_km']:.1f}km")
            if "gap_1st_to_2nd_km" in gaps_dict:
                gaps_list.append(f"1位→2位差: {gaps_dict['gap_1st_to_2nd_km']:.1f}km")
            if "gap_10th_to_11th_km" in gaps_dict:
                gaps_list.append(f"10位→11位差: {gaps_dict['gap_10th_to_11th_km']:.1f}km")
            gaps_str = " / ".join(gaps_list) if gaps_list else "なし"

            zone_text = (
                f"{i}. 【{zone['zone']}】\n"
                f"   - 対象大学: {teams_str}\n"
                f"   - 順位範囲: {rank_range_str}\n"
                f"   - チーム詳細: {facts_str if facts_str else 'なし'}\n"
                f"   - 距離差指標: {gaps_str}\n"
                f"   - 注目理由: {zone['reason']}"
            )
            zones_lines.append(zone_text)
        themes_text = "\n".join(zones_lines)

        prompt_parts = [
            "# 大会コンテキスト",
            f"- 大会名: {tournament_title or '大会名称未設定'}",
            f"- スタート日: {start_date or '開始日未設定'}",
            f"- コース概要: {course_description or 'コース情報未設定'}",
            "- 読者は大会ルールを理解している前提で書くこと。",
            "- 走行距離と順位のルール説明は不要。",
            "",
            "# 記事の内容構成・ルール",
            "- 提示された「今日のテーマ候補ゾーン」から、レース全体の構造を見て採用・統合・小見出し数を判断して書くこと。",
            "- 記事全体を現在走行中のチーム・走者の動きに集中させ、既にゴールしたチームの回顧は避けること。ただし当日フィニッシュは新規性として扱ってよい。",
            "- 当日フィニッシュしたチームは、必ず総合順位を確認してから表現すること。総合2位以下なら『2位でフィニッシュ』のように順位を明記し、『先頭』『首位』『優勝』とは書かないこと。",
            "- 走行中チームの首位・シードライン・追い上げの構図は具体的な距離差や区間情報とともに描写すること。",
            "- 大学名、選手名は太字で扱うこと。選手名には必ず「君」付けすること（例:**上武大学**の**佐野君**）。",
            "- 選手名の先頭に数字がある場合（例: 1甲佐）、出力時は数字を削除して名前のみ（甲佐君）にすること。",
            "",
            "# 今日のテーマ候補ゾーン",
            themes_text or "- 特になし",
            "",
            "# 本日のレース状況",
            f"- 大会日: {race_day}日目",
            f"- 現在のレース状況: {race_status_summary}",
        ]

        finish_status_notes = self._build_finish_status_notes(race_day)
        if finish_status_notes:
            prompt_parts.append("\n# ゴール済み順位と本日フィニッシュ")
            prompt_parts.extend(finish_status_notes)

        prompt_parts.append("- 本日の総合順位:")
        prompt_parts.append(self.format_ranking_table())

        # 物語状態から継続中のコンテキストを追加
        narrative_notes = []
        state = self.narrative_state
        if state.get('main_story'):
            m = state['main_story']
            started = m.get('started_day', 1)
            if started < int(race_day):
                narrative_notes.append(f"- 前回からの主要テーマ: {m.get('summary')} (開始: {started}日目 ※前回値として参照)")
            else:
                narrative_notes.append(f"- 今日の主要テーマ: {m.get('summary')}")

        if state.get('ongoing_battles'):
            for b in state['ongoing_battles']:
                gap_val = b.get('last_observed_gap_km') or b.get('previous_gap_km', 0.0)
                narrative_notes.append(f"- 継続中の攻防: {b.get('summary')} (開始: {b.get('started_day')}日目、前回観測時点の差: {gap_val:.1f}km ※前回値として参照)")

        if state.get('momentum'):
            for mo in state['momentum']:
                narrative_notes.append(f"- 勢いのあるチーム: {mo.get('team')} ({mo.get('summary')}、開始: {mo.get('started_day')}日目 ※前回値として参照)")

        if state.get('runner_threads'):
            for r in state['runner_threads']:
                narrative_notes.append(f"- 注目選手スレッド: {r.get('team')}の{r.get('runner')}君 ({r.get('summary')}、開始: {r.get('started_day')}日目)")

        resolved_today = [s for s in state.get('resolved_stories', []) if s.get('resolved_day') == int(race_day)]
        if resolved_today:
            narrative_notes.append("- 本日決着した物語:")
            for s in resolved_today[:2]:
                narrative_notes.append(f"  * {s.get('summary')} (理由: {s.get('reason')})")

        if narrative_notes:
            prompt_parts.append("\n# 継続中の物語（race_narrative_state）")
            prompt_parts.extend(narrative_notes)

        daily_notes = self.build_daily_notes(race_day)
        if daily_notes:
            prompt_parts.append("\n# 取材メモ")
            prompt_parts.extend(daily_notes)

        relay_infos = self.format_relay_info()
        if relay_infos:
            prompt_parts.append("\n# 本日の主なタスキリレー")
            prompt_parts.extend(relay_infos)

        manager_comments = self.prepare_manager_comments()
        if manager_comments:
            prompt_parts.append("\n# 昨晩の監督コメント")
            prompt_parts.extend(manager_comments)

        team_story_notes = self._get_light_team_story_notes(selected_zones)
        if team_story_notes:
            prompt_parts.append("\n# 注目チームの対決文脈")
            prompt_parts.extend(team_story_notes)

        leg_story_notes = self._get_light_leg_story_notes()
        if leg_story_notes:
            prompt_parts.append("\n# 注目区間の文脈")
            prompt_parts.extend(leg_story_notes)

        player_story_notes = self._get_relevant_player_story_notes()
        if player_story_notes:
            prompt_parts.append("\n# 注目走者の個人実績 (最大2名まで活用可)")
            prompt_parts.extend(player_story_notes)

        prompt_parts.append(
            "\n---\n"
            "# 出力フォーマットと文体\n"
            "- 全体の文字数は1400〜2600字程度（小見出し数に応じて可変）。\n"
            "- 1行目はタイトル（『# 』を使用）。\n"
            "- 2行目以降は、レース全体を象徴するメイン見出し（『### 』）を1つ、その下に各トピックの小見出し（『#### 』）を2〜4つ書くこと（箇条書きは多用しない）。\n"
            "- 小見出しの数は2〜4件で可変とする（大きな争点が少ない日は2件、複数の独立した争点がある日は3〜4件）。件数を満たすための水増しは禁止する。\n"
            "- テーマ候補ゾーンの中から、どのゾーンを採用・統合して小見出しを作るかは、レース全体の構造を見て判断すること。\n"
            "- 構成判断および記述ルール：\n"
            "  - 順位帯を機械的に網羅しないこと。\n"
            "  - 隣接順位のチームは「争い」として統合し、同一の上位集団を2〜3つの小見出しに分割しないこと（近接した上位校を別々の小見出しに分けない）。\n"
            "  - 固定距離だけで評価語を決めず、レース進行と各種変化を総合判断すること。現在の累積距離差、前日終値との差および変化、前回観測時点との差および変化、当日走行距離、順位変動、大会日数、現在区間などを総合して、レース状況（「独走」「接戦」「追走」など）を相対的に判断すること。同じチームや争いを重複して小見出しにしないこと。\n"
            "  - 首位が独走状態の場合、首位への言及は簡潔に留め、後方の追走集団の接戦を主要テーマ（見出し本文）にすること。\n"
            "  - 大幅順位上昇や本日最長距離は、原則として所属するゾーンのテーマを補強する材料として記述すること。\n"
            "  - レース全体に意味のある動きがあれば、中位、シード境界、圏外のゾーンにも視野を広げること。\n"
            "  - 提供された事実のないドラマや因果関係は作らないこと。\n"
            "- 各トピックの見出しタイトルは簡潔に保ち、長文化しないこと。\n"
            "- 各トピック本文の文字数は400〜500字程度を目安とすること。\n"
            "- 各トピック本文は以下の構成で詳細に記述すること：\n"
            "  1. 冒頭に短い実況調の一文（『追いつかせない！』のような表現）を1文だけ置く\n"
            "  2. 現在の具体的な順位・距離・首位差などの数値を記述する\n"
            "  3. 前日からの順位変動や、前日から継続している物語の展開を記述する\n"
            "  4. 選手・チーム・区間背景のうち、提供された関連する補助情報を織り込んで解説を深く詳細に記述すること\n"
            "- 同じ順位や距離の数値を別の段落や文章で重複して繰り返すことで字数を水増ししないこと。\n"
            "- 提供されたデータやコンテキストにない、選手の心理状態、天候、観客の反応、将来のレース結果などを想像で創作しないこと。\n"
            "- 最後の小見出しは必ず『#### 今日の総括・明日への展望』とし、一日の軌跡、当日の全体構図、継続中の争点、翌日の注目点までを約600字程度を目安に記述すること（本文の単なる言い換えにしないこと）。\n"
            "- 各見出しは、何が起きたかが一読で分かり、かつドラマチックな表現を含めること。\n"
            "解説記事:"
        )
        return "\n".join(prompt_parts)


    def validate_generated_article(self, article_text, metrics):
        """生成された記事の内容について簡易的な事実検証を行います。
        検証に問題がある場合は警告を出力し、Falseを返します。"""
        ekiden_data = self.all_data.get('ekiden_data', {})

        # Markdown太字装飾（**）を前処理で除去したプレーンテキストを生成
        plain_article = re.sub(r'\*\*([^*]+)\*\*', r'\1', article_text)

        # 1. マスタデータの準備
        valid_teams = {t.get('name') for t in ekiden_data.get('teams', []) if t.get('name')}
        valid_teams_fuzzy = set(valid_teams)
        for t in valid_teams:
            valid_teams_fuzzy.add(t.replace('大学', '大'))
            if t.endswith('大学'):
                valid_teams_fuzzy.add(t[:-2])

        valid_runners = set()
        for t in ekiden_data.get('teams', []):
            for member_type in ['runners', 'substitutes', 'substituted_out']:
                valid_runners.update(
                    p.get('name') for p in t.get(member_type, []) if isinstance(p, dict) and p.get('name')
                )
        plain_runners = {re.sub(r'（.+）', '', name).strip() for name in valid_runners if name}
        plain_runners = {re.sub(r'^\d+', '', name).strip() for name in plain_runners}
        valid_runners.update(plain_runners)

        valid_runners_fuzzy = set(valid_runners)
        for name in valid_runners:
            valid_runners_fuzzy.add(name.replace('選手', '').replace('君', '').strip())

        warnings = []

        # 2. 本文全体から大学名・選手名と思われる箇所を抽出して照合 (非太字も含む、装飾除去済みテキストを使用)
        team_candidates = re.findall(r'([\u4e00-\u9faf\u30a0-\u30ff]{2,}(?:大学|大))(?:[がはのを受けに]|$)', plain_article)
        for cand in team_candidates:
            clean_cand = cand.strip()
            if clean_cand in ["大会", "大差", "最大", "重大", "東大", "京大", "全国大学"] or not clean_cand:
                continue
            if clean_cand.endswith('大') and len(clean_cand) <= 2:
                continue
            if clean_cand not in valid_teams_fuzzy:
                stem = clean_cand[:-1] if clean_cand.endswith('大') else clean_cand[:-2]
                if stem not in valid_teams_fuzzy:
                    warnings.append(f"マスタに存在しない大学名と思われる表記: {cand}")

        runner_candidates = re.findall(r'([\u4e00-\u9faf\u30a0-\u30ff]{2,}(?:君|選手))(?:[がはのを受けに]|$)', plain_article)
        exclude_prefixes = ["注目", "両", "各", "全", "有力", "先頭", "出場", "現役", "若手", "エース", "後続", "同", "新", "元", "実況", "解説", "日本人", "新鋭", "他"]
        for cand in runner_candidates:
            clean_cand = cand.replace('君', '').replace('選手', '').strip()
            clean_cand = re.sub(r'^\d+', '', clean_cand).strip()
            if not clean_cand or len(clean_cand) < 2:
                continue
            if any(clean_cand.startswith(prefix) for prefix in exclude_prefixes) or clean_cand in exclude_prefixes:
                continue
            if clean_cand not in valid_runners_fuzzy:
                warnings.append(f"マスタに存在しない選手名と思われる表記: {cand}")

        # 3. 危険語（「逆転」「浮上」「優勝」等）の文脈整合性チェック
        rank_changes = metrics.get('rank_changes', {})

        keywords = ["逆転", "浮上", "ジャンプアップ"]
        for kw in keywords:
            pos = 0
            while True:
                idx = plain_article.find(kw, pos)
                if idx == -1:
                    break

                start = max(0, idx - 30)
                end = min(len(plain_article), idx + len(kw) + 30)
                window = plain_article[start:end]

                found_teams = []
                for team in valid_teams:
                    short_team = team.replace('大学', '大')
                    stem_team = team[:-2] if team.endswith('大学') else team
                    if team in window or short_team in window or stem_team in window:
                        found_teams.append(team)

                for team in found_teams:
                    change = rank_changes.get(team)
                    if change:
                        if change['diff'] <= 0:
                            warnings.append(f"順位が上昇していないチーム '{team}' に関連して 『{kw}』 という表現が使われています。(周辺テキスト: '...{window}...')")

                pos = idx + len(kw)

        # 4. 全体的な危険語の使用制限
        has_rank_up = any(change['diff'] > 0 for change in rank_changes.values())
        if ("逆転" in plain_article or "浮上" in plain_article) and not has_rank_up:
            warnings.append("記事内に『逆転』または『浮上』の表記がありますが、本日の順位データに順位上昇校がありません。")

        # 5. 「優勝」の不適切な使用制限
        sentences = re.split(r'[。！\n]', plain_article)
        for s in sentences:
            s = s.strip()
            if not s:
                continue

            has_winner_keyword = any(k in s for k in ["優勝", "王者", "頂点", "制した"])
            if not has_winner_keyword:
                continue

            # 歴史記述・過去の言及かチェック
            is_history = False
            history_patterns = [
                r"過去に(?:優勝|王者|頂点|制した)",
                r"(?:前回|前年)大会の(?:優勝|王者)",
                r"第\d+回(?:大会)?で(?:優勝|王者|頂点|制した)",
                r"(?:優勝|制覇|連覇)した実績",
                r"前回王者",
                r"(?:連覇|優勝)経験",
                r"歴代(?:優勝|王者)"
            ]
            for hp in history_patterns:
                if re.search(hp, s):
                    is_history = True
                    break

            if is_history:
                continue

            is_present_victory = any(k in s for k in ["優勝した", "優勝を決めた", "王者となった", "頂点に立った", "頂点に輝いた", "制した", "優勝は", "優勝を決めたのは"])
            if not is_present_victory:
                continue

            # 優勝の主語を正規表現で厳密に抽出する
            found_team_name = None
            match1 = re.search(r'([\u4e00-\u9faf\u30a0-\u30ff]+(?:大学|大))\s*(?:が|も).*?(?:優勝を決めた|優勝した|王者となった|頂点に立った|頂点に輝いた|制した|優勝)', s)
            match2 = re.search(r'(?:優勝は|優勝を決めたのは|王者となったのは|頂点に立ったのは|頂点に輝いたのは|制したのは).*?([\u4e00-\u9faf\u30a0-\u30ff]+(?:大学|大))', s)

            if match1:
                found_team_name = match1.group(1)
            elif match2:
                found_team_name = match2.group(1)


            if not found_team_name:
                warnings.append(f"優勝に関する断定記述がありますが、主語となる大学名が特定できませんでした。(文: '{s}')")
                continue

            clean_team = found_team_name.strip()
            matched_team = None
            for team in valid_teams:
                short_team = team.replace('大学', '大')
                stem_team = team[:-2] if team.endswith('大学') else team
                if clean_team == team or clean_team == short_team or clean_team == stem_team:
                    matched_team = team
                    break

            if not matched_team:
                warnings.append(f"優勝校として特定された大学 '{clean_team}' がマスタに登録されていません。(文: '{s}')")
                continue

            realtime_teams = self.all_data.get('realtime_report', {}).get('teams', [])
            team_data = next((t for t in realtime_teams if t['name'] == matched_team), None)

            is_valid_champion = False
            if team_data:
                is_goal = (team_data.get('runner') == 'ゴール' or team_data.get('finishDay') is not None)
                is_rank_1 = (team_data.get('overallRank') == 1)
                if is_goal and is_rank_1:
                    is_valid_champion = True

            if not is_valid_champion:
                warnings.append(f"総合1位ゴールしていないチーム '{matched_team}' が優勝したと記述されています。(文: '{s}')")


        if warnings:
            print("⚠️ 【検証警告】生成された記事に整合性の懸念があります:")
            for w in warnings:
                print(f"  - {w}")
            return False

        print("✅ 生成記事の簡易事実検証をパスしました。")
        return True


    def update_narrative_state(self, metrics, selected_themes):
        """Pythonの決定的ロジックにより、レース状況と選定されたテーマに基づいて物語状態（state）を更新します。"""
        race_day = metrics.get('race_day', 1)
        state = self.narrative_state

        if state.get('updated_day') == race_day:
            state['ongoing_battles'] = [b for b in state.get('ongoing_battles', []) if b.get('started_day', 1) < race_day]
            state['momentum'] = [m for m in state.get('momentum', []) if m.get('started_day', 1) < race_day]
            state['runner_threads'] = [r for r in state.get('runner_threads', []) if r.get('started_day', 1) < race_day]
            state['resolved_stories'] = [s for s in state.get('resolved_stories', []) if s.get('resolved_day', 1) < race_day]

        state['updated_day'] = race_day

        # 0. main_story の更新
        if selected_themes:
            primary_theme = selected_themes[0]
            existing_main = state.get('main_story', {})

            p_type = primary_theme.get('type') or primary_theme.get('zone')
            p_title = primary_theme.get('title') or primary_theme.get('zone')
            p_details = primary_theme.get('details') or primary_theme.get('reason', '')
            involved_teams = primary_theme.get('teams') or [t for t in metrics.get('rank_changes', {}).keys() if t in p_title or t in p_details]

            is_same = False
            if existing_main and existing_main.get('type') == p_type:
                existing_teams = existing_main.get('teams', [])
                if any(t in existing_teams for t in involved_teams):
                    is_same = True

            if is_same:
                state['main_story'] = {
                    "type": p_type,
                    "summary": p_title,
                    "started_day": existing_main.get('started_day', race_day),
                    "last_updated_day": race_day,
                    "teams": involved_teams
                }
            else:
                state['main_story'] = {
                    "type": p_type,
                    "summary": p_title,
                    "started_day": race_day,
                    "last_updated_day": race_day,
                    "teams": involved_teams
                }

        # 1. 首位争いの更新
        lead_battle = metrics.get('lead_battle')
        if lead_battle:
            t1, t2 = lead_battle['team1'], lead_battle['team2']
            gap = lead_battle['gap_current']

            existing = None
            for b in state.get('ongoing_battles', []):
                if b.get('id') == "lead_battle":
                    existing = b
                    break

            is_resolved = False
            realtime_teams = self.all_data.get('realtime_report', {}).get('teams', [])
            t1_data = next((t for t in realtime_teams if t['name'] == t1), None)
            t2_data = next((t for t in realtime_teams if t['name'] == t2), None)
            is_goal = (t1_data and t1_data.get('runner') == 'ゴール') or (t2_data and t2_data.get('runner') == 'ゴール')

            is_resolved = is_goal

            if is_resolved:
                resolved_entry = {
                    "summary": f"首位攻防決着：{t1}と{t2}の争いはゴールに到達したため決着 (最終観測差: {gap:.1f}km)",
                    "resolved_day": race_day,
                    "reason": "ゴール"
                }
                state.setdefault('resolved_stories', []).append(resolved_entry)
                if existing in state.get('ongoing_battles', []):
                    state['ongoing_battles'].remove(existing)
            else:
                if existing:
                    existing_teams = existing.get('teams', [])
                    if t1 in existing_teams and t2 in existing_teams:
                        # 同一ペア
                        existing['last_updated_day'] = race_day
                        existing['last_observed_gap_km'] = gap
                        existing['previous_gap_km'] = gap
                    else:
                        # 異なるペアへの交代
                        prev_gap_val = existing.get('last_observed_gap_km') or existing.get('previous_gap_km', 0.0)
                        resolved_entry = {
                            "summary": f"首位攻防交代：{', '.join(existing_teams)}の争いから{t1}と{t2}の争いへ移行 (前回観測時の差 {prev_gap_val:.1f}km)",
                            "resolved_day": race_day,
                            "reason": "首位交代"
                        }
                        state.setdefault('resolved_stories', []).append(resolved_entry)
                        state['ongoing_battles'].remove(existing)

                        battle_entry = {
                            "id": "lead_battle",
                            "kind": "lead",
                            "teams": [t1, t2],
                            "summary": f"{t1}と{t2}による首位争い",
                            "started_day": race_day,
                            "last_updated_day": race_day,
                            "last_observed_gap_km": gap,
                            "previous_gap_km": gap
                        }
                        state.setdefault('ongoing_battles', []).append(battle_entry)
                else:
                    battle_entry = {
                        "id": "lead_battle",
                        "kind": "lead",
                        "teams": [t1, t2],
                        "summary": f"{t1}と{t2}による首位争い",
                        "started_day": race_day,
                        "last_updated_day": race_day,
                        "last_observed_gap_km": gap,
                        "previous_gap_km": gap
                    }
                    state.setdefault('ongoing_battles', []).append(battle_entry)

        # 2. 順位上昇（momentum）の更新・整理
        rank_changes = metrics.get('rank_changes', {})
        current_momentums = state.setdefault('momentum', [])
        updated_momentums = []

        # 既存 momentum のチェックと更新
        for m in list(current_momentums):
            t_name = m.get('team')
            change = rank_changes.get(t_name)

            if change and change['diff'] >= 3:
                m['last_updated_day'] = race_day
                m['previous_rank'] = change['prev']
                m['current_rank'] = change['curr']
                m['diff'] = change['diff']
                m['summary'] = f"{change['prev']}位から{change['curr']}位へ急浮上"
                updated_momentums.append(m)
            else:
                curr_rank = change['curr'] if change else m.get('current_rank')
                resolved_entry = {
                    "summary": f"勢い落ち着く：{t_name}の急浮上（本日{curr_rank}位）",
                    "resolved_day": race_day,
                    "reason": "勢い低下"
                }
                exists = any(
                    res.get('summary') == resolved_entry['summary'] and res.get('resolved_day') == race_day
                    for res in state.get('resolved_stories', [])
                )
                if not exists:
                    state.setdefault('resolved_stories', []).append(resolved_entry)

        # 新規 momentum の追加
        for t_name, change in rank_changes.items():
            if change['diff'] >= 3:
                if not any(m.get('team') == t_name for m in updated_momentums):
                    momentum_entry = {
                        "team": t_name,
                        "summary": f"{change['prev']}位から{change['curr']}位へ急浮上",
                        "started_day": race_day,
                        "last_updated_day": race_day,
                        "previous_rank": change['prev'],
                        "current_rank": change['curr'],
                        "diff": change['diff']
                    }
                    updated_momentums.append(momentum_entry)

        # 優先順にソート (last_updated_day 降順、続いて本日変動幅 diff 降順)
        updated_momentums.sort(key=lambda x: (x.get('last_updated_day', 0), x.get('diff', 0)), reverse=True)
        state['momentum'] = updated_momentums

        # 3. 走者スレッドの更新
        realtime_teams = self.all_data.get('realtime_report', {}).get('teams', [])
        substitutions = self._load_recent_substitution_logs()
        sub_runners_out = {s['runner_out'] for s in substitutions}

        for thread in list(state.get('runner_threads', [])):
            team_name = thread.get('team')
            thread_runner = thread.get('runner')

            team_state = next((t for t in realtime_teams if t.get('name') == team_name), None)

            should_resolve = False
            reason = "区間交代"
            summary_desc = ""

            if not team_state:
                should_resolve = True
                reason = "不明"
                summary_desc = f"チーム離脱：{team_name}のデータが見つかりません"
            elif team_state.get('runner') == 'ゴール' or team_state.get('finishDay') is not None:
                should_resolve = True
                reason = "ゴール"
                summary_desc = f"フィニッシュ：{team_name}がゴールし、{thread_runner}君の走行が終了"
            else:
                curr_runner_raw = team_state.get('runner') or ''
                curr_runner_clean = re.sub(r'^\d+', '', curr_runner_raw).strip()
                if curr_runner_clean != thread_runner or thread_runner in sub_runners_out:
                    should_resolve = True
                    reason = "区間交代"
                    summary_desc = f"選手交代：{team_name}の{thread_runner}君から新走者へタスキ"

            if should_resolve:
                resolved_entry = {
                    "summary": summary_desc or f"走者交代：{team_name}の{thread_runner}君の走行終了",
                    "resolved_day": race_day,
                    "reason": reason
                }
                exists = any(
                    res.get('summary') == resolved_entry['summary'] and res.get('resolved_day') == race_day
                    for res in state.get('resolved_stories', [])
                )
                if not exists:
                    state.setdefault('resolved_stories', []).append(resolved_entry)

                if thread in state.get('runner_threads', []):
                    state['runner_threads'].remove(thread)

        today_stars = sorted(self._get_active_teams(), key=lambda t: t.get('todayDistance', 0.0), reverse=True)
        if today_stars and today_stars[0].get('todayDistance', 0.0) > 0:
            star = today_stars[0]
            runner_name = star.get('runner')
            if runner_name and runner_name != 'ゴール':
                clean_runner = re.sub(r'^\d+', '', runner_name).strip()
                existing_r = next((r for r in state.get('runner_threads', []) if r.get('runner') == clean_runner), None)
                if not existing_r:
                    thread_entry = {
                        "runner": clean_runner,
                        "team": star['name'],
                        "summary": f"本日最速 {star.get('todayDistance', 0.0):.1f}km の快走",
                        "started_day": race_day,
                        "last_updated_day": race_day
                    }
                    state.setdefault('runner_threads', []).append(thread_entry)


        # 4. 配列サイズ制限
        state['ongoing_battles'] = state.get('ongoing_battles', [])[:3]
        state['momentum'] = state.get('momentum', [])[:3]
        state['runner_threads'] = state.get('runner_threads', [])[:3]
        state['resolved_stories'] = state.get('resolved_stories', [])[-5:]

    def run(self):
        """Main execution logic."""
        print("日次振り返り解説の生成を開始します...")
        self.load_all_data()

        # 数値計算を実行
        metrics = self.calculate_race_metrics()

        system_prompt = self.build_system_prompt()
        user_prompt = self.build_user_prompt(metrics)

        print("------------------------------------")
        print("OpenAIへのsystem prompt:")
        print(system_prompt)
        print("------------------------------------")
        print("OpenAIへのuser prompt:")
        print(user_prompt)
        print("------------------------------------")

        if self.dry_run:
            print("\n--dry-runモードのため、ファイルへの書き込みは行わずに終了します。")
            # デバッグ用に選定されたテーマや継続物語を出力
            selected_zones = self.select_today_themes(metrics)
            print("\n[dry-run] 生成された今日のテーマ候補ゾーン:")
            for t in selected_zones:
                spread = t.get('gaps', {}).get('max_spread_km', 0.0)
                print(f"  - 【{t['zone']}】対象チーム: {', '.join(t['teams'])} (最大差: {spread:.1f}km) - 理由: {t['reason']}")
            print("\n[dry-run] 読み込んだ継続物語の数:")
            print(f"  - ongoing_battles: {len(self.narrative_state.get('ongoing_battles', []))}")
            print(f"  - momentum: {len(self.narrative_state.get('momentum', []))}")
            print(f"  - runner_threads: {len(self.narrative_state.get('runner_threads', []))}")
            return

        try:
            response = self.client.responses.create(
                model=self.model_name,
                instructions=system_prompt,
                input=user_prompt
            )
            raw_article_text = response.output_text.strip()
            print("記事をMarkdownでフォーマットしています...")
            article_text = self.format_article_with_markdown(raw_article_text)
            print("✅ OpenAIによる解説記事の生成に成功しました。")

            # 生成された記事のバリデーションを実行
            validation_success = self.validate_generated_article(article_text, metrics)

            prompt_payload = json.dumps(
                {"system": system_prompt, "user": user_prompt},
                ensure_ascii=False,
                indent=2
            )

            # 検証が成功した場合にのみ、物語状態を更新して保存する
            if validation_success:
                print("物語状態を更新しています...")
                selected_themes = self.select_today_themes(metrics)
                self.update_narrative_state(metrics, selected_themes)
                self.save_narrative_state()

                self._save_article_to_history(prompt_payload, raw_article_text)

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
            else:
                print("⚠️ バリデーション警告があるため、ファイル保存、履歴保存および物語状態の更新をすべてスキップします。")
        except Exception as e:
            print(f"❌ OpenAI API呼び出し中にエラーが発生しました: {e}")
            print("⚠️ APIエラーのため、ファイル保存および物語状態の更新をスキップします。")

def main():
    """Parses arguments and runs the generator."""
    parser = argparse.ArgumentParser(description='高温大学駅伝の1日の総括記事を生成します（履歴機能付き）。')
    parser.add_argument('--dry-run', action='store_true', help='OpenAI APIを呼び出さずにプロンプトのデバッグ表示のみ行います。')
    args = parser.parse_args()

    generator = DailySummaryGenerator(dry_run=args.dry_run)
    generator.run()

if __name__ == '__main__':
    main()
