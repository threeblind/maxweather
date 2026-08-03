"""
process_substitutions.py のテスト。

方針 (leader 承認済み):
- テストは過去交代を現行 config へ戻さず、一時 config/state/HTML (fixture) で実施する。
- 環境変数 (EKIDEN_*) でパスを差し替え、importlib.reload でモジュール定数を再解決する。
- ケース: 走行中交代成功 / 事前交代成功 / 過去区間=review / trip一致・不一致 /
  兼任trip / 文字列・辞書混在 / 未知大学 / 交代後が補欠にない / 重複投稿 /
  複数ブロック全成功 / 複数ブロック1つ不正で全体review / tripなし大学 /
  明示alias / 原子書き込み。
"""
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import process_substitutions as ps
import with_lock as wl


# ---------------------------------------------------------------
# fixture ヘルパー
# ---------------------------------------------------------------

def _load_real_config():
    """現行 config を読み、学連選抜を「交代前」状態（大栃が5区・嬉野が補欠）に戻す。"""
    with open(PROJECT_ROOT / "config" / "ekiden_data.json", encoding="utf-8") as f:
        data = json.load(f)
    for t in data["teams"]:
        if t["id"] == 8:  # 学連選抜
            # 交代後状態を元に戻す: runners[4]=嬉野 → 大栃、substitutes に嬉野追加
            t["runners"][4] = "大栃"
            subs = [r if isinstance(r, str) else r.get("name") for r in t.get("substitutes", [])]
            if "嬉野" not in subs:
                t["substitutes"].append("嬉野")
            t["substituted_out"] = [r for r in t.get("substituted_out", []) if r != "大栃"]
    return data


def _load_real_state():
    with open(PROJECT_ROOT / "data" / "ekiden_state.json", encoding="utf-8") as f:
        return json.load(f)


def _make_html(posts):
    """posts: [(data_id, postusername, content)] → 5ch風 HTML 文字列"""
    parts = []
    for pid, name, content in posts:
        parts.append(
            f'<div class="post" data-id="{pid}">'
            f'<span class="postusername">{name}</span>'
            f'<div class="post-content">{content}</div>'
            f'</div>'
        )
    return "<html><body>" + "".join(parts) + "</body></html>"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """一時ディレクトリに fixture config/state/html を配置し、環境変数を設定して
    process_substitutions モジュールをリロードする。"""
    cfg_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    logs_dir = tmp_path / "logs"
    cfg_dir.mkdir()
    data_dir.mkdir()

    ekiden = _load_real_config()
    (cfg_dir / "ekiden_data.json").write_text(
        json.dumps(ekiden, ensure_ascii=False, indent=2), encoding="utf-8")
    (cfg_dir / "outline.json").write_text(
        json.dumps({"mainThreadUrl": "https://example.test/thread/"}), encoding="utf-8")
    state = _load_real_state()
    (data_dir / "ekiden_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    monkeypatch.setenv("EKIDEN_DATA_FILE", str(cfg_dir / "ekiden_data.json"))
    monkeypatch.setenv("EKIDEN_OUTLINE_FILE", str(cfg_dir / "outline.json"))
    monkeypatch.setenv("EKIDEN_STATE_FILE", str(data_dir / "ekiden_state.json"))
    monkeypatch.setenv("EKIDEN_LOGS_DIR", str(logs_dir))

    importlib.reload(ps)
    yield {
        "ekiden_file": cfg_dir / "ekiden_data.json",
        "state_file": data_dir / "ekiden_state.json",
        "logs_dir": logs_dir,
        "html_file": None,
    }
    importlib.reload(ps)


def _run(env, posts_html):
    html = tmp = None
    # html を一時ファイルに書く
    html_file = env["logs_dir"].parent / "thread.html"
    html_file.write_text(posts_html, encoding="utf-8")
    os.environ["EKIDEN_POSTS_HTML"] = str(html_file)
    importlib.reload(ps)
    ps.process_substitutions()
    del os.environ["EKIDEN_POSTS_HTML"]
    importlib.reload(ps)


def _team_by_id(env, team_id):
    data = json.loads(Path(env["ekiden_file"]).read_text(encoding="utf-8"))
    return next(t for t in data["teams"] if t["id"] == team_id)


def _read_logs(env, name):
    p = env["logs_dir"] / name
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------
# ユニット: トリップ抽出・チーム解決
# ---------------------------------------------------------------

def test_extract_trip_normalizes_space():
    assert ps.extract_trip("■鳥取大学監督（白黒タビー） ◆ CT6iZVF9L") == "◆CT6iZVF9L"
    assert ps.extract_trip("■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6") == "◆oIdAWXadP6"
    assert ps.extract_trip("７７４＠沿道") is None


def test_extract_trip_keeps_trailing_dot():
    # 末尾ドットは勝手に追加しない（投稿側が ◆CT6iZVF9L. ならそのまま）
    assert ps.extract_trip("◆CT6iZVF9L.") == "◆CT6iZVF9L."


def test_get_allowed_trips_from_manager():
    team = {"manager": "■山学大学監督【帰ってきたベストマン】 ◆UXxynGMChpf3"}
    assert ps.get_allowed_trips(team) == {"◆UXxynGMChpf3"}


def test_get_allowed_trips_accepts_array():
    team = {"manager": "◆AAA", "accepted_tripcodes": ["◆BBB", "CCC"]}
    assert ps.get_allowed_trips(team) == {"◆AAA", "◆BBB", "◆CCC"}


def test_build_team_lookup_short_name():
    teams = [{"name": "名古屋大学", "short_name": "名大", "id": 1}]
    lookup = ps.build_team_lookup(teams)
    assert lookup["名古屋大学"]["id"] == 1
    assert lookup["名大"]["id"] == 1


def test_runner_name_mixed():
    assert ps.runner_name("美濃") == "美濃"
    assert ps.runner_name({"name": "府中", "station_code": "67326"}) == "府中"


def test_resolve_runner_name_alias():
    team = {"runners": ["伏木", "福井", "美浜", "大野（福井）"],
            "substitutes": ["金沢"]}
    assert ps.resolve_runner_name(team, "大野") == "大野（福井）"
    assert ps.resolve_runner_name(team, "伏木") == "伏木"
    assert ps.resolve_runner_name(team, "存在しない") is None


# ---------------------------------------------------------------
# ユニット: ブロックパース
# ---------------------------------------------------------------

def test_parse_block_typical():
    block = """
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
４区なら活躍だったので本当に申し訳ないのですが交代です
"""
    d = ps.parse_block(block)
    assert d["university"] == "学連選抜"
    assert d["leg"] == 5
    assert d["runner_out"] == "大栃"
    assert d["runner_in"] == "嬉野"


def test_parse_block_halfwidth_leg():
    block = """
大学名: 福島大学
区間: 3区
交代: 石川→長岡
"""
    d = ps.parse_block(block)
    assert d["leg"] == 3


def test_parse_block_does_not_grab_trailing_text():
    # 交代行の後続テキストは選手名に取り込まれない
    block = """
大学名: 金沢大学
区間: 4区
交代: 今庄→大野
お手間をかけさせてしまい申し訳ありません
"""
    d = ps.parse_block(block)
    assert d["runner_out"] == "今庄"
    assert d["runner_in"] == "大野"


def test_extract_blocks_multiple():
    content = """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
【選手交代】
大学名: 鹿児島大学
区間: ４区
交代: 加久藤→西米良
"""
    blocks = ps.extract_blocks(content)
    assert len(blocks) == 2
    assert ps.parse_block(blocks[0])["university"] == "学連選抜"
    assert ps.parse_block(blocks[1])["university"] == "鹿児島大学"


# ---------------------------------------------------------------
# 統合: 走行中交代 (currentLeg=5, 5区) 成功
# ---------------------------------------------------------------

def test_applies_current_leg_substitution(env):
    posts = _make_html([
        ("178", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """学連選抜
４区２日目　秩父選手　35.9km
【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
４区なら活躍だったので本当に申し訳ないのですが交代です"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][4] == "嬉野", f'runners[4] 期待 嬉野 got {team["runners"][4]}'
    assert "大栃" in team["substituted_out"]
    subs = [r if isinstance(r, str) else r.get("name") for r in team["substitutes"]]
    assert "嬉野" not in subs
    # processed log に記録される
    assert "178" in ps.get_processed_posts()
    # 監査ログに applied
    audits = _read_logs(env, "substitution_audit.jsonl")
    assert any(a["post_id"] == "178" and a["status"] == "applied" for a in audits)


# ---------------------------------------------------------------
# 統合: 事前交代 (currentLeg=4, 5区) 成功
# ---------------------------------------------------------------

def test_applies_next_leg_pre_substitution(env):
    # 学連選抜 currentLeg を 4 に変更
    state = json.loads(Path(env["state_file"]).read_text(encoding="utf-8"))
    for s in state:
        if s["id"] == 8:
            s["currentLeg"] = 4
    Path(env["state_file"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    posts = _make_html([
        ("178", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][4] == "嬉野"


# ---------------------------------------------------------------
# 統合: 過去区間は自動適用せず review
# ---------------------------------------------------------------

def test_past_leg_goes_to_review(env):
    # currentLeg=5 のまま 4区の交代投稿
    posts = _make_html([
        ("200", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ４区
交代: 秩父→我孫子"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][3] == "秩父", "過去区間の交代は適用されない"
    assert "200" not in ps.get_processed_posts()
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "200" and "past_leg" in r["reason"] for r in reviews)


# ---------------------------------------------------------------
# 統合: trip 不一致・兼任
# ---------------------------------------------------------------

def test_trip_mismatch_review(env):
    posts = _make_html([
        ("201", "■三重大学監督（風来の試練）◆g8a8AxWMVk",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][4] == "大栃", "別大学tripでは適用されない"
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "201" and "trip_mismatch" in r["reason"] for r in reviews)


def test_dual_role_manager_trip_allowed(env):
    # 名古屋大学監督 (◆Ai4OO8X72O3b) は広島経済大学 (id=6) も兼任
    # 広島経済大学の現行: runners[3]=加計 (4区), substituted_out=[大竹]
    # 走行中交代を再現するため state の currentLeg を4にし、4区を大竹に戻す
    data = json.loads(Path(env["ekiden_file"]).read_text(encoding="utf-8"))
    for t in data["teams"]:
        if t["id"] == 6:
            t["runners"][3] = "大竹"
            subs = [r if isinstance(r, str) else r.get("name") for r in t["substitutes"]]
            if "加計" not in subs:
                t["substitutes"].append("加計")
            t["substituted_out"] = []
    Path(env["ekiden_file"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    state = json.loads(Path(env["state_file"]).read_text(encoding="utf-8"))
    for s in state:
        if s["id"] == 6:
            s["currentLeg"] = 4
    Path(env["state_file"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    posts = _make_html([
        ("157", "■名古屋大学監督(ロマン派)◆Ai4OO8X72O3b",
         """【選手交代】
大学名: 広島経済大学
区間: 4区
交代: 大竹→加計
本当は3日間走って欲しいところですが加計に賭けます"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 6)
    assert team["runners"][3] == "加計", f'兼任監督の交代が適用される: {team["runners"][3]}'
    assert "大竹" in team["substituted_out"]


# ---------------------------------------------------------------
# 統合: 文字列/辞書混在 runners
# ---------------------------------------------------------------

def test_dict_runner_with_station_code_preserved(env):
    # 鹿児島大学 (id=17): 現行 runners[idx6]=川内 (辞書+station_code)
    # currentLeg=5 のため自動適用候補は 5区/6区。6区(idx5)=大口 を辞書形式に置き換え、
    # 交代後も辞書形式 (station_code 保持) を検証する。
    data = json.loads(Path(env["ekiden_file"]).read_text(encoding="utf-8"))
    for t in data["teams"]:
        if t["id"] == 17:
            # 6区 (idx5) を辞書形式に置き換え
            t["runners"][5] = {"name": "大口", "station_code": "89532"}
            # 既存の文字列「西米良」を辞書形式 (station_code 付き) に置き換え
            t["substitutes"] = [
                {"name": "西米良", "station_code": "87356"} if (r if isinstance(r, str) else r.get("name")) == "西米良" else r
                for r in t["substitutes"]
            ]
    Path(env["ekiden_file"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    posts = _make_html([
        ("210", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 鹿児島大学
区間: ６区
交代: 大口→西米良"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 17)
    # 辞書形式の交代後選手が station_code を保持して runners に入る
    runner6 = team["runners"][5]
    assert isinstance(runner6, dict), "辞書形式が保持される"
    assert runner6["name"] == "西米良"
    assert runner6["station_code"] == "87356", "交代後の station_code が保持される"
    subs = [r for r in team["substitutes"]]
    assert not any((r.get("name") if isinstance(r, dict) else r) == "西米良" for r in subs)
    # substituted_out に辞書形式の「大口」が station_code ごと入る
    outs = team["substituted_out"]
    assert any(isinstance(o, dict) and o.get("name") == "大口" and o.get("station_code") == "89532" for o in outs)


# ---------------------------------------------------------------
# 統合: 未知大学・交代後が補欠にない
# ---------------------------------------------------------------

def test_unknown_team_review(env):
    posts = _make_html([
        ("211", "◆oIdAWXadP6",
         """【選手交代】
大学名: 存在しない大学
区間: ５区
交代: 大栃→嬉野"""),
    ])
    _run(env, posts)
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "211" and "unknown_team" in r["reason"] for r in reviews)


def test_runner_in_not_substitute_review(env):
    posts = _make_html([
        ("212", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→補欠にいない選手"""),
    ])
    _run(env, posts)
    team = _team_by_id(env, 8)
    assert team["runners"][4] == "大栃", "補欠にない選手への交代は適用されない"
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "212" and "runner_in" in r["reason"] for r in reviews)


# ---------------------------------------------------------------
# 統合: 重複投稿 (post_id 冪等)
# ---------------------------------------------------------------

def test_duplicate_post_id_skipped(env):
    posts = _make_html([
        ("178", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野"""),
    ])
    _run(env, posts)
    # 1回目の状態: 適用済み
    team1 = _team_by_id(env, 8)
    assert team1["runners"][4] == "嬉野"

    # 2回目: 同じ post_id を再実行 → スキップ（processed にあるため）
    _run(env, posts)
    team2 = _team_by_id(env, 8)
    assert team2["runners"][4] == "嬉野"
    # substituted_out に大栃が1回だけ
    outs = [o if isinstance(o, str) else o.get("name") for o in team2["substituted_out"]]
    assert outs.count("大栃") == 1


# ---------------------------------------------------------------
# 統合: review/audit ログの重複防止（必須修正1）
# ---------------------------------------------------------------

def test_review_log_not_duplicated_on_rerun(env):
    """検証失敗投稿（例: past_leg）を再実行しても review/audit に同一内容を無限追記しない。"""
    posts = _make_html([
        ("200", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ４区
交代: 秩父→我孫子"""),
    ])
    _run(env, posts)
    _run(env, posts)  # 再実行

    reviews = _read_logs(env, "substitution_review.jsonl")
    audits = _read_logs(env, "substitution_audit.jsonl")
    # 同一 post_id+block_index+status+reason は1件のみ
    r_keys = [(r["post_id"], r["block_index"], r["status"], r["reason"]) for r in reviews]
    a_keys = [(a["post_id"], a["block_index"], a["status"], a["reason"]) for a in audits]
    assert len(r_keys) == len(set(r_keys)), f'review 重複: {r_keys}'
    assert len(a_keys) == len(set(a_keys)), f'audit 重複: {a_keys}'
    # 各1件ずつ
    assert len(reviews) == 1
    assert len(audits) == 1


def test_review_then_applied_keeps_review(env):
    """過去区間で review 記録 → currentLeg が進み再実行 → applied として成功、
    既存 review は残ったまま processed にも進む。"""
    # 学連選抜: runners[3]=秩父(4区)、substitutes=[加賀中津原, 笠利]
    posts = _make_html([
        ("200", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ４区
交代: 秩父→加賀中津原"""),
    ])
    _run(env, posts)
    assert "200" not in ps.get_processed_posts()

    # 学連選抜 currentLeg を 3 に戻す（4区が走行中になる）
    state = json.loads(Path(env["state_file"]).read_text(encoding="utf-8"))
    for s in state:
        if s["id"] == 8:
            s["currentLeg"] = 3
    Path(env["state_file"]).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][3] == "加賀中津原", "currentLeg が進んだ後は適用される"
    assert "200" in ps.get_processed_posts()
    # 既存 review は残っている
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "200" and r["status"] == "review" for r in reviews)
    # applied 監査が追加されている
    audits = _read_logs(env, "substitution_audit.jsonl")
    assert any(a["post_id"] == "200" and a["status"] == "applied" for a in audits)


def test_multiple_blocks_review_keys_separated(env):
    """同一投稿内の複数ブロックは block_index でキーが分離される。"""
    posts = _make_html([
        ("221", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
【選手交代】
大学名: 学連選抜
区間: ４区
交代: 秩父→我孫子"""),
    ])
    _run(env, posts)
    _run(env, posts)  # 再実行しても重複しない

    reviews = _read_logs(env, "substitution_review.jsonl")
    # 2ブロック分（1つは ok だが投稿全体が review になるため両方記録される）
    r_keys = [(r["post_id"], r["block_index"], r["status"], r["reason"]) for r in reviews]
    assert len(r_keys) == len(set(r_keys))
    block_indices = sorted({r["block_index"] for r in reviews if r["post_id"] == "221"})
    assert block_indices == [0, 1], f'block_index が分離されている: {block_indices}'


# ---------------------------------------------------------------
# 統合: 複数ブロック
# ---------------------------------------------------------------

def test_multiple_blocks_all_ok_applies_all(env):
    # 兼任監督が2大学の交代を1投稿に書くケース
    # 学連選抜 (id=8): 5区 大栃→嬉野 (fixture で交代前状態)
    # 鹿児島大学 (id=17): 5区 さつま柏原→西米良 (文字列 runners、currentLeg=5 走行中)
    posts = _make_html([
        ("220", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
【選手交代】
大学名: 鹿児島大学
区間: ５区
交代: さつま柏原→西米良"""),
    ])
    _run(env, posts)

    team8 = _team_by_id(env, 8)
    team17 = _team_by_id(env, 17)
    assert team8["runners"][4] == "嬉野"
    assert team17["runners"][4] == "西米良"
    assert "220" in ps.get_processed_posts()


def test_multiple_blocks_one_bad_review_all(env):
    # 1つ目OK・2つ目不正（過去区間）→ 投稿全体を適用せず review
    posts = _make_html([
        ("221", "■全日本学連選抜監督（夏の日の1994)◆oIdAWXadP6",
         """【選手交代】
大学名: 学連選抜
区間: ５区
交代: 大栃→嬉野
【選手交代】
大学名: 学連選抜
区間: ４区
交代: 秩父→我孫子"""),
    ])
    _run(env, posts)

    team = _team_by_id(env, 8)
    assert team["runners"][4] == "大栃", "1つでも不正があれば全体を適用しない"
    assert "221" not in ps.get_processed_posts()
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "221" for r in reviews)


# ---------------------------------------------------------------
# 統合: trip なし大学
# ---------------------------------------------------------------

def test_no_allowed_trip_team_review(env):
    # 日本大学 (id=11): トリップなし → 自動適用せず review
    posts = _make_html([
        ("230", "◆g8a8AxWMVk",
         """【選手交代】
大学名: 日本大学
区間: 3区
交代: 何か→何か"""),
    ])
    _run(env, posts)
    reviews = _read_logs(env, "substitution_review.jsonl")
    assert any(r["post_id"] == "230" and "no_allowed_trip" in r["reason"] for r in reviews)


# ---------------------------------------------------------------
# ユニット: 原子書き込み
# ---------------------------------------------------------------

def test_atomic_write_json(tmp_path):
    target = tmp_path / "out.json"
    ps.atomic_write_json(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    # 一時ファイルが残らない
    assert list(tmp_path.glob(".tmp_*")) == []


# ---------------------------------------------------------------
# 統合: ロック（with_lock.py の --try モードと realtime 相互排他）
# ---------------------------------------------------------------

def _with_lock_script():
    return str(PROJECT_ROOT / "scripts" / "with_lock.py")


def test_with_lock_try_mode_acquires_and_releases(tmp_path):
    import subprocess
    lockfile = tmp_path / "t.lock"
    # 取得できる状態 → コマンド実行・exit 0
    r = subprocess.run(
        [sys.executable, _with_lock_script(), str(lockfile), "--try", "--",
         sys.executable, "-c", "print('ran')"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "ran" in r.stdout


def test_with_lock_try_mode_fails_when_locked(tmp_path):
    import fcntl
    import subprocess
    lockfile = tmp_path / "t.lock"
    f = open(lockfile, 'a+')
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        # ロック中 → --try は専用終了コードでコマンドを実行しない
        r = subprocess.run(
            [sys.executable, _with_lock_script(), str(lockfile), "--try", "--",
             sys.executable, "-c", "print('SHOULD NOT RUN')"],
            capture_output=True, text=True)
        assert r.returncode == wl.LOCK_BUSY_EXIT
        assert "SHOULD NOT RUN" not in r.stdout
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def test_with_lock_blocking_waits(tmp_path):
    import fcntl
    import subprocess
    import time
    lockfile = tmp_path / "t.lock"
    f = open(lockfile, 'a+')
    fcntl.flock(f, fcntl.LOCK_EX)
    # ロック中でも通常モード（--）はブロッキングで待つ。解放後に実行される。
    proc = subprocess.Popen(
        [sys.executable, _with_lock_script(), str(lockfile), "--",
         sys.executable, "-c", "print('ran-after')"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.3)
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    out, err = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert "ran-after" in out


def test_update_realtime_skips_when_locked(tmp_path, monkeypatch):
    """update_realtime.sh はロック中（交代処理中）に --try で取得できずスキップする。"""
    import subprocess
    lockfile = PROJECT_ROOT / "logs" / "substitution.lock"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    import fcntl
    f = open(lockfile, 'a+')
    fcntl.flock(f, fcntl.LOCK_EX)
    try:
        r = subprocess.run(
            ["bash", str(PROJECT_ROOT / "update_realtime.sh")],
            capture_output=True, text=True, timeout=60, cwd=str(PROJECT_ROOT))
        assert r.returncode == 0
        assert "スキップ" in r.stdout, f'ロック中はスキップされる: {r.stdout[-500:]}'
        # 速報生成が実行されていない（generate_report が走っていない）
        assert "generate_report.py --realtime を実行中" not in r.stdout
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def test_update_realtime_runs_when_unlocked():
    """ロックが解放されていれば update_realtime.sh は通常実行される（テストモードでcommit/push抑制）。"""
    import subprocess
    env = dict(os.environ)
    env["EKIDEN_DISABLE_GIT_PUSH"] = "1"
    r = subprocess.run(
        ["bash", str(PROJECT_ROOT / "update_realtime.sh")],
        capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT), env=env)
    assert r.returncode == 0, f'stdout: {r.stdout[-500:]} stderr: {r.stderr[-500:]}'
    assert "generate_report.py --realtime を実行中" in r.stdout
    assert "選手交代処理の実行中（ロック取得不可）" not in r.stdout


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
