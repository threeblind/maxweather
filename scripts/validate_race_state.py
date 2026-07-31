#!/usr/bin/env python3
"""
チーム状態 (ekiden_state.json) と個人記録 (individual_results.json) の整合性を検証する。

ルール (severity 分類):
- fatal (exit 1): 全体停止が必要な問題
  - JSON破損 / 必須ファイル欠落
  - state全体が配列でない / leg_boundaries欠落
  - teamId欠落(全体構造) / stateに存在しないteamId (orphan)
  - shadow_team.json の構造破損 / decode error (全体構造の計算不能)
- warning (exit 2): 大学単位・局所的な問題 (degraded 継続可)
  - W1: 特定チームの state.totalDistance と個人記録合計の差
  - W2: 特定チームの currentLeg と個人記録の最大区間の差 (交代由来の先行含む)
  - W3: 区間記録連合の局所的な状態差 (totalDistance減少, currentLeg/境界不一致, state存在なし)
  - W4: 局所的な teamId 欠落 (unknown_team_runners 等)

戻り値 (CLI終了コード): 0=問題なし, 1=fatal, 2=warningのみ
標準出力: 従来形式の日本語メッセージ + 最終行に機械可読 JSON (VALIDATION_RESULT {...})
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'
CONFIG_DIR = PROJECT_DIR / 'config'

STATE_FILE = Path(os.environ.get('VALIDATE_STATE_FILE', str(DATA_DIR / 'ekiden_state.json')))
INDIVIDUAL_RESULTS_FILE = Path(os.environ.get('VALIDATE_INDIVIDUAL_FILE', str(DATA_DIR / 'individual_results.json')))
EKIDEN_DATA_FILE = Path(os.environ.get('VALIDATE_EKIDEN_FILE', str(CONFIG_DIR / 'ekiden_data.json')))
SHADOW_TEAM_FILE = Path(os.environ.get('VALIDATE_SHADOW_FILE', str(CONFIG_DIR / 'shadow_team.json')))
# 前回状態ファイルの明示指定（テスト用）。未指定時は直近の daily_snapshot を自動探索する。
PREVIOUS_STATE_FILE = os.environ.get('VALIDATE_PREVIOUS_STATE_FILE', '') or None

# --- severity コード定義 ---
SEV_FATAL = 'fatal'
SEV_WARNING = 'warning'

# 直近の検証結果 (構造化 issues)。CLI 出力と機械可読出力に使用する。
LAST_ISSUES = []
# 直近で検証した全大学 [{team_id, team_name}]
LAST_VALIDATED_TEAMS = []


def make_issue(severity, code, message, team_id=None, team_name=None):
    """構造化された issue を生成する。"""
    return {
        'severity': severity,
        'code': code,
        'team_id': team_id,
        'team_name': team_name,
        'message': message,
    }


def load_json(path, label=''):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return None, json.load(f)
    except FileNotFoundError:
        return f'{label} not found: {path}', None
    except json.JSONDecodeError as e:
        return f'{label} decode error: {e}', None
    except IOError as e:
        return f'{label} IO error: {e}', None


def determine_leg_from_total_distance(total_distance, leg_boundaries):
    """総合距離から 1-based の区間番号を返す（generate_report.py と同一ロジック）。境界値は次区間扱い。"""
    try:
        total_dist = float(total_distance)
    except (TypeError, ValueError):
        return 1

    if total_dist < 0:
        return 1

    for i, boundary in enumerate(leg_boundaries):
        if total_dist < boundary:
            return i + 1

    return len(leg_boundaries) + 1


def validate_shadow_structure(shadow_data):
    """config/shadow_team.json の JSON 構造を検証し、fatal issue リストを返す。"""
    issues = []
    if not isinstance(shadow_data, dict):
        return [make_issue(SEV_FATAL, 'F4', 'shadow_team.json is not an object')]

    if not shadow_data.get('id'):
        issues.append(make_issue(SEV_FATAL, 'F4', 'shadow_team.json: id がありません'))
    if not shadow_data.get('name'):
        issues.append(make_issue(SEV_FATAL, 'F4', 'shadow_team.json: name がありません'))

    runners = shadow_data.get('runners')
    if not isinstance(runners, list) or not runners:
        issues.append(make_issue(SEV_FATAL, 'F4', 'shadow_team.json: runners が空またはリストではありません'))
    else:
        for idx, r in enumerate(runners):
            if not isinstance(r, dict):
                issues.append(make_issue(SEV_FATAL, 'F4', f'shadow_team.json runners[{idx}]: オブジェクトではありません'))
                continue
            label = r.get('name', f'runners[{idx}]')
            if not r.get('leg'):
                issues.append(make_issue(SEV_FATAL, 'F4', f'shadow_team.json {label}: leg がありません'))
            if not r.get('name'):
                issues.append(make_issue(SEV_FATAL, 'F4', f'shadow_team.json runners[{idx}]: name がありません'))
            try:
                record = float(r.get('record', 0) or 0)
            except (TypeError, ValueError):
                issues.append(make_issue(SEV_FATAL, 'F4', f'shadow_team.json {label}: record が数値ではありません'))
                record = 0.0
            if record <= 0:
                issues.append(make_issue(SEV_FATAL, 'F4', f'shadow_team.json {label}: record が 0 以下です'))
    return issues


def is_shadow_state(team_state, shadow_data):
    """state エントリがシャドーチームか判定する（config の id/name 一致、または is_shadow_confederation フラグ）。"""
    if not isinstance(team_state, dict):
        return False
    if team_state.get('is_shadow_confederation'):
        return True
    if isinstance(shadow_data, dict):
        sid = shadow_data.get('id')
        sname = shadow_data.get('name')
        if sid is not None and team_state.get('id') == sid:
            return True
        if sname and team_state.get('name') == sname:
            return True
    return False


def find_previous_shadow_total(shadow_id, shadow_name):
    """
    前回のシャドーチーム totalDistance を探す。
    - VALIDATE_PREVIOUS_STATE_FILE が指定されていればそのファイルを使う
    - 未指定なら data/daily_snapshots/ の今日より前の最新 ekiden_state.json を自動探索する
    見つからない場合は None（非減少チェックはスキップ）。
    """
    candidates = []
    if PREVIOUS_STATE_FILE:
        candidates = [Path(PREVIOUS_STATE_FILE)]
    else:
        snapshots_dir = DATA_DIR / 'daily_snapshots'
        if snapshots_dir.is_dir():
            today = date.today().isoformat()
            candidates = [
                d / 'ekiden_state.json'
                for d in sorted(snapshots_dir.iterdir())
                if d.is_dir() and d.name < today and (d / 'ekiden_state.json').exists()
            ]

    for f in reversed(candidates):
        try:
            with open(f, 'r', encoding='utf-8') as fh:
                prev_state = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(prev_state, list):
            continue
        for s in prev_state:
            if not isinstance(s, dict):
                continue
            if (shadow_id is not None and s.get('id') == shadow_id) or (shadow_name and s.get('name') == shadow_name):
                try:
                    return float(s.get('totalDistance'))
                except (TypeError, ValueError):
                    return None
    return None


def validate_shadow_team(shadow_data, shadow_states, leg_boundaries):
    """シャドーチーム専用検証。warning issue リストを返す。個人記録合計との比較は行わない。"""
    issues = []
    shadow_id = shadow_data.get('id')
    shadow_name = shadow_data.get('name') or f'id={shadow_id}'

    # team/state 存在 (W3: 局所的な状態差)
    if not shadow_states:
        issues.append(make_issue(
            SEV_WARNING, 'W3',
            f'shadow team {shadow_name}: ekiden_state.json に該当する state がありません',
            team_id=shadow_id, team_name=shadow_name,
        ))
        return issues

    state_entry = shadow_states[0]
    total = state_entry.get('totalDistance')
    leg = state_entry.get('currentLeg')

    if total is None:
        issues.append(make_issue(SEV_WARNING, 'W3', f'shadow team {shadow_name}: totalDistance がありません',
                                 team_id=shadow_id, team_name=shadow_name))
    else:
        try:
            total = float(total)
        except (TypeError, ValueError):
            issues.append(make_issue(SEV_WARNING, 'W3',
                                     f'shadow team {shadow_name}: totalDistance が数値ではありません: {total!r}',
                                     team_id=shadow_id, team_name=shadow_name))
            total = None

    if leg is None:
        issues.append(make_issue(SEV_WARNING, 'W3', f'shadow team {shadow_name}: currentLeg がありません',
                                 team_id=shadow_id, team_name=shadow_name))
    else:
        try:
            leg = int(leg)
        except (TypeError, ValueError):
            issues.append(make_issue(SEV_WARNING, 'W3',
                                     f'shadow team {shadow_name}: currentLeg が整数ではありません: {leg!r}',
                                     team_id=shadow_id, team_name=shadow_name))
            leg = None

    if total is None or leg is None:
        return issues

    # totalDistance 非減少（前回比較が可能な場合のみ）
    prev_total = find_previous_shadow_total(shadow_id, shadow_name)
    if prev_total is None:
        print(f'ℹ️ shadow team {shadow_name}: 前回状態が比較できないため totalDistance 非減少チェックをスキップします')
    elif total < prev_total - 0.05:  # 0.1km 単位で丸められるため 0.05 の誤差を許容
        issues.append(make_issue(
            SEV_WARNING, 'W3',
            f'shadow team {shadow_name}: state.totalDistance={total:.1f} が '
            f'前回 {prev_total:.1f} より減少しています',
            team_id=shadow_id, team_name=shadow_name,
        ))

    # currentLeg と距離境界の整合 (W3: 交代由来の先行も warning 扱い、削除しない)
    expected_leg = determine_leg_from_total_distance(total, leg_boundaries)
    if leg != expected_leg:
        issues.append(make_issue(
            SEV_WARNING, 'W3',
            f'shadow team {shadow_name}: state.currentLeg={leg} だが '
            f'totalDistance={total:.1f} から期待される区間は {expected_leg} です',
            team_id=shadow_id, team_name=shadow_name,
        ))

    return issues


def validate():
    """
    検証を実行し終了コード (int) を返す。
    0=問題なし, 1=fatal, 2=warningのみ。
    構造化 issues はグローバル LAST_ISSUES に格納する。
    """
    global LAST_ISSUES, LAST_VALIDATED_TEAMS
    issues = []
    fatal_errors = []  # 読み込み失敗など即時 fatal

    # --- データ読み込み ---
    err, state_data = load_json(STATE_FILE, 'ekiden_state')
    if err:
        print(f'❌ {err}')
        fatal_errors.append(make_issue(SEV_FATAL, 'F1', err))
        LAST_ISSUES = issues + fatal_errors
        return 1

    err, ind_results = load_json(INDIVIDUAL_RESULTS_FILE, 'individual_results')
    if err:
        print(f'❌ {err}')
        fatal_errors.append(make_issue(SEV_FATAL, 'F1', err))
        LAST_ISSUES = issues + fatal_errors
        return 1

    err, ekiden_data = load_json(EKIDEN_DATA_FILE, 'ekiden_data')
    if err:
        print(f'❌ {err}')
        fatal_errors.append(make_issue(SEV_FATAL, 'F1', err))
        LAST_ISSUES = issues + fatal_errors
        return 1

    leg_boundaries = ekiden_data.get('leg_boundaries', [])
    if not leg_boundaries:
        print('❌ leg_boundaries not found in ekiden_data.json')
        fatal_errors.append(make_issue(SEV_FATAL, 'F2', 'leg_boundaries not found in ekiden_data.json'))
        LAST_ISSUES = issues + fatal_errors
        return 1

    # --- シャドーチーム定義の読み込み（存在しない場合は検証スキップ） ---
    shadow_data = None
    shadow_load_err = None
    try:
        with open(SHADOW_TEAM_FILE, 'r', encoding='utf-8') as f:
            shadow_data = json.load(f)
    except FileNotFoundError:
        print('ℹ️ shadow_team.json が見つからないため、シャドーチーム検証はスキップします')
    except json.JSONDecodeError as e:
        shadow_load_err = f'shadow_team.json decode error: {e}'
    except IOError as e:
        shadow_load_err = f'shadow_team.json IO error: {e}'
    if shadow_load_err:
        issues.append(make_issue(SEV_FATAL, 'F4', shadow_load_err))

    # shadow_team.json の構造検証 (F4: 全体構造の計算不能)
    if shadow_data is not None:
        issues.extend(validate_shadow_structure(shadow_data))

    # state がリスト形式か確認 (F2)
    if not isinstance(state_data, list):
        print('❌ ekiden_state.json is not a list')
        fatal_errors.append(make_issue(SEV_FATAL, 'F2', 'ekiden_state.json is not a list'))
        LAST_ISSUES = issues + fatal_errors
        return 1

    # team_id → team_name マップ
    team_name_map = {t.get('id'): t.get('name', '?') for t in ekiden_data.get('teams', []) if t.get('id')}

    # --- individual_results の runner → teamId 集計 ---
    # team_id → [runners]
    team_runners = {}
    unknown_team_runners = []
    for runner_name, info in ind_results.items():
        tid = info.get('teamId')
        if tid is None:
            unknown_team_runners.append(runner_name)
            continue
        team_runners.setdefault(tid, []).append(runner_name)

    # unknown_team_runners: 局所なら warning (W4)、多数なら全体構造破損として fatal (F3)
    if unknown_team_runners:
        if len(unknown_team_runners) <= 10:
            issues.append(make_issue(SEV_WARNING, 'W4', f'teamId 欠落: {unknown_team_runners}'))
        else:
            issues.append(make_issue(SEV_FATAL, 'F3', f'teamId 欠落 (多数): {len(unknown_team_runners)}件'))

    # individual_results の teamId がどの state の id とも一致しない場合も fatal (F3)
    state_ids = set(s.get('id') for s in state_data if isinstance(s, dict) and s.get('id') is not None)
    ind_team_ids = set(info.get('teamId') for info in ind_results.values() if info.get('teamId') is not None)
    orphan_team_ids = ind_team_ids - state_ids
    if orphan_team_ids:
        issues.append(make_issue(SEV_FATAL, 'F3',
                                 f'individual_results に存在するが ekiden_state に存在しない teamId: {orphan_team_ids}'))

    # --- state 要素の構造検証 (F2/F3) ---
    config_team_ids = set(t.get('id') for t in ekiden_data.get('teams', []) if t.get('id') is not None)
    for idx, team_state in enumerate(state_data):
        if not isinstance(team_state, dict):
            issues.append(make_issue(
                SEV_FATAL, 'F2',
                f'ekiden_state[{idx}]: 要素がオブジェクトではありません: {type(team_state).__name__}'))
            continue
        tid = team_state.get('id')
        if tid is None:
            issues.append(make_issue(
                SEV_FATAL, 'F3', f'ekiden_state[{idx}]: id がありません'))
            continue
        # state に存在するが config/ekiden_data.json にない team id (シャドー以外) は fatal
        if not is_shadow_state(team_state, shadow_data) and tid not in config_team_ids:
            issues.append(make_issue(
                SEV_FATAL, 'F3',
                f'ekiden_state に存在するが config/ekiden_data.json に存在しない teamId: {tid}',
                team_id=tid, team_name=team_state.get('name', f'id={tid}')))
        # totalDistance / currentLeg が数値化不能な場合も fatal (F3)
        for field in ('totalDistance', 'currentLeg'):
            raw = team_state.get(field)
            try:
                float(raw)
            except (TypeError, ValueError):
                issues.append(make_issue(
                    SEV_FATAL, 'F3',
                    f'ekiden_state[{idx}] id={tid}: {field} が数値化できません: {raw!r}',
                    team_id=tid, team_name=team_state.get('name', f'id={tid}')))

    # --- teamごとに検証（シャドーチームは専用検証へ分離） ---
    shadow_states = []
    for team_state in state_data:
        if not isinstance(team_state, dict):
            # 構造検証 (F2) で既に報告済み。ここではスキップしてクラッシュ回避。
            continue
        tid = team_state.get('id')
        if tid is None:
            # 構造検証 (F3) で既に報告済み。ここではスキップしてクラッシュ回避。
            continue

        if is_shadow_state(team_state, shadow_data):
            shadow_states.append(team_state)
            continue

        try:
            state_total = float(team_state.get('totalDistance', 0.0))
            state_leg = int(team_state.get('currentLeg', 1))
        except (TypeError, ValueError):
            # 構造検証 (F3) で既に報告済み。数値化不能な要素はスキップしてクラッシュ回避。
            continue

        team_name = team_name_map.get(tid, team_state.get('name', f'id={tid}'))
        runner_list = team_runners.get(tid, [])

        # 個人記録の合計を計算
        runner_total = 0.0
        runner_max_leg = 0
        for rname in runner_list:
            info = ind_results.get(rname, {})
            for rec in info.get('records', []):
                dist = rec.get('distance', 0) or 0
                runner_total += dist
                leg = rec.get('leg', 0) or 0
                if leg > runner_max_leg:
                    runner_max_leg = leg

        # 1. totalDistance 検証 (W1)
        # state が個人合計を下回っている場合は不整合（個人記録が更新されたがstate未更新）
        if state_total < runner_total - 0.01:  # float 誤差許容
            issues.append(make_issue(
                SEV_WARNING, 'W1',
                f'{team_name}: state.totalDistance={state_total:.1f} < '
                f'個人記録合計={runner_total:.1f} (差分={runner_total-state_total:.1f})',
                team_id=tid, team_name=team_name,
            ))

        # 2. currentLeg 検証 (W2)
        # currentLeg が1の場合は runner_max_leg が0でも可（未出走）
        if state_leg > 1 and runner_max_leg > 0:
            # currentLeg は完了している区間の次、なので runner_max_leg >= state_leg-1 が妥当
            if runner_max_leg < state_leg - 1:
                issues.append(make_issue(
                    SEV_WARNING, 'W2',
                    f'{team_name}: state.currentLeg={state_leg} だが '
                    f'個人記録の最大区間={runner_max_leg} (状態が進みすぎ)',
                    team_id=tid, team_name=team_name,
                ))

            # 3. 区間境界チェック (W3: 交代由来の currentLeg 先行も warning 扱い、削除しない)
            # currentLeg は距離到達だけでなく、速報で確定した交代を表す。
            # 交代済みでも次区間の境界未到達の場合があるため、境界値だけで全体停止しない (warning)
            if state_leg > 1 and state_leg <= len(leg_boundaries):
                boundary = leg_boundaries[state_leg - 2]  # 前の区間の境界
                if runner_total < boundary - 1:
                    issues.append(make_issue(
                        SEV_WARNING, 'W3',
                        f'{team_name}: currentLeg={state_leg} だが '
                        f'個人記録合計={runner_total:.1f} < 境界={boundary} (状態が進みすぎ)',
                        team_id=tid, team_name=team_name,
                    ))

    # --- シャドーチーム検証（個人記録合計との比較はスキップ） ---
    if isinstance(shadow_data, dict) and shadow_data.get('id'):
        issues.extend(validate_shadow_team(shadow_data, shadow_states, leg_boundaries))

    # --- 検証した全大学 (validated_teams) ---
    validated_teams = []
    for team_state in state_data:
        if not isinstance(team_state, dict):
            continue
        tid = team_state.get('id')
        if tid is None:
            continue
        name = team_state.get('name') or team_name_map.get(tid, f'id={tid}')
        validated_teams.append({'team_id': tid, 'team_name': name})

    # --- exit code 判定 ---
    has_fatal = any(i.get('severity') == SEV_FATAL for i in issues)
    if has_fatal:
        exit_code = 1
    elif issues:
        exit_code = 2
    else:
        exit_code = 0

    LAST_ISSUES = issues
    LAST_VALIDATED_TEAMS = validated_teams
    return exit_code


def print_issues(issues):
    """従来形式の日本語メッセージを出力する。"""
    if not issues:
        print('✅ 全チームの状態と個人記録が整合')
        return
    fatal_count = sum(1 for i in issues if i.get('severity') == SEV_FATAL)
    warning_count = sum(1 for i in issues if i.get('severity') == SEV_WARNING)
    if fatal_count:
        print(f'❌ {len(issues)}件の不整合 (fatal={fatal_count}, warning={warning_count})')
    else:
        print(f'⚠️ {len(issues)}件の警告 (fatal=0, warning={warning_count})')
    for i in issues:
        prefix = '❌' if i.get('severity') == SEV_FATAL else '⚠️'
        print(f'   {prefix} [{i.get("code")}] {i.get("message")}')


if __name__ == '__main__':
    exit_code = validate()
    print_issues(LAST_ISSUES)
    # 機械可読出力 (D5): 最終行に1行JSON (validated_teams も含む)
    print(f'VALIDATION_RESULT {json.dumps({"exit_code": exit_code, "issues": LAST_ISSUES, "validated_teams": LAST_VALIDATED_TEAMS}, ensure_ascii=False)}')
    sys.exit(exit_code)
