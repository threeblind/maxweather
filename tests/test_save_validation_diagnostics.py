"""
scripts/save_validation_diagnostics.py のテスト。

検証失敗時の診断成果物（状態・個人記録・検証出力）が日付付きディレクトリへ
保存されることを検証する。元データは変更されない。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PROJECT_ROOT / "scripts" / "save_validation_diagnostics.py"


def _run_script(tmpdir, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=str(tmpdir),
    )


def test_saves_diagnostics_with_output():
    """状態・個人記録・検証出力・マニフェストが日付付きディレクトリに保存される"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        data_dir.mkdir()
        (data_dir / "ekiden_state.json").write_text('{"state": true}', encoding='utf-8')
        (data_dir / "individual_results.json").write_text('{"runners": []}', encoding='utf-8')

        result = _run_script(
            root,
            "--output", "❌ 1件の不整合\n   - テスト",
            "--state", str(data_dir / "ekiden_state.json"),
            "--individual", str(data_dir / "individual_results.json"),
            "--dir", str(root / "diagnostics"),
        )
        assert result.returncode == 0, f'rc={result.returncode} stdout={result.stdout} stderr={result.stderr}'

        diag_root = root / "diagnostics"
        dirs = [d for d in diag_root.iterdir() if d.is_dir()]
        assert len(dirs) == 1, f"日付付きディレクトリが1つあるべき: {dirs}"
        out_dir = dirs[0]

        assert (out_dir / "ekiden_state.json").read_text(encoding='utf-8') == '{"state": true}'
        assert (out_dir / "individual_results.json").read_text(encoding='utf-8') == '{"runners": []}'
        assert (out_dir / "validation_output.txt").read_text(encoding='utf-8') == '❌ 1件の不整合\n   - テスト'

        manifest = json.loads((out_dir / "manifest.json").read_text(encoding='utf-8'))
        assert manifest["reason"] == "validation failure diagnostics"
        assert "ekiden_state.json" in manifest["files"]
        assert "validation_output.txt" in manifest["files"]

        # 元データは変更されない
        assert (data_dir / "ekiden_state.json").read_text(encoding='utf-8') == '{"state": true}'


def test_missing_state_skipped():
    """状態ファイルが無い場合はスキップしつつ、検証出力は保存される"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = _run_script(
            root,
            "--output", "検証失敗",
            "--state", str(root / "no_such_state.json"),
            "--individual", str(root / "no_such_individual.json"),
            "--dir", str(root / "diagnostics"),
        )
        assert result.returncode == 0, f'rc={result.returncode} stdout={result.stdout} stderr={result.stderr}'
        out_dir = next((root / "diagnostics").iterdir())
        assert (out_dir / "validation_output.txt").read_text(encoding='utf-8') == '検証失敗'
        assert not (out_dir / "ekiden_state.json").exists()
        assert not (out_dir / "individual_results.json").exists()


def test_empty_output_ok():
    """検証出力が空でも保存できる"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = _run_script(root, "--dir", str(root / "diagnostics"))
        assert result.returncode == 0, f'rc={result.returncode} stdout={result.stdout} stderr={result.stderr}'
        out_dir = next((root / "diagnostics").iterdir())
        assert (out_dir / "validation_output.txt").read_text(encoding='utf-8') == ''


# ============================================================

if __name__ == '__main__':
    tests = [
        ("saves_diagnostics_with_output", test_saves_diagnostics_with_output),
        ("missing_state_skipped", test_missing_state_skipped),
        ("empty_output_ok", test_empty_output_ok),
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
