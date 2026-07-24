"""
scripts/generate_daily_summary.py render_article_tokens /
build_token_output_instruction のテスト。
API 呼び出しなし、fixture/mock のみ。
"""
import sys, json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_daily_summary import DailySummaryGenerator

SAMPLE_TEAMS = [
    {"id": 1, "name": "名古屋大学", "runner": "2美濃"},
    {"id": 4, "name": "山梨学院大学", "runner": "1佐久間"},
    {"id": 7, "name": "福岡大学", "runner": "ゴール"},
]

ALL_DATA = {
    "realtime_report": {"teams": SAMPLE_TEAMS},
    "ekiden_data": {"teams": [
        {"id": 1, "name": "名古屋大学", "short_name": "名大"},
        {"id": 4, "name": "山梨学院大学", "short_name": "山学"},
        {"id": 7, "name": "福岡大学", "short_name": "福岡"},
    ]},
}

render = DailySummaryGenerator.render_article_tokens
instruction = DailySummaryGenerator.build_token_output_instruction


# --- テスト1: TEAM token 正常展開 ---
def test_team_token():
    result = render("{{TEAM:1}}が快走", ALL_DATA)
    assert "名古屋大学" in result
    assert "{{TEAM:1}}" not in result


# --- テスト2: RUNNER token 正常展開（先頭数字除去）---
def test_runner_token_strip_number():
    result = render("{{RUNNER:1}}選手", ALL_DATA)
    assert "美濃" in result
    assert "2美濃" not in result  # 先頭数字は除去
    assert "{{RUNNER:1}}" not in result


# --- テスト3: 数値IDでも引ける ---
def test_team_name_id():
    result = render("{{TEAM:1}}", ALL_DATA)
    assert result == "名古屋大学"


# --- テスト4: 同一token複数置換 ---
def test_multiple_same_token():
    result = render("{{TEAM:1}}と{{TEAM:1}}", ALL_DATA)
    assert result == "名古屋大学と名古屋大学"


# --- テスト5: unknown team_id 拒否 ---
def test_unknown_team_id():
    raised = False
    try:
        render("{{TEAM:unknown}}", ALL_DATA)
    except ValueError:
        raised = True
    assert raised


# --- テスト6: 未対応トークン種別拒否 ---
def test_unsupported_token_type():
    raised = False
    try:
        render("{{FOO:1}}", ALL_DATA)
    except ValueError:
        raised = True
    assert raised


# --- テスト7: トークンなしarticleはそのまま ---
def test_no_tokens_passes():
    result = render("通常の記事本文です。", ALL_DATA)
    assert result == "通常の記事本文です。"


# --- テスト8: 複数種別混在 ---
def test_mixed_tokens():
    result = render("{{TEAM:1}}の{{RUNNER:4}}選手", ALL_DATA)
    assert "名古屋大学" in result
    assert "佐久間" in result
    assert "1佐久間" not in result


# --- テスト9: instruction が有効な内容を含む ---
def test_instruction_content():
    instr = instruction()
    assert "{{TEAM:" in instr
    assert "{{RUNNER:" in instr
    assert "team_id" in instr
    assert "トークン" in instr


# --- テスト10: runnerが「ゴール」の場合 ---
def test_runner_goal():
    result = render("{{RUNNER:7}}", ALL_DATA)
    assert result == "ゴール"


# --- テスト11: render後に通常のMarkdownが保持される ---
def test_markdown_preserved():
    text = "# タイトル\n### 見出し\n{{TEAM:1}}が活躍\n- 箇条書き"
    result = render(text, ALL_DATA)
    assert "# タイトル" in result
    assert "### 見出し" in result
    assert "- 箇条書き" in result
    assert "名古屋大学" in result


def test_validate_direct_team_name_rejected():
    from generate_daily_summary import DailySummaryGenerator
    val = DailySummaryGenerator.validate_article_tokens
    warnings = val("名古屋大学が快走", ALL_DATA)
    # 既知名はwarningとして返る（保存継続）
    assert len(warnings) > 0
    assert any(w["type"] == "direct_team_name" and w["name"] == "名古屋大学" for w in warnings)


def test_validate_tokens_only_passes():
    from generate_daily_summary import DailySummaryGenerator
    val = DailySummaryGenerator.validate_article_tokens
    warnings = val("{{TEAM:1}}が{{RUNNER:4}}と競う", ALL_DATA)
    assert len(warnings) == 0, "tokenのみ通過すべき"


def test_validate_direct_runner_rejected():
    from generate_daily_summary import DailySummaryGenerator
    val = DailySummaryGenerator.validate_article_tokens
    warnings = val("佐久間選手が走行", ALL_DATA)
    # 既知名はwarningとして返る（保存継続）
    assert len(warnings) > 0
    assert any(w["type"] == "direct_runner_name" for w in warnings)


def test_validate_goal_not_detected():
    from generate_daily_summary import DailySummaryGenerator
    val = DailySummaryGenerator.validate_article_tokens
    warnings = val("ゴールしました", ALL_DATA)
    assert len(warnings) == 0, "ゴールは検出対象外"


# --- テスト16: ASCII ID token成功 ---
def test_ascii_id_token():
    result = render("{{TEAM:nagoya}}が快走", ALL_DATA)
    assert "名古屋大学" in result


# --- テスト17: 日本語トークンID拒否 ---
def test_japanese_token_id_rejected():
    """日本語チーム名を token team_id に使うと パターン不一致で展開されずに残る"""
    result = render("{{TEAM:名古屋大学}}", ALL_DATA)
    # 日本語名はトークンパターンにマッチしないので、そのまま残る
    assert "{{TEAM:名古屋大学}}" in result


# --- テスト18: mapping の存在確認 ---
def test_team_mapping_includes_all():
    from generate_daily_summary import DailySummaryGenerator
    mapping = DailySummaryGenerator.build_team_id_mapping(ALL_DATA)
    # SAMPLE_TEAMS の全チームがマッピングに含まれる
    mapped_names = {info["team"] for info in mapping.values()}
    for t in ALL_DATA["realtime_report"]["teams"]:
        assert t["name"] in mapped_names, f"{t['name']} がマッピングにありません"


# --- validate_generated_article の fatal/warning 分類テスト ---

def test_validate_history_winner_is_warning():
    """過去実績表現（第14回、第15回を制した）はwarningで保存継続"""
    gen = DailySummaryGenerator(dry_run=True)
    gen.all_data = {
        "ekiden_data": {
            "teams": [{"id": 1, "name": "名古屋大学", "runners": [{"name": "美濃加茂"}]}]
        },
        "realtime_report": {
            "raceDay": 2,
            "teams": [{"name": "名古屋大学", "runner": "美濃加茂", "overallRank": 1, "todayDistance": 30, "totalDistance": 60, "previousRank": 1}]
        }
    }
    metrics = gen.calculate_race_metrics()
    can_save, warnings, fatal_errors = gen.validate_generated_article(
        "第14回、第15回を制した連覇校が、今大会でも早くも先頭に立った。", metrics
    )
    assert can_save is True, "過去実績は保存継続"
    # 歴史記述として正しく検出・スキップされ、warningなしで通過
    assert len(warnings) == 0, "過去実績は正しく歴史パターンとして検出されスキップされる"
    assert len(fatal_errors) == 0, "過去実績表現でfatalは出ない"


def test_validate_wrong_present_winner_is_fatal():
    """現大会の誤った優勝断定はfatalで保存停止"""
    gen = DailySummaryGenerator(dry_run=True)
    gen.all_data = {
        "ekiden_data": {
            "teams": [{"id": 1, "name": "名古屋大学", "runners": [{"name": "美濃加茂"}]}]
        },
        "realtime_report": {
            "raceDay": 2,
            "teams": [{"name": "名古屋大学", "runner": "美濃加茂", "overallRank": 1, "todayDistance": 30, "totalDistance": 60, "previousRank": 1}]
        }
    }
    metrics = gen.calculate_race_metrics()
    # 未ゴールなのに優勝と書く
    can_save, warnings, fatal_errors = gen.validate_generated_article(
        "名古屋大学が優勝した。", metrics
    )
    assert can_save is False, "現大会の誤った優勝断定は保存停止"
    assert len(fatal_errors) > 0, "誤った優勝断定はfatal"
    assert any("総合1位ゴールしていない" in e for e in fatal_errors)


def test_validate_unknown_team_is_fatal():
    """マスタに存在しない大学名はfatalで保存停止"""
    gen = DailySummaryGenerator(dry_run=True)
    gen.all_data = {
        "ekiden_data": {
            "teams": [{"id": 1, "name": "名古屋大学", "runners": [{"name": "美濃加茂"}]}]
        },
        "realtime_report": {
            "raceDay": 2,
            "teams": [{"name": "名古屋大学", "runner": "美濃加茂", "overallRank": 1, "todayDistance": 30, "totalDistance": 60, "previousRank": 1}]
        }
    }
    metrics = gen.calculate_race_metrics()
    can_save, warnings, fatal_errors = gen.validate_generated_article(
        "架空大学が本日急浮上しました。", metrics
    )
    assert can_save is False, "存在しない大学名は保存停止"
    assert len(fatal_errors) > 0
    assert any("存在しない大学名" in e for e in fatal_errors)


if __name__ == "__main__":
    tests = [
        ("team_token", test_team_token),
        ("runner_strip_number", test_runner_token_strip_number),
        ("team_name_id", test_team_name_id),
        ("multiple_same_token", test_multiple_same_token),
        ("unknown_team_id", test_unknown_team_id),
        ("unsupported_token_type", test_unsupported_token_type),
        ("no_tokens_passes", test_no_tokens_passes),
        ("mixed_tokens", test_mixed_tokens),
        ("instruction_content", test_instruction_content),
        ("runner_goal", test_runner_goal),
        ("markdown_preserved", test_markdown_preserved),
        ("validate_direct_team_name_rejected", test_validate_direct_team_name_rejected),
        ("validate_tokens_only_passes", test_validate_tokens_only_passes),
        ("validate_direct_runner_rejected", test_validate_direct_runner_rejected),
        ("validate_goal_not_detected", test_validate_goal_not_detected),
        ("ascii_id_token", test_ascii_id_token),
        ("japanese_token_id_rejected", test_japanese_token_id_rejected),
        ("team_mapping_includes_all", test_team_mapping_includes_all),
        ("validate_history_winner_is_warning", test_validate_history_winner_is_warning),
        ("validate_wrong_present_winner_is_fatal", test_validate_wrong_present_winner_is_fatal),
        ("validate_unknown_team_is_fatal", test_validate_unknown_team_is_fatal),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n結果: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
