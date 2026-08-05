import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_daily_summary import DailySummaryGenerator


def _generator(teams, rank_history=None):
    generator = DailySummaryGenerator.__new__(DailySummaryGenerator)
    generator.all_data = {
        "realtime_report": {"raceDay": 15, "teams": teams},
        "rank_history": {"teams": rank_history or []},
    }
    return generator


def test_lower_zone_keeps_only_notable_lower_teams():
    teams = [
        {"name": "首位", "overallRank": 1, "previousRank": 1, "todayDistance": 35.0, "totalDistance": 500.0},
        {"name": "10位", "overallRank": 10, "previousRank": 10, "todayDistance": 31.0, "totalDistance": 480.0},
        {"name": "金沢大学", "overallRank": 13, "previousRank": 13, "todayDistance": 30.9, "totalDistance": 450.0},
        {"name": "上武大学", "overallRank": 14, "previousRank": 14, "todayDistance": 28.7, "totalDistance": 448.0},
        {"name": "琉球大学", "overallRank": 15, "previousRank": 16, "todayDistance": 30.5, "totalDistance": 447.0},
        {"name": "日本大学", "overallRank": 16, "previousRank": 15, "todayDistance": 27.7, "totalDistance": 445.0},
        {"name": "福島大学", "overallRank": 17, "previousRank": 17, "todayDistance": 29.1, "totalDistance": 430.0},
        {"name": "東北大学", "overallRank": 18, "previousRank": 18, "todayDistance": 27.4, "totalDistance": 410.0},
    ]

    zones = _generator(teams).select_today_themes({"race_day": 15})
    lower = next(zone for zone in zones if zone["zone"] == "シード圏外状況")

    assert set(lower["teams"]) == {"金沢大学", "琉球大学"}
    assert "上武大学" not in lower["teams"]


def test_lower_zone_is_omitted_without_a_notable_event():
    teams = [
        {"name": "首位", "overallRank": 1, "previousRank": 1, "todayDistance": 35.0, "totalDistance": 500.0},
        {"name": "10位", "overallRank": 10, "previousRank": 10, "todayDistance": 31.0, "totalDistance": 480.0},
        {"name": "下位A", "overallRank": 13, "previousRank": 13, "todayDistance": 28.0, "totalDistance": 450.0},
        {"name": "下位B", "overallRank": 14, "previousRank": 14, "todayDistance": 28.0, "totalDistance": 448.0},
        {"name": "下位C", "overallRank": 15, "previousRank": 15, "todayDistance": 28.0, "totalDistance": 447.0},
    ]

    zones = _generator(teams).select_today_themes({"race_day": 15})

    assert not any(zone["zone"] == "シード圏外状況" for zone in zones)
