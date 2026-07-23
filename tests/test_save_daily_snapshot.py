import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from save_daily_snapshot import save_daily_snapshot


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class SaveDailySnapshotTests(unittest.TestCase):
    def test_uses_realtime_report_date_and_copies_available_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "data"
            output = root / "daily_snapshots"
            realtime = {
                "updateTime": "2026/07/23 23:55",
                "raceDay": 1,
                "teams": [{"id": 1, "name": "名古屋大学"}],
            }
            write_json(source / "realtime_report.json", realtime)
            write_json(source / "rank_history.json", {"dates": ["2026-07-23"]})

            destination, manifest = save_daily_snapshot(source, output)

            self.assertEqual(destination, output / "2026-07-23")
            self.assertEqual(
                json.loads((destination / "realtime_report.json").read_text()),
                realtime,
            )
            self.assertTrue((destination / "rank_history.json").exists())
            self.assertEqual(manifest["snapshotDate"], "2026-07-23")
            self.assertEqual(manifest["sourceUpdateTime"], "2026/07/23 23:55")
            self.assertEqual(manifest["raceDay"], 1)
            expected_hash = hashlib.sha256(
                (destination / "realtime_report.json").read_bytes()
            ).hexdigest()
            self.assertEqual(
                manifest["files"]["realtime_report.json"]["sha256"], expected_hash
            )

    def test_date_override_controls_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "data"
            output = root / "daily_snapshots"
            write_json(
                source / "realtime_report.json",
                {"updateTime": "2026/07/24 00:05", "raceDay": 1, "teams": []},
            )

            destination, manifest = save_daily_snapshot(
                source, output, date_override=date(2026, 7, 23)
            )

            self.assertEqual(destination, output / "2026-07-23")
            self.assertEqual(manifest["snapshotDate"], "2026-07-23")
            self.assertEqual(manifest["sourceUpdateTime"], "2026/07/24 00:05")


if __name__ == "__main__":
    unittest.main()
