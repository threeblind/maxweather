import argparse
import tempfile
from pathlib import Path

import generate_daily_summary as summary


def main():
    parser = argparse.ArgumentParser(description="過去の速報から日次サマリーを安全に再生成します。")
    parser.add_argument(
        "snapshot",
        type=Path,
        help="realtime_report.json、または日次スナップショットのディレクトリ",
    )
    parser.add_argument("--output", type=Path, default=Path("data/daily_summary.json"))
    args = parser.parse_args()

    snapshot_dir = args.snapshot if args.snapshot.is_dir() else args.snapshot.parent
    realtime_report = (
        args.snapshot / "realtime_report.json"
        if args.snapshot.is_dir()
        else args.snapshot
    )
    if not realtime_report.exists():
        raise SystemExit(f"エラー: 速報ファイルがありません: {realtime_report}")

    with tempfile.TemporaryDirectory(prefix="weather-historical-summary-") as temp_dir:
        temp_path = Path(temp_dir)
        summary.REALTIME_REPORT_FILE = realtime_report
        summary.OUTPUT_FILE = args.output
        summary.ARTICLE_HISTORY_FILE = temp_path / "article_history.json"
        summary.NARRATIVE_STATE_FILE = temp_path / "race_narrative_state.json"
        for constant_name, filename in {
            "MANAGER_COMMENTS_FILE": "manager_comments.json",
            "RANK_HISTORY_FILE": "rank_history.json",
            "INDIVIDUAL_RESULTS_FILE": "individual_results.json",
        }.items():
            snapshot_file = snapshot_dir / filename
            if snapshot_file.exists():
                setattr(summary, constant_name, snapshot_file)

        generator = summary.DailySummaryGenerator()

        original_validate = generator.validate_generated_article

        def validate_with_snapshot_runners(article_text, metrics):
            ekiden_data = generator.all_data.get("ekiden_data", {})
            realtime_teams = {
                team.get("id"): team
                for team in generator.all_data.get("realtime_report", {}).get("teams", [])
            }
            for team in ekiden_data.get("teams", []):
                team["runners"] = [
                    {"name": runner} if isinstance(runner, str) else runner
                    for runner in team.get("runners", [])
                ]
                current_runner = realtime_teams.get(team.get("id"), {}).get("runner")
                if current_runner:
                    team["runners"].append({"name": current_runner})
            return original_validate(article_text, metrics)

        generator.validate_generated_article = validate_with_snapshot_runners
        generator.run()


if __name__ == "__main__":
    main()
