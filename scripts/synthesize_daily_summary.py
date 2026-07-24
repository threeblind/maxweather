#!/usr/bin/env python3
"""
scripts/synthesize_daily_summary.py

Gemini/OpenAI 両方で記事案を生成し、第三段階の AI 編集で 1 本に統合する。
既存の generate_daily_summary.py の単独生成フローは変更しない。
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# プロジェクトルートのパス
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
HISTORY_DATA_DIR = PROJECT_ROOT / "history_data"

# --- 環境変数設定 ---
SYNTHESIS_PROVIDER = os.getenv("SUMMARY_SYNTHESIS_PROVIDER", "openai").strip().lower()
SYNTHESIS_MODEL = os.getenv("SUMMARY_SYNTHESIS_MODEL", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# --- ファイルパス ---
REALTIME_REPORT_FILE = DATA_DIR / "realtime_report.json"
EKIDEN_DATA_FILE = CONFIG_DIR / "ekiden_data.json"
RANK_HISTORY_FILE = DATA_DIR / "rank_history.json"
INDIVIDUAL_RESULTS_FILE = DATA_DIR / "individual_results.json"
MANAGER_COMMENTS_FILE = DATA_DIR / "manager_comments.json"
PLAYER_STORY_CONTEXT_FILE = CONFIG_DIR / "player_story_context.json"
TEAM_STORY_CONTEXT_FILE = CONFIG_DIR / "team_story_context.json"
LEG_STORY_CONTEXT_FILE = CONFIG_DIR / "leg_story_context.json"
DAILY_SUMMARY_FILE = DATA_DIR / "daily_summary.json"
ARTICLE_HISTORY_FILE = HISTORY_DATA_DIR / "article_history.json"
NARRATIVE_STATE_FILE = DATA_DIR / "race_narrative_state.json"

SYNTHESIS_PROMPT_FILE = CONFIG_DIR / "summary_synthesis_prompt_template.txt"


def load_json(file_path, default=None):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(file_path, data):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_all_data():
    """generate_daily_summary.py と同じデータ読込"""
    data = {}
    files_to_load = {
        "realtime_report": REALTIME_REPORT_FILE,
        "ekiden_data": EKIDEN_DATA_FILE,
        "rank_history": RANK_HISTORY_FILE,
        "individual_results": INDIVIDUAL_RESULTS_FILE,
        "manager_comments": MANAGER_COMMENTS_FILE,
        "player_story_context": PLAYER_STORY_CONTEXT_FILE,
        "team_story_context": TEAM_STORY_CONTEXT_FILE,
        "leg_story_context": LEG_STORY_CONTEXT_FILE,
    }
    for key, file_path in files_to_load.items():
        loaded = load_json(file_path)
        if loaded is None:
            if key in (
                "manager_comments",
                "player_story_context",
                "team_story_context",
                "leg_story_context",
                "individual_results",
            ):
                print(f"情報: {file_path.name} が見つからないためスキップします。")
                data[key] = [] if key == "manager_comments" else {}
            else:
                print(f"エラー: 必須データ '{file_path}' が見つかりません。")
                sys.exit(1)
        else:
            data[key] = loaded
    return data


def load_synthesis_prompt_template():
    """統合編集プロンプトテンプレートを読み込む"""
    if SYNTHESIS_PROMPT_FILE.exists():
        with open(SYNTHESIS_PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
    # 既定のテンプレート
    return DEFAULT_SYNTHESIS_TEMPLATE


def format_race_facts(all_data):
    """本日のレース事実データをテキスト形式に整形（簡易版）"""
    report = all_data.get("realtime_report", {})
    lines = [f"更新時刻: {report.get('updateTime', '不明')}"]
    lines.append(f"レース日: {report.get('raceDay', '?')}日目\n")

    teams_data = report.get("teams", [])
    if isinstance(teams_data, dict):
        teams_data = teams_data.values()
    teams_sorted = sorted(teams_data, key=lambda t: t.get("overallRank") if isinstance(t.get("overallRank"), (int, float)) else 999)

    for t in teams_sorted:
        runner = t.get("runner", "")
        td = t.get("todayDistance", 0)
        total = t.get("totalDistance", 0)
        rank = t.get("overallRank", "?")
        leg = t.get("currentLeg", 1)
        lines.append(
            f"  {rank}位 {t.get('name', '?')} "
            f"(走行中: {runner}, 本日: {td}km, 総合: {total}km, 区間: {leg}区)"
        )

    # レース展開情報
    lines.append("")
    report_text = report.get("breakingNewsFullText", "")
    if report_text:
        lines.append("【レース展開】")
        lines.append(report_text)

    # 順位変動
    rank_changes = _calc_rank_changes(all_data)
    if rank_changes:
        lines.append("\n【前日からの順位変動】")
        for team_name, change in sorted(
            rank_changes.items(), key=lambda x: -abs(x[1]["diff"])
        ):
            if change["diff"] != 0:
                lines.append(
                    f"  {team_name}: {change['prev']}位→{change['current']}位 "
                    f"({'+' if change['diff'] > 0 else ''}{change['diff']})"
                )

    return "\n".join(lines)


def _calc_rank_changes(all_data):
    """前日からの順位変動を計算"""
    report = all_data.get("realtime_report", {})
    rank_history = all_data.get("rank_history", {})
    race_day = report.get("raceDay")
    try:
        day_idx = int(race_day) - 1
    except (TypeError, ValueError):
        return {}

    teams_data = report.get("teams", [])
    if isinstance(teams_data, dict):
        teams_data = teams_data.values()

    changes = {}
    for t in teams_data:
        name = t.get("name", "")
        current_rank = t.get("overallRank")
        if current_rank is None:
            continue
        prev_rank = None
        hist = next(
            (
                ht
                for ht in rank_history.get("teams", [])
                if ht.get("name") == name
            ),
            None,
        )
        if hist and day_idx > 0:
            prev_ranks = hist.get("ranks", [])
            if len(prev_ranks) >= day_idx:
                prev_rank = prev_ranks[day_idx - 1]
        if prev_rank is not None and prev_rank != current_rank:
            changes[name] = {
                "prev": prev_rank,
                "current": current_rank,
                "diff": prev_rank - current_rank,
            }
    return changes


def _call_ai(prompt_text, provider, model="", dry_run=False):
    """AIプロバイダーを呼び出して記事を生成"""
    if dry_run:
        return f"[{provider} dry-run] 生成された記事"

    api_key = GEMINI_API_KEY if provider == "gemini" else OPENAI_API_KEY
    if not api_key:
        print(f"エラー: 環境変数が未設定です (provider={provider})")
        return None
    selected_model = model or (GEMINI_MODEL if provider == "gemini" else OPENAI_MODEL)

    try:
        if provider == "gemini":
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=selected_model, contents=prompt_text
            )
            return response.text
        else:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=selected_model,
                messages=[{"role": "user", "content": prompt_text}],
            )
            return response.choices[0].message.content
    except Exception as e:
        print(f"エラー: {provider} API呼び出し失敗: {e}")
        return None


def format_article_with_markdown(article_text):
    """generate_daily_summary.py の format_article_with_markdown と同等"""
    text = re.sub(
        r"^■\s*(.+)$", r"### \1", article_text, flags=re.MULTILINE
    )
    text = re.sub(r"^【(.+)】$", r"#### \1", text, flags=re.MULTILINE)
    return text


def validate_article(article_text, all_data):
    """generate_daily_summary.py の validate_generated_article を利用"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from generate_daily_summary import DailySummaryGenerator
    except ModuleNotFoundError as e:
        print(f"❌ バリデーションに必要な依存モジュールが不足しています: {e}")
        print("   導入手順: pip install -r requirements.txt")
        return False  # 依存不足なら保存を中止

    gen = DailySummaryGenerator.__new__(DailySummaryGenerator)
    gen.all_data = all_data

    report = all_data.get("realtime_report", {})
    metrics = {
        "rank_changes": _calc_rank_changes(all_data),
        "race_day": report.get("raceDay"),
    }

    # validate_generated_article は警告があれば print、True/False を返す
    import io
    from contextlib import redirect_stdout

    f = io.StringIO()
    with redirect_stdout(f):
        success = gen.validate_generated_article(article_text, metrics)

    warnings_output = f.getvalue()
    if "検証警告" in warnings_output:
        print(warnings_output)
        return False
    return success




def run_synthesis(dry_run=False, no_write=False, save_drafts_dir=None):
    """統合編集のメインフロー"""
    print("=" * 60)
    print("記事統合編集を開始します")
    print("=" * 60)

    # 1. データ読み込み
    print("\n1. データを読み込み中...")
    all_data = load_all_data()

    # 2. レース事実データを整形
    print("2. レース事実データを準備中...")
    race_facts = format_race_facts(all_data)

    # 3. Gemini 記事案を生成
    print(f"\n3. Gemini 記事案を生成中...")
    gemini_prompt = _build_draft_prompt(all_data, "gemini", dry_run=dry_run)
    gemini_article = _call_ai(gemini_prompt, "gemini", dry_run=dry_run)
    if gemini_article is None and not dry_run:
        print("❌ Gemini 記事案の生成に失敗しました。終了します。")
        return False
    if save_drafts_dir:
        Path(save_drafts_dir).mkdir(parents=True, exist_ok=True)
        with open(Path(save_drafts_dir) / "gemini_draft.md", "w") as f:
            f.write(gemini_article or "")
    print(f"   Gemini 記事案: {len(gemini_article or '')}文字")

    # 4. OpenAI 記事案を生成
    print(f"\n4. OpenAI 記事案を生成中...")
    openai_prompt = _build_draft_prompt(all_data, "openai", dry_run=dry_run)
    openai_article = _call_ai(openai_prompt, "openai", dry_run=dry_run)
    if openai_article is None and not dry_run:
        print("❌ OpenAI 記事案の生成に失敗しました。終了します。")
        return False
    if save_drafts_dir:
        with open(Path(save_drafts_dir) / "openai_draft.md", "w") as f:
            f.write(openai_article or "")
    print(f"   OpenAI 記事案: {len(openai_article or '')}文字")

    # 5. 統合編集
    print(f"\n5. 統合編集 AI を呼び出し中...")
    template = load_synthesis_prompt_template()
    synthesis_prompt = (
        template.replace("{race_facts}", race_facts)
        .replace("{gemini_article}", gemini_article or "(生成失敗)")
        .replace("{openai_article}", openai_article or "(生成失敗)")
    )

    if dry_run:
        print("\n[dry-run] 統合プロンプト (先頭500文字):")
        print(synthesis_prompt[:500])
        if save_drafts_dir:
            with open(Path(save_drafts_dir) / "synthesis_prompt.txt", "w") as f:
                f.write(synthesis_prompt)
        return True

    synthesis_provider = SYNTHESIS_PROVIDER
    synthesis_model = SYNTHESIS_MODEL or ""
    final_article = _call_ai(
        synthesis_prompt, synthesis_provider, model=synthesis_model
    )
    if final_article is None:
        print("❌ 統合記事の生成に失敗しました。")
        return False

    # Markdown整形
    final_article = format_article_with_markdown(final_article)

    if save_drafts_dir:
        with open(Path(save_drafts_dir) / "synthesized_final.md", "w") as f:
            f.write(final_article)

    # 6. 検証・保存
    print(f"\n6. 最終記事を検証・保存中...")
    print(f"   統合記事: {len(final_article)}文字")
    return save_article_if_valid(final_article, all_data, synthesis_prompt, no_write)


def _build_draft_prompt(all_data, provider, dry_run=False):
    """生成プロンプトを DailySummaryGenerator._build_prompt で構築する"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from generate_daily_summary import DailySummaryGenerator, NARRATIVE_STATE_FILE
    except ModuleNotFoundError as e:
        print(f"❌ プロンプト生成に必要な依存モジュールが不足しています: {e}")
        print("   導入手順: pip install -r requirements.txt")
        sys.exit(1)

    gen = DailySummaryGenerator.__new__(DailySummaryGenerator)
    gen.all_data = all_data
    gen.provider = provider
    gen.dry_run = False
    # 物語状態はインスタンス変数として設定
    try:
        with open(NARRATIVE_STATE_FILE, "r") as f:
            gen.narrative_state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        gen.narrative_state = {}

    # _build_prompt は race_day を引数に取る
    report = all_data.get("realtime_report", {})
    race_day = report.get("raceDay")
    try:
        race_day_int = int(race_day)
    except (TypeError, ValueError):
        race_day_int = 0

    # _build_prompt は DaySummaryGenerator のメソッド
    # 引数 (self, teams_sorted, lead_battle, seed_battle, additional_context)
    # calculate_race_metrics を呼んで metrics を取得
    gen_load_all_data = getattr(gen, "load_all_data", None)
    calc_metrics = getattr(gen, "calculate_race_metrics", None)

    prompt_text = None
    if calc_metrics:
        metrics = calc_metrics()
        # _build_prompt は戻り値 (prompt, additional_context)
        build_func = getattr(gen, "_build_prompt", None)
        if build_func:
            teams_sorted = metrics.get("teams_sorted", [])
            lead_battle = metrics.get("lead_battle")
            seed_battle = metrics.get("seed_battle")
            additional_context = metrics.get("additional_context", "")
            prompt_result = build_func(teams_sorted, lead_battle, seed_battle, additional_context)
            if isinstance(prompt_result, tuple):
                prompt_text = prompt_result[0]

    if not prompt_text:
        if dry_run:
            # dry-run 時のみ簡易プロンプトで続行
            race_day_str = report.get("raceDay", "?")
            prompt_text = (
                f"あなたは全国大学対抗高温駅伝の実況ライターです。"
                f"以下のレースデータをもとに、{race_day_str}日目の記事を作成してください。\n\n"
                f"{format_race_facts(all_data)}"
            )
        else:
            print("❌ 既存のプロンプト構築に失敗しました（_build_promptがNoneまたは無効な戻り値）")
            sys.exit(1)

    return prompt_text


def _safe_save_json(file_path, data):
    """一時ファイルに書き込んでから os.replace で原子更新"""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix=file_path.stem + "_", dir=file_path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, str(file_path))
    except Exception:
        # 後片付け
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_article_if_valid(article_text, all_data, prompt_text, no_write=False):
    """バリデーションを先に実行し、成功時のみ保存（no_write時は保存スキップ）"""
    # 常にバリデーションを実行
    print("最終記事を検証中...")
    if not validate_article(article_text, all_data):
        print("❌ バリデーション警告があります。保存を中断します。")
        return False

    if no_write:
        print("--no-write: バリデーション通過。保存はスキップします。")
        return True

    # daily_summary.json
    report = all_data.get("realtime_report", {})
    summary_data = {
        "updateTime": report.get("updateTime", datetime.now().strftime("%Y/%m/%d %H:%M")),
        "article": article_text,
        "raceDay": report.get("raceDay"),
    }
    _safe_save_json(DAILY_SUMMARY_FILE, summary_data)
    print(f"✅ daily_summary.json を更新しました。")

    # article_history.json
    history = load_json(ARTICLE_HISTORY_FILE, [])
    new_entry = {
        "date": summary_data["updateTime"].split(" ")[0],
        "prompt": prompt_text,
        "article": article_text,
    }
    _safe_save_json(ARTICLE_HISTORY_FILE, [new_entry] + history)
    print(f"✅ article_history.json を更新しました。")

    # race_narrative_state.json（簡易更新: updated_day を進める）
    narrative = load_json(NARRATIVE_STATE_FILE, {"updated_day": 0})
    narrative["updated_day"] = report.get("raceDay", narrative.get("updated_day", 0))
    _safe_save_json(NARRATIVE_STATE_FILE, narrative)
    print(f"✅ race_narrative_state.json を更新しました。")

    return True


# --- 既定の統合編集プロンプトテンプレート ---

DEFAULT_SYNTHESIS_TEMPLATE = """あなたは全国大学対抗高温駅伝の最終編集者です。
以下の「本日のレース事実データ」「Gemini案」「OpenAI案」を使い、事実に基づく完成記事を1本だけ作成してください。

# 編集方針
- 数値、順位、順位変動、選手名、距離は本日のレース事実データを正本とする。
- OpenAI案の構造・事実整理を基本にする。
- Gemini案の実況感・熱量は、事実データに根拠がある表現だけ取り入れる。
- 片方の記事にしかない情報は、事実データで確認できる場合だけ採用する。
- 事実データにない心理、天候、観客反応、監督発言、将来の結果は創作しない。
- 「執念」「必死」「プレッシャー」「圧倒的」等は、順位差・順位変動・タスキ・提供コメント等の根拠がある場合だけ使用する。
- 数値は展開上意味があるものだけ使い、数値を連続列挙しない。数値を使う場合、その差・順位・変動が何を意味するか同じ文脈で説明する。
- 首位争い、上位〜中位の混戦、シード権争い等から最低3カテゴリを扱う。
- 特定1チームに集中しすぎず、本文で5〜8チームを重点的に扱う。全チームを均等に列挙しない。
- 同じ争いを複数見出しで重複させない。
- 前日から順位が上がっていないチームに「浮上」「ジャンプアップ」「逆転」を結果断定として使わない。
- 「逆転を狙う」「浮上の可能性」等の将来表現は、実績の順位変動と区別する。
- 最後は本文の繰り返しではなく、翌日に残る具体的な争点で締める。

# 出力形式
- 完成記事本文だけを出力し、編集方針・比較結果・前置きは出力しない。
- 1行目は#タイトル。
- ###メイン見出しは1つ。
- ####小見出しは2〜4つ。
- 最後の小見出しは必ず「今日の総括・明日への展望」。
- 1400〜2600字程度。
- 数値だけの羅列は禁止。

# 本日のレース事実データ
{race_facts}

# Gemini案
{gemini_article}

# OpenAI案
{openai_article}
"""


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Gemini/OpenAI の両方で記事案を生成し、AI編集で1本に統合する"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIを呼ばず、統合プロンプトの確認だけ行う",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="APIは呼ぶが daily_summary.json 等へ書き込まない",
    )
    parser.add_argument(
        "--save-drafts",
        type=str,
        default=None,
        metavar="DIR",
        help="Gemini/OpenAI/統合の各案を DIR へ保存する",
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()
    success = run_synthesis(
        dry_run=args.dry_run,
        no_write=args.no_write,
        save_drafts_dir=args.save_drafts,
    )
    if success:
        print("\n✅ 統合編集が正常に完了しました。")
    else:
        print("\n❌ 統合編集に失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
