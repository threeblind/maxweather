#!/usr/bin/env python3
"""fcntl ロックラッパー: ロックを取得してから指定コマンドを実行する。

macOS / Linux 両対応（fcntl.flock は両OSで利用可能）。
flock(1) コマンドは macOS に存在しないため、このラッパーを使う。

使い方:
    python scripts/with_lock.py <lockfile> -- <command...>

ロックファイルは開いたまま保持され、プロセス終了時に自動解放される。
異常終了（set -e 等）でもカーネルが解放するためロックが残らない。

--check モード（他スクリプトのガード用・ロックを保持しない）:
    python scripts/with_lock.py <lockfile> --check
    ロックを非ブロッキングで取得できれば exit 0、取得できなければ exit 1。
    取得後すぐ解放するため、処理全体を囲むのには使わないこと。

--try モード（ロックを取得できた場合のみコマンドを実行）:
    python scripts/with_lock.py <lockfile> --try -- <command...>
    ロックを非ブロッキングで取得できればコマンドを実行（ロック保持中）、
    取得できなければ exit 75（コマンドは実行しない）。
"""

import fcntl
import os
import subprocess
import sys

LOCK_BUSY_EXIT = 75


def acquire(lockfile, blocking=True):
    f = open(lockfile, 'a+')
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    fcntl.flock(f, flags)
    return f


def main():
    if len(sys.argv) < 3:
        print('使い方: with_lock.py <lockfile> -- <command...> | '
              '--check | --try -- <command...>', file=sys.stderr)
        return 2

    lockfile = sys.argv[1]

    # --check モード: ロック取得可否のみ確認（取得後すぐ解放）
    if len(sys.argv) >= 3 and sys.argv[2] == '--check':
        try:
            acquire(lockfile, blocking=False)
            return 0
        except OSError:
            return 1

    # --try モード: 取得できればコマンド実行、ビジーなら専用終了コード
    if len(sys.argv) >= 4 and sys.argv[2] == '--try' and sys.argv[3] == '--':
        try:
            lock = acquire(lockfile, blocking=False)
        except BlockingIOError:
            return LOCK_BUSY_EXIT
        except OSError as exc:
            print(f'ロックファイルを開けません: {exc}', file=sys.stderr)
            return 1
        return _run_with_lock(lock, sys.argv[4:])

    # 通常モード: ブロッキングで取得してコマンド実行
    if len(sys.argv) >= 4 and sys.argv[2] == '--':
        lock = acquire(lockfile, blocking=True)
        return _run_with_lock(lock, sys.argv[3:])

    print('使い方: with_lock.py <lockfile> -- <command...> | '
          '--check | --try -- <command...>', file=sys.stderr)
    return 2


def _run_with_lock(lock, command):
    try:
        return subprocess.call(command)
    finally:
        # 明示解放（プロセス終了でも自動解放されるが、後続の--checkに備える）
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            lock.close()


if __name__ == '__main__':
    sys.exit(main())
