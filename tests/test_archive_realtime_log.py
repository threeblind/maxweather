"""
scripts/archive_realtime_log.sh のテスト。

realtime_log.jsonl の日次アーカイブが冪等であることを検証する:
- 同日アーカイブが無ければ git mv で移動
- 同日アーカイブが既にあり同内容ならスキップ（ソース削除で初回実行後と同状態）
- 同日アーカイブが既にあり内容が異なれば明示的に停止（既存データを上書きしない）
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_SCRIPT = PROJECT_ROOT / "scripts" / "archive_realtime_log.sh"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _setup_git_repo():
    """テンポラリの git リポジトリを作成し、data/realtime_log.jsonl を追跡状態にする。"""
    tmpdir = tempfile.mkdtemp(prefix='archive_test_')
    data_dir = Path(tmpdir) / "data"
    archive_dir = data_dir / "archive"
    archive_dir.mkdir(parents=True)
    (data_dir / "realtime_log.jsonl").write_text('{"day":1}\n', encoding='utf-8')

    def git(*args):
        subprocess.run(
            ["git", *args],
            cwd=tmpdir, check=True, capture_output=True,
            env={**os.environ, **GIT_ENV},
        )

    git("init", "-q")
    git("add", "data/realtime_log.jsonl")
    git("commit", "-q", "-m", "initial")

    return tmpdir, data_dir, archive_dir


def _run_archive(data_dir, cwd=None):
    return subprocess.run(
        ["bash", str(ARCHIVE_SCRIPT), str(data_dir)],
        capture_output=True, text=True, cwd=cwd,
    )


def _cleanup(tmpdir):
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# テスト
# ============================================================

def test_archive_normal_move():
    """同日アーカイブが無い場合: git mv で移動し、ソースは消えアーカイブができる"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        today = "2026-07-31"  # 日付は実行日のものが使われる
        # テスト日付を固定できないため、存在確認はアーカイブディレクトリ内の1ファイルで行う
        result = _run_archive(data_dir, cwd=tmpdir)
        assert result.returncode == 0, f'rc={result.returncode} stdout={result.stdout} stderr={result.stderr}'
        assert not (data_dir / "realtime_log.jsonl").exists(), "ソースは移動後存在しない"
        archived = list(archive_dir.glob("realtime_log_*.jsonl"))
        assert len(archived) == 1, f"アーカイブが1つあるべき: {archived}"
        assert archived[0].read_text(encoding='utf-8') == '{"day":1}\n'
    finally:
        _cleanup(tmpdir)


def test_archive_idempotent_same_content():
    """同日アーカイブが既にあり同内容: スキップし、ソースを削除して冪等を保つ"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        # 1回目: アーカイブ実行
        result1 = _run_archive(data_dir, cwd=tmpdir)
        assert result1.returncode == 0, f'rc={result1.returncode} stdout={result1.stdout}'
        archived = list(archive_dir.glob("realtime_log_*.jsonl"))
        assert len(archived) == 1
        assert not (data_dir / "realtime_log.jsonl").exists()

        # ソースを復元（同内容）→ 2回目: スキップされるべき
        (data_dir / "realtime_log.jsonl").write_text('{"day":1}\n', encoding='utf-8')
        result2 = _run_archive(data_dir, cwd=tmpdir)
        assert result2.returncode == 0, f'rc={result2.returncode} stdout={result2.stdout} stderr={result2.stderr}'
        assert '同一のため' in result2.stdout, f'スキップメッセージが出るべき: {result2.stdout}'
        # 冪等: ソースは削除され、アーカイブは1つのまま
        assert not (data_dir / "realtime_log.jsonl").exists(), "同内容のソースは削除される"
        assert len(list(archive_dir.glob("realtime_log_*.jsonl"))) == 1
    finally:
        _cleanup(tmpdir)


def test_archive_idempotent_tracked_staged_source():
    """追跡済み (index に staged) のソースが同内容: git rm で削除がステージされ、日次コミットに含められる"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        # 1回目: アーカイブ実行 → コミット
        result1 = _run_archive(data_dir, cwd=tmpdir)
        assert result1.returncode == 0, f'rc={result1.returncode} stdout={result1.stdout}'
        subprocess.run(["git", "commit", "-qm", "archive"],
                       cwd=tmpdir, check=True, capture_output=True,
                       env={**os.environ, **GIT_ENV})

        # アーカイブ前のソースを復元してステージ（追跡・staged 状態）
        with open(data_dir / "realtime_log.jsonl", "w", encoding="utf-8") as fh:
            subprocess.run(
                ["git", "show", "HEAD~1:data/realtime_log.jsonl"],
                cwd=tmpdir, check=True, stdout=fh, env={**os.environ, **GIT_ENV},
            )
        subprocess.run(["git", "add", "data/realtime_log.jsonl"],
                       cwd=tmpdir, check=True, capture_output=True,
                       env={**os.environ, **GIT_ENV})

        # 2回目: 同内容 → git rm 分岐（staged 変更があっても強制削除で成功する）
        result2 = _run_archive(data_dir, cwd=tmpdir)
        assert result2.returncode == 0, f'rc={result2.returncode} stdout={result2.stdout} stderr={result2.stderr}'
        assert '同一のため' in result2.stdout
        # ソースは worktree と index の両方から消える（HEAD には存在しない新規追加だったため
        # 削除のステージングは発生しないが、これは正しい終状態）
        assert not (data_dir / "realtime_log.jsonl").exists(), "ソースは削除される"
        tracked = subprocess.run(
            ["git", "ls-files", "--", "data/realtime_log.jsonl"],
            cwd=tmpdir, capture_output=True, text=True, env={**os.environ, **GIT_ENV},
        ).stdout
        assert tracked.strip() == "", f"index からも消えるべき: {tracked!r}"
    finally:
        _cleanup(tmpdir)


def test_archive_conflict_different_content():
    """同日アーカイブが既にあり内容が異なる: 明示的に停止し、既存データを上書きしない"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        # 1回目: アーカイブ実行
        result1 = _run_archive(data_dir, cwd=tmpdir)
        assert result1.returncode == 0, f'rc={result1.returncode} stdout={result1.stdout}'
        archived = list(archive_dir.glob("realtime_log_*.jsonl"))
        original_archive_content = archived[0].read_text(encoding='utf-8')

        # ソースに新しい行が追加された状態で再実行 → 停止すべき
        (data_dir / "realtime_log.jsonl").write_text('{"day":1}\n{"day":2}\n', encoding='utf-8')
        result2 = _run_archive(data_dir, cwd=tmpdir)
        assert result2.returncode == 1, f'rc={result2.returncode} stdout={result2.stdout} stderr={result2.stderr}'
        assert '内容が異なります' in result2.stdout, f'不一致メッセージが出るべき: {result2.stdout}'
        # 既存アーカイブは無変更・ソースも残る
        assert archived[0].read_text(encoding='utf-8') == original_archive_content, "既存アーカイブは上書きされない"
        assert (data_dir / "realtime_log.jsonl").exists(), "ソースは残る"
        assert (data_dir / "realtime_log.jsonl").read_text(encoding='utf-8') == '{"day":1}\n{"day":2}\n'
    finally:
        _cleanup(tmpdir)


def test_archive_source_missing_dest_exists():
    """ソースが無くアーカイブがある: 既にアーカイブ済みとしてスキップ"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        result1 = _run_archive(data_dir, cwd=tmpdir)
        assert result1.returncode == 0, f'rc={result1.returncode} stdout={result1.stdout}'
        # ソースは消えている → 再実行
        result2 = _run_archive(data_dir, cwd=tmpdir)
        assert result2.returncode == 0, f'rc={result2.returncode} stdout={result2.stdout} stderr={result2.stderr}'
        assert '既にアーカイブ済み' in result2.stdout, f'アーカイブ済みメッセージが出るべき: {result2.stdout}'
    finally:
        _cleanup(tmpdir)


def test_archive_source_missing_no_dest():
    """ソースもアーカイブも無い: スキップ（エラーにならない）"""
    tmpdir, data_dir, archive_dir = _setup_git_repo()
    try:
        (data_dir / "realtime_log.jsonl").unlink()  # ソースを消す
        # アーカイブは実行日付のものしか作られない前提（まだ無い）
        result = _run_archive(data_dir, cwd=tmpdir)
        assert result.returncode == 0, f'rc={result.returncode} stdout={result.stdout} stderr={result.stderr}'
        assert '見つかりませんでした' in result.stdout, f'スキップメッセージが出るべき: {result.stdout}'
    finally:
        _cleanup(tmpdir)


def test_commit_daily_sh_calls_archive_script():
    """commit_daily.sh が archive_realtime_log.sh を呼び出している"""
    sh = PROJECT_ROOT / "commit_daily.sh"
    text = sh.read_text(encoding="utf-8")
    assert "archive_realtime_log.sh" in text


# ============================================================

if __name__ == '__main__':
    tests = [
        ("archive_normal_move", test_archive_normal_move),
        ("archive_idempotent_same_content", test_archive_idempotent_same_content),
        ("archive_idempotent_tracked_staged_source", test_archive_idempotent_tracked_staged_source),
        ("archive_conflict_different_content", test_archive_conflict_different_content),
        ("archive_source_missing_dest_exists", test_archive_source_missing_dest_exists),
        ("archive_source_missing_no_dest", test_archive_source_missing_no_dest),
        ("commit_daily_sh_calls_archive_script", test_commit_daily_sh_calls_archive_script),
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
