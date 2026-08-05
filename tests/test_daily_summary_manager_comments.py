"""
generate_daily_summary.py の監督コメントAI入力（prepare_manager_comments）のテスト。

修正内容 (scripts/generate_daily_summary.py, 2026-08-05):
- prepare_manager_comments(): 直近48時間のコメントを投稿時刻順で両側（最新6件+古い6件）選定し、
  各コメントに投稿日時・監督名・出典・source/post_id のメタデータを付けて返す
- prompt見出しを「昨晩の監督コメント」固定から「監督コメント（投稿時刻順、分類前の判断材料）」へ変更
- 「今日/昨日」の断定分類はしない（19時を境界に機械分類しない）
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import generate_daily_summary as gds
from time_utils import JST

NOW_JST = datetime(2026, 8, 5, 21, 0, tzinfo=JST)  # 固定の現在時刻（JST）


def _mk_comment(ts_str, post_id, text='<p>名古屋大学 5区2日目 多治見 31.5km</p>',
                url='https://kizuna.5ch.io/test/read.cgi/sky/1782726210/', kind='5ch'):
    return {
        'timestamp': ts_str,
        'posted_name': '■名古屋大学監督(ロマン派)',
        'official_name': '■名古屋大学監督(ロマン派)',
        'tripcode': '◆Ai4OO8X72O3b',
        'content_html': text,
        'source_url': url,
        'source_kind': kind,
        'post_id': post_id,
    }


def _make_gen(comments, update_time='2026/08/05 20:55'):
    """DailySummaryGenerator を軽量生成する（__init__ 副作用なし）。"""
    gen = gds.DailySummaryGenerator.__new__(gds.DailySummaryGenerator)
    gen.all_data = {
        "ekiden_data": {"teams": []},
        "realtime_report": {"teams": [], "raceDay": 13, "updateTime": update_time},
        "rank_history": {"teams": []},
        "individual_results": {},
        "manager_comments": comments,
        "player_story_context": {},
        "team_story_context": {},
        "leg_story_context": {},
    }
    gen.narrative_state = {}
    gen.dry_run = True
    return gen


def test_both_day_comments_included(monkeypatch):
    """当日の夜間コメントと前日の朝コメント（前日振り返り）が同時に候補へ含まれる。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [
        _mk_comment('2026-08-05T20:30:00', '200', text='<p>本日の走りを振り返る夜のコメント</p>'),
        _mk_comment('2026-08-04T06:30:00', '150', text='<p>前日の走りを振り返る朝のコメント</p>'),
    ]
    lines = _make_gen(comments).prepare_manager_comments()
    assert len(lines) == 2
    joined = "\n".join(lines)
    assert '2026/08/05 20:30' in joined
    assert '2026/08/04 06:30' in joined


def test_old_comments_not_dropped_when_many(monkeypatch):
    """コメントが多い場合も最新6件+古い6件を残し、前日コメントが消えない。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = []
    # 当日側: 14件（08/05 19:00〜20:59）
    for i in range(14):
        ts = datetime(2026, 8, 5, 19, 0, tzinfo=JST) + timedelta(minutes=i)
        comments.append(_mk_comment(ts.strftime('%Y-%m-%dT%H:%M:%S'), str(100 + i),
                                    text=f'<p>当日コメント {i}</p>'))
    # 前日側: 2件（08/04 朝）
    comments.append(_mk_comment('2026-08-04T06:00:00', '1', text='<p>前日振り返りA</p>'))
    comments.append(_mk_comment('2026-08-04T06:10:00', '2', text='<p>前日振り返りB</p>'))

    lines = _make_gen(comments).prepare_manager_comments()
    assert len(lines) == 12  # 最新6 + 古い6
    joined = "\n".join(lines)
    # 前日のコメントが選定から消えていない
    assert '2026/08/04 06:00' in joined
    assert '2026/08/04 06:10' in joined
    # 最新側も含まれる
    assert '2026/08/05 19:00' in joined


def test_metadata_included(monkeypatch):
    """各コメントに comment_key（source_url#post_id）・投稿日時・監督名・出典が付く。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [_mk_comment('2026-08-05T20:30:00', '200')]
    lines = _make_gen(comments).prepare_manager_comments()
    line = lines[0]
    assert 'comment_key: https://kizuna.5ch.io/test/read.cgi/sky/1782726210/#200' in line
    assert '投稿日時: 2026/08/05 20:30 JST' in line
    assert '監督: ■名古屋大学監督(ロマン派)' in line
    assert '出典: 5ch' in line
    assert '内容: 「' in line


def test_prompt_heading_is_neutral(monkeypatch):
    """prompt見出しが「昨晩の監督コメント」固定でなく中立な見出しになる。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    gen = _make_gen([_mk_comment('2026-08-05T20:30:00', '200')])
    metrics = gen.calculate_race_metrics()
    prompt = gen.build_user_prompt(metrics)
    assert '# 監督コメント（投稿時刻順、分類前の判断材料）' in prompt
    assert '# 昨晩の監督コメント' not in prompt
    # AI向け指示も含まれる
    assert '# 監督コメントの扱い方（判断材料と指示）' in prompt
    assert '19時を固定的な正解にせず' in prompt


def test_no_19h_boundary_classification(monkeypatch):
    """19時を境界として当日/前日を機械断定しない（18時台と20時台が両方含まれる）。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [
        _mk_comment('2026-08-05T18:00:00', '1800', text='<p>18時台のコメント</p>'),
        _mk_comment('2026-08-05T20:00:00', '2000', text='<p>20時台のコメント</p>'),
    ]
    lines = _make_gen(comments).prepare_manager_comments()
    joined = "\n".join(lines)
    assert '18:00' in joined
    assert '20:00' in joined


def test_leg_day_runner_content_kept(monkeypatch):
    """本文に区間・日目・選手名があるコメントをAI判断材料として保持する。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [_mk_comment('2026-08-05T20:30:00', '200',
                            text='<p>名古屋大学 5区2日目 多治見 31.5km 合計66.3km 良いペース</p>')]
    lines = _make_gen(comments).prepare_manager_comments()
    assert '5区2日目' in lines[0]
    assert '多治見' in lines[0]
    assert '31.5km' in lines[0]


def test_invalid_timestamp_skipped(monkeypatch):
    """不正timestampはスキップされ、summary生成を停止しない。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [
        _mk_comment('不正な日時', '1', text='<p>不正</p>'),
        _mk_comment('2026-08-05T20:30:00', '2', text='<p>正常</p>'),
        {},
    ]
    lines = _make_gen(comments).prepare_manager_comments()
    assert len(lines) == 1
    assert '正常' in lines[0]


def test_empty_comments_ok(monkeypatch):
    """manager_comments が空でも既存summary生成が動作する。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    gen = _make_gen([])
    assert gen.prepare_manager_comments() == []
    metrics = gen.calculate_race_metrics()
    prompt = gen.build_user_prompt(metrics)
    assert '# 監督コメント' not in prompt  # コメントなしならセクション自体が現れない


def test_thank_you_comments_excluded(monkeypatch):
    """謝辞コメント（ありがとうございました等）は従来どおり除外される。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [
        _mk_comment('2026-08-05T20:30:00', '1', text='<p>ありがとうございました</p>'),
        _mk_comment('2026-08-05T20:31:00', '2', text='<p>お世話になりました</p>'),
        _mk_comment('2026-08-05T20:32:00', '3', text='<p>通常コメント</p>'),
    ]
    lines = _make_gen(comments).prepare_manager_comments()
    assert len(lines) == 1
    assert '通常コメント' in lines[0]


# --- P1-1: timezone-aware timestamp の JST 変換 ---
def test_parse_timestamp_converts_aware_offsets():
    """+00:00 / +05:00 付き timestamp は JST へ変換される。"""
    gen = _make_gen([])
    assert gen._parse_manager_comment_timestamp(
        _mk_comment('2026-08-03T12:00:00+00:00', '1')) == datetime(2026, 8, 3, 21, 0)
    assert gen._parse_manager_comment_timestamp(
        _mk_comment('2026-08-03T12:00:00+05:00', '2')) == datetime(2026, 8, 3, 16, 0)
    # naive は JST として扱う
    assert gen._parse_manager_comment_timestamp(
        _mk_comment('2026-08-05T19:30:00', '3')) == datetime(2026, 8, 5, 19, 30)
    assert gen._parse_manager_comment_timestamp(_mk_comment('不正', '4')) is None


def test_aware_timestamp_kept_within_48h(monkeypatch):
    """+00:00 付きコメントも JST 換算で48時間窓に残る（P1-1再現）。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    # 2026-08-03T12:00:00+00:00 = 2026-08-03 21:00 JST = 48時間前ちょうど手前（NOW 08-05 21:00）
    lines = _make_gen([_mk_comment('2026-08-03T12:00:00+00:00', '1')]).prepare_manager_comments()
    assert len(lines) == 1


def test_get_summary_target_date_uses_update_time(monkeypatch):
    """対象日は updateTime（JST）を正本に取る（スラッシュ区切り・aware 両対応）。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    assert _make_gen([], update_time='2026/08/05 20:55')._get_summary_target_date() == datetime(2026, 8, 5).date()
    assert _make_gen([], update_time='2026-08-04T15:00:00+00:00')._get_summary_target_date() == datetime(2026, 8, 5).date()
    # updateTime 不正 → now_jst の日付へフォールバック
    assert _make_gen([], update_time='')._get_summary_target_date() == datetime(2026, 8, 5).date()


# --- P1-3: historical 再生成時の参照時刻 ---
def test_historical_reference_time_keeps_target_day_comments(monkeypatch):
    """historical 再生成では updateTime 基準の48時間窓で対象日コメントを保持する。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)  # 現在は 08-05 でも…
    gen = _make_gen([_mk_comment('2026-07-25T08:00:00', '1', text='<p>対象日の朝コメント</p>')],
                    update_time='2026/07/25 23:00')
    # 参照時刻を対象日 updateTime に設定（run_historical_summary.py と同様）
    gen.manager_comments_reference_time = datetime(2026, 7, 25, 23, 0)
    lines = gen.prepare_manager_comments()
    assert len(lines) == 1
    assert '対象日の朝コメント' in lines[0]


# --- P2-1: max_comments 上限 ---
def test_max_comments_limit_enforced(monkeypatch):
    """戻り値は必ず max_comments 件以下（1件指定・0件指定）。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    comments = [_mk_comment(f'2026-08-05T{19 + i // 60}:{i % 60:02d}:00', str(i),
                            text=f'<p>コメント {i}</p>') for i in range(14)]
    gen = _make_gen(comments)
    assert len(gen.prepare_manager_comments(max_comments=1)) <= 1
    assert len(gen.prepare_manager_comments(max_comments=0)) == 0
    assert len(gen.prepare_manager_comments(max_comments=2)) <= 2
    assert len(gen.prepare_manager_comments(max_comments=12)) <= 12
    # 通常の12件選定（最新側+古い側）は維持される
    lines = gen.prepare_manager_comments(max_comments=12)
    assert len(lines) == 12


# --- 最終敵対的再現: summary側の時刻上限（P1） ---
def test_live_future_comment_excluded(monkeypatch):
    """live: 現在時刻より未来のコメントはAIへ渡さない（now=20:00, 投稿21:00 → 0件）。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: datetime(2026, 8, 5, 20, 0, tzinfo=JST))
    gen = _make_gen([_mk_comment('2026-08-05T21:00:00', '1', text='<p>未来コメント</p>')])
    assert gen.prepare_manager_comments() == []


def test_historical_future_comment_excluded(monkeypatch):
    """historical: 参照時刻（updateTime）より後のコメントはAIへ渡さない。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    gen = _make_gen([_mk_comment('2026-07-26T01:00:00', '1', text='<p>対象日後のコメント</p>')],
                    update_time='2026/07/25 23:00')
    gen.manager_comments_reference_time = datetime(2026, 7, 25, 23, 0)
    assert gen.prepare_manager_comments() == []


def test_historical_aware_utc_reference_normalized(monkeypatch):
    """historical: aware UTC の参照時刻も JST 23:00 として判定される。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: NOW_JST)
    # 参照時刻: 2026-07-25T14:00:00+00:00 = 2026-07-25 23:00 JST
    gen = _make_gen([_mk_comment('2026-07-25T22:00:00', '1', text='<p>JST22時=窓内</p>'),
                     _mk_comment('2026-07-25T15:00:00+00:00', '2', text='<p>UTC15時=JST翌日0時=窓外</p>')],
                    update_time='2026-07-25 23:00')
    gen.manager_comments_reference_time = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)
    lines = gen.prepare_manager_comments()
    assert len(lines) == 1
    assert '窓内' in lines[0]


def test_cutoff_and_upper_boundary_kept(monkeypatch):
    """cutoffちょうど・上限ちょうどのコメントは保持される。"""
    monkeypatch.setattr(gds, 'now_jst', lambda: datetime(2026, 8, 5, 20, 0, tzinfo=JST))
    # ref = 2026-08-05 20:00 → cutoff = 2026-08-03 20:00
    comments = [
        _mk_comment('2026-08-03T20:00:00', '1', text='<p>cutoffちょうど</p>'),
        _mk_comment('2026-08-05T20:00:00', '2', text='<p>上限ちょうど</p>'),
    ]
    lines = _make_gen(comments).prepare_manager_comments()
    assert len(lines) == 2
