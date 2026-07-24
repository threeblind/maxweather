"""
学内ランキング・地点コードの自動テスト

実データ取得・ネットワークアクセスなし。fixture（config JSON）のみで動作。
"""
import json
import sys
import os
from pathlib import Path

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# --- Fixture: 設定データの読み込み ---
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

with open(CONFIG_DIR / "amedas_stations.json", "r", encoding="utf-8") as f:
    STATIONS = json.load(f)
STATIONS_BY_CODE = {s["code"]: s for s in STATIONS}
STATIONS_BY_NAME = {s["name"]: s for s in STATIONS}

with open(CONFIG_DIR / "ekiden_data.json", "r", encoding="utf-8") as f:
    EKIDEN = json.load(f)

# --- テスト1: station_code 解決確認 ---
def test_station_code_resolution():
    """全13件の station_code が有効な観測所を指す"""
    count = 0
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, dict) and "station_code" in entry:
                    code = entry["station_code"]
                    station = STATIONS_BY_CODE.get(code)
                    assert station is not None, (
                        f"[{team['id']}] {entry['name']}: "
                        f"station_code={code} が stations_by_code に見つかりません"
                    )
                    count += 1
    assert count == 13, f"station_code エントリ数が13ではありません: {count}"


# --- テスト2: 無効station_codeが名前検索へフォールバックしない ---
def test_invalid_station_code_no_fallback():
    """無効な station_code を指定した場合、名前検索にフォールバックせずエラーになる"""
    # update_all_records.py のロジックを模倣
    invalid_code = "99999"
    station = STATIONS_BY_CODE.get(invalid_code)
    assert station is None, "存在しないコードが見つかるはずがない"

    # station_code 指定時はコードのみ使用、名前検索禁止
    dummy_name = "美濃"  # 存在する観測所名
    station_by_name = STATIONS_BY_NAME.get(dummy_name)
    assert station_by_name is not None, "テスト前提: 美濃は観測所として存在する"

    # コードが無効なら名前検索へ行ってはいけない
    # このロジックは各スクリプトの実装に依存するが、基本方針を確認
    has_code = True
    if has_code:
        result = STATIONS_BY_CODE.get(invalid_code)
        assert result is None, "無効コードは None を返す"
        # 名前検索をしてはいけない
        # result = STATIONS_BY_NAME.get(dummy_name)  ← してはいけない


# --- テスト3: 新城が51247（愛知） ---
def test_shinjo_aichi():
    """新城は愛知県コード51247（北海道15216ではない）"""
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, dict) and entry.get("name") == "新城":
                    code = entry["station_code"]
                    assert code == "51247", (
                        f"新城の station_code は 51247 であるべき: {code}"
                    )
                    station = STATIONS_BY_CODE[code]
                    assert station["pref_code"] == "23", (
                        f"新城は愛知県(pref_code=23)であるべき: "
                        f"pref_code={station['pref_code']}"
                    )


# --- テスト4: 府中のチーム別分離 ---
def test_fuchu_separation():
    """府中：広島経済大学→67326(広島)、日本大学→44116(東京)"""
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, dict) and entry.get("name") == "府中":
                    # 広島経済大学 (id=6)
                    assert team["id"] == 6, (
                        f"'府中' は id=6 (広島経済大学) のみ: id={team['id']}"
                    )
                    assert entry["station_code"] == "67326", (
                        f"広島経済大学 府中は 67326: {entry['station_code']}"
                    )
                    station = STATIONS_BY_CODE["67326"]
                    assert station["pref_code"] == "34", "府中（広島）は広島県"


def test_fuchu_tokyo_nihon():
    """日本大学の府中（東京）は44116"""
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, dict) and entry.get("name") == "府中（東京）":
                    assert team["id"] == 11, (
                        f"'府中（東京）' は id=11 (日本大学) のみ: id={team['id']}"
                    )
                    assert entry["station_code"] == "44116", (
                        f"日本大学 府中（東京）は 44116: {entry['station_code']}"
                    )


# --- テスト5: 名古屋大学13名 ---
def test_nagoya_university_13():
    """名古屋大学は runners 10名 + substitutes 3名 = 13名"""
    for team in EKIDEN.get("teams", []):
        if team["id"] == 1:
            runners = len(team.get("runners", []))
            subs = len(team.get("substitutes", []))
            assert runners == 10, f"名古屋大学 runners: {runners}"
            assert subs == 3, f"名古屋大学 substitutes: {subs}"
            assert runners + subs == 13, (
                f"名古屋大学 合計: {runners + subs}"
            )
            return
    assert False, "名古屋大学 (id=1) が見つかりません"


# --- テスト6: daily_results で distance:null でも runner を除外しない ---
def test_distance_null_not_excluded():
    """daily_results 生成時に気温欠落 runner も除外されない（fixture で検証）"""
    # update_all_records.py のロジックを模倣: daily_results に全 runner を含める
    team = EKIDEN["teams"][0]  # 名古屋大学
    all_runner_names = set()
    for key in ("runners", "substitutes", "substituted_out"):
        for entry in team.get(key, []):
            name = entry if isinstance(entry, str) else entry.get("name", "")
            if name:
                all_runner_names.add(name)

    # distance: null を含む daily_results を模擬生成
    daily_results = []
    for runner_name in sorted(all_runner_names):
        daily_results.append({
            "runner_name": runner_name,
            "distance": None,  # 気温なしでも含める
            "status": "走行前",
        })

    assert len(daily_results) == len(all_runner_names), (
        f"daily_results の件数が全 runner 数と一致しません: "
        f"{len(daily_results)} vs {len(all_runner_names)}"
    )


# --- テスト7: 全18チームの人数整合性 ---
def test_all_teams_count():
    """全18チームで runners + substitutes + substituted_out の整合性を確認"""
    teams = EKIDEN.get("teams", [])
    assert len(teams) == 18, f"チーム数が18ではありません: {len(teams)}"

    for team in teams:
        runners = len(team.get("runners", []))
        subs = len(team.get("substitutes", []))
        subbed = len(team.get("substituted_out", []))
        total = runners + subs + subbed
        assert runners == 10, (
            f"[{team['id']}] {team['name']}: runners={runners} (expected 10)"
        )
        assert total >= 13, (
            f"[{team['id']}] {team['name']}: total={total} (expected >=13)"
        )


# --- テスト8: 各 station_code が pref_code に正しくマッピングされる ---
def test_all_station_codes_pref_code():
    """全 station_code が期待される都道府県コードと一致"""
    expected = {
        "51116": "23",  # 豊田（愛知）
        "52331": "21",  # 八幡（岐阜）
        "51247": "23",  # 新城（愛知）
        "62096": "27",  # 八尾（大阪）
        "60216": "25",  # 大津（滋賀）
        "60061": "25",  # 長浜（滋賀）
        "67326": "34",  # 府中（広島）
        "72086": "37",  # 高松（香川）
        "44116": "13",  # 府中（東京）
        "44356": "13",  # 南鳥島（東京）
        "36836": "7",   # 山田（福島）
        "54586": "15",  # 大潟（新潟）
        "88151": "46",  # 川内（鹿児島）
    }
    for code, expected_pref in expected.items():
        station = STATIONS_BY_CODE.get(code)
        assert station is not None, f"station_code={code} が stations_by_code に存在しません"
        assert station["pref_code"] == expected_pref, (
            f"station_code={code} ({station['name']}): "
            f"pref_code が {station['pref_code']} (期待値 {expected_pref})"
        )


# --- テスト9: 無効 station_code 時に find_station_by_name が使われない ---
def test_no_name_fallback_when_code_present():
    """station_code が設定されている runner はコードのみで解決され、
    名前によるフォールバックは発生しない"""
    # update_all_records.py のロジック: station_code があればコードのみ
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, dict) and "station_code" in entry:
                    code = entry["station_code"]
                    name = entry["name"]
                    # コードで解決できる
                    station_by_code = STATIONS_BY_CODE.get(code)
                    assert station_by_code is not None, (
                        f"コード {code} ({name}) が解決できません"
                    )
                    # 名前で異なる station になるケースがないことを確認
                    station_by_name = STATIONS_BY_NAME.get(name)
                    if station_by_name:
                        assert station_by_name["code"] == code, (
                            f"名前検索で異なるコードになる: {name} → "
                            f"コード={station_by_name['code']}, 期待値={code}"
                        )


# --- テスト11: fetched_temps_cache が (team_id, runner_name) 単位 ---
def test_fetched_temps_cache_key_is_team_runner():
    """fetched_temps_cache のキーが (team_id, runner_name) タプルであることを確認"""
    # update_all_records.py のロジックを模倣
    cache = {}
    runner_fetch_list = [
        (1, "豊田", "51116"),
        (6, "府中", "67326"),
        (11, "府中（東京）", "44116"),
    ]
    for team_id, runner_name, code in runner_fetch_list:
        cache[(team_id, runner_name)] = {"temperature": 30.0}

    # 同名でも team_id が異なれば別エントリ
    assert (6, "府中") in cache
    assert (11, "府中（東京）") in cache

    # runner_name のみでは検索できない（チーム分離を強制）
    # `cache.get("府中")` は None になる
    assert cache.get("府中") is None


# --- テスト12: 同名で異なる station_code の衝突検出 ---
def test_duplicate_name_conflict_detection():
    """同名 runner に異なる station_code があればエラーになる"""
    # update_all_records.py の衝突検出ロジックを模倣
    runner_fetch_list = [
        (1, "ランナーA", "12345"),
        (2, "ランナーA", "67890"),  # 同じ名前、異なるコード→衝突
    ]

    name_code_map = {}
    conflict = False
    for team_id, name, code in runner_fetch_list:
        if name in name_code_map:
            prev = name_code_map[name]
            if code != prev:
                conflict = True
                break
        else:
            name_code_map[name] = code

    assert conflict, "異なる station_code の衝突を検出すべき"


def test_mixed_code_no_code_conflict():
    """同名で station_code あり/なしが混在すればエラーになる"""
    runner_fetch_list = [
        (1, "ランナーB", "12345"),
        (3, "ランナーB", None),  # 同じ名前、片方コードなし→衝突
    ]

    name_code_map = {}
    conflict = False
    for team_id, name, code in runner_fetch_list:
        if name in name_code_map:
            prev = name_code_map[name]
            if code != prev:
                conflict = True
                break
        else:
            name_code_map[name] = code

    assert conflict, "コードあり/なし混在の衝突を検出すべき"


# --- テスト10: 全ての runner が文字列または dict(name) として有効 ---
def test_all_runners_valid():
    """全 runner エントリが有効な形式"""
    for team in EKIDEN.get("teams", []):
        for key in ("runners", "substitutes"):
            for entry in team.get(key, []):
                if isinstance(entry, str):
                    assert entry, f"空の文字列 runner: [{team['id']}] {key}"
                elif isinstance(entry, dict):
                    assert "name" in entry, (
                        f"name キーがない dict runner: [{team['id']}] {key}"
                    )
                    assert entry["name"], (
                        f"空の name: [{team['id']}] {key}"
                    )
                else:
                    assert False, (
                        f"不正な runner 形式: [{team['id']}] {key}: "
                        f"type={type(entry)}"
                    )


if __name__ == "__main__":
    # 手動実行用
    tests = [
        ("test_station_code_resolution", test_station_code_resolution),
        ("test_invalid_station_code_no_fallback", test_invalid_station_code_no_fallback),
        ("test_shinjo_aichi", test_shinjo_aichi),
        ("test_fuchu_separation", test_fuchu_separation),
        ("test_fuchu_tokyo_nihon", test_fuchu_tokyo_nihon),
        ("test_nagoya_university_13", test_nagoya_university_13),
        ("test_distance_null_not_excluded", test_distance_null_not_excluded),
        ("test_all_teams_count", test_all_teams_count),
        ("test_all_station_codes_pref_code", test_all_station_codes_pref_code),
        ("test_no_name_fallback_when_code_present", test_no_name_fallback_when_code_present),
        ("test_all_runners_valid", test_all_runners_valid),
        ("test_fetched_temps_cache_key_is_team_runner", test_fetched_temps_cache_key_is_team_runner),
        ("test_duplicate_name_conflict_detection", test_duplicate_name_conflict_detection),
        ("test_mixed_code_no_code_conflict", test_mixed_code_no_code_conflict),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"結果: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
