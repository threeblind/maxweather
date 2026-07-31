"""
scripts/validate_race_state.py のテスト。
環境変数でパスを差し替えて検証（モジュール変数は変更しない）。

- 通常チーム: 既存の fail-fast ルール（totalDistance >= 個人記録合計、currentLeg 整合）
- シャドーチーム: config/shadow_team.json の id/name で識別し、個人記録合計との比較はスキップ。
  JSON構造 / state存在 / totalDistance非減少 / currentLegと距離境界の整合を検証
"""
import sys
import json
import os
import shutil
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ============================================================
# テスト用ヘルパー
# ============================================================

# 通常テスト用の共通データ
DEFAULT_LEG_BOUNDARIES = [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055]
DEFAULT_SHADOW_CONFIG = {
    "id": 99,
    "name": "区間記録連合",
    "short_name": "区間記録",
    "is_shadow_confederation": True,
    "runners": [
        {"leg": 1, "name": "梁川", "team_name": "福島大学", "edition": 15, "record": 38.967},
        {"leg": 2, "name": "佐野", "team_name": "上武大学", "edition": 13, "record": 38.8},
        {"leg": 3, "name": "伊勢崎", "team_name": "上武大学", "edition": 13, "record": 39.067},
    ],
}


def _validate_with_data(state_list, ind_results, ekiden_data, shadow_data=None, previous_state_list=None):
    """環境変数でパスを差し替えて validate() を実行

    - shadow_data=None: シャドーチーム未設定として検証（shadow_team.json 不在扱い）
    - previous_state_list=None: 前回状態なし（非減少チェックはスキップ）
    """
    tmpdir = tempfile.mkdtemp(prefix='validate_test_')
    f_state = os.path.join(tmpdir, 'state.json')
    f_ind = os.path.join(tmpdir, 'ind.json')
    f_ek = os.path.join(tmpdir, 'ekiden.json')
    f_shadow = os.path.join(tmpdir, 'shadow_team.json')
    f_prev = os.path.join(tmpdir, 'prev_state.json')

    with open(f_state, 'w', encoding='utf-8') as fh:
        json.dump(state_list, fh, ensure_ascii=False)
    with open(f_ind, 'w', encoding='utf-8') as fh:
        json.dump(ind_results, fh, ensure_ascii=False)
    with open(f_ek, 'w', encoding='utf-8') as fh:
        json.dump(ekiden_data, fh, ensure_ascii=False)
    if shadow_data is not None:
        with open(f_shadow, 'w', encoding='utf-8') as fh:
            json.dump(shadow_data, fh, ensure_ascii=False)
    if previous_state_list is not None:
        with open(f_prev, 'w', encoding='utf-8') as fh:
            json.dump(previous_state_list, fh, ensure_ascii=False)

    env_keys = [
        'VALIDATE_STATE_FILE',
        'VALIDATE_INDIVIDUAL_FILE',
        'VALIDATE_EKIDEN_FILE',
        'VALIDATE_SHADOW_FILE',
        'VALIDATE_PREVIOUS_STATE_FILE',
    ]
    old_env = {k: os.environ.get(k) for k in env_keys}

    try:
        os.environ['VALIDATE_STATE_FILE'] = f_state
        os.environ['VALIDATE_INDIVIDUAL_FILE'] = f_ind
        os.environ['VALIDATE_EKIDEN_FILE'] = f_ek
        os.environ['VALIDATE_SHADOW_FILE'] = f_shadow  # 存在しない場合はスキップ扱い
        if previous_state_list is not None:
            os.environ['VALIDATE_PREVIOUS_STATE_FILE'] = f_prev
        else:
            # 自動探索で実データ (data/daily_snapshots) に触れないよう存在しないパスを明示指定
            os.environ['VALIDATE_PREVIOUS_STATE_FILE'] = os.path.join(tmpdir, 'no_prev_state.json')

        # 環境変数を反映するため、モジュールをリロード
        import validate_race_state
        import importlib
        importlib.reload(validate_race_state)
        rc = validate_race_state.validate()
        return rc
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        # 元のモジュールを再リロード（環境変数クリア後）
        import validate_race_state
        import importlib
        importlib.reload(validate_race_state)
        shutil.rmtree(tmpdir, ignore_errors=True)


def _regular_state(team_id, total, leg):
    return {"id": team_id, "currentLeg": leg, "totalDistance": total}


def _shadow_state(total, leg, name="区間記録連合", team_id=99):
    return {"id": team_id, "name": name, "currentLeg": leg, "totalDistance": total}


# ============================================================
# 通常チームの既存ケース（回帰）
# ============================================================

def test_consistent_state():
    """正常一致: state.totalDistance == 個人記録合計"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [_regular_state(1, 121.0, 2)]
    ind = {
        "美濃": {"teamId": 1, "records": [
            {"day": 1, "leg": 1, "distance": 40.8},
            {"day": 2, "leg": 1, "distance": 40.2},
            {"day": 3, "leg": 1, "distance": 40.0},
        ]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 0, f'expected=0 got={rc}'


def test_stale_state():
    """stateが個人合計を下回る"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 7, "name": "琉球大学"}]
    }
    state = [_regular_state(7, 98.9, 2)]
    ind = {
        "北原": {"teamId": 7, "records": [
            {"day": 1, "leg": 1, "distance": 38.0},
            {"day": 2, "leg": 1, "distance": 35.0},
            {"day": 3, "leg": 1, "distance": 33.0},
            {"day": 4, "leg": 1, "distance": 26.6},
        ]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 2, f'expected=2 (W1 warning) got={rc}'


def test_boundary_cross():
    """境界を跨いだ currentLeg の整合性"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [_regular_state(1, 150.0, 2)]
    ind = {
        "美濃": {"teamId": 1, "records": [
            {"day": 1, "leg": 1, "distance": 40.0},
            {"day": 2, "leg": 1, "distance": 35.0},
            {"day": 3, "leg": 1, "distance": 35.0},
            {"day": 4, "leg": 1, "distance": 30.0},
        ]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 0, f'expected=0 got={rc}'


def test_unknown_team_id():
    """unknown teamId → FAIL"""
    ekiden = {
        "leg_boundaries": [100, 210],
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [_regular_state(1, 120.0, 2)]
    ind = {
        "美濃": {"teamId": 99, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 1, f'expected=1 got={rc}'


def test_missing_team_id():
    """teamId欠落(局所) → W4 warning (exit 2)"""
    ekiden = {
        "leg_boundaries": [100, 210],
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [_regular_state(1, 120.0, 2)]
    ind = {
        "美濃": {"records": [{"day": 1, "leg": 1, "distance": 40.0}]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 2, f'expected=2 (W4 warning) got={rc}'


def test_invalid_json():
    """JSON破損 → FAIL"""
    import validate_race_state
    import importlib
    old = os.environ.get('VALIDATE_STATE_FILE')
    try:
        os.environ['VALIDATE_STATE_FILE'] = '/nonexistent/state.json'
        importlib.reload(validate_race_state)
        rc = validate_race_state.validate()
        assert rc == 1, f'expected=1 got={rc}'
    finally:
        if old is None:
            os.environ.pop('VALIDATE_STATE_FILE', None)
        else:
            os.environ['VALIDATE_STATE_FILE'] = old
        importlib.reload(validate_race_state)


def test_commit_daily_sh_has_validation():
    """commit_daily.sh に validation 呼び出しが含まれている"""
    sh = PROJECT_ROOT / 'commit_daily.sh'
    text = sh.read_text(encoding='utf-8')
    assert 'validate_race_state' in text


# ============================================================
# シャドーチームの正常ケース
# ============================================================

def test_shadow_team_consistent():
    """shadow 正常: 個人記録合計が境界未満でも state と整合していれば合格

    シャドーランナーの個人記録 (66.9km) は state.totalDistance (249.1km) と
    意味論が異なるため比較しない。
    """
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
        # シャドーランナーの個人記録合計は境界(210)未満だが比較しない
        "佐野": {"teamId": 99, "records": [{"day": 8, "leg": 3, "distance": 36.8},
                                           {"day": 9, "leg": 3, "distance": 30.1}]},
    }
    previous = [_shadow_state(200.0, 3)]
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG, previous_state_list=previous)
    assert rc == 0, f'expected=0 got={rc}'


def test_shadow_team_skips_individual_comparison():
    """shadow は個人記録合計が state を上回っていても比較しない"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
        # シャドーランナー個人記録合計が state を大幅に上回っても無視される
        "佐野": {"teamId": 99, "records": [{"day": 8, "leg": 3, "distance": 250.0}]},
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG)
    assert rc == 0, f'expected=0 got={rc}'


def test_shadow_team_previous_unavailable():
    """前回状態が無い場合は totalDistance 非減少チェックをスキップして合格"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    # previous_state_list=None → 前回なし（スキップ）
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG)
    assert rc == 0, f'expected=0 got={rc}'


def test_shadow_team_name_match():
    """state エントリが id でなく name で一致してもシャドーチームとして扱う"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        # id が異なるが name が一致
        _shadow_state(249.1, 3, team_id=999),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG)
    assert rc == 0, f'expected=0 got={rc}'


# ============================================================
# シャドーチームの不整合ケース
# ============================================================

def test_shadow_team_state_missing():
    """shadow config はあるが ekiden_state に存在しない → W3 warning (exit 2)"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [_regular_state(1, 120.0, 2)]  # シャドーチームなし
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG)
    assert rc == 2, f'expected=2 (W3 warning) got={rc}'


def test_shadow_team_bad_structure():
    """shadow_team.json の構造不正 (id 欠落) → FAIL"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    bad_config = {"name": "区間記録連合", "runners": []}
    rc = _validate_with_data(state, ind, ekiden, shadow_data=bad_config)
    assert rc == 1, f'expected=1 got={rc}'


def test_shadow_team_bad_runner_record():
    """shadow_team.json の runner record が 0 以下 → FAIL"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    bad_config = {
        "id": 99, "name": "区間記録連合",
        "runners": [{"leg": 1, "name": "梁川", "record": 0.0}],
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=bad_config)
    assert rc == 1, f'expected=1 got={rc}'


def test_shadow_total_distance_decreased():
    """shadow totalDistance が前回より減少 → W3 warning (exit 2)"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        _shadow_state(249.1, 3),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    previous = [_shadow_state(250.0, 3)]  # 前回の方が大きい
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG, previous_state_list=previous)
    assert rc == 2, f'expected=2 (W3 warning) got={rc}'


def test_shadow_current_leg_mismatch():
    """shadow currentLeg が totalDistance から期待される区間と不一致 → W3 warning (exit 2)"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [
        _regular_state(1, 120.0, 2),
        # totalDistance=249.1 は境界[100,210,310]で第3区のはずだが currentLeg=2
        _shadow_state(249.1, 2),
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=DEFAULT_SHADOW_CONFIG)
    assert rc == 2, f'expected=2 (W3 warning) got={rc}'


def test_shadow_missing_config_skips_checks():
    """shadow_team.json が無い場合はシャドーチーム検証をスキップ（通常チーム検証のみ）"""
    ekiden = {
        "leg_boundaries": DEFAULT_LEG_BOUNDARIES,
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    # is_shadow_confederation フラグ付き state は通常チーム検証から除外される
    state = [
        _regular_state(1, 120.0, 2),
        {"id": 99, "name": "区間記録連合", "currentLeg": 3, "totalDistance": 249.1,
         "is_shadow_confederation": True},
    ]
    ind = {
        "美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0},
                                          {"day": 2, "leg": 1, "distance": 40.0},
                                          {"day": 3, "leg": 1, "distance": 40.0}]},
    }
    rc = _validate_with_data(state, ind, ekiden, shadow_data=None)
    assert rc == 0, f'expected=0 got={rc}'


# ============================================================

if __name__ == '__main__':
    tests = [
        ("consistent_state", test_consistent_state),
        ("stale_state", test_stale_state),
        ("boundary_cross", test_boundary_cross),
        ("unknown_team_id", test_unknown_team_id),
        ("missing_team_id", test_missing_team_id),
        ("invalid_json", test_invalid_json),
        ("commit_sh_has_validation", test_commit_daily_sh_has_validation),
        ("shadow_team_consistent", test_shadow_team_consistent),
        ("shadow_team_skips_individual_comparison", test_shadow_team_skips_individual_comparison),
        ("shadow_team_previous_unavailable", test_shadow_team_previous_unavailable),
        ("shadow_team_name_match", test_shadow_team_name_match),
        ("shadow_team_state_missing", test_shadow_team_state_missing),
        ("shadow_team_bad_structure", test_shadow_team_bad_structure),
        ("shadow_team_bad_runner_record", test_shadow_team_bad_runner_record),
        ("shadow_total_distance_decreased", test_shadow_total_distance_decreased),
        ("shadow_current_leg_mismatch", test_shadow_current_leg_mismatch),
        ("shadow_missing_config_skips_checks", test_shadow_missing_config_skips_checks),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  ✓ {name}')
            passed += 1
        except Exception as e:
            print(f'  ✗ {name}: {type(e).__name__}: {e}')
            failed += 1
    print(f'\n結果: {passed} passed, {failed} failed')
    sys.exit(0 if failed == 0 else 1)
