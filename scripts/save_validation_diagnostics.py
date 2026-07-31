#!/usr/bin/env python3
"""
検証 (validate_race_state.py) 失敗時の診断成果物を日付付きディレクトリへ保存する。

保存内容 (data/diagnostics/YYYY-MM-DD_HHMMSS/):
- ekiden_state.json        ... 検証時点の状態（不整合のあった状態）
- individual_results.json  ... 個人記録
- validation_output.txt    ... 検証出力（エラーメッセージ）

既存の復元動作（generate_report.py --commit のバックアップ復元）には干渉しない。
本スクリプトは読み取り専用のコピーを作るだけで、元データは変更しない。

使い方:
  scripts/save_validation_diagnostics.py [--output "検証出力テキスト"]
      [--state FILE] [--individual FILE] [--dir DIR]

戻り値: 0=成功, 1=失敗
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from time_utils import now_jst

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / 'data'
CONFIG_DIR = PROJECT_DIR / 'config'

# 参照用に同梱する設定ファイル（存在すればコピー）
EXTRA_FILES = [CONFIG_DIR / 'ekiden_data.json', CONFIG_DIR / 'shadow_team.json']


def save_diagnostics(output_text, state_file, individual_file, out_dir):
    """診断成果物を out_dir に保存し、保存先パスを返す。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 状態ファイルと個人記録（存在すればコピー）
    copied = []
    for src, dest_name in [
        (Path(state_file), 'ekiden_state.json'),
        (Path(individual_file), 'individual_results.json'),
    ]:
        if Path(src).exists():
            shutil.copy2(src, out_dir / dest_name)
            copied.append(dest_name)

    # 参照用の設定ファイル（存在すればコピー）
    for src in EXTRA_FILES:
        if Path(src).exists():
            shutil.copy2(src, out_dir / src.name)
            copied.append(src.name)

    # 検証出力
    output_path = out_dir / 'validation_output.txt'
    output_path.write_text(output_text or '', encoding='utf-8')

    # マニフェスト
    manifest = {
        'savedAt': now_jst().isoformat(),
        'reason': 'validation failure diagnostics',
        'files': copied + ['validation_output.txt'],
    }
    (out_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    return out_dir


def main():
    parser = argparse.ArgumentParser(description='検証失敗時の診断成果物を保存する')
    parser.add_argument('--output', default='', help='検証出力テキスト')
    parser.add_argument('--state', default=str(DATA_DIR / 'ekiden_state.json'), help='状態ファイル')
    parser.add_argument('--individual', default=str(DATA_DIR / 'individual_results.json'), help='個人記録ファイル')
    parser.add_argument('--dir', default=str(DATA_DIR / 'diagnostics'), help='保存先ディレクトリ')
    args = parser.parse_args()

    base_dir = Path(args.dir)
    stamp = now_jst().strftime('%Y-%m-%d_%H%M%S')
    out_dir = base_dir / stamp

    try:
        saved = save_diagnostics(args.output, args.state, args.individual, out_dir)
    except OSError as e:
        print(f'❌ 診断成果物の保存に失敗しました: {e}', file=sys.stderr)
        return 1

    print(f'✅ 診断成果物を保存しました: {saved}')
    for name in sorted(p.name for p in saved.iterdir()):
        print(f'   - {name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
