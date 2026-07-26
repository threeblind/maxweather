#!/usr/bin/env python3
"""
Runner comments migration script.

Migrates comments from config/team_comments.json and config/player_profiles.json
into a single config/player_comments.json keyed by station_code.

Usage:
  python3 scripts/migrate_player_comments.py
"""
import json
import sys
from pathlib import Path

CONFIG_DIR = Path('config')
TEAM_COMMENTS_FILE = CONFIG_DIR / 'team_comments.json'
PLAYER_PROFILES_FILE = CONFIG_DIR / 'player_profiles.json'
EKIDEN_DATA_FILE = CONFIG_DIR / 'ekiden_data.json'
AMEDAS_STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
PLAYER_COMMENTS_FILE = CONFIG_DIR / 'player_comments.json'


def load_json(path, label=''):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return None, json.load(f)
    except FileNotFoundError:
        return f'{label} not found: {path}', None
    except json.JSONDecodeError as e:
        return f'{label} decode error: {e}', None


def build_name_to_code_map(ekiden_data, amedas_stations):
    """
    ekiden_data.json の runner/substitute と amedas_stations から
    runner_name → station_code のマップを構築する。
    """
    name_to_code = {}

    # 1. ekiden_data の runner/substitute から（station_code 付き dict 優先）
    for team in ekiden_data.get('teams', []):
        for r in team.get('runners', []) + team.get('substitutes', []):
            if isinstance(r, dict):
                name = r.get('name', '')
                code = r.get('station_code', '')
                if name and code:
                    name_to_code[name] = code
            elif isinstance(r, str):
                name = r
                if name and name not in name_to_code:
                    name_to_code[name] = None  # 仮置き、後で amedas で解決

    # 2. amedas_stations で未解決名を補完
    stations_by_name = {}
    for s in amedas_stations:
        sname = s.get('name', '')
        code = s.get('code', '')
        if sname and code:
            stations_by_name[sname] = code

    for name in list(name_to_code.keys()):
        if name_to_code[name] is None and name in stations_by_name:
            name_to_code[name] = stations_by_name[name]

    return name_to_code


def collect_comments_from_profiles(player_profiles):
    """player_profiles.json から非空 comment を收集"""
    comments = {}
    for name, profile in player_profiles.items():
        comment = profile.get('comment', '').strip()
        code = profile.get('code', '')
        if comment and code:
            comments[code] = {'runner_name': name, 'comment': comment}
    return comments


def main():
    issues = []
    migrated = 0
    unresolved_names = []
    skipped_empty = 0

    # データ読み込み
    err, ekiden_data = load_json(EKIDEN_DATA_FILE, 'ekiden_data')
    if err:
        print(f'FATAL: {err}')
        sys.exit(1)

    err, amedas_stations = load_json(AMEDAS_STATIONS_FILE, 'amedas_stations')
    if err:
        print(f'FATAL: {err}')
        sys.exit(1)

    err, team_comments = load_json(TEAM_COMMENTS_FILE, 'team_comments')
    if err:
        print(f'WARN: {err}')
        team_comments = {}

    err, player_profiles = load_json(PLAYER_PROFILES_FILE, 'player_profiles')
    if err:
        print(f'WARN: {err}')
        player_profiles = {}

    # name → code マップ
    name_to_code = build_name_to_code_map(ekiden_data, amedas_stations)
    print(f'name→code map: {sum(1 for v in name_to_code.values() if v)}/{len(name_to_code)} resolved')

    # 結果格納用
    result = {}
    seen_codes = set()

    # 優先順位: player_comments.json が既にあれば最優先（初回は空）
    err, existing = load_json(PLAYER_COMMENTS_FILE, 'player_comments')
    if err is None:
        for code, entry in existing.items():
            if entry.get('comment', '').strip():
                result[code] = entry
                seen_codes.add(code)
                migrated += 1

    # team_comments から移行
    if isinstance(team_comments, dict):
        for team_id_str, runners in team_comments.items():
            if not isinstance(runners, dict):
                continue
            for runner_name, comment in runners.items():
                comment = comment.strip()
                if not comment:
                    skipped_empty += 1
                    continue
                code = name_to_code.get(runner_name)
                if not code:
                    unresolved_names.append(runner_name)
                    continue
                if code in seen_codes:
                    continue  # 既存の player_comments 優先
                result[code] = {'runner_name': runner_name, 'comment': comment}
                seen_codes.add(code)
                migrated += 1

    # player_profiles から移行（team_comments で未解決のもののみ）
    for name, profile in player_profiles.items():
        comment = profile.get('comment', '').strip()
        code = profile.get('code', '')
        if not comment or not code:
            continue
        if code in seen_codes:
            continue
        result[code] = {'runner_name': name, 'comment': comment}
        seen_codes.add(code)
        migrated += 1

    # 結果出力
    PLAYER_COMMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PLAYER_COMMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f'\n✅ player_comments.json 生成完了')
    print(f'   移行件数: {migrated}')
    print(f'   解決不能: {len(unresolved_names)}')
    if unresolved_names:
        for n in unresolved_names:
            print(f'     未解決: {n}')
            issues.append(f'station_code 未解決: {n}')
    print(f'   空スキップ: {skipped_empty}')

    if issues:
        print(f'\n⚠️ {len(issues)}件の課題')
        for i in issues:
            print(f'   {i}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
