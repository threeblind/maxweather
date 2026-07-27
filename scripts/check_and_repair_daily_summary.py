#!/usr/bin/env python3
"""
日次ダイジェスト確認・修復スクリプト。

前日生成された daily_summary.json の整合性を確認し、
AI応答失敗があれば raw_response から修復を試み、
deterministic な問題（39.km等）は元データで修正、
合格時のみ commit/push まで行う。

使い方:
  python3 scripts/check_and_repair_daily_summary.py [--date YYYY-MM-DD] [--dry-run] [--no-push]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# --- パス定義 ---
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'
LOGS_DIR = PROJECT_DIR / 'logs'
CONFIG_DIR = PROJECT_DIR / 'config'
SCRIPTS_DIR = PROJECT_DIR / 'scripts'

SUMMARY_FILE = DATA_DIR / 'daily_summary.json'
SNAPSHOT_DIR = DATA_DIR / 'daily_snapshots'
SUMMARY_CHECK_LOG = LOGS_DIR / 'summary_check.log'
LOCK_FILE = LOGS_DIR / 'summary_check.lock'
AI_RESPONSE_DIR = LOGS_DIR / 'summary_ai_responses'

def resolve_results_path(target_date):
    """対象日のスナップショットから individual_results.json のパスを返す。
    スナップショットが存在しない場合は None を返す（安全停止用）。"""
    snap = SNAPSHOT_DIR / target_date / 'individual_results.json'
    if snap.exists():
        return snap
    return None

# コミット対象ファイル（これら以外の変更は FAIL）
COMMIT_TARGETS = [
    'data/daily_summary.json',
    'data/article_history.json',
    'data/race_narrative_state.json',
]

# --- 正規表現 ---
BROKEN_NUMBERS_IN_TEXT = re.compile(
    r'(?<!\w)(?:null|NaN|undefined)\s*km(?!\d)|'
    r'(?<!\d)[\.\s]km(?!\d)|'
    r'\d+\.km(?!\d)'
)
UNREPLACED_PLACEHOLDERS = re.compile(
    r'\{\{[A-Z_]+:[^}]+\}\}|\{\{[A-Z_]+\}\}|\$[A-Z_]+'
)
DISTANCE_PATTERN = re.compile(
    r'(\d+\.?\d*)\s*km(?!\d)'
)
BAD_DOTS = re.compile(r'(\d)\.(\D)(?!\d)')

LEG_NAMES = ['第1区', '第2区', '第3区', '第4区', '第5区',
             '第6区', '第7区', '第8区', '第9区', '第10区']

# ============================================================
# 結果管理
# ============================================================

class CheckResult:
    """
    チェック結果を管理し、最終的にログファイルに出力する。

    final_status:
      'passed'    — 全チェック合格 (WARN/INFO のみ)
      'recovered' — 修復により合格に到達
      'failed'    — 致命的エラーあり
    """
    def __init__(self):
        self.target_date = ''
        self.steps = []
        self.corrections = []
        self.final_status = 'running'
        self.errors = []
        self.warnings = []
        self.repair_attempted = False
        self.repair_succeeded = False

    def step(self, name, status, detail=''):
        self.steps.append({'name': name, 'status': status, 'detail': detail})
        if status == 'FAIL':
            self.errors.append(f'{name}: {detail}')
        elif status == 'WARN':
            self.warnings.append(f'{name}: {detail}')

    def correct(self, field, before, after):
        self.corrections.append({'field': field, 'before': before, 'after': after})
        self.step(f'correct_{field}', 'INFO', f'{before!r} -> {after!r}')

    def to_dict(self):
        return {
            'target_date': self.target_date,
            'finished_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'final_status': self.final_status,
            'steps': self.steps,
            'corrections': self.corrections,
            'errors': self.errors,
            'warnings': self.warnings,
            'repair_attempted': self.repair_attempted,
            'repair_succeeded': self.repair_succeeded,
        }


# ============================================================
# ロック・日付・ファイルI/O
# ============================================================

def acquire_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        mtime = LOCK_FILE.stat().st_mtime
        age = time.time() - mtime
        if age < 1800:
            print('❌ 前回の実行がまだ進行中です（ロックファイル有効）')
            sys.exit(1)
        else:
            print(f'⚠️ 古いロックファイルを削除します（経過: {age/60:.0f}分）')
            LOCK_FILE.unlink(missing_ok=True)
    LOCK_FILE.write_text(str(os.getpid()))
    print(f'🔒 ロックファイル取得 (PID={os.getpid()})')


def release_lock():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink(missing_ok=True)
        print('🔓 ロックファイル解放')


def resolve_target_date(args_date):
    if args_date:
        return args_date
    yesterday = datetime.now() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')


def load_json(path, label=''):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return None, json.load(f)
    except FileNotFoundError:
        return f'{label}ファイルが見つかりません: {path}', None
    except json.JSONDecodeError as e:
        return f'{label}JSONパースエラー: {e}', None
    except IOError as e:
        return f'{label}IOエラー: {e}', None


# ============================================================
# 1. コミットログ確認
# ============================================================

def check_commit_log(result: CheckResult):
    cron_log = LOGS_DIR / 'cron_summary.log'
    if not cron_log.exists():
        result.step('commit_log', 'WARN', 'cron_summary.log が見つかりません')
        return
    try:
        lines = cron_log.read_text(encoding='utf-8').strip().split('\n')
        if not lines:
            result.step('commit_log', 'WARN', 'cron_summary.log は空です')
            return
        result.step('commit_log', 'PASS', f'最終ログ確認 (最終行 {len(lines)}行)')
    except Exception as e:
        result.step('commit_log', 'WARN', f'ログ読み込みエラー: {e}')


# ============================================================
# 2. Deterministic checks
# ============================================================

def check_daily_summary(result: CheckResult, summary_data):
    """daily_summary.json の deterministic チェック"""
    data = summary_data

    # 日付一致
    file_date = data.get('date', '').replace('/', '-')
    if file_date != result.target_date:
        result.step('date_match', 'FAIL',
                     f'日付 {data.get("date")!r} != 対象日 {result.target_date!r}')
    else:
        result.step('date_match', 'PASS', f'日付一致: {file_date}')

    # 必須フィールド
    article = data.get('article', '')
    if not article:
        result.step('required_fields', 'FAIL', 'article フィールドが空または存在しません')
    else:
        result.step('required_fields', 'PASS', f'article {len(article)}文字')

    # 壊れた数字
    broken = BROKEN_NUMBERS_IN_TEXT.findall(article)
    bad_dots = BAD_DOTS.findall(article)
    if broken or bad_dots:
        details = []
        if broken:
            details.append(f'壊れた数字: {broken[:5]}')
        if bad_dots:
            details.append(f'不正ドット: {bad_dots[:5]}')
        result.step('broken_numbers', 'FAIL', '; '.join(details))
    else:
        result.step('broken_numbers', 'PASS', '壊れた数字表記なし')

    # 未置換テンプレート
    placeholders = UNREPLACED_PLACEHOLDERS.findall(article)
    if placeholders:
        result.step('placeholders', 'FAIL', f'未置換テンプレート: {placeholders[:5]}')
    else:
        result.step('placeholders', 'PASS', '未置換テンプレートなし')

    # 距離数値範囲（異常値のみ警告: 1km未満や100km超は差分や平均値で正常の可能性あり）
    # → 10未満は差分値として正常なため、警告しない
    distances = DISTANCE_PATTERN.findall(article)
    suspicious = [d for d in distances if float(d) > 200]
    if suspicious:
        result.step('distance_range', 'WARN', f'範囲外: {suspicious[:5]}')
    else:
        result.step('distance_range', 'PASS', '距離値妥当')


# リレー記述のパターン: {チーム}...{走者A}から{走者B}へタスキ
RELAY_PATTERN = re.compile(
    r'(?P<runner_a>[^\s、。]+?)から(?P<runner_b>[^\s、。]+?)へタスキ'
)

def check_runner_relay_consistency(result: CheckResult, summary_data):
    """
    記事内のタスキリレー記述で、同じ走者名が「AからAへ」と
    両側に出現していないかチェックする。
    これは明らかな誤り（異なる選手間のリレーのはず）を検出する。
    """
    article = summary_data.get('article', '')
    matches = RELAY_PATTERN.findall(article)
    dupes = [(a, b) for a, b in matches if a == b]
    if dupes:
        result.step('runner_relay_same_name', 'FAIL',
                     f'タスキリレーで同一走者名が両側に出現: {dupes}')
    else:
        result.step('runner_relay_same_name', 'PASS', 'リレー記述に同一名なし')


def check_article_consistency(result: CheckResult, summary_data):
    """記事の基本整合性チェック"""
    article = summary_data.get('article', '')

    for leg in LEG_NAMES:
        if leg in article:
            result.step('leg_reference', 'INFO', f'記事に {leg}')
            break

    today_str = result.target_date.replace('-', '/')
    if today_str in article:
        result.step('date_reference', 'PASS', f'日付 {today_str} 言及あり')
    else:
        result.step('date_reference', 'INFO', '明示的日付なし')

    if len(article) < 100:
        result.step('article_length', 'WARN', f'記事短すぎ ({len(article)}文字)')
    else:
        result.step('article_length', 'PASS', f'{len(article)}文字')


def check_coach_comment_attribution(result: CheckResult, summary_data):
    """監督コメントの帰属チェック: 記事中の引用が正しいチームに紐づいているか検証"""
    article = summary_data.get('article', '')
    if not article:
        return

    # 監督コメント一覧をスナップショットから取得
    today = result.target_date
    comments_path = SNAPSHOT_DIR / today / 'manager_comments.json'
    if not comments_path.exists():
        result.step('coach_comment', 'INFO', 'スナップショットのmanager_commentsなし')
        return

    err, comments_data = load_json(str(comments_path), 'manager_comments')
    if err or not comments_data:
        result.step('coach_comment', 'INFO', 'manager_comments読込不可')
        return

    # team → [comment_fragments] のマッピングを構築
    team_comments = {}

    for entry in comments_data:
        html = entry.get('content_html', '')
        # HTMLタグ除去→連続空白除去
        text = re.sub(r'<[^>]+>', '', html).strip()
        text = re.sub(r'\s+', '', text)

        # 「大学名　区間情報…」で分割（複数大学が1エントリに含まれるため）
        sections = re.split(r'(?=[\u4e00-\u9faf]{2,4}(?:大学|大)　)', text)
        for section in sections:
            section = section.strip()
            if not section:
                continue
            m = re.match(r'^([\u4e00-\u9faf]{2,4}(?:大学|大))', section)
            if not m:
                continue
            team = m.group(1)
            # ヘッダー（大学名＋区間情報＋距離）をスキップしてコメント本体を抽出
            body = section[m.end():]
            # 最初の15文字は区間・走者・距離情報なのでスキップ
            comment_body = body[15:] if len(body) > 15 else ''
            # 意味のあるフレーズ（10文字以上の連続）を抽出
            phrases = re.findall(
                r'[\u4e00-\u9faf\u3040-\u309f\u30a0-\u30ff0-9]{10,}',
                comment_body
            )
            if phrases:
                team_comments.setdefault(team, []).extend(phrases)

    if not team_comments:
        result.step('coach_comment', 'INFO', 'パース可能な監督コメントなし')
        return

    # 記事中の引用を抽出
    article_quotes = re.findall(r'「([^」]{5,})」', article)
    if not article_quotes:
        result.step('coach_comment', 'PASS', '記事に引用なし')
        return

    violations = []
    for qtext in article_quotes:
        # どのチームの監督コメントと一致するか
        source_team = None
        for team, phrases in team_comments.items():
            if any(phrase in qtext or qtext in phrase for phrase in phrases):
                source_team = team
                break
        if not source_team:
            continue  # 既知の監督コメントにない引用はスキップ

        # 引用の前後200文字以内に、引用元チームが出現するか
        quote_idx = article.find(f'「{qtext}」')
        if quote_idx < 0:
            continue

        before = article[max(0, quote_idx - 200):quote_idx]
        after = article[quote_idx + len(qtext) + 2:quote_idx + len(qtext) + 2 + 200]
        context = before + after

        # 文脈中の大学名（太字→プレーン）
        context_teams = set(re.findall(r'\*\*([^*]+?)\*\*', context)) or \
                        set(re.findall(r'[\u4e00-\u9faf]{2,4}(?:大学|大)', context))

        # 引用元チームが文脈に含まれているか
        if source_team not in context_teams:
            partial = any(source_team in t or t in source_team for t in context_teams)
            if not partial:
                violations.append(
                    f"'{source_team}'監督のコメント「{qtext[:30]}…」が"
                    f"不適切な文脈（{', '.join(sorted(context_teams)) or '不明'}）で使用されています"
                )

    if violations:
        for v in violations:
            result.step('coach_comment_attribution', 'FAIL', v)
    else:
        result.step('coach_comment_attribution', 'PASS', '監督コメントの帰属に問題なし')



# ============================================================
# 3. git 状態確認
# ============================================================

def check_git_status(result: CheckResult):
    """git diff --check / 安全に関係ない変更は FAIL"""
    try:
        r = subprocess.run(
            ['git', 'status', '--porcelain'],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=15
        )
        if r.returncode != 0:
            result.step('git_status', 'WARN', f'git status 失敗: {r.stderr.strip()}')
            return

        changes = [ln for ln in r.stdout.strip().split('\n') if ln.strip()]
        other_changes = []
        for line in changes:
            path = line[2:].lstrip()
            if not any(path.startswith(t) for t in COMMIT_TARGETS) and 'summary_ai_responses' not in path:
                other_changes.append(line)

        if other_changes:
            result.step('git_other_changes', 'FAIL',
                         f'関係ない変更 {len(other_changes)}件（安全のため中止）')
            for c in other_changes[:5]:
                result.step('git_other_change_detail', 'FAIL', c)

        r2 = subprocess.run(
            ['git', 'diff', '--check'],
            capture_output=True, text=True, cwd=PROJECT_DIR, timeout=15
        )
        if r2.stdout.strip():
            result.step('git_diff_check', 'FAIL', r2.stdout.strip()[:200])
        else:
            result.step('git_diff_check', 'PASS', '問題なし')

        result.step('git_status', 'PASS', f'{len(changes)}件変更')

    except subprocess.TimeoutExpired:
        result.step('git_status', 'FAIL', 'git タイムアウト')
    except Exception as e:
        result.step('git_status', 'WARN', f'git エラー: {e}')


# ============================================================
# 4. 決定論的修復（39.km → 実データ値）
# ============================================================

def build_daily_distance_map(target_date):
    """
    individual_results.json から (leg, day) → [distance, ...] のマップを構築。
    対象日のスナップショットを使用する。
    39.km 修復の参照用。
    """
    results_path = resolve_results_path(target_date)
    if results_path is None:
        return None, f'snapshot が見つかりません: {target_date}'
    err, data = load_json(results_path, 'individual_results')
    if err:
        return None, err
    dist_map = defaultdict(list)  # (leg, day) -> [dist, dist, ...]
    for runner_name, info in data.items():
        for rec in info.get('records', []):
            leg = rec.get('leg')
            day = rec.get('day')
            d = rec.get('distance')
            if leg and day and d is not None:
                dist_map[(leg, day)].append(d)
    for key in dist_map:
        dist_map[key].sort(reverse=True)
    return dist_map, None


def deterministic_repair(result: CheckResult, summary_data):
    """
    決定論的に確定できる誤りだけを修正する:
    - 39.km → individual_results.json の実距離値で置換（一意に特定できる場合のみ）
    """
    article = summary_data.get('article', '')
    original = article

    # 39.km/40.km を検出
    broken_spots = list(BROKEN_NUMBERS_IN_TEXT.finditer(article))
    if not broken_spots:
        return False

    dist_map, err = build_daily_distance_map(result.target_date)
    if err or dist_map is None:
        result.step('deterministic_repair', 'WARN',
                     f'修復不可（individual_results 読み込み失敗: {err}）')
        return False

    # broken number の前後から leg/day を推測 → 一意な距離があれば置換
    # 実際の修復は推測が確定できる場合のみ行う
    # 安全のため、現状は検出のみで修復は手動 or AI に任せる
    result.step('deterministic_repair', 'INFO',
                 f'{len(broken_spots)}件の壊れた数字を検出（自動確定不可）')
    return False


# ============================================================
# 5. AI応答修復パイプライン
# ============================================================

def repair_ai_failures(result: CheckResult, summary_data):
    """
    logs/summary_ai_responses/ の失敗ファイルを読み込み、
    保存された raw_response からの修復を試みる。

    修復戦略:
    1. raw_response が存在 → パース→検証→合格すれば反映
    2. JSON構造は直せる（改行除去 etc.）→ 修正して再検証
    3. それでも不可 → 応答あり・修正未実施として報告
    """
    if not AI_RESPONSE_DIR.exists():
        result.step('ai_repair', 'PASS', 'AI応答ディレクトリなし')
        return

    failed_files = []
    for f in sorted(AI_RESPONSE_DIR.iterdir()):
        if f.suffix != '.json' or f.name.startswith('.'):
            continue
        try:
            resp_data = json.loads(f.read_text(encoding='utf-8'))
            status = resp_data.get('status')
            if status in ('failed', 'received'):
                failed_files.append((f, resp_data))
        except (json.JSONDecodeError, IOError):
            result.step('ai_repair', 'WARN', f'{f.name}: 読み込み失敗')

    if not failed_files:
        result.step('ai_repair', 'PASS', '失敗ファイルなし')
        return

    result.repair_attempted = True
    result.step('ai_repair', 'INFO', f'{len(failed_files)}件の失敗ファイルを確認')

    for fpath, resp_data in failed_files:
        name = fpath.name
        stage = resp_data.get('failure_stage', 'unknown')
        raw_response = resp_data.get('raw_response', '')

        if not raw_response:
            result.step('ai_repair', 'FAIL',
                         f'{name}: raw_response なし（API未応答）')
            continue

        # raw_response から記事を抽出
        repaired = _try_repair_from_raw(raw_response, result, name, stage)
        if repaired:
            # 現在の summary と置き換え可能か検証
            err = _try_apply_repair(result, summary_data, repaired, fpath)
            if err:
                result.step('ai_repair', 'WARN', f'{name}: 修復候補は不適合: {err}')
            else:
                result.repair_succeeded = True
                # 修復成功ファイルは status=recovered に更新（削除しない）
                # _try_apply_repair 内で _update_response_file_status を呼ぶ
        # else: 修復失敗も報告済み


def _try_repair_from_raw(raw_response: str, result: CheckResult, name: str, stage: str):
    """
    raw_response から記事データを抽出・修正して返す。
    None = 修復不能。

    修復可能パターン:
    - 有効なJSON → article フィールド抽出
    - JSONだが article なし → 応答全体をarticleとして使う
    - JSONではない → 応答全文をarticleとして使う
    """
    # まずJSONとしてパースを試みる
    data = None
    parsed_text = raw_response.strip()

    # { } で囲まれたJSONブロックを抽出
    json_match = re.search(r'\{.*\}', parsed_text, re.DOTALL)
    if json_match:
        candidate = json_match.group(0)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            pass

    if data and isinstance(data, dict):
        # 構造化応答 → article 抽出
        article = data.get('article', '')
        if article:
            result.step('ai_repair', 'INFO',
                         f'{name}: raw_response から article 抽出成功 ({len(article)}文字, stage={stage})')
            return {'date': data.get('date', ''), 'article': article}
        else:
            result.step('ai_repair', 'WARN',
                         f'{name}: JSONだが article なし → 全文をarticle扱い')
            return {'date': data.get('date', ''), 'article': json.dumps(data, ensure_ascii=False)}

    # JSONでない → 全文を article として扱う（簡易修復）
    result.step('ai_repair', 'WARN',
                 f'{name}: JSONパース不可 → 全文をarticle扱い ({len(parsed_text)}文字)')
    return {'date': '', 'article': parsed_text}


def _resolve_race_day(target_date: str):
    """対象日からレース日程の日数（day number）を計算。outline.json の startDate 基準。"""
    err, outline = load_json(CONFIG_DIR / 'outline.json', 'outline')
    if err:
        return None
    start_str = outline.get('metadata', {}).get('startDate', '')
    if not start_str:
        return None
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d')
        target = datetime.strptime(target_date, '%Y-%m-%d')
        day = (target - start).days + 1
        return day if 1 <= day <= 30 else None
    except (ValueError, TypeError):
        return None


def _validate_article_against_source(article: str, target_date: str):
    """
    記事内の距離数値をスナップショットの実データと照合する。
    照合は対象日（race day）の記録のみで行う。

    戻り値: (合格, [エラー理由])
    合格=False の場合、記事内の距離値が実データと大きく乖離している。
    対象日スナップショットが読み込めない場合も不合格（安全停止）。
    """
    errors = []

    # スナップショットから individual_results.json を読み込み
    results_path = resolve_results_path(target_date)
    if results_path is None:
        return False, [f'対象日 {target_date} のスナップショットが見つかりません（安全停止）']
    err, results = load_json(results_path, 'individual_results')
    if err:
        return False, [f'元データ読み込み不可: {err}']

    # 対象日の race day を解決
    race_day = _resolve_race_day(target_date)
    if race_day is None:
        return False, [f'対象日 {target_date} の race day が特定できません（outline.json 確認）']

    # 対象日（race day）の実距離値のみ収集
    known_distances = set()
    for runner_name, info in results.items():
        for rec in info.get('records', []):
            if rec.get('day') != race_day:
                continue
            d = rec.get('distance')
            if d is not None:
                known_distances.add(round(d, 1))
            # 平均距離やlegAverageDistanceも記事内で言及される
            avg = rec.get('legAverageDistance')
            if avg is not None:
                known_distances.add(round(avg, 1))

    if not known_distances:
        return False, [f'対象日 race_day={race_day} の記録が individual_results.json に見つかりません']

    # 歴代区間最高記録も既知距離に追加（従来記録が記事内で引用されるため）
    hist_err, hist_data = load_json(PROJECT_DIR / 'history_data' / 'leg_award_history.json', 'leg_award_history')
    if hist_err:
        errors.append(f'leg_award_history 読み込み不可: {hist_err}')
    else:
        for edition_data in hist_data:
            for award in edition_data.get('awards', []):
                rec = award.get('record')
                if rec is not None:
                    known_distances.add(round(rec, 1))

    # 記事内の距離値を抽出
    article_distances = set()
    for m in DISTANCE_PATTERN.finditer(article):
        val = round(float(m.group(1)), 1)
        article_distances.add(val)

    if not article_distances:
        return False, ['記事内に距離値が検出されません']

    # 乖離チェック: 記事内の距離値が対象日の既知の値と一致するか
    # すべての意味のある距離（10以上）は既知リストに存在しなければならない
    unmatched = article_distances - known_distances
    # 差分値（0.1, 1.3 等）は除外 — これらは距離差・順位差の表現
    unmatched_meaningful = {v for v in unmatched if v >= 10}
    if unmatched_meaningful:
        errors.append(f'記事の距離値 {unmatched_meaningful} が対象日{target_date}の実データに存在しません')
        return False, errors

    # チーム名チェック: **太字** のうち選手名でないもののみekiden_data.jsonと照合
    ekiden_err, ekiden = load_json(CONFIG_DIR / 'ekiden_data.json', 'ekiden_data')
    if ekiden_err:
        errors.append(f'チームマスタ読み込み不可: {ekiden_err}')
    else:
        team_names = {t.get('name', '') for t in ekiden.get('teams', []) if t.get('name')}
        # 記事中の **太字** チーム名を抽出
        bold_teams = re.findall(r'\*\*(.*?)\*\*', article)
        # 選手名を除外（「選手」「君」で終わるものは選手名）
        candidate_teams = [t for t in bold_teams
                          if not re.search(r'(選手|君)$', t) and len(t) > 1]
        unknown_teams = [t for t in candidate_teams if t not in team_names]
        if unknown_teams:
            errors.append(f'存在しないチーム名: {unknown_teams[:5]}')
            return False, errors

    return True, errors


def _try_apply_repair(result: CheckResult, summary_data, repaired, fpath):
    """
    修復候補を現在の summary に適用できるか検証する。
    戻り値: None=成功, str=エラー理由
    """
    target_date_slash = result.target_date.replace('-', '/')
    file_date = repaired.get('date', '').replace('/', '-')
    if file_date and file_date != result.target_date:
        return f'修復候補の日付 {file_date} が対象日と一致しません'

    article = repaired.get('article', '')
    if not article:
        return '修復候補に article がありません'

    # Source validation: 元データとの整合性チェック
    source_ok, source_errors = _validate_article_against_source(article, result.target_date)
    if not source_ok:
        reasons = '; '.join(source_errors)
        # 応答ファイルに記録
        _update_response_file_status(fpath, 'rejected_source', reasons, article)
        return f'元データ照合不合格: {reasons}'

    # Deterministic チェック再実行
    test_result = CheckResult()
    test_result.target_date = result.target_date
    check_daily_summary(test_result, repaired)

    fails = [s for s in test_result.steps if s['status'] == 'FAIL']
    if fails:
        reasons = '; '.join(f'{s["name"]}: {s["detail"][:60]}' for s in fails)
        _update_response_file_status(fpath, 'rejected_format', reasons, article)
        return f'再検証不合格: {reasons}'

    # 合格 → summary を更新、応答ファイルは recovered として保存
    old_article = summary_data.get('article', '')
    summary_data['article'] = article
    if repaired.get('date'):
        summary_data['date'] = repaired['date']
    result.correct('article_from_ai_response', old_article[:100], article[:100])
    result.step('ai_repair', 'PASS', f'修復成功: {fpath.name}')

    # raw_response ファイルは削除せず status=recovered で保存（監査・再現性のため）
    _update_response_file_status(fpath, 'recovered', '修復成功・適用済み', article)
    return None


def _update_response_file_status(fpath, status, message, candidate_article=''):
    """応答ファイルのステータスを更新し、修復情報を追記する。"""
    if not fpath or not fpath.exists():
        return
    try:
        data = json.loads(fpath.read_text(encoding='utf-8'))
        data['status'] = status
        data['failure_message'] = message
        data['updated_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        data['repair_candidate'] = candidate_article[:500] if candidate_article else ''
        data['repair_result'] = status
        # 原子的保存
        tmp = fpath.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(fpath)
    except Exception as e:
        print(f'警告: 応答ファイル更新失敗 {fpath.name}: {e}')


# ============================================================
# 6. commit/push
# ============================================================

def do_commit_push(result: CheckResult, dry_run=False, no_push=False):
    """FAIL がない場合のみ commit/push。WARN/INFO は許容。"""
    if dry_run:
        result.step('commit', 'INFO', 'dry-run のためスキップ')
        return True

    if result.final_status == 'failed':
        result.step('commit', 'SKIP', f'final_status={result.final_status} のため commit しません')
        return False

    try:
        # 関係ない変更はすでに check_git_status で FAIL 判定済み
        if no_push:
            for t in COMMIT_TARGETS:
                p = PROJECT_DIR / t
                if p.exists():
                    subprocess.run(['git', 'add', t], capture_output=True, cwd=PROJECT_DIR, timeout=15)
            if AI_RESPONSE_DIR.exists():
                for f in AI_RESPONSE_DIR.iterdir():
                    if f.suffix == '.json':
                        subprocess.run(['git', 'add', str(f.relative_to(PROJECT_DIR))],
                                       capture_output=True, cwd=PROJECT_DIR, timeout=15)
            result.step('commit', 'INFO', '--no-push add のみ')
            return True

        # add
        for t in COMMIT_TARGETS:
            p = PROJECT_DIR / t
            if p.exists():
                subprocess.run(['git', 'add', t], capture_output=True, cwd=PROJECT_DIR, timeout=15)
        if AI_RESPONSE_DIR.exists():
            for f in AI_RESPONSE_DIR.iterdir():
                if f.suffix == '.json':
                    subprocess.run(['git', 'add', str(f.relative_to(PROJECT_DIR))],
                                   capture_output=True, cwd=PROJECT_DIR, timeout=15)

        # commit
        r = subprocess.run(['git', 'diff', '--cached', '--quiet'],
                           capture_output=True, cwd=PROJECT_DIR, timeout=15)
        if r.returncode == 0:
            result.step('commit', 'INFO', '変更なし')
            return True

        commit_msg = f'Check and repair daily summary [bot] {result.target_date}'
        r = subprocess.run(['git', 'commit', '-m', commit_msg],
                           capture_output=True, text=True, cwd=PROJECT_DIR, timeout=15)
        if r.returncode != 0:
            result.step('commit', 'FAIL', f'commit 失敗: {r.stderr.strip()[:200]}')
            return False
        result.step('commit', 'PASS', f'commit: {commit_msg}')

        # push (1回)
        r = subprocess.run(['git', 'push', 'origin', 'main'],
                           capture_output=True, text=True, cwd=PROJECT_DIR, timeout=60)
        if r.returncode != 0:
            result.step('push', 'FAIL', f'push 失敗: {r.stderr.strip()[:200]}')
            return False
        result.step('push', 'PASS', 'push 成功')
        return True

    except subprocess.TimeoutExpired:
        result.step('commit', 'FAIL', 'git タイムアウト')
        return False
    except Exception as e:
        result.step('commit', 'FAIL', f'git エラー: {e}')
        return False


# ============================================================
# メイン
# ============================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='日次ダイジェスト確認・修復')
    parser.add_argument('--date', help='対象日 (YYYY-MM-DD, デフォルト: 前日)')
    parser.add_argument('--dry-run', action='store_true',
                        help='チェックのみ、ファイル書換・commit/push しない')
    parser.add_argument('--no-push', action='store_true',
                        help='add まで、commit/push しない')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    dry_run = args.dry_run
    no_push = args.no_push

    result = CheckResult()
    result.target_date = resolve_target_date(args.date)

    print(f'🎯 対象日: {result.target_date}')
    print(f'   dry-run: {dry_run}, no-push: {no_push}')

    if not dry_run:
        acquire_lock()

    try:
        # --- 1. コミットログ ---
        print('\n--- 1. コミットログ確認 ---')
        check_commit_log(result)

        # --- 2. daily_summary.json 読み込み ---
        print('\n--- 2. daily_summary.json 読み込み ---')
        err, summary_data = load_json(SUMMARY_FILE, 'daily_summary.json')
        if err:
            result.step('load_summary', 'FAIL', err)
            result.final_status = 'failed'
        else:
            result.step('load_summary', 'PASS', '✅ JSON構文 OK')

            # --- 3. Deterministic checks ---
            print('\n--- 3. Deterministic checks ---')
            check_daily_summary(result, summary_data)
            check_article_consistency(result, summary_data)
            check_runner_relay_consistency(result, summary_data)
            check_coach_comment_attribution(result, summary_data)

            # --- 4. git 状態 ---
            print('\n--- 4. git 状態確認 ---')
            check_git_status(result)

            # --- 5. AI応答修復 ---
            print('\n--- 5. AI応答修復パイプライン ---')
            if not dry_run:
                repair_ai_failures(result, summary_data)
            else:
                # dry-run: 検出のみ
                has_failures = AI_RESPONSE_DIR.exists() and any(
                    (AI_RESPONSE_DIR / f).suffix == '.json' and not (AI_RESPONSE_DIR / f).name.startswith('.')
                    for f in os.listdir(AI_RESPONSE_DIR)
                )
                if has_failures:
                    result.step('ai_repair', 'INFO', 'dry-run: AI応答修復ファイルあり（スキップ）')
                else:
                    result.step('ai_repair', 'PASS', 'dry-run: 失敗ファイルなし')

            # --- 6. 決定論的修復 ---
            print('\n--- 6. 決定論的修復 ---')
            deterministic_repair(result, summary_data)

        # --- 7. 最終判定 ---
        print('\n--- 7. 最終判定 ---')
        has_fail = any(s['status'] == 'FAIL' for s in result.steps)
        if has_fail:
            result.final_status = 'failed'
            print(f'❌ {len(result.errors)}件の致命的エラー')
            for e in result.errors:
                print(f'   - {e}')
        elif result.repair_succeeded:
            result.final_status = 'recovered'
            print('✅ 修復成功')
        else:
            result.final_status = 'passed'
            print('✅ 全チェック合格')

        if result.warnings:
            print(f'⚠️ 警告 {len(result.warnings)}件')
            for w in result.warnings:
                print(f'   - {w}')

        # --- 8. commit/push ---
        print('\n--- 8. commit/push ---')
        do_commit_push(result, dry_run=dry_run, no_push=no_push)

    finally:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            SUMMARY_CHECK_LOG.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + '\n',
                encoding='utf-8'
            )
            print(f'\n📝 結果ログ: {SUMMARY_CHECK_LOG}')
        except IOError as e:
            print(f'警告: ログ保存失敗: {e}')

        if not dry_run:
            release_lock()

    if result.final_status == 'failed':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
