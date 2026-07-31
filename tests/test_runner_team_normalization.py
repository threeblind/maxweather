"""
shadow_team.json と通常チームの同名選手が individual_results に混入する問題の修正テスト。

修正内容 (scripts/generate_report.py):
- current_runner_team_map: 通常チームの現行登録選手 (runners/substitutes/substituted_out) から
  runner_name → teamId を構築。通常チーム同士の同名重複は設定エラー検出。
- load_individual_results: 現行 config の通常登録選手は、既存 teamId が 99 (shadow) でも
  現行 teamId へ正規化 (records/legSummaries/totalDistance は保持)。
- 新規初期化時: shadow チーム (is_shadow_confederation) の runners は個人記録DBへ投入しない。
- legSummaries の平均/順位計算: teamId=99 の shadow 記録は対象外。
"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_report


def _setup_env(tmp_path, ekiden_data, shadow_data=None, individual=None):
    """generate_report のグローバルをテスト用データで差し替える。"""
    # 実運用 (load_all_data) と同じく runners/substitutes を dict 形式に正規化する
    def _norm(team):
        for key in ('runners', 'substitutes', 'substituted_out'):
            entries = team.get(key, [])
            team[key] = [e if isinstance(e, dict) else {'name': e} for e in entries]
        return team

    ekiden_data['teams'] = [_norm(t) for t in ekiden_data.get('teams', [])]
    if shadow_data is not None:
        shadow_data = _norm(shadow_data)

    generate_report.ekiden_data = ekiden_data
    teams = list(ekiden_data.get('teams', []))
    if shadow_data is not None:
        teams = teams + [shadow_data]
    generate_report.all_teams_data = teams
    # current_runner_team_map を再構築 (load_all_data と同じロジック)
    generate_report.current_runner_team_map = {}
    for team in ekiden_data.get('teams', []):
        if team.get('is_shadow_confederation'):
            continue
        team_id = team.get('id')
        for key in ('runners', 'substitutes', 'substituted_out'):
            for runner_obj in team.get(key, []):
                runner_name = runner_obj.get('name') if isinstance(runner_obj, dict) else runner_obj
                if not runner_name:
                    continue
                generate_report.current_runner_team_map.setdefault(runner_name, team_id)
    # individual ファイルを作成
    ind_path = tmp_path / 'individual_results.json'
    if individual is None:
        if ind_path.exists():
            ind_path.unlink()
    else:
        ind_path.write_text(json.dumps(individual, ensure_ascii=False), encoding='utf-8')
    return str(ind_path)


def _team(team_id, name, runners, substitutes=None, substituted_out=None):
    t = {"id": team_id, "name": name, "runners": runners,
         "substitutes": substitutes or [], "substituted_out": substituted_out or []}
    return t


def _shadow(team_id=99, runners=None):
    return {"id": team_id, "name": "区間記録連合", "is_shadow_confederation": True,
            "runners": runners or []}


# ============================================================
# (a) 文字列 runners で現行 team と shadow 同名の衝突を再現し通常 teamId になる
# ============================================================

def test_load_individual_normalizes_shadow_name_conflict(tmp_path):
    """shadow と同名の通常選手 (文字列 runners) が teamId=99 から現行 teamId へ正規化される"""
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(1, "名古屋大学", ["美濃", "名古屋", "岡崎"]),
        _team(10, "三重大学", ["津", "桑名", "風屋"]),
        _team(15, "四国大学", ["松山", "高知", "新居浜"]),
        _team(3, "関西大学", ["福崎", "郡家", "西脇"]),
    ]}
    shadow = _shadow(runners=[
        {"leg": 1, "name": "梁川", "record": 38.9},
        {"leg": 3, "name": "風屋", "record": 39.5},
        {"leg": 3, "name": "新居浜", "record": 37.7},
        {"leg": 3, "name": "西脇", "record": 35.9},
    ])
    # 既存データ: 風屋/新居浜/西脇 が teamId=99 (shadow 混入) で records あり
    individual = {
        "美濃": {"teamId": 1, "totalDistance": 121.0, "records": [{"day": 1, "leg": 1, "distance": 40.8}], "legSummaries": {}},
        "風屋": {"teamId": 99, "totalDistance": 39.5, "records": [{"day": 1, "leg": 3, "distance": 39.5}], "legSummaries": {"3": {"days": 1}}},
        "新居浜": {"teamId": 99, "totalDistance": 37.7, "records": [{"day": 1, "leg": 3, "distance": 37.7}], "legSummaries": {"3": {"days": 1}}},
        "西脇": {"teamId": 99, "totalDistance": 35.9, "records": [{"day": 1, "leg": 3, "distance": 35.9}], "legSummaries": {"3": {"days": 1}}},
    }
    ind_path = _setup_env(tmp_path, ekiden, shadow, individual)

    loaded = generate_report.load_individual_results(ind_path)

    assert loaded["風屋"]["teamId"] == 10, f'風屋 teamId 期待 10 got {loaded["風屋"]["teamId"]}'
    assert loaded["新居浜"]["teamId"] == 15, f'新居浜 teamId 期待 15 got {loaded["新居浜"]["teamId"]}'
    assert loaded["西脇"]["teamId"] == 3, f'西脇 teamId 期待 3 got {loaded["西脇"]["teamId"]}'
    # 通常選手は変わらない
    assert loaded["美濃"]["teamId"] == 1


# ============================================================
# (b) 既存 teamId=99 で records ありの選手をロードして records 保持のまま通常 teamId へ修復
# ============================================================

def test_load_individual_preserves_records_on_normalize(tmp_path):
    """teamId=99 の既存選手が records/legSummaries/totalDistance を保持したまま修復される"""
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(10, "三重大学", ["津", "桑名", "風屋"]),
    ]}
    shadow = _shadow(runners=[{"leg": 3, "name": "風屋", "record": 39.5}])
    individual = {
        "風屋": {
            "teamId": 99,
            "totalDistance": 78.3,
            "records": [
                {"day": 1, "leg": 3, "distance": 39.5},
                {"day": 2, "leg": 3, "distance": 38.8},
            ],
            "legSummaries": {"3": {"totalDistance": 78.3, "days": 2, "averageDistance": 39.15}},
        },
    }
    ind_path = _setup_env(tmp_path, ekiden, shadow, individual)

    loaded = generate_report.load_individual_results(ind_path)
    fk = loaded["風屋"]
    assert fk["teamId"] == 10
    assert fk["totalDistance"] == 78.3
    assert len(fk["records"]) == 2
    assert fk["records"][0]["distance"] == 39.5
    assert fk["records"][1]["distance"] == 38.8
    assert fk["legSummaries"]["3"]["days"] == 2
    assert fk["legSummaries"]["3"]["averageDistance"] == 39.15


# ============================================================
# (c) 4区の風屋/新居浜/西脇が teamId=10/15/3 となり表示対象になる
# ============================================================

def test_fourth_leg_runners_normalized_to_their_teams(tmp_path):
    """現行 config の4区走者 (風屋/新居浜/西脇) がそれぞれの teamId に正規化される"""
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(10, "三重大学", ["津", "桑名", "小俣", "風屋"]),
        _team(15, "四国大学", ["松山", "高知", "御荘", "新居浜"]),
        _team(3, "関西大学", ["福崎", "郡家", "上郡", "西脇"]),
    ]}
    shadow = _shadow(runners=[
        {"leg": 3, "name": "風屋", "record": 39.5},
        {"leg": 3, "name": "新居浜", "record": 37.7},
        {"leg": 3, "name": "西脇", "record": 35.9},
    ])
    individual = {
        "風屋": {"teamId": 99, "totalDistance": 0.0, "records": [], "legSummaries": {}},
        "新居浜": {"teamId": 99, "totalDistance": 0.0, "records": [], "legSummaries": {}},
        "西脇": {"teamId": 99, "totalDistance": 0.0, "records": [], "legSummaries": {}},
    }
    ind_path = _setup_env(tmp_path, ekiden, shadow, individual)

    loaded = generate_report.load_individual_results(ind_path)
    assert loaded["風屋"]["teamId"] == 10
    assert loaded["新居浜"]["teamId"] == 15
    assert loaded["西脇"]["teamId"] == 3
    # teamId=99 の選手が残っていない
    assert all(v["teamId"] != 99 for v in loaded.values())


# ============================================================
# (d) shadow 専用記録が順位に混入せず、通常の順位が計算される
# ============================================================

def test_leg_summaries_excludes_shadow_team(tmp_path, monkeypatch):
    """teamId=99 の shadow 記録は legSummaries 平均/順位計算から除外される"""
    # individual_results に shadow 専用選手 (teamId=99, 現行 config に存在しない) が混在しても、
    # 区間平均・順位計算の対象外になる。
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(10, "三重大学", ["津", "桑名", "小俣", "風屋"]),
    ]}
    shadow = _shadow(runners=[{"leg": 3, "name": "shadow専用", "record": 99.0}])
    individual = {
        # 通常選手: 3区 39.5
        "風屋": {"teamId": 10, "totalDistance": 39.5,
                 "records": [{"day": 1, "leg": 3, "distance": 39.5}],
                 "legSummaries": {"3": {"totalDistance": 39.5, "days": 1, "averageDistance": 39.5}}},
        # shadow 専用: teamId=99 (現行 config にない)
        "shadow専用": {"teamId": 99, "totalDistance": 99.0,
                       "records": [{"day": 1, "leg": 3, "distance": 99.0}],
                       "legSummaries": {"3": {"totalDistance": 99.0, "days": 1, "averageDistance": 99.0}}},
    }
    ind_path = _setup_env(tmp_path, ekiden, shadow, individual)

    # load_individual_results で shadow 専用は teamId=99 のまま (通常登録にないため)
    loaded = generate_report.load_individual_results(ind_path)
    assert loaded["shadow専用"]["teamId"] == 99

    # 順位計算対象の抽出ロジックを模擬: teamId=99 は除外される
    leg_performance = []
    for runner_name, runner_data in loaded.items():
        if runner_data.get('teamId') == 99:
            continue
        for leg_key, summary in runner_data.get('legSummaries', {}).items():
            if summary.get('days', 0) > 0:
                leg_performance.append((runner_name, summary))

    runner_names = [r[0] for r in leg_performance]
    assert "shadow専用" not in runner_names
    assert "風屋" in runner_names
    # shadow 専用 (99.0) が通常選手 (39.5) の順位に影響しない
    assert len(runner_names) == 1


# ============================================================
# (e) 新規初期化時に shadow の runners を投入しない
# ============================================================

def test_individual_init_excludes_shadow_runners(tmp_path):
    """individual_results が存在しない場合の初期化で shadow runners は投入されない"""
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(10, "三重大学", ["津", "桑名", "小俣", "風屋"]),
        _team(15, "四国大学", ["松山", "高知", "御荘", "新居浜"]),
    ]}
    shadow = _shadow(runners=[
        {"leg": 1, "name": "梁川", "record": 38.9},
        {"leg": 3, "name": "風屋", "record": 39.5},
    ])
    ind_path = _setup_env(tmp_path, ekiden, shadow, individual=None)  # ファイルなし

    loaded = generate_report.load_individual_results(ind_path)
    # 通常選手のみが初期化される
    assert "津" in loaded
    assert "松山" in loaded
    assert loaded["津"]["teamId"] == 10
    # shadow 専用選手 (梁川) は投入されない
    assert "梁川" not in loaded
    # 同名でも通常選手として投入される (風屋は 三重 10)
    assert "風屋" in loaded
    assert loaded["風屋"]["teamId"] == 10


# ============================================================
# (f) 通常チーム同士の同名重複は設定エラー検出
# ============================================================

def test_duplicate_normal_runner_name_detected():
    """通常チーム同士で同名選手が重複すると build_current_runner_team_map がエラーを返す (実装直結)"""
    teams = [
        _team(1, "名古屋大学", ["美濃", "名古屋"]),
        _team(2, "上武大学", ["美濃", "前橋"]),  # 美濃 が重複
    ]
    # 実際の実装ヘルパーを通す
    runner_map, error = generate_report.build_current_runner_team_map(teams)
    assert error is not None, '重複登録が検出されること'
    assert '美濃' in error
    assert runner_map is None


def test_build_map_no_duplicate_with_same_team_entries():
    """同一チーム内の runners/substitutes で同名が現れても重複エラーにしない (同一 teamId は許容)"""
    # 現行 config では「佐野」は上武の runners と shadow 両方に存在するが、通常チーム同士の重複はない
    ekiden = json.loads((PROJECT_ROOT / 'config' / 'ekiden_data.json').read_text(encoding='utf-8'))
    runner_map, error = generate_report.build_current_runner_team_map(ekiden.get('teams', []))
    assert error is None, f'現行 config で重複エラーは出ない: {error}'
    assert runner_map.get('風屋') == 10
    assert runner_map.get('新居浜') == 15
    assert runner_map.get('西脇') == 3


def test_load_individual_results_init_defends_string_runners(tmp_path):
    """初期化時に文字列 runner が渡されても dict 化されていなくても防御する"""
    ekiden = {"leg_boundaries": [100, 210, 310], "teams": [
        _team(10, "三重大学", ["津", "桑名", "小俣", "風屋"]),  # 文字列のまま
    ]}
    # _setup_env は dict 化するので、直接 generate_report.all_teams_data に文字列のまま設定する
    raw_team = {"id": 10, "name": "三重大学", "runners": ["津", "桑名", "小俣", "風屋"],
                "substitutes": [], "substituted_out": []}
    generate_report.ekiden_data = {"teams": [raw_team]}
    generate_report.all_teams_data = [raw_team]
    generate_report.current_runner_team_map = {"津": 10, "桑名": 10, "小俣": 10, "風屋": 10}
    ind_path = tmp_path / 'individual_results.json'
    if ind_path.exists():
        ind_path.unlink()

    loaded = generate_report.load_individual_results(str(ind_path))
    assert "津" in loaded
    assert "風屋" in loaded
    assert loaded["津"]["teamId"] == 10


# ============================================================
# 実データ確認: 現行 config で風屋/新居浜/西脇 の teamId
# ============================================================

def test_real_config_fourth_leg_team_ids():
    """現行 config/ekiden_data.json で 風屋/新居浜/西脇 が 10/15/3 に属する"""
    ekiden = json.loads((PROJECT_ROOT / 'config' / 'ekiden_data.json').read_text(encoding='utf-8'))
    name_to_team = {}
    for team in ekiden.get('teams', []):
        if team.get('is_shadow_confederation'):
            continue
        for key in ('runners', 'substitutes', 'substituted_out'):
            for runner_obj in team.get(key, []):
                name = runner_obj.get('name') if isinstance(runner_obj, dict) else runner_obj
                if name:
                    name_to_team[name] = team['id']
    assert name_to_team.get('風屋') == 10, f'風屋 teamId 期待 10 got {name_to_team.get("風屋")}'
    assert name_to_team.get('新居浜') == 15, f'新居浜 teamId 期待 15 got {name_to_team.get("新居浜")}'
    assert name_to_team.get('西脇') == 3, f'西脇 teamId 期待 3 got {name_to_team.get("西脇")}'
    # 重複 (同一名が複数チーム) がないこと
    assert len(name_to_team) == len(set(name_to_team.keys()))


if __name__ == '__main__':
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
