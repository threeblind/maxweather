"""
scripts/validate_race_state.py のテスト。
環境変数でパスを差し替えて検証（モジュール変数は変更しない）。
"""
import sys
import json
import os
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ============================================================
# テスト用ヘルパー
# ============================================================

def _validate_with_data(state_list, ind_results, ekiden_data):
    """環境変数でパスを差し替えて validate() を実行"""
    f_state = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(state_list, f_state, ensure_ascii=False)
    f_state.close()

    f_ind = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(ind_results, f_ind, ensure_ascii=False)
    f_ind.close()

    f_ek = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    json.dump(ekiden_data, f_ek, ensure_ascii=False)
    f_ek.close()

    old_env = {}
    for k in ['VALIDATE_STATE_FILE', 'VALIDATE_INDIVIDUAL_FILE', 'VALIDATE_EKIDEN_FILE']:
        old_env[k] = os.environ.get(k)

    try:
        os.environ['VALIDATE_STATE_FILE'] = f_state.name
        os.environ['VALIDATE_INDIVIDUAL_FILE'] = f_ind.name
        os.environ['VALIDATE_EKIDEN_FILE'] = f_ek.name

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
        # テンポラリファイル後片付け
        for p in [f_state.name, f_ind.name, f_ek.name]:
            try:
                os.unlink(p)
            except OSError:
                pass


# ============================================================
# テスト
# ============================================================

def test_consistent_state():
    """正常一致: state.totalDistance == 個人記録合計"""
    ekiden = {
        "leg_boundaries": [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055],
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [{"id": 1, "currentLeg": 2, "totalDistance": 121.0}]
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
        "leg_boundaries": [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055],
        "teams": [{"id": 7, "name": "琉球大学"}]
    }
    state = [{"id": 7, "currentLeg": 2, "totalDistance": 98.9}]
    ind = {
        "北原": {"teamId": 7, "records": [
            {"day": 1, "leg": 1, "distance": 38.0},
            {"day": 2, "leg": 1, "distance": 35.0},
            {"day": 3, "leg": 1, "distance": 33.0},
            {"day": 4, "leg": 1, "distance": 26.6},
        ]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 1, f'expected=1 got={rc}'


def test_boundary_cross():
    """境界を跨いだ currentLeg の整合性"""
    ekiden = {
        "leg_boundaries": [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055],
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [{"id": 1, "currentLeg": 2, "totalDistance": 150.0}]
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
    state = [{"id": 1, "currentLeg": 2, "totalDistance": 120.0}]
    ind = {
        "美濃": {"teamId": 99, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 1, f'expected=1 got={rc}'


def test_missing_team_id():
    """teamId欠落 → FAIL"""
    ekiden = {
        "leg_boundaries": [100, 210],
        "teams": [{"id": 1, "name": "名古屋大学"}]
    }
    state = [{"id": 1, "currentLeg": 2, "totalDistance": 120.0}]
    ind = {
        "美濃": {"records": [{"day": 1, "leg": 1, "distance": 40.0}]}
    }
    rc = _validate_with_data(state, ind, ekiden)
    assert rc == 1, f'expected=1 got={rc}'


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

if __name__ == '__main__':
    tests = [
        ("consistent_state", test_consistent_state),
        ("stale_state", test_stale_state),
        ("boundary_cross", test_boundary_cross),
        ("unknown_team_id", test_unknown_team_id),
        ("missing_team_id", test_missing_team_id),
        ("invalid_json", test_invalid_json),
        ("commit_sh_has_validation", test_commit_daily_sh_has_validation),
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
