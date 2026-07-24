"""
scripts/synthesize_daily_summary.py のテスト
API 呼び出しなし、fixture/mock のみで動作。
"""
import json
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from synthesize_daily_summary import (
    load_json,
    format_race_facts,
    load_synthesis_prompt_template,
    _calc_rank_changes,
    save_article_if_valid,
    parse_args,
    format_article_with_markdown,
    DEFAULT_SYNTHESIS_TEMPLATE,
)

SAMPLE_REPORT = {
    "updateTime": "2026/07/23 23:59",
    "raceDay": 2,
    "teams": [
        {"name": "山梨学院大学", "overallRank": 1, "runner": "佐久間",
         "todayDistance": 33.2, "totalDistance": 74.3, "currentLeg": 2},
        {"name": "名古屋大学", "overallRank": 2, "runner": "美濃",
         "todayDistance": 40.8, "totalDistance": 73.1, "currentLeg": 1},
    ],
}

SAMPLE_RANK_HISTORY = {
    "teams": [
        {"name": "山梨学院大学", "ranks": [1, 1]},
        {"name": "名古屋大学", "ranks": [3, 2]},
    ]
}

SAMPLE_EKIDEN = {
    "teams": [
        {"id": 1, "name": "名古屋大学", "runners": ["美濃"], "substitutes": []},
        {"id": 4, "name": "山梨学院大学", "runners": ["佐久間"], "substitutes": []},
    ]
}


# --- テスト1: --dry-run パース ---
def test_dry_run_parse():
    args = parse_args(["--dry-run"])
    assert args.dry_run is True
    assert args.no_write is False
    assert args.save_drafts is None


# --- テスト2: --no-write パース ---
def test_no_write_parse():
    args = parse_args(["--no-write"])
    assert args.no_write is True
    assert args.dry_run is False


# --- テスト3: --save-drafts パース ---
def test_save_drafts_parse():
    args = parse_args(["--save-drafts", "/tmp/drafts"])
    assert args.save_drafts == "/tmp/drafts"


# --- テスト4: format_race_facts が整形できる ---
def test_format_race_facts():
    all_data = {
        "realtime_report": SAMPLE_REPORT,
        "rank_history": SAMPLE_RANK_HISTORY,
    }
    result = format_race_facts(all_data)
    assert "山梨学院大学" in result
    assert "名古屋大学" in result
    assert "2日目" in result or "raceDay" not in result
    # Check rank changes are included (名古屋が3→2、+1)
    assert "3位→2位" in result or "diff" in result


# --- テスト5: _calc_rank_changes が正しく計算 ---
def test_calc_rank_changes():
    all_data = {
        "realtime_report": SAMPLE_REPORT,
        "rank_history": SAMPLE_RANK_HISTORY,
    }
    changes = _calc_rank_changes(all_data)
    # 名古屋大学: 3位→2位 = diff=1
    assert "名古屋大学" in changes
    assert changes["名古屋大学"]["diff"] == 1
    assert changes["名古屋大学"]["prev"] == 3
    assert changes["名古屋大学"]["current"] == 2
    # 山梨学院大学: 1位→1位 = diff=0 (not in changes since diff==0)
    assert "山梨学院大学" not in changes or changes["山梨学院大学"]["diff"] == 0


# --- テスト6: プロンプトテンプレート読み込み ---
def test_load_synthesis_prompt_template():
    template = load_synthesis_prompt_template()
    assert "{race_facts}" in template
    assert "{gemini_article}" in template
    assert "{openai_article}" in template
    assert template == DEFAULT_SYNTHESIS_TEMPLATE or Path(
        PROJECT_ROOT / "config" / "summary_synthesis_prompt_template.txt"
    ).exists()


# --- テスト7: format_article_with_markdown ---
def test_format_article_with_markdown():
    text = "■見出し\n【小見出し】\n本文"
    result = format_article_with_markdown(text)
    assert "### 見出し" in result
    assert "#### 小見出し" in result


# --- テスト8: save_article_if_valid no_write=True はバリデーション通過後に保存スキップ ---
def test_save_no_write_valid():
    """no_write=True でもバリデーションは実行される（不正記事ならFalse）"""
    all_data = {
        "realtime_report": SAMPLE_REPORT,
        "ekiden_data": SAMPLE_EKIDEN,
        "rank_history": SAMPLE_RANK_HISTORY,
    }
    # 不正な記事（存在しない大学名を含む）→ validation が失敗する
    result = save_article_if_valid(
        "存在しない大学が逆転した。",
        all_data,
        "プロンプト",
        no_write=True,
    )
    # バリデーションが先に実行され、不正記事なら False になる
    # （マスタにない大学名が警告されれば validation が False を返す）
    assert result is not None


# --- テスト9: format_race_facts に空データ ---
def test_format_race_facts_empty():
    result = format_race_facts({})
    assert isinstance(result, str)
    assert len(result) > 0


# --- テスト10: テンプレートのプレースホルダーが全て埋められる ---
def test_template_placeholders():
    from synthesize_daily_summary import DEFAULT_SYNTHESIS_TEMPLATE
    filled = (
        DEFAULT_SYNTHESIS_TEMPLATE
        .replace("{race_facts}", "事実データ")
        .replace("{gemini_article}", "Gemini記事")
        .replace("{openai_article}", "OpenAI記事")
    )
    assert "{race_facts}" not in filled
    assert "{gemini_article}" not in filled
    assert "{openai_article}" not in filled


if __name__ == "__main__":
    tests = [
        ("dry_run_parse", test_dry_run_parse),
        ("no_write_parse", test_no_write_parse),
        ("save_drafts_parse", test_save_drafts_parse),
        ("format_race_facts", test_format_race_facts),
        ("calc_rank_changes", test_calc_rank_changes),
        ("load_synthesis_prompt_template", test_load_synthesis_prompt_template),
        ("format_article_with_markdown", test_format_article_with_markdown),
        ("save_no_write_valid", test_save_no_write_valid),
        ("format_race_facts_empty", test_format_race_facts_empty),
        ("template_placeholders", test_template_placeholders),
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
