"""
沿道レポート自動生成の統合テスト（commit_daily.sh + save_daily_snapshot.py 連係）。
"""
import sys
import json
import os
import subprocess
import tempfile
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def test_save_daily_snapshot_print_path():
    """save_daily_snapshot.py --print-path がディレクトリパスのみを出力"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        source_dir = tmpdir / 'data'
        source_dir.mkdir()
        # Create minimal realtime_report.json
        rt = {"updateTime": "2026/07/27 23:55:00", "raceDay": 4}
        with open(source_dir / 'realtime_report.json', 'w') as f:
            json.dump(rt, f)

        result = subprocess.run(
            [sys.executable, 'scripts/save_daily_snapshot.py',
             '--source-dir', str(source_dir),
             '--output-dir', str(tmpdir / 'snapshots'),
             '--print-path'],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
        )
        assert result.returncode == 0, f'stderr: {result.stderr}'
        path = result.stdout.strip()
        assert path, '出力が空'
        assert 'snapshots' in path and '2026-07-27' in path


def test_add_to_manifest():
    """save_daily_snapshot.py --add-to-manifest が manifest を更新"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        snap_dir = tmpdir / '2026-07-27'
        snap_dir.mkdir(parents=True)
        # Create manifest
        manifest = {"schemaVersion": 1, "snapshotDate": "2026-07-27",
                     "files": {"existing.txt": {"bytes": 10, "sha256": "x"}}}
        with open(snap_dir / 'manifest.json', 'w') as f:
            json.dump(manifest, f)
        # Create file to add
        with open(snap_dir / 'alongroad_report.txt', 'w') as f:
            f.write('test content')

        result = subprocess.run(
            [sys.executable, 'scripts/save_daily_snapshot.py',
             '--add-to-manifest', 'alongroad_report.txt',
             '--manifest-dir', str(snap_dir)],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
        )
        assert result.returncode == 0, f'stderr: {result.stderr}'

        with open(snap_dir / 'manifest.json') as f:
            updated = json.load(f)
        assert 'alongroad_report.txt' in updated['files']
        assert updated['files']['alongroad_report.txt']['bytes'] > 0


def test_commit_sh_calls_alongroad():
    """commit_daily.sh に沿道レポート生成の呼び出しが含まれている"""
    sh = PROJECT_ROOT / 'commit_daily.sh'
    text = sh.read_text(encoding='utf-8')
    assert 'generate_alongroad_report' in text, 'commit_daily.sh に沿道生成が含まれていません'
    assert '--save' in text, '--save フラグがありません'
    assert 'SNAPSHOT_DATE' in text, '日付解決がありません'


def test_add_to_manifest_no_dir():
    """--add-to-manifest に --manifest-dir がない場合はエラー"""
    result = subprocess.run(
        [sys.executable, 'scripts/save_daily_snapshot.py',
         '--add-to-manifest', 'alongroad_report.txt'],
        capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
    )
    assert result.returncode != 0


def test_save_daily_snapshot_still_works():
    """--print-path なしの通常動作は従来通り"""
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        source_dir = tmpdir / 'data'
        source_dir.mkdir()
        rt = {"updateTime": "2026/07/27 23:55:00", "raceDay": 4}
        with open(source_dir / 'realtime_report.json', 'w') as f:
            json.dump(rt, f)

        result = subprocess.run(
            [sys.executable, 'scripts/save_daily_snapshot.py',
             '--source-dir', str(source_dir),
             '--output-dir', str(tmpdir / 'snapshots')],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10
        )
        assert result.returncode == 0
        assert 'スナップショット' in result.stdout


# ============================================================

if __name__ == '__main__':
    tests = [
        ("print_path", test_save_daily_snapshot_print_path),
        ("add_to_manifest", test_add_to_manifest),
        ("commit_sh_calls_alongroad", test_commit_sh_calls_alongroad),
        ("add_to_manifest_no_dir", test_add_to_manifest_no_dir),
        ("normal_mode_still_works", test_save_daily_snapshot_still_works),
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
