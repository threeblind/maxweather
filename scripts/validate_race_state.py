#!/usr/bin/env python3
"""
チーム状態 (ekiden_state.json) と個人記録 (individual_results.json) の整合性を検証する。

ルール:
- 各チームの ekiden_state.totalDistance が個人記録の合計を下回らない
- 個人記録の合計が leg_boundaries の currentLeg 境界を超えている場合と currentLeg の整合
- teamId 欠落・未知選手・JSON破損は FAIL

戻り値: 0=合格, 1=不整合あり
"""
import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'
CONFIG_DIR = PROJECT_DIR / 'config'

STATE_FILE = Path(os.environ.get('VALIDATE_STATE_FILE', str(DATA_DIR / 'ekiden_state.json')))
INDIVIDUAL_RESULTS_FILE = Path(os.environ.get('VALIDATE_INDIVIDUAL_FILE', str(DATA_DIR / 'individual_results.json')))
EKIDEN_DATA_FILE = Path(os.environ.get('VALIDATE_EKIDEN_FILE', str(CONFIG_DIR / 'ekiden_data.json')))


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

    # --- teamごとに検証 ---
    for team_state in state_data:
        tid = team_state.get('id')
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
