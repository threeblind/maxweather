#!/usr/bin/env python3
"""
チーム状態 (ekiden_state.json) と個人記録 (individual_results.json) の整合性を検証する。

ルール:
- 通常チーム (既存 fail-fast を維持):
  - ekiden_state.totalDistance が個人記録の合計を下回らない
  - 個人記録の合計が leg_boundaries の currentLeg 境界を超えている場合と currentLeg の整合
  - teamId 欠落・未知選手・JSON破損は FAIL
- シャドーチーム (config/shadow_team.json の id/name で識別):
  - 個人記録合計との比較はスキップ（シャドーランナーの個人記録は state と意味論が異なるため）
  - 代わりに以下を検証:
    - shadow_team.json の JSON 構造 (id / name / runners[leg, name, record])
    - ekiden_state.json への team/state 存在
    - totalDistance 非減少（前回状態が比較可能な場合のみ。直近の daily_snapshot を自動探索、
      または VALIDATE_PREVIOUS_STATE_FILE で明示指定）
    - currentLeg と距離境界の整合（generate_report.py の determine_leg_from_total_distance と同一ロジック）

戻り値: 0=合格, 1=不整合あり
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
    """config/shadow_team.json の JSON 構造を検証し、エラーリストを返す。"""
    errors = []
    if not isinstance(shadow_data, dict):
        return ['shadow_team.json is not an object']

    if not shadow_data.get('id'):
        errors.append('shadow_team.json: id がありません')
    if not shadow_data.get('name'):
        errors.append('shadow_team.json: name がありません')

    runners = shadow_data.get('runners')
    if not isinstance(runners, list) or not runners:
        errors.append('shadow_team.json: runners が空またはリストではありません')
    else:
        for idx, r in enumerate(runners):
            if not isinstance(r, dict):
                errors.append(f'shadow_team.json runners[{idx}]: オブジェクトではありません')
                continue
            label = r.get('name', f'runners[{idx}]')
            if not r.get('leg'):
                errors.append(f'shadow_team.json {label}: leg がありません')
            if not r.get('name'):
                errors.append(f'shadow_team.json runners[{idx}]: name がありません')
            try:
                record = float(r.get('record', 0) or 0)
            except (TypeError, ValueError):
                errors.append(f'shadow_team.json {label}: record が数値ではありません')
                record = 0.0
            if record <= 0:
                errors.append(f'shadow_team.json {label}: record が 0 以下です')
    return errors


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
    """シャドーチーム専用検証。エラーリストを返す。個人記録合計との比較は行わない。"""
    errors = []
    shadow_id = shadow_data.get('id')
    shadow_name = shadow_data.get('name') or f'id={shadow_id}'

    # team/state 存在
    if not shadow_states:
        errors.append(f'shadow team {shadow_name}: ekiden_state.json に該当する state がありません')
        return errors

    state_entry = shadow_states[0]
    total = state_entry.get('totalDistance')
    leg = state_entry.get('currentLeg')

    if total is None:
        errors.append(f'shadow team {shadow_name}: totalDistance がありません')
    else:
        try:
            total = float(total)
        except (TypeError, ValueError):
            errors.append(f'shadow team {shadow_name}: totalDistance が数値ではありません: {total!r}')
            total = None

    if leg is None:
        errors.append(f'shadow team {shadow_name}: currentLeg がありません')
    else:
        try:
            leg = int(leg)
        except (TypeError, ValueError):
            errors.append(f'shadow team {shadow_name}: currentLeg が整数ではありません: {leg!r}')
            leg = None

    if total is None or leg is None:
        return errors

    # totalDistance 非減少（前回比較が可能な場合のみ）
    prev_total = find_previous_shadow_total(shadow_id, shadow_name)
    if prev_total is None:
        print(f'ℹ️ shadow team {shadow_name}: 前回状態が比較できないため totalDistance 非減少チェックをスキップします')
    elif total < prev_total - 0.05:  # 0.1km 単位で丸められるため 0.05 の誤差を許容
        errors.append(
            f'shadow team {shadow_name}: state.totalDistance={total:.1f} が '
            f'前回 {prev_total:.1f} より減少しています'
        )

    # currentLeg と距離境界の整合
    expected_leg = determine_leg_from_total_distance(total, leg_boundaries)
    if leg != expected_leg:
        errors.append(
            f'shadow team {shadow_name}: state.currentLeg={leg} だが '
            f'totalDistance={total:.1f} から期待される区間は {expected_leg} です'
        )

    return errors


def validate():
    errors = []

    # --- データ読み込み ---
    err, state_data = load_json(STATE_FILE, 'ekiden_state')
    if err:
        print(f'❌ {err}')
        return 1

    err, ind_results = load_json(INDIVIDUAL_RESULTS_FILE, 'individual_results')
    if err:
        print(f'❌ {err}')
        return 1

    err, ekiden_data = load_json(EKIDEN_DATA_FILE, 'ekiden_data')
    if err:
        print(f'❌ {err}')
        return 1

    leg_boundaries = ekiden_data.get('leg_boundaries', [])
    if not leg_boundaries:
        print('❌ leg_boundaries not found in ekiden_data.json')
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
        errors.append(shadow_load_err)

    # shadow_team.json の構造検証
    if shadow_data is not None:
        errors.extend(validate_shadow_structure(shadow_data))

    # state がリスト形式か確認
    if not isinstance(state_data, list):
        print('❌ ekiden_state.json is not a list')
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

    if unknown_team_runners:
        errors.append(f'teamId 欠落: {unknown_team_runners}')

    # individual_results の teamId がどの state の id とも一致しない場合も FAIL
    state_ids = set(s.get('id') for s in state_data if s.get('id') is not None)
    ind_team_ids = set(info.get('teamId') for info in ind_results.values() if info.get('teamId') is not None)
    orphan_team_ids = ind_team_ids - state_ids
    if orphan_team_ids:
        errors.append(f'individual_results に存在するが ekiden_state に存在しない teamId: {orphan_team_ids}')

    # --- teamごとに検証（シャドーチームは専用検証へ分離） ---
    shadow_states = []
    for team_state in state_data:
        tid = team_state.get('id')

        if is_shadow_state(team_state, shadow_data):
            shadow_states.append(team_state)
            continue

        state_total = team_state.get('totalDistance', 0.0)
        state_leg = team_state.get('currentLeg', 1)

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

        # 1. totalDistance 検証
        # state が個人合計を下回っている場合は不整合（個人記録が更新されたがstate未更新）
        if state_total < runner_total - 0.01:  # float 誤差許容
            errors.append(
                f'{team_name}: state.totalDistance={state_total:.1f} < '
                f'個人記録合計={runner_total:.1f} (差分={runner_total-state_total:.1f})'
            )

        # 2. currentLeg 検証
        # currentLeg が1の場合は runner_max_leg が0でも可（未出走）
        if state_leg > 1 and runner_max_leg > 0:
            # currentLeg は完了している区間の次、なので runner_max_leg >= state_leg-1 が妥当
            if runner_max_leg < state_leg - 1:
                errors.append(
                    f'{team_name}: state.currentLeg={state_leg} だが '
                    f'個人記録の最大区間={runner_max_leg} (状態が進みすぎ)'
                )
            # また、currentLeg が leg_boundaries と合っているかも確認
            if state_leg > 1 and state_leg <= len(leg_boundaries):
                boundary = leg_boundaries[state_leg - 2]  # 前の区間の境界
                if runner_total < boundary - 1 and state_leg > 1:
                    errors.append(
                        f'{team_name}: currentLeg={state_leg} だが '
                        f'個人記録合計={runner_total:.1f} < 境界={boundary} (状態が進みすぎ)'
                    )

    # --- シャドーチーム検証（個人記録合計との比較はスキップ） ---
    if isinstance(shadow_data, dict) and shadow_data.get('id'):
        errors.extend(validate_shadow_team(shadow_data, shadow_states, leg_boundaries))

    # --- 出力 ---
    if errors:
        print(f'❌ {len(errors)}件の不整合')
        for e in errors:
            print(f'   - {e}')
        return 1
    else:
        print('✅ 全チームの状態と個人記録が整合')
        return 0


if __name__ == '__main__':
    sys.exit(validate())
