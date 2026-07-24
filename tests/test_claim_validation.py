"""
scripts/generate_daily_summary.py validate_claims のテスト。
API 呼び出しなし、fixture/mock のみ。
"""
import sys, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_daily_summary import DailySummaryGenerator

SAMPLE_TEAMS = [
    {"id": 1, "name": "名古屋大学", "overallRank": 2, "previousRank": 3,
     "runner": "美濃", "todayDistance": 40.8, "totalDistance": 73.1},
    {"id": 2, "name": "山梨学院大学", "overallRank": 1, "previousRank": 1,
     "runner": "1佐久間", "todayDistance": 33.2, "totalDistance": 74.3},
    {"id": 3, "name": "関西大学", "overallRank": 5, "previousRank": 5,
     "runner": "福崎", "todayDistance": 38.5, "totalDistance": 65.2},
]
SAMPLE_RANK_HISTORY = {"teams": [
    {"name": "名古屋大学", "ranks": [3, 2]},
    {"name": "山梨学院大学", "ranks": [1, 1]},
]}

ALL_DATA = {
    "realtime_report": {
        "raceDay": 2,
        "teams": SAMPLE_TEAMS,
    },
    "rank_history": SAMPLE_RANK_HISTORY,
}

gen = DailySummaryGenerator.__new__(DailySummaryGenerator)


def v(claims):
    """validate_claims のラッパー"""
    return gen.validate_claims(claims, ALL_DATA)


# --- テスト1: 正しいrank_change up ---
def test_rank_change_up():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "rank_change",
         "evidence": "3位から2位に浮上",
         "previous_rank": 3, "current_rank": 2, "direction": "up"}
    ])
    assert len(result) == 1


# --- テスト2: 正しいrank_change same ---
def test_rank_change_same():
    result = v([
        {"team_id": "山梨学院大学", "claim_type": "rank_change",
         "evidence": "1位を維持",
         "previous_rank": 1, "current_rank": 1, "direction": "same"}
    ])
    assert len(result) == 1


# --- テスト3: direction不一致拒否 ---
def test_rank_change_direction_mismatch():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "rank_change",
             "evidence": "test", "previous_rank": 3, "current_rank": 2,
             "direction": "down"}
        ])
    except ValueError:
        raised = True
    assert raised, "upなのにdown→ValueError"


# --- テスト4: current_rank不一致拒否 ---
def test_rank_change_current_mismatch():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "rank_change",
             "evidence": "test", "previous_rank": 3, "current_rank": 5,
             "direction": "up"}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト5: unknown team_id拒否 ---
def test_unknown_team_id():
    raised = False
    try:
        v([
            {"team_id": "存在しない大学", "claim_type": "rank_change",
             "evidence": "test", "previous_rank": 1, "current_rank": 1,
             "direction": "same"}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト6: unknown claim_type拒否 ---
def test_unknown_claim_type():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "invalid_type",
             "evidence": "test"}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト7: distance todayDistance 正しい ---
def test_distance_today_ok():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "distance",
         "evidence": "40.8km走行",
         "distance_kind": "todayDistance", "value": 40.8}
    ])
    assert len(result) == 1


# --- テスト8: distance totalDistance 正しい ---
def test_distance_total_ok():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "distance",
         "evidence": "73.1km総合",
         "distance_kind": "totalDistance", "value": 73.1}
    ])
    assert len(result) == 1


# --- テスト9: distance 値の許容範囲外拒否 ---
def test_distance_out_of_tolerance():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "distance",
             "evidence": "間違った値",
             "distance_kind": "todayDistance", "value": 50.0}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト10: runner 一致 ---
def test_runner_match():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "runner",
         "evidence": "美濃選手が走行",
         "runner": "美濃"}
    ])
    assert len(result) == 1


# --- テスト11: runner 一致（先頭数字対応）---
def test_runner_match_with_number():
    result = v([
        {"team_id": "山梨学院大学", "claim_type": "runner",
         "evidence": "佐久間選手",
         "runner": "1佐久間"}
    ])
    assert len(result) == 1


# --- テスト12: runner 不一致拒否 ---
def test_runner_mismatch():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "runner",
             "evidence": "違う選手",
             "runner": "佐久間"}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト13: battle opponent 存在 ---
def test_battle_opponent_ok():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "battle",
         "evidence": "山梨学院との争い",
         "opponent_team_id": "山梨学院大学"}
    ])
    assert len(result) == 1


# --- テスト14: battle 自分自身拒否 ---
def test_battle_self_opponent():
    raised = False
    try:
        v([
            {"team_id": "名古屋大学", "claim_type": "battle",
             "evidence": "自分との戦い",
             "opponent_team_id": "名古屋大学"}
        ])
    except ValueError:
        raised = True
    assert raised


# --- テスト15: claims 空配列成功 ---
def test_empty_claims_ok():
    result = v([])
    assert result == []


# --- テスト16: claim 非dict拒否 ---
def test_claim_non_dict():
    raised = False
    try:
        v(["not_a_dict"])
    except ValueError:
        raised = True
    assert raised


# --- テスト17: team_id 欠落拒否 ---
def test_team_id_missing():
    raised = False
    try:
        v([{"claim_type": "runner", "evidence": "test", "runner": "美濃"}])
    except ValueError:
        raised = True
    assert raised


# --- テスト18: 必須項目 evidence 欠落拒否 ---
def test_evidence_missing():
    raised = False
    try:
        v([{"team_id": "名古屋大学", "claim_type": "runner", "runner": "美濃"}])
    except ValueError:
        raised = True
    assert raised


# --- テスト19: claims検証失敗時にval戻り値が返らない ---
def test_validation_failure_stops(monkeypatch):
    """validate_claims が ValueError を投げることを確認"""
    bad_claims = [{"team_id": "名古屋大学", "claim_type": "unknown_type", "evidence": "test"}]
    raised = False
    try:
        gen.validate_claims(bad_claims, ALL_DATA)
    except ValueError:
        raised = True
    assert raised


# --- テスト20: gap_km 照合 ---
def test_battle_gap_km():
    result = v([
        {"team_id": "名古屋大学", "claim_type": "battle",
         "evidence": "山梨学院と接戦",
         "opponent_team_id": "山梨学院大学",
         "gap_km": 1.2}  # |73.1 - 74.3| = 1.2
    ])
    assert len(result) == 1


if __name__ == "__main__":
    tests = [
        ("rank_change_up", test_rank_change_up),
        ("rank_change_same", test_rank_change_same),
        ("direction_mismatch", test_rank_change_direction_mismatch),
        ("current_mismatch", test_rank_change_current_mismatch),
        ("unknown_team_id", test_unknown_team_id),
        ("unknown_claim_type", test_unknown_claim_type),
        ("distance_today_ok", test_distance_today_ok),
        ("distance_total_ok", test_distance_total_ok),
        ("distance_out_of_tolerance", test_distance_out_of_tolerance),
        ("runner_match", test_runner_match),
        ("runner_match_with_number", test_runner_match_with_number),
        ("runner_mismatch", test_runner_mismatch),
        ("battle_opponent_ok", test_battle_opponent_ok),
        ("battle_self_opponent", test_battle_self_opponent),
        ("empty_claims_ok", test_empty_claims_ok),
        ("claim_non_dict", test_claim_non_dict),
        ("team_id_missing", test_team_id_missing),
        ("evidence_missing", test_evidence_missing),
        ("validation_failure_stops", test_validation_failure_stops),
        ("battle_gap_km", test_battle_gap_km),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
