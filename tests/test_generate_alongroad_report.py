"""
scripts/generate_alongroad_report.py のテスト。
実スナップショットは使わず、一時ファイルを用いる。
"""
import sys
import json
import tempfile
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_alongroad_report import (
    generate_report,
    strip_leg_number,
    get_alongroad_name,
    resolve_race_day,
    ALONGROAD_NAMES,
)


# ============================================================
# テスト用ヘルパー
# ============================================================

def _create_snapshot_dir(date_str, teams_data, ind_data, race_day=None):
    """一時ディレクトリにスナップショットを作成"""
    import generate_alongroad_report as mod

    # raceDay 未指定時はカレンダーから計算
    if race_day is None:
        from datetime import datetime
        sd = datetime.strptime('2026-07-23', '%Y-%m-%d')
        td = datetime.strptime(date_str, '%Y-%m-%d')
        race_day = (td - sd).days + 1

    tmpdir = Path(tempfile.mkdtemp())
    snapshot = tmpdir / date_str
    snapshot.mkdir(parents=True)

    rt = {
        "updateTime": f"{date_str}T23:55:00",
        "raceDay": race_day,
        "teams": teams_data,
    }
    with open(snapshot / 'realtime_report.json', 'w', encoding='utf-8') as f:
        json.dump(rt, f, ensure_ascii=False)

    with open(snapshot / 'individual_results.json', 'w', encoding='utf-8') as f:
        json.dump(ind_data, f, ensure_ascii=False)

    return tmpdir, snapshot


def _run_with_temp_snapshot(date_str, teams_data, ind_data=None):
    """一時スナップショットで generate_report を実行"""
    import generate_alongroad_report as mod

    orig_base = mod.SNAPSHOT_BASE
    tmpdir, snapshot = _create_snapshot_dir(date_str, teams_data, ind_data or {})
    try:
        mod.SNAPSHOT_BASE = tmpdir
        result = generate_report(date_str)
        return result
    finally:
        mod.SNAPSHOT_BASE = orig_base
        shutil.rmtree(tmpdir)


# ============================================================
# テスト: 補助関数
# ============================================================

def test_strip_leg_number():
    assert strip_leg_number('2名古屋') == '名古屋'
    assert strip_leg_number('1佐久間') == '佐久間'
    assert strip_leg_number('ゴール') == 'ゴール'
    assert strip_leg_number('美濃') == '美濃'


def test_get_alongroad_name():
    assert get_alongroad_name('名古屋大学', '名大') == '名古屋大'
    assert get_alongroad_name('上武大学', '上武') == '上武'
    assert get_alongroad_name('山梨学院大学', '山学') == '山梨学院'
    assert get_alongroad_name('福岡大学', '福岡') == '福岡'
    assert '名古屋大学' in ALONGROAD_NAMES
    assert '山梨学院大学' in ALONGROAD_NAMES
    assert '広島経済大学' in ALONGROAD_NAMES
    assert '鹿児島大学' in ALONGROAD_NAMES
    assert '立命館大学' in ALONGROAD_NAMES
    assert '熊本学園大学' in ALONGROAD_NAMES


def test_resolve_race_day():
    day = resolve_race_day('2026-07-23')
    assert day == 1, f'expected 1 got {day}'
    day = resolve_race_day('2026-07-24')
    assert day == 2, f'expected 2 got {day}'
    day = resolve_race_day('2026-07-27')
    assert day == 5, f'expected 5 got {day}'


# ============================================================
# テスト: generate_report
# ============================================================

def test_normal_18_teams():
    """正常18校、overallRank順、shadow除外"""
    teams = []
    for i in range(18):
        teams.append({
            "id": i + 1,
            "name": f"大学{i+1}",
            "short_name": f"短{i+1}",
            "runner": f"1走者{i+1}",
            "todayDistance": 35.0 + i * 0.5,
            "todayRank": i + 1,
            "totalDistance": 100.0 + i * 10,
            "overallRank": i + 1,
            "previousRank": i + 2,
            "nextRunner": f"次{i+1}",
        })
    # shadow 追加
    teams.append({
        "id": 99, "name": "シャドー", "short_name": "影",
        "runner": "1影走者", "todayDistance": 99.0,
        "overallRank": 19, "is_shadow_confederation": True,
    })
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '大学' in result
    assert '【' in result and '日目　結果】' in result
    assert 'シャドー' not in result
    assert '影' not in result
    assert result.count('\n') > 20


def test_rank10_11_separator():
    """10位と11位の間に罫線"""
    teams = []
    for i in range(18):
        teams.append({
            "id": i + 1, "name": f"大学{i+1}", "short_name": f"短{i+1}",
            "runner": f"1走者{i+1}", "todayDistance": 35.0,
            "todayRank": i + 1, "totalDistance": 100.0,
            "overallRank": i + 1, "previousRank": i + 1,
            "nextRunner": "",
        })
    result = _run_with_temp_snapshot('2026-07-27', teams)
    lines = result.split('\n')
    # ヘッダ区切り（1本目）+ 10位と11位の間（2本目）
    sep_count = sum(1 for l in lines if l.strip() == '-' * 52)
    assert sep_count == 2, f'罫線数: {sep_count}（ヘッダ+10-11間）'
    # 10位の行の後ろにある
    rank10_found = False
    for i, line in enumerate(lines):
        if '10(' in line or ('10 ' in line and '/10' not in line):
            rank10_found = True
            assert lines[i + 1].strip() == '-' * 52, f'10位の次の行が罫線ではない: {lines[i+1]}'
            break
    assert rank10_found, '10位の行が見つかりません'


def test_today_distance_2digits():
    """順位2桁と前日順位"""
    teams = [{
        "id": 1, "name": "テスト大学", "short_name": "テスト",
        "runner": "1選手A", "todayDistance": 35.5,
        "todayRank": 12, "totalDistance": 150.0,
        "overallRank": 12, "previousRank": 10,
        "nextRunner": "",
    }]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    # 02d: overall=12 → '12', prev=10 → '10'
    assert '12(10)' in result, f'02d format: {result}'
    assert '35.5' in result


def test_today_distance_fallback():
    """todayDistance=0 の場合、individual_results から当日値を補完"""
    teams = [{
        "id": 1, "name": "テスト大学", "short_name": "テスト",
        "runner": "1太郎", "todayDistance": 0,
        "todayRank": 1, "totalDistance": 120.0,
        "overallRank": 1, "previousRank": 1,
        "nextRunner": "",
    }]
    ind = {
        "太郎": {"records": [
            {"day": 5, "leg": 1, "distance": 33.7},
        ]}
    }
    result = _run_with_temp_snapshot('2026-07-27', teams, ind)
    assert '33.7' in result, f'補完失敗: {result}'


def test_today_distance_fallback_not_found():
    """補完不能（individual_results に該当日なし）は --"""
    teams = [{
        "id": 1, "name": "テスト大学", "short_name": "テスト",
        "runner": "1太郎", "todayDistance": 0,
        "todayRank": 1, "totalDistance": 100.0,
        "overallRank": 1, "previousRank": 1,
        "nextRunner": "",
    }]
    ind = {}  # 該当なし
    result = _run_with_temp_snapshot('2026-07-27', teams, ind)
    assert '--' in result, f'補完不能マークなし: {result}'


def test_snapshot_not_found():
    """snapshot 不存在 → エラーメッセージ"""
    import generate_alongroad_report as mod
    orig = mod.SNAPSHOT_BASE
    try:
        mod.SNAPSHOT_BASE = Path('/nonexistent')
        result = generate_report('2026-07-27')
        assert 'エラー' in result
    finally:
        mod.SNAPSHOT_BASE = orig


def test_shadow_excluded():
    """shadow チームは除外"""
    teams = [
        {"id": 1, "name": "名古屋大学", "short_name": "名大",
         "runner": "1美濃", "todayDistance": 35.0, "todayRank": 1,
         "totalDistance": 100.0, "overallRank": 1, "previousRank": 1,
         "nextRunner": ""},
        {"id": 99, "name": "シャドー", "short_name": "影",
         "runner": "1影", "todayDistance": 99.0, "overallRank": 2,
         "is_shadow_confederation": True},
    ]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '名古屋大' in result, f'shadow除外: {result}'
    assert 'シャドー' not in result


def test_heading_format():
    """見出しが全角『７月２７日　５日目　結果』形式"""
    teams = [{"id": 1, "name": "名古屋大学", "short_name": "名大",
              "runner": "1美濃", "todayDistance": 30.0, "todayRank": 1,
              "totalDistance": 100.0, "overallRank": 1, "previousRank": 1,
              "nextRunner": ""}]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '７月２７日　５日目' in result, f'heading: {result[:100]}'
    assert '速報' not in result


def test_race_day_from_snapshot():
    """snapshot 内の raceDay を正本とする"""
    teams = [{"id": 1, "name": "名古屋大学", "short_name": "名大",
              "runner": "1美濃", "todayDistance": 35.0, "todayRank": 1,
              "totalDistance": 100.0, "overallRank": 1, "previousRank": 1,
              "nextRunner": ""}]
    # raceDay=4 のスナップショット（2026-07-27 ディレクトリだが中身は4日目）
    import generate_alongroad_report as mod
    orig_base = mod.SNAPSHOT_BASE
    tmpdir, snapshot = _create_snapshot_dir('2026-07-27', teams, {})
    try:
        # 4日目に設定
        rt_file = snapshot / 'realtime_report.json'
        import json
        with open(rt_file) as f:
            rt = json.load(f)
        rt['raceDay'] = 4
        with open(rt_file, 'w') as f:
            json.dump(rt, f, ensure_ascii=False)
        mod.SNAPSHOT_BASE = tmpdir
        result = mod.generate_report('2026-07-27')
        assert '４日目' in result, f'raceDay=4が反映されていません: {result}'
    finally:
        mod.SNAPSHOT_BASE = orig_base
        import shutil
        shutil.rmtree(tmpdir)


def test_footer_notes():
    """注記行が含まれる"""
    teams = [{"id": 1, "name": "A大", "short_name": "A",
              "runner": "1a", "todayDistance": 30.0, "todayRank": 1,
              "totalDistance": 100.0, "overallRank": 1, "previousRank": 1,
              "nextRunner": ""}]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '※( )内は前日順位' in result
    assert '※選手名の前の数字は担当区' in result


def test_zero_padded_ranks():
    """順位がゼロ埋め2桁（01〜）"""
    teams = [{"id": 1, "name": "名古屋大学", "short_name": "名大",
              "runner": "1美濃", "todayDistance": 35.0, "todayRank": 1,
              "totalDistance": 100.0, "overallRank": 1, "previousRank": 2,
              "nextRunner": ""},
             {"id": 2, "name": "山梨学院大学", "short_name": "山学",
              "runner": "1佐久間", "todayDistance": 34.0, "todayRank": 2,
              "totalDistance": 90.0, "overallRank": 10, "previousRank": 11,
              "nextRunner": ""}]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '01' in result, f'ゼロ埋めなし: {result}'


def test_runner_with_leg_number():
    """走者表示に区番号を含む（例: 2名古屋）"""
    teams = [{"id": 1, "name": "名古屋大学", "short_name": "名大",
              "runner": "2名古屋", "todayDistance": 35.0, "todayRank": 1,
              "totalDistance": 100.0, "overallRank": 1, "previousRank": 1,
              "nextRunner": ""}]
    result = _run_with_temp_snapshot('2026-07-27', teams)
    assert '2名古屋' in result, f'区番号なし: {result}'


# ============================================================

if __name__ == '__main__':
    tests = [
        ("strip_leg_number", test_strip_leg_number),
        ("get_alongroad_name", test_get_alongroad_name),
        ("resolve_race_day", test_resolve_race_day),
        ("normal_18_teams", test_normal_18_teams),
        ("rank10_11_separator", test_rank10_11_separator),
        ("today_distance_2digits", test_today_distance_2digits),
        ("today_distance_fallback", test_today_distance_fallback),
        ("today_distance_fallback_not_found", test_today_distance_fallback_not_found),
        ("snapshot_not_found", test_snapshot_not_found),
        ("shadow_excluded", test_shadow_excluded),
        ("heading_format", test_heading_format),
        ("footer_notes", test_footer_notes),
        ("zero_padded_ranks", test_zero_padded_ranks),
        ("runner_with_leg_number", test_runner_with_leg_number),
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
