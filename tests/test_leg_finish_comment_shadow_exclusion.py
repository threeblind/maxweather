"""
区間走破コメントからの区間記録連合（シャドーチーム）除外のテスト。

修正内容 (scripts/generate_report.py):
- _generate_leg_finish_comment: is_shadow_confederation=True のチームを区間走破コメント対象から除外
  （通常チームIDに依存せずフラグで判定）。
- _comment_contains_shadow_team: 古いコメントの1時間維持（retention）で、
  シャドーチーム名を含む過去の混入コメントを次回更新で保持しないためのガード。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_report

LEG_BOUNDARIES = [100, 210, 310, 399, 522, 639]


def _setup():
    """generate_report のグローバルをテスト用データで差し替える。"""
    generate_report.ekiden_data = {"leg_boundaries": LEG_BOUNDARIES}
    generate_report.all_teams_data = [
        {"id": 17, "name": "鹿児島大学"},
        {"id": 99, "name": "区間記録連合", "is_shadow_confederation": True},
    ]


def _team(team_id, name, total_distance, current_leg, is_shadow=False):
    return {
        "id": team_id, "name": name,
        "totalDistance": total_distance, "currentLeg": current_leg,
        "is_shadow_confederation": is_shadow,
    }


def test_regular_and_shadow_cross_same_boundary_only_regular_appears():
    """通常チーム+シャドーチームが同じ区間境界を跨いだ場合、通常チーム名だけになる。"""
    _setup()
    previous_report_data = {
        "teams": [
            _team(17, "鹿児島大学", 521.5, 5),
            _team(99, "区間記録連合", 517.2, 5, is_shadow=True),
        ]
    }
    current_results = [
        _team(17, "鹿児島大学", 522.4, 6),
        _team(99, "区間記録連合", 522.0, 6, is_shadow=True),
    ]
    comment = generate_report._generate_leg_finish_comment(current_results, previous_report_data)
    assert comment == "【区間走破】鹿児島大学が5区を走りきりました！"
    assert "区間記録連合" not in comment


def test_shadow_only_crossing_produces_no_comment():
    """シャドーチームのみが境界を跨いだ場合はコメントを生成しない。"""
    _setup()
    previous_report_data = {
        "teams": [
            _team(17, "鹿児島大学", 510.0, 5),
            _team(99, "区間記録連合", 517.2, 5, is_shadow=True),
        ]
    }
    current_results = [
        _team(17, "鹿児島大学", 515.0, 5),
        _team(99, "区間記録連合", 522.0, 6, is_shadow=True),
    ]
    comment = generate_report._generate_leg_finish_comment(current_results, previous_report_data)
    assert comment is None


def test_regular_only_crossing_still_generates_comment():
    """通常チームのみが境界を跨ぐ従来動作は維持される。"""
    _setup()
    previous_report_data = {
        "teams": [
            _team(17, "鹿児島大学", 521.5, 5),
            _team(99, "区間記録連合", 517.2, 5, is_shadow=True),
        ]
    }
    current_results = [
        _team(17, "鹿児島大学", 522.4, 6),
        _team(99, "区間記録連合", 519.0, 5, is_shadow=True),
    ]
    comment = generate_report._generate_leg_finish_comment(current_results, previous_report_data)
    assert comment == "【区間走破】鹿児島大学が5区を走りきりました！"


def test_comment_contains_shadow_team_detects_shadow_name():
    """retentionガード: シャドーチーム名を含む古いコメントを検出する。"""
    _setup()
    assert generate_report._comment_contains_shadow_team(
        "【区間走破】鹿児島大学、区間記録連合が5区を走りきりました！"
    ) is True


def test_comment_contains_shadow_team_ignores_normal_comments():
    """retentionガード: 通常コメント・空文字は検出しない。"""
    _setup()
    assert generate_report._comment_contains_shadow_team(
        "【首位交代】鹿児島大学がトップに浮上！レースが大きく動きました！"
    ) is False
    assert generate_report._comment_contains_shadow_team("") is False
    assert generate_report._comment_contains_shadow_team(None) is False
