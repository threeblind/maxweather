"""
scripts/generate_daily_summary.py の AI応答保存機能テスト。
実API呼び出しなし、モック/fixture のみ。
"""
import sys
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from generate_daily_summary import (
    _save_ai_raw_response,
    _update_ai_response_status,
    _delete_ai_response_file,
    AI_RESPONSE_DIR,
)


def _cleanup():
    """テスト後に AI_RESPONSE_DIR をクリーンアップ"""
    if AI_RESPONSE_DIR.exists():
        for f in AI_RESPONSE_DIR.iterdir():
            f.unlink()
        AI_RESPONSE_DIR.rmdir()


def setup_function():
    _cleanup()


def teardown_function():
    _cleanup()


# ============================================================
# テスト: _save_ai_raw_response
# ============================================================

def test_save_initial_response():
    """API応答取得後にファイルが生成され、raw_responseが完全一致する"""
    raw = '{"article": "テスト記事", "claims": []}'
    filepath, err = _save_ai_raw_response(
        raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json"
    )
    assert err is None
    assert filepath is not None
    assert Path(filepath).exists()

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    assert data['raw_response'] == raw
    assert data['status'] == 'received'
    assert data['provider'] == 'openai'
    assert data['model'] == 'gpt-4o-mini'
    assert data['race_date'] == '2026-07-25'
    assert data['failure_stage'] is None
    assert data['failure_message'] is None
    assert 'saved_at' in data


def test_save_multiple_unique():
    """同時刻・同一内容でもUUIDによりファイルが上書きされない"""
    raw = '{"article": "同一内容", "claims": []}'
    fp1, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    fp2, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    # UUIDにより常に異なるファイル名
    assert fp1 != fp2
    assert Path(fp1).exists()
    assert Path(fp2).exists()
    # 同一内容が両方保存されている
    with open(fp1) as f:
        assert json.load(f)['raw_response'] == raw
    with open(fp2) as f:
        assert json.load(f)['raw_response'] == raw


def test_save_prompt_not_included():
    """プロンプト/APIキー/Authorizationが保存JSONに含まれない"""
    raw = '{"article": "結果", "claims": []}'
    filepath, _ = _save_ai_raw_response(raw, "gemini", "gemini-3.1-flash-lite", "2026-07-25", "data/daily_summary.json")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # raw_response = APIの生テキストのみ（prompt/APIキーなし）
    assert data['raw_response'] == raw
    # プロンプト関連キーがないことを確認
    assert 'system_prompt' not in data
    assert 'user_prompt' not in data
    assert 'api_key' not in data
    assert 'authorization' not in data
    assert 'Authorization' not in json.dumps(data)


# ============================================================
# テスト: _update_ai_response_status
# ============================================================

def test_update_status_failed_parse():
    """parse失敗でstatus=failed, failure_stage=parse"""
    raw = 'invalid json'
    filepath, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    _update_ai_response_status(filepath, 'failed', 'parse', 'JSONパースエラー: unexpected token')

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['status'] == 'failed'
    assert data['failure_stage'] == 'parse'
    assert 'JSONパースエラー' in data['failure_message']


def test_update_status_failed_claims():
    """claims検証失敗でstatus=failed, failure_stage=claims"""
    raw = '{"article": "test", "claims": []}'
    filepath, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    _update_ai_response_status(filepath, 'failed', 'claims', 'distance_kind=recordDistance')

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['status'] == 'failed'
    assert data['failure_stage'] == 'claims'
    assert 'recordDistance' in data['failure_message']


def test_update_status_succeeded():
    """成功時は status=succeeded"""
    raw = '{"article": "成功", "claims": []}'
    filepath, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    _update_ai_response_status(filepath, 'succeeded')

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert data['status'] == 'succeeded'


# ============================================================
# テスト: _delete_ai_response_file
# ============================================================

def test_delete_ai_response_file():
    """成功時はファイルを削除できる"""
    raw = '{"article": "削除テスト", "claims": []}'
    filepath, _ = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    assert Path(filepath).exists()
    _delete_ai_response_file(filepath)
    assert not Path(filepath).exists()


def test_delete_nonexistent():
    """存在しないファイルの削除はエラーにならない"""
    _delete_ai_response_file("/nonexistent/path.json")  # エラーなしで通過


# ============================================================
# テスト: 正常系が壊れないことの確認
# ============================================================

def test_normal_flow_preserves_existing_output():
    """正常系の _save_ai_raw_response は既存のデータ生成を壊さない"""
    # 単純に保存→成功ステータス→削除の流れが例外なく動作する
    raw = '{"article": "正常記事", "claims": [{"team_id": 1, "claim_type": "lead"}]}'
    filepath, err = _save_ai_raw_response(raw, "gemini", "gemini-3.1-flash-lite", "2026-07-25", "data/daily_summary.json")
    assert err is None
    _update_ai_response_status(filepath, 'succeeded')
    _delete_ai_response_file(filepath)
    assert not Path(filepath).exists()


def test_encoding_utf8():
    """UTF-8/ensure_ascii=False で日本語が保存される"""
    raw = '{"article": "本日の走行距離は40.5kmでした。", "claims": []}'
    filepath, err = _save_ai_raw_response(raw, "openai", "gpt-4o-mini", "2026-07-25", "data/daily_summary.json")
    assert err is None
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    assert '走行距離' in data['raw_response']
    assert '\\u' not in repr(data['raw_response'])  # 日本語がそのまま


# ============================================================
# テストランナー
# ============================================================

if __name__ == '__main__':
    tests = [
        ("save_initial_response", test_save_initial_response),
        ("save_multiple_unique", test_save_multiple_unique),
        ("save_prompt_not_included", test_save_prompt_not_included),
        ("update_status_failed_parse", test_update_status_failed_parse),
        ("update_status_failed_claims", test_update_status_failed_claims),
        ("update_status_succeeded", test_update_status_succeeded),
        ("delete_ai_response_file", test_delete_ai_response_file),
        ("delete_nonexistent", test_delete_nonexistent),
        ("normal_flow_preserves_existing_output", test_normal_flow_preserves_existing_output),
        ("encoding_utf8", test_encoding_utf8),
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
