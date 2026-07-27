#!/usr/bin/env python3
"""
沿道様向け速報テキスト生成。

日次スナップショットのデータから5chへ貼り付けやすい速報表を生成する。

使い方:
  python3 scripts/generate_alongroad_report.py [--date YYYY-MM-DD] [--save]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SNAPSHOT_BASE = PROJECT_DIR / 'data' / 'daily_snapshots'
CONFIG_DIR = PROJECT_DIR / 'config'

# 沿道様向け大学表示名マッピング（short_name の上書き）
ALONGROAD_NAMES = {
    '名古屋大学': '名古屋大',
    '山梨学院大学': '山梨学院',
    '広島経済大学': '広島経済',
    '鹿児島大学': '鹿児島大',
    '立命館大学': '立命館大',
    '熊本学園大学': '熊本学園',
}
# 残りは ekiden_data.json の short_name をそのまま使う


def load_json(path, label=''):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return None, json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return f'{label}: {e}', None


def resolve_snapshot_dir(target_date):
    """対象日の snapshot ディレクトリを解決する"""
    d = SNAPSHOT_BASE / target_date
    if d.exists():
        return d
    return None


def resolve_race_day(target_date):
    """対象日から race day を計算 (outline.json の startDate 基準)"""
    err, outline = load_json(CONFIG_DIR / 'outline.json', 'outline')
    if err:
        return None
    start_str = outline.get('metadata', {}).get('startDate', '')
    if not start_str:
        return None
    try:
        start = datetime.strptime(start_str, '%Y-%m-%d')
        target = datetime.strptime(target_date, '%Y-%m-%d')
        return (target - start).days + 1
    except (ValueError, TypeError):
        return None


def get_alongroad_name(team_name, short_name):
    """沿道様向け大学表示名を返す"""
    return ALONGROAD_NAMES.get(team_name, short_name)


def strip_leg_number(runner_name):
    """走者名から先頭の区番号を除去（例: '2名古屋' → '名古屋'）"""
    return re.sub(r'^\d+', '', runner_name)


def build_short_name_map(ekiden_data):
    """ekiden_data から {team_name: short_name} マップを構築"""
    return {t.get('name', ''): t.get('short_name', '') for t in ekiden_data.get('teams', []) if t.get('name')}


def generate_report(target_date):
    """沿道様向け速報テキストを生成して返す"""
    snapshot_dir = resolve_snapshot_dir(target_date)
    if not snapshot_dir:
        return f'エラー: {target_date} のスナップショットが見つかりません'

    rt_file = snapshot_dir / 'realtime_report.json'
    ind_file = snapshot_dir / 'individual_results.json'

    err, rt = load_json(rt_file, 'realtime_report')
    if err:
        return f'エラー: {err}'
    err, ind = load_json(ind_file, 'individual_results')
    if err:
        return f'エラー: {err}'

    err, ekiden = load_json(CONFIG_DIR / 'ekiden_data.json', 'ekiden_data')
    if err:
        return f'エラー: {err}'

    # raceDay は snapshot 内の値を正本とする（manifest→realtime_report の順）
    race_day = rt.get('raceDay') or 0
    if not race_day:
        err, manifest = load_json(snapshot_dir / 'manifest.json', 'manifest')
        if err is None:
            race_day = manifest.get('raceDay') or 0
    if not race_day:
        return f'エラー: {target_date} の raceDay がスナップショットから取得できません'

    # 実際の大会日を startDate + (raceDay - 1) で計算
    start_str = ekiden.get('metadata', {}).get('startDate', '') if isinstance(ekiden, dict) and ekiden else ''
    if not start_str:
        err, outline = load_json(CONFIG_DIR / 'outline.json', 'outline')
        if err is None:
            start_str = outline.get('metadata', {}).get('startDate', '')
    if not start_str:
        return f'エラー: 大会開始日が解決できません'
    start_date = datetime.strptime(start_str, '%Y-%m-%d')
    race_calendar_date = start_date + timedelta(days=race_day - 1)

    # 見出し: 全角形式「７月２６日　４日目　結果」
    def to_fullwidth(n):
        return str(n).translate(str.maketrans('0123456789', '０１２３４５６７８９'))
    month_fw = to_fullwidth(race_calendar_date.month)
    day_fw = to_fullwidth(race_calendar_date.day)
    heading = f'【{month_fw}月{day_fw}日　{race_day}日目　結果】'

    short_name_map = build_short_name_map(ekiden)

    # --- チームデータを整形 & shadow除外 & overallRank昇順 ---
    teams = rt.get('teams', [])
    teams = [t for t in teams if not t.get('is_shadow_confederation')]
    teams.sort(key=lambda t: t.get('overallRank', 999))

    lines = []
    lines.append(heading)
    lines.append('')
    lines.append(f'{"大学":8s} {"走者":8s} {"本日":>6s} {"順":>3s} {"総距離":>7s} {"総合順":>4s} {"次走者":8s}')
    lines.append('-' * 52)

    for i, t in enumerate(teams):
        team_name = t.get('name', '')
        short_name = short_name_map.get(team_name, '')
        display_name = get_alongroad_name(team_name, short_name)
        if not display_name:
            display_name = short_name or team_name

        runner_raw = t.get('runner', '')
        runner_name = strip_leg_number(runner_raw)

        # 本日距離: 欠損/0 の場合は individual_results から補完
        today_dist = t.get('todayDistance', 0) or 0
        if today_dist == 0 and runner_name:
            ind_info = ind.get(runner_name, {})
            for rec in ind_info.get('records', []):
                if rec.get('day') == race_day:
                    d = rec.get('distance', 0) or 0
                    if d > 0:
                        today_dist = d
                        break

        today_dist_str = f'{today_dist:.1f}' if today_dist > 0 else '--'

        today_rank = t.get('todayRank', '')
        today_rank_str = f'{today_rank:>2d}' if today_rank is not None and today_rank != '' else '--'

        total_dist = t.get('totalDistance', 0) or 0
        total_dist_str = f'{total_dist:.1f}'

        overall_rank = t.get('overallRank', 0) or 0
        prev_rank = t.get('previousRank', '')
        if prev_rank is not None and prev_rank != '':
            rank_str = f'{overall_rank:>2d}({prev_rank:>2d})'
        else:
            rank_str = f'{overall_rank:>2d}'

        next_runner = t.get('nextRunner', '') or ''

        line = f'{display_name:8s} {runner_name:8s} {today_dist_str:>6s} {today_rank_str:>3s} {total_dist_str:>7s} {rank_str:>4s} {next_runner:8s}'
        lines.append(line)

        # 10位と11位の間に罫線
        if overall_rank == 10 and i + 1 < len(teams):
            lines.append('-' * 52)

    lines.append('')
    lines.append('※( )内は前日順位')
    lines.append('※選手名の前の数字は担当区')
    lines.append('')

    return '\n'.join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='沿道様向け速報テキスト生成')
    parser.add_argument('--date', help='対象日 (YYYY-MM-DD, デフォルト: 最新snapshot)')
    parser.add_argument('--save', action='store_true', help='snapshotディレクトリ内に alongroad_report.txt として保存')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # 日付解決
    if args.date:
        target_date = args.date
    else:
        # 最新の snapshot ディレクトリを探す
        snapshots = sorted(SNAPSHOT_BASE.iterdir()) if SNAPSHOT_BASE.exists() else []
        if not snapshots:
            print('エラー: snapshot ディレクトリが見つかりません', file=sys.stderr)
            return 1
        target_date = snapshots[-1].name

    report = generate_report(target_date)
    print(report)

    if args.save:
        snapshot_dir = resolve_snapshot_dir(target_date)
        if snapshot_dir:
            out_file = snapshot_dir / 'alongroad_report.txt'
            out_file.write_text(report, encoding='utf-8')
            print(f'(保存: {out_file})', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
