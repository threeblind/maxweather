import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_FILES = (
    "realtime_report.json",
    "ekiden_state.json",
    "individual_results.json",
    "rank_history.json",
    "leg_rank_history.json",
    "runner_locations.json",
    "daily_temperatures.json",
    "intramural_rankings.json",
    "manager_comments.json",
    "fetch_status.json",
    "commit_status.json",
)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_realtime_metadata(source_dir):
    realtime_path = source_dir / "realtime_report.json"
    if not realtime_path.exists():
        raise FileNotFoundError(f"必須ファイルがありません: {realtime_path}")

    with realtime_path.open(encoding="utf-8") as source:
        realtime = json.load(source)

    update_time = realtime.get("updateTime")
    if not update_time:
        raise ValueError("realtime_report.json に updateTime がありません。")

    try:
        snapshot_date = datetime.strptime(update_time.split()[0], "%Y/%m/%d").date()
    except ValueError as exc:
        raise ValueError(f"updateTimeの日付形式が不正です: {update_time}") from exc

    return snapshot_date, update_time, realtime.get("raceDay")


def atomic_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        shutil.copy2(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(destination, payload):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(payload, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def save_daily_snapshot(source_dir, output_dir, date_override=None):
    detected_date, source_update_time, race_day = load_realtime_metadata(source_dir)
    snapshot_date = date_override or detected_date
    destination_dir = output_dir / snapshot_date.isoformat()
    captured_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()
    manifest_files = {}

    for filename in DEFAULT_FILES:
        source = source_dir / filename
        if not source.exists():
            print(f"情報: 任意ファイルをスキップします: {source}")
            continue
        destination = destination_dir / filename
        atomic_copy(source, destination)
        manifest_files[filename] = {
            "bytes": destination.stat().st_size,
            "sha256": sha256(destination),
        }

    manifest = {
        "schemaVersion": 1,
        "snapshotDate": snapshot_date.isoformat(),
        "capturedAt": captured_at,
        "timezone": "Asia/Tokyo",
        "sourceUpdateTime": source_update_time,
        "raceDay": race_day,
        "files": manifest_files,
    }
    # commit_status.json がある場合は状態を manifest にも記録する
    commit_status_path = source_dir / "commit_status.json"
    if commit_status_path.exists():
        try:
            with commit_status_path.open(encoding="utf-8") as f:
                commit_status = json.load(f)
            manifest["commitStatus"] = commit_status.get("status")
            manifest["validationSeverity"] = commit_status.get("validationSeverity")
        except (json.JSONDecodeError, OSError):
            print("情報: commit_status.json の読み込みに失敗したため manifest には状態を記録しません")
    atomic_write_json(destination_dir / "manifest.json", manifest)
    return destination_dir, manifest


def main():
    parser = argparse.ArgumentParser(
        description="その日の確定データを日付付きディレクトリへ保存します。"
    )
    parser.add_argument("--source-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--output-dir", type=Path, default=Path("data/daily_snapshots")
    )
    parser.add_argument(
        "--date",
        type=lambda value: datetime.strptime(value, "%Y-%m-%d").date(),
        help="保存日を明示します。省略時は realtime_report.json の updateTime を使います。",
    )
    parser.add_argument(
        "--print-path",
        action="store_true",
        help="保存後にスナップショットディレクトリのパスのみ出力します（機械可読用）。",
    )
    parser.add_argument(
        "--add-to-manifest",
        type=str,
        help="既存の manifest.json にファイルを追加します（--manifest-dirと併用）。",
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        help="--add-to-manifest で更新する manifest.json があるディレクトリ。",
    )
    args = parser.parse_args()

    if args.add_to_manifest:
        if not args.manifest_dir:
            print("エラー: --add-to-manifest には --manifest-dir も指定してください。", file=sys.stderr)
            return 1
        manifest_path = args.manifest_dir / "manifest.json"
        if not manifest_path.exists():
            print(f"エラー: manifest.json が見つかりません: {manifest_path}", file=sys.stderr)
            return 1
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        file_path = args.manifest_dir / args.add_to_manifest
        if not file_path.exists():
            print(f"エラー: 追加するファイルが見つかりません: {file_path}", file=sys.stderr)
            return 1
        manifest.setdefault("files", {})[args.add_to_manifest] = {
            "bytes": file_path.stat().st_size,
            "sha256": sha256(file_path),
        }
        atomic_write_json(manifest_path, manifest)
        print(f"✅ manifest.json に {args.add_to_manifest} を追加しました。")
        return 0

    destination, manifest = save_daily_snapshot(
        args.source_dir, args.output_dir, args.date
    )

    if args.print_path:
        print(destination)
    else:
        print(
            f"✅ 日次確定スナップショットを '{destination}' に保存しました"
            f"（{len(manifest['files'])}ファイル）。"
        )


if __name__ == "__main__":
    sys.exit(main())
