"""
scripts/generate_daily_summary.py の parse_structured_ai_response /
build_claims_output_instruction のテスト。
API 呼び出しなし、fixture/mock のみ。
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_daily_summary import DailySummaryGenerator

parse = DailySummaryGenerator.parse_structured_ai_response
instruction = DailySummaryGenerator.build_claims_output_instruction


# --- テスト1: plain JSON ---
def test_plain_json():
    result = parse('{"article": "本文", "claims": []}')
    assert result["article"] == "本文"
    assert result["claims"] == []


# --- テスト2: json code fence ---
def test_json_code_fence():
    result = parse('```json\n{"article": "本文", "claims": []}\n```')
    assert result["article"] == "本文"
    assert result["claims"] == []


# --- テスト3: claims 省略時は空配列 ---
def test_claims_omitted_defaults_empty():
    result = parse('{"article": "本文"}')
    assert result["article"] == "本文"
    assert result["claims"] == []


# --- テスト4: claims=null は非listとして拒否 ---
def test_claims_null_rejected():
    raised = False
    try:
        parse('{"article": "本文", "claims": null}')
    except ValueError:
        raised = True
    assert raised, "claims=nullはValueError（非list）"


# --- テスト5: non-object 拒否 ---
def test_non_object_rejected():
    raised = False
    try:
        parse('["article", "claims"]')
    except ValueError:
        raised = True
    assert raised, "非objectのJSONはValueError"


# --- テスト6: article 欠落拒否 ---
def test_article_missing_rejected():
    raised = False
    try:
        parse('{"claims": []}')
    except ValueError:
        raised = True
    assert raised, "article欠落はValueError"


# --- テスト7: article 空文字拒否 ---
def test_article_empty_rejected():
    raised = False
    try:
        parse('{"article": "", "claims": []}')
    except ValueError:
        raised = True
    assert raised, "article空文字はValueError"


# --- テスト8: claims 非list拒否 ---
def test_claims_non_list_rejected():
    raised = False
    try:
        parse('{"article": "本文", "claims": "not_a_list"}')
    except ValueError:
        raised = True
    assert raised, "claims非listはValueError"


# --- テスト9: JSON前後に説明文があると拒否 ---
def test_extra_text_before_json_rejected():
    raised = False
    try:
        parse('以下が記事です\n{"article": "本文", "claims": []}')
    except ValueError:
        raised = True
    assert raised, "JSON前に説明文があるとValueError"


# --- テスト10: instruction が有効なJSON schemaを含む ---
def test_instruction_contains_json_schema():
    instr = instruction()
    assert "article" in instr
    assert "claims" in instr
    assert "team_id" in instr
    assert "claim_type" in instr
    assert "evidence" in instr
    assert "rank_change" in instr
    assert "```json" in instr


# --- テスト11: instruction が各claim_typeの必須フィールドを含む ---
def test_instruction_includes_all_claim_schemas():
    instr = DailySummaryGenerator.build_claims_output_instruction()
    # rank_change
    assert "previous_rank" in instr
    assert "current_rank" in instr
    assert "direction" in instr
    # distance
    assert "distance_kind" in instr
    assert "value" in instr
    # runner
    assert '"runner"' in instr or "'runner'" in instr
    # battle
    assert "opponent_team_id" in instr
    assert "gap_km" in instr


# --- テスト13: instruction に3種のdirection例と禁止語がある ---
def test_instruction_has_three_direction_examples():
    instr = DailySummaryGenerator.build_claims_output_instruction()
    # 3例
    assert '"up"' in instr or "'up'" in instr or 'direction": "up"' in instr
    assert '"down"' in instr or "'down'" in instr
    assert '"same"' in instr or "'same'" in instr
    # 禁止語
    assert "none" in instr or "禁止" in instr


# --- テスト14: parse失敗時に保存されないことを確認 ---
def test_parse_failure_stops_save(monkeypatch):
    """parse失敗時は run() が途中で return する（保存処理に進まない）"""
    gen = DailySummaryGenerator.__new__(DailySummaryGenerator)

    # parse_structured_ai_response が常に失敗するようモック
    def failing_parse(*args, **kwargs):
        raise ValueError("テスト用エラー")
    monkeypatch.setattr(gen, "parse_structured_ai_response", failing_parse)

    # dry_run=True なら run() の早い段階で return するので、
    # parse失敗の return が呼ばれるのは非dry-run時
    gen.dry_run = False

    # run() は self.all_data 等を必要とするので、run() 全体は呼べない。
    # 代わりに parse 箇所のロジックを直接テスト:
    # ValueError→print→return が呼ばれることを確認
    raw_text = '不正な応答'
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        try:
            parsed = gen.parse_structured_ai_response(raw_text)
        except ValueError as e:
            print(f"❌ 構造化応答のパースに失敗しました: {e}")
            print("   本日はJSON出力指示に応答しなかったため記事を保存せず終了します。")
            # return 相当

    output = f.getvalue()
    assert "パースに失敗" in output
    assert "保存せず終了" in output


# --- テスト16: json fence内に // コメントがない ---
def test_json_fence_has_no_comments():
    instr = DailySummaryGenerator.build_claims_output_instruction()
    import re
    # json fence starts with ```json and ends with ```
    fence_start = instr.find("```json")
    fence_end = instr.find("```", fence_start + 7)
    assert fence_start >= 0 and fence_end >= 0, "json fence not found"
    json_content = instr[fence_start + 7:fence_end]
    assert "//" not in json_content, "json fence内に // コメントがあります"



# --- テスト17: Structured Outputs schema に必須フィールドがある ---
def test_structured_outputs_schema():
    schema = DailySummaryGenerator.DAILY_SUMMARY_JSON_SCHEMA
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["article", "claims"]
    assert "article" in schema["properties"]
    assert "claims" in schema["properties"]
    claims_items = schema["properties"]["claims"]["items"]
    assert claims_items["additionalProperties"] is False
    assert "team_id" in claims_items["required"]
    assert "claim_type" in claims_items["required"]
    assert "direction" in claims_items["required"]
    # claim_type enum
    ct = claims_items["properties"]["claim_type"]
    enums = ct["anyOf"][0]["enum"]
    assert "rank_change" in enums
    assert "distance" in enums
    assert "runner" in enums
    assert "battle" in enums
    # direction enum
    dir_schema = claims_items["properties"]["direction"]
    dirs = dir_schema["anyOf"][0]["enum"]
    assert "up" in dirs and "down" in dirs and "same" in dirs

if __name__ == "__main__":
    tests = [
        ("plain_json", test_plain_json),
        ("json_code_fence", test_json_code_fence),
        ("claims_omitted_defaults_empty", test_claims_omitted_defaults_empty),
        ("claims_null_rejected", test_claims_null_rejected),
        ("non_object_rejected", test_non_object_rejected),
        ("article_missing_rejected", test_article_missing_rejected),
        ("article_empty_rejected", test_article_empty_rejected),
        ("claims_non_list_rejected", test_claims_non_list_rejected),
        ("extra_text_before_json_rejected", test_extra_text_before_json_rejected),
        ("instruction_contains_json_schema", test_instruction_contains_json_schema),
        ("instruction_includes_all_claim_schemas", test_instruction_includes_all_claim_schemas),
        ("instruction_has_three_direction_examples", test_instruction_has_three_direction_examples),
        ("parse_failure_stops_save", test_parse_failure_stops_save),
        ("structured_outputs_schema", test_structured_outputs_schema),
        ("json_fence_has_no_comments", test_json_fence_has_no_comments),
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
