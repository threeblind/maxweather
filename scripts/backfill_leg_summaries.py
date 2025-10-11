#!/usr/bin/env python3
"""
既存の individual_results.json を新スキーマに補完するスクリプト。
区間ごとのサマリー情報や暫定/確定順位を leg_rank_history.json などから復元する。
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, List

DATA_DIR = Path("data")
CONFIG_DIR = Path("config")

INDIVIDUAL_RESULTS_FILE = DATA_DIR / "individual_results.json"
LEG_RANK_HISTORY_FILE = DATA_DIR / "leg_rank_history.json"
REALTIME_REPORT_FILE = DATA_DIR / "realtime_report.json"
EKIDEN_DATA_FILE = CONFIG_DIR / "ekiden_data.json"

BACKUP_FILE_SUFFIX = ".backup"


def load_json(path: Path, default=None):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def ensure_backup(file_path: Path) -> Path:
    backup_path = file_path.with_suffix(file_path.suffix + BACKUP_FILE_SUFFIX)
    if backup_path.exists():
        return backup_path
    try:
        data = file_path.read_bytes()
    except FileNotFoundError:
        return backup_path
    backup_path.write_bytes(data)
    return backup_path


def build_team_lookup(ekiden_data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    lookup = {}
    if not ekiden_data:
        return lookup
    for team in ekiden_data.get("teams", []):
        lookup[team.get("id")] = team
    return lookup


def build_leg_rank_lookup(leg_rank_history: Dict[str, Any]) -> Dict[int, List[int]]:
    lookup = {}
    if not leg_rank_history:
        return lookup
    for team_entry in leg_rank_history.get("teams", []):
        team_id = team_entry.get("id")
        if team_id is None:
            continue
        lookup[team_id] = team_entry.get("leg_ranks", [])
    return lookup


def determine_leg_status(team_id: int, leg_number: int, leg_rank_lookup: Dict[int, List[int]]) -> bool:
    ranks = leg_rank_lookup.get(team_id) or []
    index = leg_number - 1
    if 0 <= index < len(ranks):
        return ranks[index] is not None
    return False


def calculate_leg_summaries(individual_results: Dict[str, Any], leg_rank_lookup: Dict[int, List[int]]) -> None:
    leg_performance_map = defaultdict(list)

    for runner_name, runner_data in individual_results.items():
        if not isinstance(runner_data, dict):
            continue
        team_id = runner_data.get("teamId")
        records = runner_data.get("records", []) or []
        leg_summaries = runner_data.setdefault("legSummaries", {})

        summary_by_leg = {}
        for record in sorted(records, key=lambda r: r.get("day", 0)):
            leg_number = record.get("leg")
            distance = record.get("distance")
            day = record.get("day")
            if leg_number is None or distance is None or day is None:
                continue

            leg_key = str(leg_number)
            summary = summary_by_leg.setdefault(leg_key, {
                "totalDistance": 0.0,
                "days": 0,
                "averageDistance": 0.0,
                "rank": None,
                "status": "provisional",
                "finalRank": None,
                "finalDay": None,
                "lastUpdatedDay": None
            })

            summary["totalDistance"] = round(summary["totalDistance"] + distance, 1)
            summary["days"] += 1
            summary["averageDistance"] = round(summary["totalDistance"] / summary["days"], 3) if summary["days"] else 0.0
            summary["lastUpdatedDay"] = day

            leg_summaries[leg_key] = summary

        for leg_key, summary in summary_by_leg.items():
            leg_number = int(leg_key)
            is_final = determine_leg_status(team_id, leg_number, leg_rank_lookup)
            summary["status"] = "final" if is_final else "provisional"
            if is_final:
                summary["finalDay"] = summary["lastUpdatedDay"]
            leg_performance_map[leg_number].append((runner_name, summary, team_id))

    for leg_number, performances in leg_performance_map.items():
        performances = [p for p in performances if isinstance(p[1].get("averageDistance"), (int, float))]
        performances.sort(key=lambda item: item[1]["averageDistance"], reverse=True)
        last_avg = None
        current_rank = 0
        for index, (runner_name, summary, team_id) in enumerate(performances):
            avg = summary.get("averageDistance", 0.0)
            rounded_avg = round(avg, 3)
            if last_avg is None or rounded_avg != last_avg:
                current_rank = index + 1
                last_avg = rounded_avg
            summary["rank"] = current_rank
            if summary.get("status") == "final":
                summary["finalRank"] = current_rank


def backfill_record_metadata(individual_results: Dict[str, Any]) -> None:
    for runner_name, runner_data in individual_results.items():
        if not isinstance(runner_data, dict):
            continue
        records = runner_data.get("records", []) or []
        leg_summaries = runner_data.get("legSummaries", {}) or {}

        cumulative_totals = {}
        cumulative_days = {}

        for record in sorted(records, key=lambda r: r.get("day", 0)):
            leg_number = record.get("leg")
            distance = record.get("distance")
            if leg_number is None or distance is None:
                continue

            leg_key = str(leg_number)
            cumulative_totals[leg_key] = cumulative_totals.get(leg_key, 0.0) + distance
            cumulative_days[leg_key] = cumulative_days.get(leg_key, 0) + 1

            avg = cumulative_totals[leg_key] / cumulative_days[leg_key]
            record["legAverageDistance"] = round(avg, 3)

            summary = leg_summaries.get(leg_key)
            if summary:
                record["legRank"] = summary.get("rank")
                final_day = summary.get("finalDay")
                if summary.get("status") == "final" and final_day == record.get("day"):
                    record["legAverageStatus"] = "final"
                    record["legRankStatus"] = "final"
                else:
                    record["legAverageStatus"] = "provisional"
                    record["legRankStatus"] = "provisional"
            else:
                record.setdefault("legRank", None)
                record.setdefault("legRankStatus", "provisional")
                record.setdefault("legAverageStatus", "provisional")


def main():
    parser = argparse.ArgumentParser(description="individual_results.json を新スキーマへ補完します。")
    parser.add_argument("--dry-run", action="store_true", help="補完結果をファイルに書き込まず標準出力に表示")
    parser.add_argument("--output", type=Path, default=INDIVIDUAL_RESULTS_FILE, help="出力先ファイル (デフォルト: individual_results.json を上書き)")
    args = parser.parse_args()

    individual_results = load_json(INDIVIDUAL_RESULTS_FILE, {})
    leg_rank_history = load_json(LEG_RANK_HISTORY_FILE, {})
    ekiden_data = load_json(EKIDEN_DATA_FILE, {})

    if not individual_results:
        print("individual_results.json が見つからないか空です。補完処理を中断します。")
        return

    leg_rank_lookup = build_leg_rank_lookup(leg_rank_history)
    build_team_lookup(ekiden_data)

    calculate_leg_summaries(individual_results, leg_rank_lookup)
    backfill_record_metadata(individual_results)

    if args.dry_run:
        print(json.dumps(individual_results, ensure_ascii=False, indent=2))
        return

    ensure_backup(args.output)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(individual_results, f, ensure_ascii=False, indent=2)
    print(f"補完したデータを {args.output} に保存しました。バックアップ: {args.output}{BACKUP_FILE_SUFFIX}")


if __name__ == "__main__":
    main()
