"""
config/player_comments.json migration and app.js player comment loading tests.
"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PC_FILE = PROJECT_ROOT / 'config' / 'player_comments.json'
TC_FILE = PROJECT_ROOT / 'config' / 'team_comments.json'
PP_FILE = PROJECT_ROOT / 'config' / 'player_profiles.json'
EK_FILE = PROJECT_ROOT / 'config' / 'ekiden_data.json'
AM_FILE = PROJECT_ROOT / 'config' / 'amedas_stations.json'


def load_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'  WARN: {path.name} 読み込み失敗: {e}')
        return None


# ============================================================

def test_player_comments_exists():
    data = load_json(PC_FILE)
    assert data is not None, 'player_comments.json が存在しません'
    assert len(data) > 0, 'player_comments.json が空です'


def test_player_comments_has_known_comments():
    data = load_json(PC_FILE)
    comments = [v for v in data.values() if v.get('comment', '').strip()]
    assert len(comments) >= 50, f'コメント数が不足: {len(comments)}'
    print(f'  コメント数: {len(comments)}')


def test_player_comments_code_is_string():
    data = load_json(PC_FILE)
    for code, entry in data.items():
        assert isinstance(code, str), f'code {code!r} が文字列ではありません'
        assert 'runner_name' in entry, f'code {code} に runner_name がありません'
        assert 'comment' in entry, f'code {code} に comment がありません'


def test_all_team_comments_migrated():
    tc = load_json(TC_FILE)
    pc = load_json(PC_FILE)
    if tc is None or pc is None:
        return  # skip if files missing
    # Collect all team_comments
    tc_comments = set()
    for team_id, runners in tc.items():
        for name, comment in runners.items():
            if comment.strip():
                tc_comments.add((name, comment.strip()))

    # Check each exists in player_comments
    pc_by_runner = {v['runner_name']: v['comment'] for v in pc.values()}
    missing = []
    for name, comment in tc_comments:
        if name not in pc_by_runner:
            missing.append(name)
        elif pc_by_runner[name] != comment:
            print(f'  コメント内容差異: {name}')

    if missing:
        print(f'  ⚠️ team_comments から移行されていない名前: {missing}')
    assert len(missing) == 0, f'{len(missing)}件の未移行コメント'


def test_player_profiles_comments_match():
    pc = load_json(PC_FILE)
    pp = load_json(PP_FILE)
    if pc is None or pp is None:
        return
    # For each player_comments entry, check the profile has the same comment
    pp_by_code = {}
    for name, profile in pp.items():
        code = profile.get('code', '')
        if code:
            pp_by_code[code] = profile.get('comment', '')

    mismatches = 0
    for code, entry in pc.items():
        comment = entry.get('comment', '')
        if not comment:
            continue
        # 過去大会の選手など、現行 player_profiles に存在しない選手は対象外。
        # コメント正本には履歴として保持する。
        if code not in pp_by_code:
            continue
        if code in pp_by_code and pp_by_code[code] != comment:
            mismatches += 1
            if mismatches <= 3:
                print(f'  code={code} pc="{comment[:30]}" pp="{pp_by_code[code][:30]}"')
    assert mismatches == 0, f'{mismatches}件のコメント不一致'


def test_resolve_name_to_code():
    """station_code 解決が正常に動作することを確認"""
    ek = load_json(EK_FILE)
    am = load_json(AM_FILE)
    if ek is None or am is None:
        return

    # Build name→code from ekiden_data
    name_to_code = {}
    for team in ek.get('teams', []):
        for r in team.get('runners', []) + team.get('substitutes', []):
            if isinstance(r, dict):
                name_to_code[r['name']] = r.get('station_code')
            elif isinstance(r, str):
                name_to_code[r] = None

    # Check a few known mappings
    assert name_to_code.get('豊田') == '51116', '豊田のstation_codeが不正'
    assert name_to_code.get('八幡') == '52331', '八幡のstation_codeが不正'


def test_get_player_comments_in_js():
    """app.js に関連関数が存在することを確認"""
    app_js = PROJECT_ROOT / 'app.js'
    text = app_js.read_text(encoding='utf-8')
    assert 'playerComments' in text, 'app.js に playerComments 変数がありません'
    assert 'function getPlayerComment' in text, 'app.js に getPlayerComment 関数がありません'
    assert 'loadPlayerComments' in text, 'app.js に loadPlayerComments 関数がありません'


def test_no_team_comments_in_app_js():
    """app.js が team_comments.json を直接読み込まない"""
    app_js = PROJECT_ROOT / 'app.js'
    text = app_js.read_text(encoding='utf-8')
    # teamComments 変数が定義されていない（コメント行は許容）
    for line in text.split('\n'):
        stripped = line.strip()
        if 'teamComments' in stripped and not stripped.startswith('//') and not stripped.startswith('*'):
            assert False, f'teamComments の実参照が残っています: {line}'


def test_generator_preserves_existing_comments():
    """generate_player_profiles.py 再生成後も既存コメントが保持される"""
    pp = load_json(PP_FILE)
    pc = load_json(PC_FILE)
    if pp is None or pc is None:
        return
    # player_comments.json の全コメントが player_profiles.json に反映されている
    missing_in_pp = 0
    profile_codes = {str(profile.get('code') or '') for profile in pp.values()}
    for code, entry in pc.items():
        comment = entry.get('comment', '')
        if not comment:
            continue
        # 現行大会のプロフィールに存在しない履歴選手は正本だけで保持する。
        if str(code) not in profile_codes:
            continue
        found = False
        for name, profile in pp.items():
            if profile.get('code') == code and profile.get('comment') == comment:
                found = True
                break
        if not found:
            missing_in_pp += 1
    assert missing_in_pp == 0, f'{missing_in_pp}件のコメントが profile に反映されていません'


# 注: 現在の player_comments.json は、既存53件と履歴復旧80件を統合した件数。
# station_code が重複する履歴2件は正規観測所名に統合している。


# ============================================================

if __name__ == '__main__':
    tests = [
        ("player_comments_exists", test_player_comments_exists),
        ("player_comments_has_known_comments", test_player_comments_has_known_comments),
        ("player_comments_code_is_string", test_player_comments_code_is_string),
        ("all_team_comments_migrated", test_all_team_comments_migrated),
        ("player_profiles_comments_match", test_player_profiles_comments_match),
        ("resolve_name_to_code", test_resolve_name_to_code),
        ("get_player_comments_in_js", test_get_player_comments_in_js),
        ("no_team_comments_in_app_js", test_no_team_comments_in_app_js),
        ("generator_preserves_comments", test_generator_preserves_existing_comments),
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
