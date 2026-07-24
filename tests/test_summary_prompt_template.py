"""
generate_daily_summary.py の build_system_prompt テンプレート接続のテスト
API 呼び出しなし、fixture/mock のみで動作。
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_daily_summary import DailySummaryGenerator

SAMPLE_EKIDEN = {
    "teams": [
        {"id": 1, "name": "名古屋大学", "prefectures": "（岐阜・愛知）",
         "runners": ["美濃"], "substitutes": []},
        {"id": 4, "name": "山梨学院大学", "prefectures": "（山梨・静岡・長野）",
         "runners": ["佐久間"], "substitutes": []},
    ],
    "leg_boundaries": [100, 210, 310],
}


def make_gen():
    """テスト用の最小 DailySummaryGenerator インスタンスを作成"""
    gen = DailySummaryGenerator.__new__(DailySummaryGenerator)
    gen.all_data = {
        "ekiden_data": json.loads(json.dumps(SAMPLE_EKIDEN)),
        "realtime_report": {
            "teams": [], "raceDay": 2,
            "updateTime": "2026/07/24 00:00",
        },
        "rank_history": {"teams": []},
        "individual_results": {},
        "manager_comments": [],
    }
    gen.narrative_state = {"updated_day": 1}
    gen.dry_run = True
    return gen


# --- テスト1: 正常テンプレート読み込みと5置換 ---
def test_template_loads_and_replaces_all():
    """5つのプレースホルダーが全て置換される"""
    gen = make_gen()
    prompt = gen.build_system_prompt()
    assert "{tournament_title}" not in prompt
    assert "{start_date}" not in prompt
    assert "{course_description}" not in prompt
    assert "{team_prefecture_list}" not in prompt
    assert "{leg_configuration}" not in prompt
    assert len(prompt) > 500


# --- テスト2: チーム都道府県一覧が含まれる ---
def test_team_prefecture_list_included():
    """チーム都道府県一覧がテンプレートに埋め込まれる"""
    gen = make_gen()
    prompt = gen.build_system_prompt()
    assert "名古屋大学" in prompt
    assert "岐阜・愛知" in prompt
    assert "山梨学院大学" in prompt
    assert "山梨・静岡・長野" in prompt


# --- テスト3: 区間構成が含まれる ---
def test_leg_config_included():
    """区間構成情報がテンプレートに埋め込まれる"""
    gen = make_gen()
    prompt = gen.build_system_prompt()
    assert "100km" in prompt or "100" in prompt
    assert "210km" in prompt or "210" in prompt



# --- テスト5: 未置換プレースホルダーでValueError ---
def test_unreplaced_placeholder_raises_error(tmp_path, monkeypatch):
    """未置換プレースホルダーがある場合はValueError（本体ファイルは変更しない）"""
    import generate_daily_summary as gds

    # tmp_path にテンプレートを作成し、CONFIG_DIR を monkeypatch
    broken_template = "タイトル: {tournament_title} {unknown_placeholder}"
    tmp_template = tmp_path / "summary_prompt_template.txt"
    tmp_template.write_text(broken_template, encoding="utf-8")
    monkeypatch.setattr(gds, "CONFIG_DIR", Path(tmp_path))

    gen = make_gen()
    raised = False
    try:
        gen.build_system_prompt()
    except ValueError as e:
        assert "unknown_placeholder" in str(e)
        raised = True
    assert raised, "ValueError が発生すべき"


# --- テスト6: テンプレート欠落でFileNotFoundError（tmp_path版）---
def test_template_missing_raises_error_v2(tmp_path, monkeypatch):
    """テンプレートファイルがない場合はFileNotFoundError（本体ファイルは変更しない）"""
    import generate_daily_summary as gds

    monkeypatch.setattr(gds, "CONFIG_DIR", Path(tmp_path))
    gen = make_gen()
    raised = False
    try:
        gen.build_system_prompt()
    except FileNotFoundError:
        raised = True
    assert raised, "FileNotFoundError が発生すべき"


# --- テスト7: テンプレートにトークン例があり直接名がない ---
def test_template_uses_tokens_not_direct_names():
    """テンプレートの本文出力例に {{TEAM:...}}/{{RUNNER:...}} があり、
    日本語正式名称が直接出力例として含まれない"""
    import generate_daily_summary as gds
    template_path = gds.CONFIG_DIR / "summary_prompt_template.txt"
    template = template_path.read_text(encoding="utf-8")

    # 執筆例セクションにトークンがあること
    assert "{{TEAM:nagoya}}" in template, "例にチームトークンが必要"
    assert "{{RUNNER:nagoya}}" in template, "例に走者トークンが必要"

    # 出力契約セクションがあること
    assert "出力契約" in template
    assert "{{TEAM:team_id}} のみ" in template


# --- テスト8: 文字数目標が約2000文字になっている ---
def test_character_count_is_2000():
    import generate_daily_summary as gds
    gen = gds.DailySummaryGenerator.__new__(gds.DailySummaryGenerator)
    gen.all_data = {
        "ekiden_data": {"teams": []},
        "realtime_report": {"teams": [], "raceDay": 1, "updateTime": ""},
        "rank_history": {"teams": []},
        "individual_results": {},
        "manager_comments": [],
        "player_story_context": {},
        "team_story_context": {},
        "leg_story_context": {},
    }
    gen.narrative_state = {}
    gen.dry_run = True
    metrics = gen.calculate_race_metrics()
    prompt = gen.build_user_prompt(metrics)
    assert "約2,000文字" in prompt or "2,000字" in prompt
    assert "1,800" in prompt and "2,200" in prompt
    assert "1400" not in prompt
    assert "2600" not in prompt
if __name__ == "__main__":
    tests = [
        ("template_loads_and_replaces_all", test_template_loads_and_replaces_all),
        ("team_prefecture_list_included", test_team_prefecture_list_included),
        ("leg_config_included", test_leg_config_included),
        ("unreplaced_placeholder_raises_error", test_unreplaced_placeholder_raises_error),
        ("template_missing_raises_error_v2", test_template_missing_raises_error_v2),
        ("template_uses_tokens_not_direct_names", test_template_uses_tokens_not_direct_names),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            if "tmp_path" in fn.__code__.co_varnames:
                import tempfile
                fn(tempfile.mkdtemp())
            else:
                fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
