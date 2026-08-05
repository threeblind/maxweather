"""
KMLコース上のマップ座標を設定距離（leg_boundaries）へ区間別に補正するテスト。

修正内容 (scripts/generate_report.py):
- _build_map_distance_calibration: KMLコース距離→設定距離の補正アンカーを構築（異常時None）
- _get_calibrated_runner_position: 設定距離をKML上の位置へ変換して座標を返す
- calculate_and_save_runner_locations / save_snapshot: 共通ヘルパーを利用（従来方式はフォールバック）

テスト方針: 合成の小さなcourse_path（子午線コース）で純粋なユニットテストを行い、
実データ（config/course_path.json + relay_points.json）に依存する検証は別テストに分離する。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_report
from generate_report import (
    _build_map_distance_calibration,
    _get_calibrated_runner_position,
)

# --- 合成コース・中継所の定義 ---
# 子午線コース: 北から南へ lat を 0.005° ずつ下げる（約0.556km/点）
# 251点: lat 35.0 → 33.75（全長 約139km）
START_LAT, STEP_DEG, N_POINTS = 35.0, 0.005, 251


def _meridian_course(n_points=N_POINTS, with_duplicates=False):
    pts = [{"lat": START_LAT - STEP_DEG * i, "lon": 139.0} for i in range(n_points)]
    if with_duplicates:
        # ゼロ長セグメント: 10点ごとに同一座標を挿入
        out = []
        for i, p in enumerate(pts):
            out.append(p)
            if i % 10 == 0 and i > 0:
                out.append(dict(p))
        return out
    return pts


# 中継所はcourse_path頂点(lat 34.5 / 34.0)からわずかにずらす(約11〜15m)
RELAY_1 = {"leg": 1, "name": "第一中継所", "target_distance_km": 50.0,
           "latitude": 34.5001, "longitude": 139.0001}
RELAY_2 = {"leg": 2, "name": "第二中継所", "target_distance_km": 100.0,
           "latitude": 34.0001, "longitude": 139.0001}
BOUNDARIES = [50.0, 100.0, 130.0]  # 中継所2つ+ゴール → アンカー数一致


def _build():
    return _build_map_distance_calibration(_meridian_course(), [RELAY_1, RELAY_2], BOUNDARIES)


# --- 必須項目1: 設定境界と実KML距離が異なるケースで、境界値が正確なanchor座標を返す ---
def test_boundary_returns_exact_anchor_coordinates():
    cal = _build()
    assert cal is not None
    # 設定境界50km→第一中継所の正確な座標（course_path頂点ではない）
    lat, lon = _get_calibrated_runner_position(50.0, _meridian_course(), cal)
    assert (lat, lon) == (RELAY_1["latitude"], RELAY_1["longitude"])
    # 100km→第二中継所
    lat, lon = _get_calibrated_runner_position(100.0, _meridian_course(), cal)
    assert (lat, lon) == (RELAY_2["latitude"], RELAY_2["longitude"])


# --- 必須項目2: target=522相当の境界値が第五中継所座標を返す（実データ） ---
def test_real_data_target_522_returns_fifth_relay_coordinate():
    course = json.load(open(PROJECT_ROOT / "config/course_path.json"))
    relays = json.load(open(PROJECT_ROOT / "config/relay_points.json"))
    boundaries = [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055]
    cal = _build_map_distance_calibration(course, relays, boundaries)
    assert cal is not None
    lat, lon = _get_calibrated_runner_position(522.0, course, cal)
    assert (lat, lon) == (34.763415, 135.594278)  # 第五中継所


# --- 必須項目3: 境界直前/直後がそれぞれ中継所の前後になる ---
def test_just_before_and_after_boundary():
    cal = _build()
    course = _meridian_course()
    # 直前(49.9)は第一中継所より北(前)
    lat_before, _ = _get_calibrated_runner_position(49.9, course, cal)
    assert lat_before > RELAY_1["latitude"]
    # 直後(50.1)は第一中継所より南(後)
    lat_after, _ = _get_calibrated_runner_position(50.1, course, cal)
    assert lat_after < RELAY_1["latitude"]


# --- 必須項目4: 区間内は設定距離の比率でactual距離を補間する（KML距離をそのまま使わない） ---
def test_within_leg_interpolation_uses_configured_ratio():
    cal = _build()
    course = _meridian_course()
    # 25km = 第1区間(0〜50)の中間 → 設定比率0.5 → KML上の第一中継所(actual≈55.6km)の中間 ≈ lat 34.75
    lat, _ = _get_calibrated_runner_position(25.0, course, cal)
    assert abs(lat - 34.75) < 0.005, f"calibrated lat={lat}"
    # KML距離25kmをそのまま速報距離として扱う場合(lat≈34.775)とは明確に異なる
    assert abs(lat - 34.775) > 0.01


# --- 必須項目5: 0以下はスタート、最終境界以上はゴール ---
def test_bounds_start_and_goal():
    cal = _build()
    course = _meridian_course()
    start = (course[0]["lat"], course[0]["lon"])
    goal = (course[-1]["lat"], course[-1]["lon"])
    assert _get_calibrated_runner_position(0.0, course, cal) == start
    assert _get_calibrated_runner_position(-5.0, course, cal) == start
    assert _get_calibrated_runner_position(130.0, course, cal) == goal
    assert _get_calibrated_runner_position(500.0, course, cal) == goal


# --- 必須項目6: ゼロ長セグメントを含むcourse_pathでも動作する ---
def test_zero_length_segments_are_skipped():
    course = _meridian_course(with_duplicates=True)
    cal = _build_map_distance_calibration(course, [RELAY_1, RELAY_2], BOUNDARIES)
    assert cal is not None
    lat, lon = _get_calibrated_runner_position(25.0, course, cal)
    assert abs(lat - 34.75) < 0.01
    assert lon == 139.0
    # 境界値も正しくアンカー座標を返す
    lat, lon = _get_calibrated_runner_position(50.0, course, cal)
    assert (lat, lon) == (RELAY_1["latitude"], RELAY_1["longitude"])


# --- 必須項目7: 異常データでcalibrationが無効になり、既存方式へフォールバックできる ---
def test_calibration_invalid_on_anchor_count_mismatch():
    course = _meridian_course()
    # 中継所2つに対して境界3つ以外 → アンカー数不一致
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2], [50.0, 100.0]) is None


def test_calibration_invalid_on_non_monotonic_boundaries():
    course = _meridian_course()
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2], [100.0, 50.0, 130.0]) is None


def test_calibration_invalid_on_reversed_relay_order():
    # leg順は1,2だが物理的に逆順（第一中継所が南、第二が北）→ アンカーindexが単調増加でない
    course = _meridian_course()
    reversed_relays = [
        {"leg": 1, "name": "第一中継所", "target_distance_km": 50.0,
         "latitude": 34.0001, "longitude": 139.0001},
        {"leg": 2, "name": "第二中継所", "target_distance_km": 100.0,
         "latitude": 34.5001, "longitude": 139.0001},
    ]
    assert _build_map_distance_calibration(course, reversed_relays, BOUNDARIES) is None


def test_calibration_invalid_on_empty_course_or_relays():
    assert _build_map_distance_calibration([], [RELAY_1, RELAY_2], BOUNDARIES) is None
    assert _build_map_distance_calibration([{"lat": 1.0, "lon": 1.0}], [RELAY_1, RELAY_2], BOUNDARIES) is None
    assert _build_map_distance_calibration(_meridian_course(), [], BOUNDARIES) is None
    assert _build_map_distance_calibration(_meridian_course(), None, BOUNDARIES) is None


# --- 必須項目8: calculate_and_save_runner_locations() が元のtotalDistanceを保持する ---
def test_calculate_and_save_preserves_total_distance(tmp_path):
    _patch_file_paths(tmp_path, valid_relay=True)
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": 25.0, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
        {"id": 2, "name": "サンプル大学", "overallRank": 2, "runner": "走者B",
         "totalDistance": 50.0, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
    ]
    generate_report.all_teams_data = [
        {"id": 1, "name": "テスト大学", "short_name": "テス大"},
        {"id": 2, "name": "サンプル大学", "short_name": "サン大"},
    ]
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 2
    by_name = {e["team_name"]: e for e in output}
    assert by_name["テスト大学"]["total_distance_km"] == 25.0
    assert by_name["サンプル大学"]["total_distance_km"] == 50.0
    # 境界値50.0のチームは第一中継所の正確な座標にsnapされる
    assert by_name["サンプル大学"]["latitude"] == RELAY_1["latitude"]
    assert by_name["サンプル大学"]["longitude"] == RELAY_1["longitude"]
    # 既存フィールドが保持される
    assert by_name["テスト大学"]["rank"] == 1
    assert by_name["テスト大学"]["runner_name"] == "走者A"
    assert by_name["テスト大学"]["current_leg"] == 2
    assert by_name["テスト大学"]["is_shadow_confederation"] is False


def test_calculate_and_save_falls_back_without_relay_points(tmp_path):
    """relay_pointsが読めない場合は従来方式へフォールバックし、出力は停止しない。"""
    _patch_file_paths(tmp_path, valid_relay=False)
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": 25.0, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
    ]
    generate_report.all_teams_data = [{"id": 1, "name": "テスト大学", "short_name": "テス大"}]
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 1
    assert output[0]["total_distance_km"] == 25.0


# --- 必須項目9: save_snapshot() も同じ補正ヘルパーを使う ---
def test_save_snapshot_uses_calibration_helper(tmp_path, monkeypatch):
    _patch_file_paths(tmp_path, valid_relay=True)
    generate_report.SNAPSHOT_DIR = tmp_path / "snapshots"
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [
        {"id": 1, "name": "テスト大学", "short_name": "テス大", "runners": [{"name": "走者A"}, {"name": "走者B"}]},
    ]

    original = generate_report._get_calibrated_runner_position
    calls = {"n": 0}

    def spy(target, course, cal):
        calls["n"] += 1
        return original(target, course, cal)

    monkeypatch.setattr(generate_report, "_get_calibrated_runner_position", spy)

    results = [{
        "id": 1, "name": "テスト大学", "runner": "走者A", "totalDistance": 50.0,
        "currentLegNumber": 1, "newCurrentLeg": 2, "todayDistance": 50.0,
        "todayRank": 1, "overallRank": 1, "previousRank": 2, "finishDay": None,
        "rawTempResult": {"error": None}, "is_shadow_confederation": False,
        "currentRunnerStartDistance": 0.0, "currentRunnerLegStartDay": 13,
    }]
    generate_report.save_snapshot(results, 13, "コメント", "2026-08-05T00:00:00+09:00")
    assert calls["n"] == 1  # 共通ヘルパーが呼ばれている

    snapshot_file = next((tmp_path / "snapshots").glob("realtime_report_*.json"))
    data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    loc = data["runnerLocations"][0]
    assert loc["distance"] == 50.0
    assert loc["latitude"] == RELAY_1["latitude"]  # 補正後の座標
    assert loc["longitude"] == RELAY_1["longitude"]
    assert loc["current_leg"] == 1


# --- 必須項目10: determine_leg_from_total_distance の回帰確認 ---
def test_determine_leg_from_total_distance_regression():
    boundaries = [100, 210, 310, 399, 522, 639, 735, 841, 942, 1055]
    assert generate_report.determine_leg_from_total_distance(0, boundaries) == 1
    assert generate_report.determine_leg_from_total_distance(100, boundaries) == 2
    assert generate_report.determine_leg_from_total_distance(521.9, boundaries) == 5
    assert generate_report.determine_leg_from_total_distance(522, boundaries) == 6
    assert generate_report.determine_leg_from_total_distance(1055, boundaries) == 11


# --- レビュー修正1: 探索中心は設定距離の正本(leg_boundaries)を使う ---
def test_calibration_works_without_target_distance_km():
    """relay_points の target_distance_km が欠落していても正しいアンカーを選ぶ。"""
    course = _meridian_course()
    relays = [
        {"leg": 1, "name": "第一中継所", "latitude": 34.5001, "longitude": 139.0001},
        {"leg": 2, "name": "第二中継所", "latitude": 34.0001, "longitude": 139.0001},
    ]
    cal = _build_map_distance_calibration(course, relays, BOUNDARIES)
    assert cal is not None
    assert cal["anchor_indices"] == [0, 100, 200, 250]
    lat, lon = _get_calibrated_runner_position(50.0, course, cal)
    assert (lat, lon) == (34.5001, 139.0001)


def test_calibration_works_with_wrong_target_distance_km():
    """target_distance_km が意図的に誤っていても設定境界を正本に正しいアンカーを選ぶ。"""
    course = _meridian_course()
    relays = [
        {"leg": 1, "name": "第一中継所", "target_distance_km": 9999.0,
         "latitude": 34.5001, "longitude": 139.0001},
        {"leg": 2, "name": "第二中継所", "target_distance_km": -1.0,
         "latitude": 34.0001, "longitude": 139.0001},
    ]
    cal = _build_map_distance_calibration(course, relays, BOUNDARIES)
    assert cal is not None
    assert cal["anchor_indices"] == [0, 100, 200, 250]
    lat, lon = _get_calibrated_runner_position(50.0, course, cal)
    assert (lat, lon) == (34.5001, 139.0001)


# --- レビュー修正2: 入力検証（欠落・不正座標で落とさずフォールバック） ---
def test_calibration_invalid_on_course_point_missing_latlon():
    course = _meridian_course()
    course[50] = {"lat": 34.75}  # lon 欠落
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2], BOUNDARIES) is None


def test_calibration_invalid_on_non_numeric_course_coords():
    course = _meridian_course()
    course[50] = {"lat": "abc", "lon": 139.0}
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2], BOUNDARIES) is None


def test_calibration_invalid_on_relay_missing_latlon():
    course = _meridian_course()
    relays = [
        {"leg": 1, "name": "第一中継所", "target_distance_km": 50.0, "longitude": 139.0001},
        {"leg": 2, "name": "第二中継所", "target_distance_km": 100.0,
         "latitude": 34.0001, "longitude": 139.0001},
    ]
    assert _build_map_distance_calibration(course, relays, BOUNDARIES) is None


def test_calibration_invalid_on_non_numeric_relay_coords():
    course = _meridian_course()
    relays = [
        {"leg": 1, "name": "第一中継所", "target_distance_km": 50.0,
         "latitude": "34.5001", "longitude": "139.0001"},
        {"leg": 2, "name": "第二中継所", "target_distance_km": 100.0,
         "latitude": "不正", "longitude": 139.0001},
    ]
    assert _build_map_distance_calibration(course, relays, BOUNDARIES) is None


def test_calibration_accepts_numeric_string_relay_coords():
    """数値文字列の座標は正常に処理される（既存正常データの挙動を変えない）。"""
    course = _meridian_course()
    relays = [
        {"leg": 1, "name": "第一中継所", "target_distance_km": 50.0,
         "latitude": "34.5001", "longitude": "139.0001"},
        {"leg": 2, "name": "第二中継所", "target_distance_km": 100.0,
         "latitude": "34.0001", "longitude": "139.0001"},
    ]
    cal = _build_map_distance_calibration(course, relays, BOUNDARIES)
    assert cal is not None
    lat, lon = _get_calibrated_runner_position(50.0, course, cal)
    assert (lat, lon) == (34.5001, 139.0001)


# --- 敵対的検証: 非有限値（NaN/Inf） ---
def test_calibration_invalid_on_nan_boundary():
    course = _meridian_course()
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2],
                                           [50.0, float('nan'), 130.0]) is None


def test_calibration_invalid_on_inf_boundary():
    course = _meridian_course()
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2],
                                           [50.0, float('inf'), 130.0]) is None
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2],
                                           [50.0, float('-inf'), 130.0]) is None


def test_calibration_invalid_on_non_finite_relay_coords():
    course = _meridian_course()
    relays_nan = [
        {"leg": 1, "name": "第一中継所", "latitude": float('nan'), "longitude": 139.0001},
        {"leg": 2, "name": "第二中継所", "latitude": 34.0001, "longitude": 139.0001},
    ]
    assert _build_map_distance_calibration(course, relays_nan, BOUNDARIES) is None
    relays_inf = [
        {"leg": 1, "name": "第一中継所", "latitude": 34.5001, "longitude": float('inf')},
        {"leg": 2, "name": "第二中継所", "latitude": 34.0001, "longitude": 139.0001},
    ]
    assert _build_map_distance_calibration(course, relays_inf, BOUNDARIES) is None


def test_calibration_invalid_on_out_of_range_coords():
    course = _meridian_course()
    course[10] = {"lat": 95.0, "lon": 139.0}  # 緯度範囲外
    assert _build_map_distance_calibration(course, [RELAY_1, RELAY_2], BOUNDARIES) is None
    course2 = _meridian_course()
    course2[10] = {"lat": 34.9, "lon": 200.0}  # 経度範囲外
    assert _build_map_distance_calibration(course2, [RELAY_1, RELAY_2], BOUNDARIES) is None


def test_calibration_invalid_on_non_dict_relay_elements():
    """relay_points の要素が文字列/null でも AttributeError を出さず None。"""
    course = _meridian_course()
    assert _build_map_distance_calibration(course, ["hoge", None], BOUNDARIES) is None
    assert _build_map_distance_calibration(course, [RELAY_1, None], BOUNDARIES) is None


def test_calibration_with_numeric_string_course_path():
    """course_path が数値文字列でも calibration 有効かつ補間が例外なく数値座標を返す。"""
    course = _meridian_course()
    str_course = [{"lat": str(p["lat"]), "lon": str(p["lon"])} for p in course]
    cal = _build_map_distance_calibration(str_course, [RELAY_1, RELAY_2], BOUNDARIES)
    assert cal is not None
    lat, lon = _get_calibrated_runner_position(25.0, str_course, cal)
    assert isinstance(lat, float) and isinstance(lon, float)
    assert abs(lat - 34.75) < 0.01
    # 境界値も例外なく正確なアンカー座標を返す
    lat, lon = _get_calibrated_runner_position(50.0, str_course, cal)
    assert (lat, lon) == (34.5001, 139.0001)


def test_get_position_with_non_finite_target_returns_start():
    """NaN/±Inf target はスタート座標(0km相当)へ統一し、意図せずゴールへ飛ばさない。"""
    cal = _build()
    course = _meridian_course()
    start = (course[0]["lat"], course[0]["lon"])
    goal = (course[-1]["lat"], course[-1]["lon"])
    for bad in (float('nan'), float('inf'), float('-inf')):
        lat, lon = _get_calibrated_runner_position(bad, course, cal)
        assert (lat, lon) == start, f"target={bad} はスタートへ"
        assert (lat, lon) != goal


def test_calculate_and_save_survives_abnormal_inputs(tmp_path):
    """入力異常（非有限target・不正boundaries）でも出力処理が停止しない。"""
    _patch_file_paths(tmp_path, valid_relay=True)
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [
        {"id": 1, "name": "テスト大学", "short_name": "テス大"},
        {"id": 2, "name": "異常大学", "short_name": "異大"},
    ]
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": float('nan'), "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
        {"id": 2, "name": "異常大学", "overallRank": 2, "runner": "走者B",
         "totalDistance": 50.0, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
    ]
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 2
    assert output[1]["total_distance_km"] == 50.0


def test_fallback_path_does_not_raise_on_abnormal_input(tmp_path):
    """フォールバック経路（calibration無効）でも例外が出ず出力される。"""
    _patch_file_paths(tmp_path, valid_relay=False)  # relay_points 不正 → フォールバック
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [{"id": 1, "name": "テスト大学", "short_name": "テス大"}]
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": float('nan'), "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
    ]
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 1


# --- 再レビュー: calibration無効時のフォールバック例外耐性 ---
def test_fallback_continues_with_invalid_course_point(tmp_path):
    """calibration無効+不正course_path(緯度95)+targetが不正点を跨ぐケースでも出力が継続する。"""
    _patch_file_paths(tmp_path, valid_relay=False)  # relay_points 不正 → calibration=None
    course = _meridian_course()
    course[100] = {"lat": 95.0, "lon": 139.0}  # 範囲外の点を途中に挿入
    (tmp_path / "course_path.json").write_text(json.dumps(course), encoding="utf-8")
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [{"id": 1, "name": "テスト大学", "short_name": "テス大"}]
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": 100.0, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False},
    ]
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 1
    assert -90.0 <= output[0]["latitude"] <= 90.0
    assert -180.0 <= output[0]["longitude"] <= 180.0


def test_fallback_non_finite_targets_are_start_equivalent(tmp_path):
    """calibration無効時も NaN/±Inf target はスタート相当(0km)へ統一し+Infをゴールへ流さない。"""
    _patch_file_paths(tmp_path, valid_relay=False)
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [{"id": 1, "name": "テスト大学", "short_name": "テス大"}]
    course = _meridian_course()
    start = (course[0]["lat"], course[0]["lon"])
    teams = [
        {"id": 1, "name": "テスト大学", "overallRank": 1, "runner": "走者A",
         "totalDistance": t, "newCurrentLeg": 2, "currentLegNumber": 1,
         "is_shadow_confederation": False}
        for t in (float('nan'), float('inf'), float('-inf'))
    ]
    generate_report.calculate_and_save_runner_locations(teams)
    output = json.loads((tmp_path / "runner_locations.json").read_text(encoding="utf-8"))
    assert len(output) == 3
    for entry in output:
        assert (entry["latitude"], entry["longitude"]) == start
        assert (entry["latitude"], entry["longitude"]) != (course[-1]["lat"], course[-1]["lon"])


def test_snapshot_fallback_survives_invalid_course(tmp_path):
    """save_snapshot() のフォールバックも不正course_path・非有限targetで停止しない。"""
    _patch_file_paths(tmp_path, valid_relay=False)
    course = _meridian_course()
    course[100] = {"lat": 95.0, "lon": 139.0}
    (tmp_path / "course_path.json").write_text(json.dumps(course), encoding="utf-8")
    generate_report.SNAPSHOT_DIR = tmp_path / "snapshots"
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    generate_report.all_teams_data = [
        {"id": 1, "name": "テスト大学", "short_name": "テス大", "runners": [{"name": "走者A"}]},
    ]
    results = [{
        "id": 1, "name": "テスト大学", "runner": "走者A", "totalDistance": float('nan'),
        "currentLegNumber": 1, "newCurrentLeg": 2, "todayDistance": 0.0,
        "todayRank": 1, "overallRank": 1, "previousRank": 2, "finishDay": None,
        "rawTempResult": {"error": None}, "is_shadow_confederation": False,
        "currentRunnerStartDistance": 0.0, "currentRunnerLegStartDay": 13,
    }]
    generate_report.save_snapshot(results, 13, "コメント", "2026-08-05T00:00:00+09:00")
    snapshot_file = next((tmp_path / "snapshots").glob("realtime_report_*.json"))
    data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert len(data["runnerLocations"]) == 1
    loc = data["runnerLocations"][0]
    assert -90.0 <= loc["latitude"] <= 90.0


def test_fallback_valid_course_matches_legacy_computation(tmp_path):
    """正常なcourse_pathのフォールバックは既存の座標計算と同一。"""
    from geopy.distance import geodesic as _geodesic

    def _legacy_ref(target, course):
        cumulative = 0.0
        lat, lon = course[0]["lat"], course[0]["lon"]
        found = False
        for i in range(1, len(course)):
            p1 = (course[i - 1]["lat"], course[i - 1]["lon"])
            p2 = (course[i]["lat"], course[i]["lon"])
            seg = _geodesic(p1, p2).kilometers
            if seg > 0 and cumulative <= target < cumulative + seg:
                frac = (target - cumulative) / seg
                lat = p1[0] + frac * (p2[0] - p1[0])
                lon = p1[1] + frac * (p2[1] - p1[1])
                found = True
                break
            cumulative += seg
        if not found and target >= cumulative:
            lat, lon = course[-1]["lat"], course[-1]["lon"]
        return (lat, lon)

    _patch_file_paths(tmp_path, valid_relay=False)  # calibration=None → フォールバック
    course = _meridian_course()
    (tmp_path / "course_path.json").write_text(json.dumps(course), encoding="utf-8")
    generate_report.ekiden_data = {"leg_boundaries": BOUNDARIES}
    for target in (-5.0, 0.0, 10.0, 50.0, 100.0, 129.0, 140.0):
        got = generate_report._legacy_runner_position(target, course, BOUNDARIES[-1])
        expected = _legacy_ref(target, course)
        assert abs(got[0] - expected[0]) < 1e-9 and abs(got[1] - expected[1]) < 1e-9, f"target={target}"


# --- ヘルパー ---
def _patch_file_paths(tmp_path, valid_relay=True):
    """generate_report のファイルパスを tmp_path 配下へ差し替える。"""
    generate_report.COURSE_PATH_FILE = tmp_path / "course_path.json"
    (tmp_path / "course_path.json").write_text(
        json.dumps(_meridian_course()), encoding="utf-8")
    generate_report.RELAY_POINTS_FILE = tmp_path / "relay_points.json"
    if valid_relay:
        (tmp_path / "relay_points.json").write_text(
            json.dumps([RELAY_1, RELAY_2]), encoding="utf-8")
    else:
        (tmp_path / "relay_points.json").write_text("{ invalid json", encoding="utf-8")
    generate_report.RUNNER_LOCATIONS_OUTPUT_FILE = tmp_path / "runner_locations.json"
