"""
個人プロフィールの日別順位 (dailyRank) テスト。

データ生成側の dailyRank 計算ロジックを検証。
実スクリプトを実行せず、ロジックをインライン再現してテスト。
"""
import sys
import json
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ============================================================
# テスト対象ロジック: competition ranking
# ============================================================

def compute_daily_rank(entries, distance_key='distance'):
    """
    generate_report.py / rebuild_history.py の dailyRank 計算ロジックを再現。
    entries: [{'record': {distance_key: float, ...}}, ...]
    各 record に dailyRank を追加する（副作用）。
    """
    entries.sort(key=lambda e: e['record'].get(distance_key, 0) or 0, reverse=True)
    last_dist, current_rank = None, 0
    for i, entry in enumerate(entries):
        record = entry['record']
        dist = record.get(distance_key, 0) or 0
        if dist != last_dist:
            current_rank = i + 1
            last_dist = dist
        record['dailyRank'] = current_rank
    return entries


def compute_daily_rank_from_records(records):
    """
    generate_player_profiles.py の dailyRank 計算ロジックを再現。
    records: [{'day': int, 'leg': int, 'distance': float, ...}, ...]
    距離リストから competition ranking を計算。
    """
    # 同一 (leg, day) グループで距離を収集
    from collections import defaultdict
    groups = defaultdict(list)
    for r in records:
        leg = r.get('leg')
        day = r.get('day')
        dist = r.get('distance')
        if leg is not None and day is not None and dist is not None:
            groups[(leg, day)].append(dist)

    # 各グループ降順ソート
    for key in groups:
        groups[key].sort(reverse=True)

    # 各レコードに dailyRank を設定
    result = []
    for r in records:
        leg = r.get('leg')
        day = r.get('day')
        dist = r.get('distance')
        if leg is not None and day is not None and dist is not None:
            day_dists = groups.get((leg, day), [])
            try:
                r['dailyRank'] = day_dists.index(dist) + 1
            except ValueError:
                r['dailyRank'] = None
        result.append(r)
    return result


# ============================================================
# テスト
# ============================================================

def test_daily_rank_basic():
    """基本的な順位付け"""
    entries = [
        {'record': {'distance': 40.0}},
        {'record': {'distance': 38.0}},
        {'record': {'distance': 35.0}},
    ]
    compute_daily_rank(entries)
    assert entries[0]['record']['dailyRank'] == 1
    assert entries[1]['record']['dailyRank'] == 2
    assert entries[2]['record']['dailyRank'] == 3


def test_daily_rank_tie():
    """同距離は同順位 (competition ranking: 1, 1, 3)"""
    entries = [
        {'record': {'distance': 40.0}},
        {'record': {'distance': 40.0}},
        {'record': {'distance': 35.0}},
    ]
    compute_daily_rank(entries)
    # 同距離は同順位
    assert entries[0]['record']['dailyRank'] == 1
    assert entries[1]['record']['dailyRank'] == 1
    assert entries[2]['record']['dailyRank'] == 3


def test_daily_rank_three_way_tie():
    """3者同点の場合は全員1位"""
    entries = [
        {'record': {'distance': 38.0}},
        {'record': {'distance': 38.0}},
        {'record': {'distance': 38.0}},
    ]
    compute_daily_rank(entries)
    assert entries[0]['record']['dailyRank'] == 1
    assert entries[1]['record']['dailyRank'] == 1
    assert entries[2]['record']['dailyRank'] == 1


def test_daily_rank_multi_tie():
    """複数段階の同順位: 40(1位), 38(2位), 38(2位), 35(4位)"""
    entries = [
        {'record': {'distance': 40.0}},
        {'record': {'distance': 38.0}},
        {'record': {'distance': 38.0}},
        {'record': {'distance': 35.0}},
    ]
    compute_daily_rank(entries)
    assert entries[0]['record']['dailyRank'] == 1  # 40.0
    assert entries[1]['record']['dailyRank'] == 2  # 38.0
    assert entries[2]['record']['dailyRank'] == 2  # 38.0
    assert entries[3]['record']['dailyRank'] == 4  # 35.0


def test_daily_rank_different_legs():
    """異なる区間は比較しない（generate_report.py版）"""
    entries = [
        {'record': {'distance': 40.0, 'leg': 1}},
        {'record': {'distance': 38.0, 'leg': 2}},
    ]
    # generate_report.py では leg ごとに別々の entries リストなので問題なし
    # ここでは同一リスト内でも単純降順ソートして順位付けするだけ
    compute_daily_rank(entries)
    assert entries[0]['record']['dailyRank'] == 1  # 40.0
    assert entries[1]['record']['dailyRank'] == 2  # 38.0


def test_daily_rank_null_distance():
    """距離がNone/nullの場合は0扱いで最下位"""
    entries = [
        {'record': {'distance': 40.0}},
        {'record': {'distance': None}},
        {'record': {'distance': 35.0}},
    ]
    compute_daily_rank(entries)
    assert entries[0]['record']['dailyRank'] == 1  # 40.0
    assert entries[1]['record']['dailyRank'] == 2  # 35.0
    assert entries[2]['record']['dailyRank'] == 3  # None→0


# ============================================================
# generate_player_profiles.py 版テスト（records ベース）
# ============================================================

def test_daily_rank_from_records_different_legs():
    """異なる区間は比較しない（player_profiles版）"""
    records = [
        {'leg': 1, 'day': 1, 'distance': 40.0, 'runner': 'A'},
        {'leg': 2, 'day': 1, 'distance': 38.0, 'runner': 'B'},
        {'leg': 1, 'day': 1, 'distance': 35.0, 'runner': 'C'},
        {'leg': 2, 'day': 1, 'distance': 30.0, 'runner': 'D'},
    ]
    result = compute_daily_rank_from_records(records)
    # Leg1: A(40)=1位, C(35)=2位
    # Leg2: B(38)=1位, D(30)=2位
    for r in result:
        if r['runner'] == 'A':
            assert r['dailyRank'] == 1
        elif r['runner'] == 'C':
            assert r['dailyRank'] == 2
        elif r['runner'] == 'B':
            assert r['dailyRank'] == 1
        elif r['runner'] == 'D':
            assert r['dailyRank'] == 2


def test_daily_rank_from_records_different_days():
    """異なる日は比較しない"""
    records = [
        {'leg': 1, 'day': 1, 'distance': 40.0, 'runner': 'A'},
        {'leg': 1, 'day': 2, 'distance': 38.0, 'runner': 'A'},
        {'leg': 1, 'day': 1, 'distance': 35.0, 'runner': 'B'},
        {'leg': 1, 'day': 2, 'distance': 30.0, 'runner': 'B'},
    ]
    result = compute_daily_rank_from_records(records)
    # Day1: A(40)=1, B(35)=2
    # Day2: A(38)=1, B(30)=2
    for r in result:
        if r['day'] == 1 and r['runner'] == 'A':
            assert r['dailyRank'] == 1
        elif r['day'] == 1 and r['runner'] == 'B':
            assert r['dailyRank'] == 2
        elif r['day'] == 2 and r['runner'] == 'A':
            assert r['dailyRank'] == 1
        elif r['day'] == 2 and r['runner'] == 'B':
            assert r['dailyRank'] == 2


def test_daily_rank_from_records_tie():
    """同距離は同順位（records版）"""
    records = [
        {'leg': 1, 'day': 1, 'distance': 40.0, 'runner': 'A'},
        {'leg': 1, 'day': 1, 'distance': 40.0, 'runner': 'B'},
        {'leg': 1, 'day': 1, 'distance': 35.0, 'runner': 'C'},
    ]
    result = compute_daily_rank_from_records(records)
    for r in result:
        if r['runner'] in ('A', 'B'):
            assert r['dailyRank'] == 1
        elif r['runner'] == 'C':
            assert r['dailyRank'] == 3


def test_daily_rank_from_records_no_distance():
    """distance None は除外（records版ではgroupsに入らない→dailyRank=None）"""
    records = [
        {'leg': 1, 'day': 1, 'distance': 40.0, 'runner': 'A'},
        {'leg': 1, 'day': 1, 'distance': None, 'runner': 'B'},
    ]
    result = compute_daily_rank_from_records(records)
    for r in result:
        if r['runner'] == 'A':
            assert r['dailyRank'] == 1
        elif r['runner'] == 'B':
            assert r.get('dailyRank') is None  # 除外（キー未設定）


def test_daily_rank_from_records_no_leg():
    """leg なしも除外"""
    records = [
        {'day': 1, 'distance': 40.0, 'runner': 'A'},
    ]
    result = compute_daily_rank_from_records(records)
    assert result[0].get('dailyRank') is None


# ============================================================
# 後方互換性テスト
# ============================================================

def test_backward_compat_no_daily_rank():
    """dailyRank がなくてもエラーにならない"""
    entries = [
        {'record': {'distance': 40.0, 'legRank': 2}},
    ]
    # dailyRank なしでフォーマット
    record = entries[0]['record']
    rank_str = record.get('dailyRank', None) or record.get('legRank', None)
    assert rank_str == 2  # legRank がフォールバックとして使われる


def test_daily_rank_preferred_over_leg_rank():
    """dailyRank が存在する場合はそちらを優先"""
    entries = [
        {'record': {'distance': 40.0, 'legRank': 5, 'dailyRank': 1}},
    ]
    record = entries[0]['record']
    rank_str = record.get('dailyRank', None) or record.get('legRank', None)
    assert rank_str == 1  # dailyRank を優先


# ============================================================
# テストランナー
# ============================================================

if __name__ == '__main__':
    tests = [
        ("daily_rank_basic", test_daily_rank_basic),
        ("daily_rank_tie", test_daily_rank_tie),
        ("daily_rank_three_way_tie", test_daily_rank_three_way_tie),
        ("daily_rank_multi_tie", test_daily_rank_multi_tie),
        ("daily_rank_different_legs", test_daily_rank_different_legs),
        ("daily_rank_null_distance", test_daily_rank_null_distance),
        ("daily_rank_from_records_different_legs", test_daily_rank_from_records_different_legs),
        ("daily_rank_from_records_different_days", test_daily_rank_from_records_different_days),
        ("daily_rank_from_records_tie", test_daily_rank_from_records_tie),
        ("daily_rank_from_records_no_distance", test_daily_rank_from_records_no_distance),
        ("daily_rank_from_records_no_leg", test_daily_rank_from_records_no_leg),
        ("backward_compat_no_daily_rank", test_backward_compat_no_daily_rank),
        ("daily_rank_preferred_over_leg_rank", test_daily_rank_preferred_over_leg_rank),
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
