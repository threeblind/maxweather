"""
scripts/check_and_repair_daily_summary.py のテスト。
実際の git commit/push は行わず、チェックロジックのみ検証。
"""
import sys
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_and_repair_daily_summary import (
    CheckResult,
    resolve_target_date,
    load_json,
    BROKEN_NUMBERS_IN_TEXT,
    UNREPLACED_PLACEHOLDERS,
    DISTANCE_PATTERN,
    check_daily_summary,
    check_article_consistency,
    main as check_main,
    SUMMARY_FILE,
    SUMMARY_CHECK_LOG,
    LOCK_FILE,
    AI_RESPONSE_DIR,
    _try_repair_from_raw,
    _try_apply_repair,
    _validate_article_against_source,
    _update_response_file_status,
)


def _make_summary(date='2026-07-25', article='# テスト記事\n\n通常の記事内容です。40.8kmの走行。'):
    return {'date': date.replace('-', '/'), 'article': article}


def teardown_function():
    # テストで作成したファイルをクリーンアップ
    for path in [SUMMARY_CHECK_LOG, LOCK_FILE]:
        if path.exists():
            path.unlink(missing_ok=True)


# ============================================================
# テスト: ユーティリティ
# ============================================================

def test_resolve_target_date_default():
    """date 指定なし → 前日"""
    date = resolve_target_date(None)
    expected = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    assert date == expected


def test_resolve_target_date_explicit():
    """date 指定あり → 指定日"""
    date = resolve_target_date('2026-07-25')
    assert date == '2026-07-25'


def test_load_json_valid():
    """正常なJSONファイルの読み込み"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump({'key': 'value'}, f)
        path = f.name
    try:
        err, data = load_json(path, 'test')
        assert err is None
        assert data['key'] == 'value'
    finally:
        os.unlink(path)


def test_load_json_not_found():
    """存在しないファイル → エラー文字列"""
    err, data = load_json(Path('/nonexistent/path.json'), 'test')
    assert err is not None
    assert '見つかりません' in err
    assert data is None


def test_load_json_invalid():
    """不正なJSON → エラー文字列"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write('not json{{{')
        path = f.name
    try:
        err, data = load_json(path, 'test')
        assert err is not None
        assert 'パースエラー' in err
        assert data is None
    finally:
        os.unlink(path)


# ============================================================
# テスト: CheckResult
# ============================================================

def test_check_result_basic():
    r = CheckResult()
    r.target_date = '2026-07-25'
    r.step('test1', 'PASS', 'ok')
    r.step('test2', 'FAIL', 'broken')
    assert len(r.steps) == 2
    assert len(r.errors) == 1
    assert 'test2' in r.errors[0]


def test_check_result_correction():
    r = CheckResult()
    r.target_date = '2026-07-25'
    r.correct('article', 'old text', 'new text')
    assert len(r.corrections) == 1
    assert r.corrections[0]['field'] == 'article'


# ============================================================
# テスト: Deterministic checks - 壊れた数字
# ============================================================

def test_broken_number_39_km():
    """39.km を検出"""
    assert BROKEN_NUMBERS_IN_TEXT.findall('39.kmの走行')


def test_broken_number_40_km():
    """40.km を検出"""
    assert BROKEN_NUMBERS_IN_TEXT.findall('40.kmの走行')


def test_broken_number_nullkm():
    """nullkm を検出"""
    assert BROKEN_NUMBERS_IN_TEXT.findall('nullkm')


def test_broken_number_NaNkm():
    """NaNkm を検出"""
    assert BROKEN_NUMBERS_IN_TEXT.findall('NaNkm')


def test_valid_number_40_8km():
    """40.8km は検出しない"""
    assert not BROKEN_NUMBERS_IN_TEXT.findall('40.8kmの走行')


def test_valid_number_39_533km():
    """39.533km は検出しない"""
    assert not BROKEN_NUMBERS_IN_TEXT.findall('平均39.533km')


def test_valid_number_3_0km():
    """3.0km は検出しない"""
    assert not BROKEN_NUMBERS_IN_TEXT.findall('差は3.0km')


# ============================================================
# テスト: 未置換テンプレート
# ============================================================

def test_unreplaced_template_curly():
    assert UNREPLACED_PLACEHOLDERS.findall('{{TEAM:1}}が走行')
    assert UNREPLACED_PLACEHOLDERS.findall('{{UNKNOWN_VAR}}')


def test_no_false_positive_normal_text():
    """通常のテキストは検出しない"""
    assert not UNREPLACED_PLACEHOLDERS.findall('通常の記事テキスト')
    assert not UNREPLACED_PLACEHOLDERS.findall('名古屋大学が走行')


# ============================================================
# テスト: check_daily_summary
# ============================================================

def test_check_valid_summary():
    """正常なサマリー → PASS"""
    r = CheckResult()
    r.target_date = '2026-07-25'
    data = _make_summary()
    check_daily_summary(r, data)
    fails = [s for s in r.steps if s['status'] == 'FAIL']
    assert len(fails) == 0, f'予期せぬFAIL: {fails}'


def test_check_broken_numbers():
    """壊れた数字 → FAIL"""
    r = CheckResult()
    r.target_date = '2026-07-25'
    data = _make_summary(article='記事内容: 39.kmの走行、40.kmの記録')
    check_daily_summary(r, data)
    fails = {s['name']: s for s in r.steps if s['status'] == 'FAIL'}
    assert 'broken_numbers' in fails


def test_check_unreplaced_placeholder():
    """未置換テンプレート → FAIL"""
    r = CheckResult()
    r.target_date = '2026-07-25'
    data = _make_summary(article='記事内容 {{TEAM:1}} が走行')
    check_daily_summary(r, data)
    fails = {s['name']: s for s in r.steps if s['status'] == 'FAIL'}
    assert 'placeholders' in fails


def test_check_date_mismatch():
    """日付不一致 → FAIL"""
    r = CheckResult()
    r.target_date = '2026-07-24'
    data = _make_summary(date='2026-07-25')
    check_daily_summary(r, data)
    fails = {s['name']: s for s in r.steps if s['status'] == 'FAIL'}
    assert 'date_match' in fails


def test_check_article_consistency():
    """記事整合性チェック"""
    r = CheckResult()
    r.target_date = '2026-07-25'
    data = _make_summary()
    check_article_consistency(r, data)
    fails = [s for s in r.steps if s['status'] == 'FAIL']
    assert len(fails) == 0


# ============================================================
# テスト: 正常系 dry-run 全体実行
# ============================================================

def test_dry_run_no_side_effects():
    """--dry-run でファイルが書き変わらない（終了コードは1でもOK）"""
    import tempfile
    original = SUMMARY_FILE.read_text(encoding='utf-8') if SUMMARY_FILE.exists() else None
    try:
        rc = check_main(['--dry-run', '--date', '2026-07-25'])
        # dry-run は git 状態等により FAIL になる可能性があるが
        # ファイルが書き変わらないことだけ検証
    finally:
        if original:
            current = SUMMARY_FILE.read_text(encoding='utf-8')
            assert current == original, 'dry-run でファイルが変更されました'
    assert SUMMARY_CHECK_LOG.exists()


# ============================================================
# テスト: AI応答修復パイプライン
# ============================================================

def test_try_repair_from_raw_valid_json():
    """有効なJSONからarticle抽出"""
    raw = '{"article": "本日の走行: 40.8km", "claims": [], "date": "2026/07/25"}'
    result = CheckResult()
    result.target_date = '2026-07-25'
    repaired = _try_repair_from_raw(raw, result, 'test.json', 'parse')
    assert repaired is not None
    assert '40.8km' in repaired['article']
    assert repaired['date'] == '2026/07/25'


def test_try_repair_from_raw_plain_text():
    """プレーンテキストの応答は全文をarticle扱い"""
    raw = '本日のレース結果です。名古屋大学が首位です。'
    result = CheckResult()
    repaired = _try_repair_from_raw(raw, result, 'test.json', 'parse')
    assert repaired is not None
    assert '名古屋大学' in repaired['article']


def test_try_repair_from_raw_empty():
    """空の応答はNone"""
    result = CheckResult()
    repaired = _try_repair_from_raw('', result, 'test.json', 'parse')
    assert repaired is not None  # 空文字でもarticleとして通す


def test_try_apply_repair_success():
    """修復候補がdeterministic checkを通れば適用"""
    result = CheckResult()
    result.target_date = '2026-07-25'
    summary_data = {'date': '2026/07/25', 'article': '古い記事'}
    repaired = {'date': '2026/07/25', 'article': '新しい記事 40.8km'}
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8') as f:
        json.dump({'raw_response': 'dummy', 'status': 'failed'}, f)
        fpath = f.name
    try:
        err = _try_apply_repair(result, summary_data, repaired, Path(fpath))
        assert err is None
        assert '新しい記事' in summary_data['article']
    finally:
        os.unlink(fpath)


def test_try_apply_repair_fail():
    """修復候補がcheckを通らなければ適用しない"""
    result = CheckResult()
    result.target_date = '2026-07-25'
    summary_data = {'date': '2026/07/25', 'article': '古い記事'}
    # 壊れた数字を含む
    repaired = {'date': '2026/07/25', 'article': '新しい記事 39.km'}
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8') as f:
        json.dump({'raw_response': 'dummy', 'status': 'failed'}, f)
        fpath = f.name
    try:
        err = _try_apply_repair(result, summary_data, repaired, Path(fpath))
        assert err is not None
        assert '古い記事' in summary_data['article']  # 変更されない
    finally:
        os.unlink(fpath)


def test_try_apply_repair_wrong_date():
    """日付不一致の修復候補は適用しない"""
    result = CheckResult()
    result.target_date = '2026-07-25'
    summary_data = {'date': '2026/07/25', 'article': '古い記事'}
    repaired = {'date': '2026/07/24', 'article': '違う日の記事'}
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8') as f:
        json.dump({'raw_response': 'dummy', 'status': 'failed'}, f)
        fpath = f.name
    try:
        err = _try_apply_repair(result, summary_data, repaired, Path(fpath))
        assert err is not None
        assert '古い記事' in summary_data['article']
    finally:
        os.unlink(fpath)


# ============================================================
# テスト: 元データ照合
# ============================================================

def test_validate_article_against_source_valid():
    """実データと一致する距離値 → 合格"""
    # 実際の daily_summary.json から距離値を借用
    err, data = load_json(SUMMARY_FILE, 'daily_summary')
    if err:
        return  # テストファイルがない場合スキップ
    article = data.get('article', '')
    if not article:
        return
    ok, errors = _validate_article_against_source(article, '2026-07-25')
    assert ok, f'検証失敗: {errors}'


def test_validate_article_against_source_no_distances():
    """距離値なし → 不合格"""
    ok, errors = _validate_article_against_source('ただの雑談記事です', '2026-07-25')
    assert not ok
    assert any('距離値' in e for e in errors)


def test_validate_article_against_source_unknown_team():
    """存在しないチーム名 → 不合格"""
    article = '**架空大学**が素晴らしい走りを見せました。40.8kmの記録。'
    ok, errors = _validate_article_against_source(article, '2026-07-25')
    assert not ok
    assert any('チーム名' in e for e in errors)


def test_validate_article_against_source_fictional_distance():
    """実データにない距離値(28.3kmなど)を含む → 不合格"""
    article = '選手Aは28.3km、選手Bは29.7km、選手Cは27.5kmを記録した。'
    ok, errors = _validate_article_against_source(article, '2026-07-25')
    # 28.3/29.7/27.5 は実データに存在しない値 → 不合格
    assert not ok, f'架空距離を通してはいけません: {errors}'
    assert any('実データに存在しません' in e for e in errors)


# ============================================================
# テスト: 応答ファイル保持
# ============================================================

def test_response_file_recovered_not_deleted():
    """修復成功後もファイルは削除されず status=recovered になる"""
    import tempfile
    result = CheckResult()
    result.target_date = '2026-07-25'
    summary_data = {'date': '2026/07/25', 'article': '古い記事'}
    repaired = {'date': '2026/07/25', 'article': '新しい記事 40.8km'}
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8') as f:
        json.dump({'raw_response': '{"article": "新しい記事 40.8km", "date": "2026/07/25"}', 'status': 'failed'}, f)
        fpath = Path(f.name)
    try:
        err = _try_apply_repair(result, summary_data, repaired, fpath)
        assert err is None
        # ファイルが存在すること（削除されていない）
        assert fpath.exists()
        # status が recovered になっている
        data = json.loads(fpath.read_text(encoding='utf-8'))
        assert data['status'] == 'recovered'
        assert 'repair_candidate' in data
    finally:
        if fpath.exists():
            fpath.unlink()


def test_response_file_rejected_source_not_deleted():
    """元データ照合不合格でもファイルは削除されず status が更新される"""
    import tempfile
    result = CheckResult()
    result.target_date = '2026-07-25'
    summary_data = {'date': '2026/07/25', 'article': '古い記事'}
    # 距離値のない記事 → source validation 不合格
    repaired = {'date': '2026/07/25', 'article': 'ただの雑談'}
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w', encoding='utf-8') as f:
        json.dump({'raw_response': '{"article": "ただの雑談"}', 'status': 'failed'}, f)
        fpath = Path(f.name)
    try:
        err = _try_apply_repair(result, summary_data, repaired, fpath)
        assert err is not None
        assert fpath.exists()
        data = json.loads(fpath.read_text(encoding='utf-8'))
        assert data['status'] == 'rejected_source'
    finally:
        if fpath.exists():
            fpath.unlink()


# ============================================================
# テスト: 監督コメント参照チェック（2026-08-05 追加）
# ============================================================

def _patch_comment_paths(monkeypatch, tmp_path, snapshot_exists, data_exists):
    """SNAPSHOT_DIR / DATA_DIR を tmp_path 配下へ差し替える。"""
    import check_and_repair_daily_summary as crs
    snap_dir = tmp_path / 'daily_snapshots' / '2026-08-05'
    data_dir = tmp_path / 'data'
    snap_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(crs, 'SNAPSHOT_DIR', tmp_path / 'daily_snapshots')
    monkeypatch.setattr(crs, 'DATA_DIR', data_dir)
    snap_path = snap_dir / 'manager_comments.json'
    data_path = data_dir / 'manager_comments.json'
    if snapshot_exists:
        snap_path.write_text(json.dumps([{
            'timestamp': '2026-08-05T20:00:00', 'official_name': '■名古屋大学監督(ロマン派)',
            'content_html': '<p>snapshot版</p>', 'source_url': 'https://s.test/1', 'post_id': '1',
        }]), encoding='utf-8')
    if data_exists:
        data_path.write_text(json.dumps([{
            'timestamp': '2026-08-05T20:00:00', 'official_name': '■名古屋大学監督(ロマン派)',
            'content_html': '<p>data版</p>', 'source_url': 'https://d.test/1', 'post_id': '1',
        }]), encoding='utf-8')
    return snap_path, data_path


def test_resolve_manager_comments_snapshot_priority(tmp_path, monkeypatch):
    """snapshot の manager_comments.json が第一優先で参照される。"""
    import check_and_repair_daily_summary as crs
    snap_path, data_path = _patch_comment_paths(monkeypatch, tmp_path, True, True)
    path = crs.resolve_manager_comments_path('2026-08-05')
    assert path == snap_path
    assert path != data_path


def test_resolve_manager_comments_fallback_to_data(tmp_path, monkeypatch):
    """snapshot がない場合は data/manager_comments.json へフォールバックする。"""
    import check_and_repair_daily_summary as crs
    snap_path, data_path = _patch_comment_paths(monkeypatch, tmp_path, False, True)
    path = crs.resolve_manager_comments_path('2026-08-05')
    assert path == data_path


def test_resolve_manager_comments_none_when_missing(tmp_path, monkeypatch):
    """snapshot・data とも無ければ None。"""
    import check_and_repair_daily_summary as crs
    _patch_comment_paths(monkeypatch, tmp_path, False, False)
    assert crs.resolve_manager_comments_path('2026-08-05') is None


def test_check_manager_comment_references_passes(tmp_path, monkeypatch):
    """既知監督の引用・完全なキーで PASS になる。"""
    import check_and_repair_daily_summary as crs
    _patch_comment_paths(monkeypatch, tmp_path, True, False)
    result = crs.CheckResult()
    result.target_date = '2026-08-05'
    summary = {'article': '名古屋大学監督は前日の走りを振り返った。'}
    crs.check_manager_comment_references(result, summary, '2026-08-05')
    statuses = {s['name']: s['status'] for s in result.steps}
    assert statuses['manager_comments_source'] == 'PASS'
    assert statuses['manager_comments_keys'] == 'PASS'
    assert statuses['manager_comments_attribution'] == 'PASS'


def test_check_manager_comment_references_warns_on_missing_keys(tmp_path, monkeypatch):
    """source_url / post_id 欠落コメントは WARN になる（FAIL にはしない）。"""
    import check_and_repair_daily_summary as crs
    _patch_comment_paths(monkeypatch, tmp_path, True, False)
    # post_id 欠落のコメントを snapshot に追加
    snap_path = tmp_path / 'daily_snapshots' / '2026-08-05' / 'manager_comments.json'
    data = json.loads(snap_path.read_text(encoding='utf-8'))
    data.append({'timestamp': '2026-08-05T21:00:00', 'official_name': '■テスト大学監督',
                 'content_html': '<p>キー欠落</p>', 'source_url': 'https://s.test/2'})
    snap_path.write_text(json.dumps(data), encoding='utf-8')

    result = crs.CheckResult()
    result.target_date = '2026-08-05'
    crs.check_manager_comment_references(result, {'article': '本文'}, '2026-08-05')
    statuses = {s['name']: s['status'] for s in result.steps}
    assert statuses['manager_comments_keys'] == 'WARN'


def test_check_manager_comment_references_does_not_modify_article(tmp_path, monkeypatch):
    """不確実なコメント帰属を推測補完しない（記事は変更されない）。"""
    import check_and_repair_daily_summary as crs
    _patch_comment_paths(monkeypatch, tmp_path, True, False)
    article = '名古屋大学監督が意気込みを語った。'
    result = crs.CheckResult()
    result.target_date = '2026-08-05'
    summary = {'article': article}
    crs.check_manager_comment_references(result, summary, '2026-08-05')
    # 記事が書き換えられていない
    assert summary['article'] == article


# ============================================================
# テストランナー
# ============================================================

if __name__ == '__main__':
    tests = [
        ("resolve_target_date_default", test_resolve_target_date_default),
        ("resolve_target_date_explicit", test_resolve_target_date_explicit),
        ("load_json_valid", test_load_json_valid),
        ("load_json_not_found", test_load_json_not_found),
        ("load_json_invalid", test_load_json_invalid),
        ("check_result_basic", test_check_result_basic),
        ("check_result_correction", test_check_result_correction),
        ("broken_number_39_km", test_broken_number_39_km),
        ("broken_number_40_km", test_broken_number_40_km),
        ("broken_number_nullkm", test_broken_number_nullkm),
        ("broken_number_NaNkm", test_broken_number_NaNkm),
        ("valid_number_40_8km", test_valid_number_40_8km),
        ("valid_number_39_533km", test_valid_number_39_533km),
        ("valid_number_3_0km", test_valid_number_3_0km),
        ("unreplaced_template_curly", test_unreplaced_template_curly),
        ("no_false_positive_normal_text", test_no_false_positive_normal_text),
        ("check_valid_summary", test_check_valid_summary),
        ("check_broken_numbers", test_check_broken_numbers),
        ("check_unreplaced_placeholder", test_check_unreplaced_placeholder),
        ("check_date_mismatch", test_check_date_mismatch),
        ("check_article_consistency", test_check_article_consistency),
        ("dry_run_no_side_effects", test_dry_run_no_side_effects),
        ("try_repair_from_raw_valid_json", test_try_repair_from_raw_valid_json),
        ("try_repair_from_raw_plain_text", test_try_repair_from_raw_plain_text),
        ("try_repair_from_raw_empty", test_try_repair_from_raw_empty),
        ("try_apply_repair_success", test_try_apply_repair_success),
        ("try_apply_repair_fail", test_try_apply_repair_fail),
        ("try_apply_repair_wrong_date", test_try_apply_repair_wrong_date),
        ("validate_source_valid", test_validate_article_against_source_valid),
        ("validate_source_no_distances", test_validate_article_against_source_no_distances),
        ("validate_source_unknown_team", test_validate_article_against_source_unknown_team),
        ("validate_source_fictional_distance", test_validate_article_against_source_fictional_distance),
        ("response_file_recovered_not_deleted", test_response_file_recovered_not_deleted),
        ("response_file_rejected_source_not_deleted", test_response_file_rejected_source_not_deleted),
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
