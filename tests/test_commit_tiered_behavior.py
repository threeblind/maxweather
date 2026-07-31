"""
commit_daily.sh 3段階化 (正常 / 警告付き継続 / 致命的停止) のテスト。

- validate_race_state.py: exit code 0/1/2 と構造化出力 (VALIDATION_RESULT)
- generate_report.py: write_commit_status / parse_validation_result
- commit_daily.sh: --best-effort 使用・DEGRADED 継続・[degraded] コミットメッセージ
- save_daily_snapshot.py: manifest への commitStatus 記録
- update_all_records.py: fetch_status.json のアクティブ欠損記録
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DEFAULT_LEG_BOUNDARIES = [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055]


# ============================================================
# validate_race_state.py: exit code 3段階
# ============================================================

def _run_validator(state_list, ind_results, ekiden_data, shadow_data=None):
    """環境変数でパスを差し替えて validate_race_state.py を CLI 実行する。"""
    tmpdir = tempfile.mkdtemp(prefix='tier_test_')
    f_state = os.path.join(tmpdir, 'state.json')
    f_ind = os.path.join(tmpdir, 'ind.json')
    f_ek = os.path.join(tmpdir, 'ekiden.json')
    f_shadow = os.path.join(tmpdir, 'shadow_team.json')
    f_prev = os.path.join(tmpdir, 'no_prev.json')

    with open(f_state, 'w', encoding='utf-8') as fh:
        json.dump(state_list, fh, ensure_ascii=False)
    with open(f_ind, 'w', encoding='utf-8') as fh:
        json.dump(ind_results, fh, ensure_ascii=False)
    with open(f_ek, 'w', encoding='utf-8') as fh:
        json.dump(ekiden_data, fh, ensure_ascii=False)
    if shadow_data is not None:
        with open(f_shadow, 'w', encoding='utf-8') as fh:
            json.dump(shadow_data, fh, ensure_ascii=False)

    env = dict(os.environ)
    env.update({
        'VALIDATE_STATE_FILE': f_state,
        'VALIDATE_INDIVIDUAL_FILE': f_ind,
        'VALIDATE_EKIDEN_FILE': f_ek,
        'VALIDATE_SHADOW_FILE': f_shadow,
        'VALIDATE_PREVIOUS_STATE_FILE': f_prev,
    })
    try:
        proc = subprocess.run(
            [sys.executable, 'scripts/validate_race_state.py'],
            capture_output=True, text=True, cwd=PROJECT_ROOT, env=env, timeout=30,
        )
        return proc.returncode, proc.stdout
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _regular_state(team_id, total, leg):
    return {"id": team_id, "currentLeg": leg, "totalDistance": total}


def test_cli_exit_0_ok():
    """正常データ → exit 0"""
    ekiden = {"leg_boundaries": DEFAULT_LEG_BOUNDARIES, "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [_regular_state(1, 121.0, 2)]
    ind = {"美濃": {"teamId": 1, "records": [
        {"day": 1, "leg": 1, "distance": 40.8},
        {"day": 2, "leg": 1, "distance": 40.2},
        {"day": 3, "leg": 1, "distance": 40.0},
    ]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 0, f'expected=0 got={rc}'
    assert 'VALIDATION_RESULT' in stdout


def test_cli_exit_2_warning():
    """1大学の totalDistance 不整合 → exit 2 (W1 warning)"""
    ekiden = {"leg_boundaries": DEFAULT_LEG_BOUNDARIES, "teams": [{"id": 7, "name": "琉球大学"}]}
    state = [_regular_state(7, 98.9, 2)]
    ind = {"北原": {"teamId": 7, "records": [
        {"day": 1, "leg": 1, "distance": 38.0},
        {"day": 2, "leg": 1, "distance": 35.0},
        {"day": 3, "leg": 1, "distance": 33.0},
        {"day": 4, "leg": 1, "distance": 26.6},
    ]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 2, f'expected=2 got={rc}'
    assert '"code": "W1"' in stdout


def test_cli_exit_2_boundary_warning():
    """交代由来の currentLeg 先行 (境界未到達) → exit 2 (W3 warning)。削除ではなく警告化"""
    ekiden = {"leg_boundaries": DEFAULT_LEG_BOUNDARIES, "teams": [{"id": 1, "name": "名古屋大学"}]}
    # currentLeg=3 だが個人記録合計は 2区境界(210) 未満 → 従来は FAIL、新仕様では W3 warning
    state = [_regular_state(1, 200.0, 3)]
    ind = {"美濃": {"teamId": 1, "records": [
        {"day": 1, "leg": 1, "distance": 40.0},
        {"day": 2, "leg": 1, "distance": 40.0},
        {"day": 3, "leg": 1, "distance": 40.0},
    ]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 2, f'expected=2 (W3 warning) got={rc}'
    assert '"code": "W3"' in stdout


def test_cli_exit_1_fatal_json():
    """JSON破損 → exit 1 (F1 fatal)"""
    ekiden = {"leg_boundaries": DEFAULT_LEG_BOUNDARIES, "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [_regular_state(1, 121.0, 2)]
    ind = {"美濃": {"teamId": 1, "records": []}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 0, f'expected=0 got={rc}'


def test_cli_exit_1_fatal_orphan_team():
    """state に存在しない teamId → exit 1 (F3 fatal)"""
    ekiden = {"leg_boundaries": [100, 210], "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [_regular_state(1, 120.0, 2)]
    ind = {"美濃": {"teamId": 99, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 1, f'expected=1 (F3 fatal) got={rc}'
    assert '"code": "F3"' in stdout


def test_cli_exit_1_fatal_state_missing_id():
    """ekiden_state 要素に id 欠落 → exit 1 (F3 fatal)"""
    ekiden = {"leg_boundaries": [100, 210], "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [{"currentLeg": 2, "totalDistance": 120.0}]  # id なし
    ind = {"美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 1, f'expected=1 (F3 fatal) got={rc}'
    assert '"code": "F3"' in stdout
    assert 'id がありません' in stdout


def test_cli_exit_1_fatal_state_unknown_id_vs_config():
    """ekiden_state に config にない team id → exit 1 (F3 fatal)"""
    ekiden = {"leg_boundaries": [100, 210], "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [_regular_state(77, 120.0, 2)]  # config に存在しない id
    ind = {"美濃": {"teamId": 77, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 1, f'expected=1 (F3 fatal) got={rc}'
    assert 'config/ekiden_data.json に存在しない teamId' in stdout


def test_cli_exit_1_fatal_state_not_dict():
    """ekiden_state 要素が dict でない → exit 1 (F2 fatal)"""
    ekiden = {"leg_boundaries": [100, 210], "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = ["not-a-dict", _regular_state(1, 120.0, 2)]
    ind = {"美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 1, f'expected=1 (F2 fatal) got={rc}'
    assert '"code": "F2"' in stdout
    assert 'オブジェクトではありません' in stdout


def test_cli_exit_1_fatal_non_numeric_distance():
    """totalDistance が数値化不能 → exit 1 (F3 fatal)"""
    ekiden = {"leg_boundaries": [100, 210], "teams": [{"id": 1, "name": "名古屋大学"}]}
    state = [{"id": 1, "name": "名古屋大学", "currentLeg": 2, "totalDistance": "abc"}]
    ind = {"美濃": {"teamId": 1, "records": [{"day": 1, "leg": 1, "distance": 40.0}]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    assert rc == 1, f'expected=1 (F3 fatal) got={rc}'
    assert '"code": "F3"' in stdout
    assert '数値化できません' in stdout


def test_validation_result_json_machine_readable():
    """最終行の VALIDATION_RESULT JSON がパース可能で issues を含む"""
    ekiden = {"leg_boundaries": DEFAULT_LEG_BOUNDARIES, "teams": [{"id": 7, "name": "琉球大学"}]}
    state = [_regular_state(7, 60.0, 2)]  # 個人記録合計 73.0 > state 60.0 → W1
    ind = {"北原": {"teamId": 7, "records": [
        {"day": 1, "leg": 1, "distance": 38.0},
        {"day": 2, "leg": 1, "distance": 35.0},
    ]}}
    rc, stdout = _run_validator(state, ind, ekiden)
    payload_line = [l for l in stdout.splitlines() if l.startswith('VALIDATION_RESULT ')][-1]
    payload = json.loads(payload_line[len('VALIDATION_RESULT '):])
    assert payload['exit_code'] == 2
    assert any(i['code'] == 'W1' for i in payload['issues'])
    assert all(i['severity'] in ('warning', 'fatal') for i in payload['issues'])


# ============================================================
# generate_report.py: write_commit_status / parse_validation_result
# ============================================================

def test_write_commit_status_ok():
    """status=ok の commit_status.json が生成される (date=YYYY-MM-DD, validatedTeams=全大学)"""
    import generate_report
    tmpdir = Path(tempfile.mkdtemp(prefix='cs_ok_'))
    generate_report.DATA_DIR = tmpdir
    generate_report.COMMIT_STATUS_FILE = tmpdir / 'commit_status.json'
    try:
        validated = [{"team_id": 1, "team_name": "名古屋大学"}, {"team_id": 15, "team_name": "四国大学"}]
        cs = generate_report.write_commit_status('ok', 0, [], [], '2026-07-31', validated)
        assert cs['status'] == 'ok'
        assert cs['schemaVersion'] == 1
        assert cs['validationSeverity'] == 0
        assert cs['date'] == '2026-07-31'
        assert cs['validatedTeams'] == validated
        assert 'data/commit_status.json' in cs['publishedFiles']
        assert 'data/fetch_status.json' in cs['publishedFiles']
        saved = json.loads((tmpdir / 'commit_status.json').read_text(encoding='utf-8'))
        assert saved['status'] == 'ok'
        assert saved['date'] == '2026-07-31'
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_commit_status_degraded():
    """status=degraded に quarantinedTeams と errors が記録される"""
    import generate_report
    tmpdir = Path(tempfile.mkdtemp(prefix='cs_deg_'))
    generate_report.DATA_DIR = tmpdir
    generate_report.COMMIT_STATUS_FILE = tmpdir / 'commit_status.json'
    try:
        issues = [{
            'severity': 'warning', 'code': 'W1', 'team_id': 16,
            'team_name': '福島大学',
            'message': '福島大学: state.totalDistance=270.7 < 個人記録合計=294.0',
        }]
        quarantined = [{'team_id': 12, 'team_name': '熊本学園大学',
                        'reason': '選手の気温確定値がありません'}]
        validated = [{"team_id": 16, "team_name": "福島大学"}, {"team_id": 12, "team_name": "熊本学園大学"}]
        cs = generate_report.write_commit_status('degraded', 2, issues, quarantined, '2026-07-31', validated)
        assert cs['status'] == 'degraded'
        assert cs['validationSeverity'] == 2
        assert cs['validatedTeams'] == validated
        assert cs['quarantinedTeams'] == quarantined
        assert len(cs['errors']) == 1
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_parse_validation_result():
    """VALIDATION_RESULT 行から (issues, validated_teams) を抽出する"""
    import generate_report
    stdout = (
        "⚠️ 1件の警告\n"
        "   ⚠️ [W1] 福島大学: ...\n"
        'VALIDATION_RESULT {"exit_code": 2, "issues": [{"severity": "warning", "code": "W1", "team_id": 16, "team_name": "福島大学", "message": "m"}], "validated_teams": [{"team_id": 16, "team_name": "福島大学"}]}\n'
    )
    issues, validated = generate_report.parse_validation_result(stdout)
    assert len(issues) == 1
    assert issues[0]['code'] == 'W1'
    assert validated == [{"team_id": 16, "team_name": "福島大学"}]


# ============================================================
# Blocker 2: apply_quarantine が state / individual / all_results を実行前値に戻す
# ============================================================

def test_apply_quarantine_restores_all_three():
    """quarantine チームは state / individual_results / all_results すべて実行前値になる

    区間境界を跨ぐ候補 (欠損気温で todayDistance=0 でも実行前 totalDistance が次の境界を
    超え、newCurrentLeg が進んでしまうケース) を想定し、all_results の全フィールド
    (finishDay / nextRunnerStartDistance / nextRunnerLegStartDay / overallRank /
    runner / currentLegNumber) が実行前値に戻ることを検証する。
    """
    import copy
    import generate_report

    # 実行前 state: 熊本学園は totalDistance=340.2, currentLeg=4 (4区開始済み)
    # 4区境界が 310 のため、340.2 は境界を超えている → 候補計算では newCurrentLeg=5 に進む
    pre_state = [
        {"id": 1, "name": "名古屋大学", "totalDistance": 302.5, "currentLeg": 3, "overallRank": 2,
         "finishDay": None, "currentRunnerStartDistance": 302.5, "currentRunnerLegStartDay": 9},
        {"id": 12, "name": "熊本学園大学", "totalDistance": 340.2, "currentLeg": 4, "overallRank": 9,
         "finishDay": None, "currentRunnerStartDistance": 340.2, "currentRunnerLegStartDay": 10},
    ]
    pre_individual = {
        "美濃": {"teamId": 1, "totalDistance": 121.0, "records": [{"day": 1, "leg": 1, "distance": 40.8}]},
        "宇目": {"teamId": 12, "totalDistance": 66.0, "records": [
            {"day": 1, "leg": 1, "distance": 38.0},
            {"day": 2, "leg": 1, "distance": 28.0},
        ]},
    }
    current_state = copy.deepcopy(pre_state)
    individual_results = copy.deepcopy(pre_individual)
    individual_results["宇目"]["records"].append({"day": 9, "leg": 4, "distance": 38.1})
    individual_results["宇目"]["totalDistance"] = 104.1

    # 候補 all_results: 熊本学園は todayDistance=0 でも境界を跨いで newCurrentLeg=5 に進む候補
    all_results = [
        {"id": 1, "name": "名古屋大学", "runner": "岡崎", "currentLegNumber": 3, "newCurrentLeg": 3,
         "todayDistance": 36.6, "totalDistance": 339.1, "previousRank": 2,
         "rawTempResult": {'temperature': 36.6, 'error': None}, "finishDay": None, "group_id": 0,
         "currentTempForLog": 36.6, "currentRunnerStartDistance": 302.5,
         "currentRunnerLegStartDay": 9, "nextRunnerStartDistance": 302.5, "nextRunnerLegStartDay": 9},
        {"id": 12, "name": "熊本学園大学", "runner": "宇目", "currentLegNumber": 4, "newCurrentLeg": 5,
         "todayDistance": 0.0, "totalDistance": 340.2, "previousRank": 8,
         "rawTempResult": {'temperature': 0, 'error': '確定気温なし (quarantine)'}, "finishDay": 9,
         "group_id": 1, "currentTempForLog": None, "currentRunnerStartDistance": 340.2,
         "currentRunnerLegStartDay": 10, "nextRunnerStartDistance": 340.2, "nextRunnerLegStartDay": 11},
    ]
    quarantined = [{"team_id": 12, "team_name": "熊本学園大学", "reason": "確定気温なし"}]
    team_info_map = {
        1: {"id": 1, "runners": ["美濃", "名古屋", "岡崎"]},
        12: {"id": 12, "runners": ["犬飼", "菊池", "宇目", "上", "熊本"]},
    }

    new_all, new_state = generate_report.apply_quarantine(
        all_results, individual_results, current_state, quarantined,
        pre_state, pre_individual, team_info_map,
    )

    # all_results: quarantine チームは全フィールド実行前値に戻る
    q_result = next(r for r in new_all if r['id'] == 12)
    assert q_result['totalDistance'] == 340.2
    assert q_result['newCurrentLeg'] == 4        # 境界を跨がず実行前 leg に戻る
    assert q_result['currentLegNumber'] == 4
    assert q_result['todayDistance'] == 0.0
    assert q_result['finishDay'] is None         # 候補の finishDay=9 が実行前 None に戻る
    assert q_result['overallRank'] == 9          # 実行前 rank に戻る
    assert q_result['nextRunnerStartDistance'] == 340.2
    assert q_result['nextRunnerLegStartDay'] == 10  # 候補の 11 が実行前 10 に戻る
    assert q_result['runner'] == '上'            # 実行前 leg=4 のランナー名
    assert q_result['group_id'] == 0             # finishDay=None → 走行中グループ
    # 非 quarantine チームは候補値のまま
    other = next(r for r in new_all if r['id'] == 1)
    assert other['totalDistance'] == 339.1
    assert other['newCurrentLeg'] == 3

    # individual_results: quarantine チームの選手は実行前値 (今日の記録なし)
    assert individual_results["宇目"]["totalDistance"] == 66.0
    assert len(individual_results["宇目"]["records"]) == 2
    assert all(r["day"] != 9 for r in individual_results["宇目"]["records"])
    assert individual_results["美濃"]["totalDistance"] == 121.0

    # state: quarantine チームは実行前値
    q_state = next(s for s in new_state if s['id'] == 12)
    assert q_state["totalDistance"] == 340.2
    assert q_state["currentLeg"] == 4
    assert q_state["overallRank"] == 9
    assert q_state["finishDay"] is None
    assert q_state["currentRunnerStartDistance"] == 340.2
    assert q_state["currentRunnerLegStartDay"] == 10

    # save_ekiden_state が読むフィールド (id/name/totalDistance/currentLeg/overallRank/
    # finishDay/currentRunnerStartDistance/currentRunnerLegStartDay) が全て揃っている
    for field in ('id', 'name', 'totalDistance', 'newCurrentLeg', 'overallRank',
                  'finishDay', 'nextRunnerStartDistance', 'nextRunnerLegStartDay'):
        assert field in q_result, f'quarantine 復元後の all_results に {field} がありません'
    # save_realtime_report / calculate_and_save_runner_locations が読むフィールドも揃っている
    for field in ('runner', 'currentLegNumber', 'todayDistance', 'todayRank',
                  'previousRank', 'rawTempResult', 'currentRunnerStartDistance',
                  'currentRunnerLegStartDay', 'is_shadow_confederation'):
        assert field in q_result, f'quarantine 復元後の all_results に {field} がありません'
    # todayRank は None (日間順位未確定)、is_shadow_confederation は False
    assert q_result['todayRank'] is None
    assert q_result['is_shadow_confederation'] is False


def test_apply_quarantine_noop_without_quarantine():
    """quarantine 対象が無ければ何も変更しない"""
    import generate_report
    all_results = [{"id": 1, "totalDistance": 340.2, "newCurrentLeg": 4, "todayDistance": 37.7}]
    individual_results = {"美濃": {"teamId": 1, "totalDistance": 121.0, "records": []}}
    current_state = [{"id": 1, "totalDistance": 302.5, "currentLeg": 3}]
    new_all, new_state = generate_report.apply_quarantine(
        all_results, individual_results, current_state, [],
        current_state, individual_results,
    )
    assert new_all == all_results
    assert new_state == current_state


# ============================================================
# Blocker 1: commit 処理の SystemExit はバックアップ復元しない構造
# ============================================================

def test_commit_section_has_systemexit_guard():
    """commit 処理の except 節に SystemExit ガードがあり、degraded 継続時に復元しない"""
    src = (PROJECT_ROOT / 'scripts' / 'generate_report.py').read_text(encoding='utf-8')
    # SystemExit は復元せず re-raise するハンドラが存在する
    assert 'except SystemExit:' in src
    assert 'raise' in src.split('except SystemExit:')[1].split('except BaseException:')[0]
    # BaseException ハンドラは SystemExit 以外のみ復元
    assert 'except BaseException:' in src
    # degraded 継続 (exit 2) はバックアップ削除後に exit する (復元しない)
    assert 'sys.exit(2)' in src


def test_restore_backups_moves_bak_files():
    """restore_backups は .bak を元ファイルへ戻す"""
    import generate_report
    tmpdir = Path(tempfile.mkdtemp(prefix='rb_'))
    try:
        orig = tmpdir / 'state.json'
        bak = tmpdir / 'state.json.bak'
        orig.write_text('new', encoding='utf-8')
        bak.write_text('old', encoding='utf-8')
        generate_report.restore_backups({str(orig): str(bak)})
        assert orig.read_text(encoding='utf-8') == 'old'
        assert not bak.exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# commit_daily.sh: 構造確認
# ============================================================

def test_commit_daily_sh_uses_best_effort():
    sh = (PROJECT_ROOT / 'commit_daily.sh').read_text(encoding='utf-8')
    assert '--commit --best-effort' in sh or '--best-effort' in sh
    assert 'COMMIT_RC' in sh
    assert 'DEGRADED' in sh


def test_commit_daily_sh_degraded_commit_message():
    sh = (PROJECT_ROOT / 'commit_daily.sh').read_text(encoding='utf-8')
    assert '[degraded]' in sh


def test_commit_daily_sh_stages_commit_status():
    sh = (PROJECT_ROOT / 'commit_daily.sh').read_text(encoding='utf-8')
    assert 'data/commit_status.json' in sh
    # Blocker 3: fetch_status.json も stage 対象
    assert 'data/fetch_status.json' in sh


# ============================================================
# save_daily_snapshot.py: manifest への commitStatus 記録
# ============================================================

def test_save_daily_snapshot_manifest_records_commit_status():
    import save_daily_snapshot
    tmpdir = Path(tempfile.mkdtemp(prefix='snap_cs_'))
    try:
        source = tmpdir / 'source'
        source.mkdir()
        (source / 'realtime_report.json').write_text(
            json.dumps({"updateTime": "2026/07/31 23:59", "raceDay": 9}), encoding='utf-8')
        (source / 'commit_status.json').write_text(
            json.dumps({"status": "degraded", "validationSeverity": 2}), encoding='utf-8')
        output = tmpdir / 'out'
        dest, manifest = save_daily_snapshot.save_daily_snapshot(source, output)
        assert manifest['commitStatus'] == 'degraded'
        assert manifest['validationSeverity'] == 2
        assert (dest / 'commit_status.json').exists()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# update_all_records.py: fetch_status.json のアクティブ欠損記録
# ============================================================

def test_update_all_records_fetch_status_marks_active_missing(monkeypatch):
    """取得失敗選手が fetch_status.json に active フラグ付きで記録される"""
    import update_all_records as uar

    tmpdir = Path(tempfile.mkdtemp(prefix='fetch_status_'))
    try:
        # データファイルを差し替え
        monkeypatch.setattr(uar, 'CONFIG_DIR', tmpdir)
        monkeypatch.setattr(uar, 'DATA_DIR', tmpdir)
        monkeypatch.setattr(uar, 'AMEDAS_STATIONS_FILE', tmpdir / 'amedas_stations.json')
        monkeypatch.setattr(uar, 'EKIDEN_DATA_FILE', tmpdir / 'ekiden_data.json')
        monkeypatch.setattr(uar, 'DAILY_TEMP_FILE', tmpdir / 'daily_temperatures.json')
        monkeypatch.setattr(uar, 'EKIDEN_STATE_FILE', tmpdir / 'ekiden_state.json')
        monkeypatch.setattr(uar, 'INTRAMURAL_RANKINGS_FILE', tmpdir / 'intramural_rankings.json')

        (tmpdir / 'amedas_stations.json').write_text(json.dumps([
            {"name": "美濃", "code": "001", "pref_code": "21"},
            {"name": "八幡", "code": "002", "pref_code": "21"},
        ]), encoding='utf-8')
        (tmpdir / 'ekiden_data.json').write_text(json.dumps({
            "teams": [
                {"id": 1, "name": "名古屋大学",
                 "runners": [{"name": "美濃"}],
                 "substitutes": [{"name": "八幡"}],
                 "substituted_out": []},
            ]
        }), encoding='utf-8')
        (tmpdir / 'ekiden_state.json').write_text(json.dumps([
            {"id": 1, "name": "名古屋大学", "totalDistance": 121.0, "currentLeg": 2},
        ]), encoding='utf-8')

        calls = {'n': 0}

        def fake_fetch(pref, code):
            calls['n'] += 1
            # 美濃は成功、八幡は失敗させる
            return {'temperature': 40.8, 'error': None} if code == '001' else {'temperature': None, 'error': '通信エラー'}

        monkeypatch.setattr(uar, 'fetch_max_temperature', fake_fetch)
        monkeypatch.setattr(uar.time, 'sleep', lambda s: None)

        uar.update_all_records()

        fetch_status = json.loads((tmpdir / 'fetch_status.json').read_text(encoding='utf-8'))
        assert fetch_status['fetched'] == 1
        assert fetch_status['total'] == 2
        missing = {m['runner_name']: m for m in fetch_status['missing']}
        assert missing['八幡']['active'] is False  # substitutes は非アクティブ
        assert missing['八幡']['reason'] == '通信エラー'
        # アクティブ選手の欠損も記録できる (美濃は成功なので欠損なし)
        assert '美濃' not in missing
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_update_all_records_fetch_status_active_runner_missing(monkeypatch):
    """正規 (active) 選手の取得失敗が active=True で記録される"""
    import update_all_records as uar

    tmpdir = Path(tempfile.mkdtemp(prefix='fetch_status_act_'))
    try:
        monkeypatch.setattr(uar, 'CONFIG_DIR', tmpdir)
        monkeypatch.setattr(uar, 'DATA_DIR', tmpdir)
        monkeypatch.setattr(uar, 'AMEDAS_STATIONS_FILE', tmpdir / 'amedas_stations.json')
        monkeypatch.setattr(uar, 'EKIDEN_DATA_FILE', tmpdir / 'ekiden_data.json')
        monkeypatch.setattr(uar, 'DAILY_TEMP_FILE', tmpdir / 'daily_temperatures.json')
        monkeypatch.setattr(uar, 'EKIDEN_STATE_FILE', tmpdir / 'ekiden_state.json')
        monkeypatch.setattr(uar, 'INTRAMURAL_RANKINGS_FILE', tmpdir / 'intramural_rankings.json')

        (tmpdir / 'amedas_stations.json').write_text(json.dumps([
            {"name": "美濃", "code": "001", "pref_code": "21"},
        ]), encoding='utf-8')
        (tmpdir / 'ekiden_data.json').write_text(json.dumps({
            "teams": [
                {"id": 1, "name": "名古屋大学",
                 "runners": [{"name": "美濃"}],
                 "substitutes": [],
                 "substituted_out": []},
            ]
        }), encoding='utf-8')
        (tmpdir / 'ekiden_state.json').write_text(json.dumps([
            {"id": 1, "name": "名古屋大学", "totalDistance": 121.0, "currentLeg": 2},
        ]), encoding='utf-8')

        monkeypatch.setattr(uar, 'fetch_max_temperature',
                            lambda pref, code: {'temperature': None, 'error': 'サイト障害'})
        monkeypatch.setattr(uar.time, 'sleep', lambda s: None)

        uar.update_all_records()

        fetch_status = json.loads((tmpdir / 'fetch_status.json').read_text(encoding='utf-8'))
        missing = {m['runner_name']: m for m in fetch_status['missing']}
        assert missing['美濃']['active'] is True  # 正規走者は active
        assert fetch_status['fetched'] == 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
