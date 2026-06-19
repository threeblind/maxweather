import sys
from pathlib import Path
import json

# プロジェクトルートをパスに追加
sys.path.append(str(Path(__file__).parent.parent))

from scripts.generate_daily_summary import DailySummaryGenerator

def setup_mock_generator():
    gen = DailySummaryGenerator(dry_run=True)
    # テスト用にモックデータを設定
    gen.all_data = {
        "ekiden_data": {
            "teams": [
                {
                    "id": 1,
                    "name": "名古屋大学",
                    "runners": [{"name": "美濃加茂"}]
                },
                {
                    "id": 2,
                    "name": "金沢大学",
                    "runners": [{"name": "秋ヶ島"}]
                },
                {
                    "id": 3,
                    "name": "琉球大学",
                    "runners": [{"name": "北原"}]
                }
            ]
        },
        "realtime_report": {
            "raceDay": 2,
            "teams": [
                {
                    "name": "名古屋大学",
                    "runner": "美濃加茂",
                    "overallRank": 1,
                    "todayDistance": 29.0,
                    "totalDistance": 60.6,
                    "previousRank": 1
                },
                {
                    "name": "金沢大学",
                    "runner": "秋ヶ島",
                    "overallRank": 2,
                    "todayDistance": 28.2,
                    "totalDistance": 59.3,
                    "previousRank": 6
                },
                {
                    "name": "琉球大学",
                    "runner": "北原",
                    "overallRank": 3,
                    "todayDistance": 28.5,
                    "totalDistance": 58.5,
                    "previousRank": 11
                }
            ]
        }
    }
    gen.narrative_state = {
        "schema_version": 1,
        "updated_day": 1,
        "main_story": {},
        "ongoing_battles": [],
        "momentum": [],
        "runner_threads": [],
        "resolved_stories": []
    }
    return gen

def test_runner_threads_resolution():
    print("--- Test 1: runner_threads_resolution ---")
    gen = setup_mock_generator()
    
    # 走者スレッドの初期状態: 名古屋大学の走者は「美濃加茂」ではなく「昔の走者」だったとする
    gen.narrative_state["runner_threads"] = [
        {
            "runner": "昔の走者",
            "team": "名古屋大学",
            "summary": "1日目の好走",
            "started_day": 1,
            "last_updated_day": 1
        }
    ]
    
    metrics = gen.calculate_race_metrics()
    gen.update_narrative_state(metrics, [])
    
    threads = gen.narrative_state["runner_threads"]
    resolved = gen.narrative_state["resolved_stories"]
    
    # 名古屋大学の現在走者は「美濃加茂」なので、「昔の走者」は resolved_stories に移行しているはず
    assert not any(t["runner"] == "昔の走者" for t in threads), "Error: 旧走者がスレッドに残っています"
    assert any("昔の走者" in r["summary"] for r in resolved), "Error: 旧走者が resolved_stories にありません"
    print("✅ Pass: 旧走者スレッドが正しく resolved_stories へ移行されました。")

def test_runner_threads_goal():
    print("--- Test 2: runner_threads_goal ---")
    gen = setup_mock_generator()
    
    # 琉球大学がゴールしているとする
    gen.all_data["realtime_report"]["teams"][2]["runner"] = "ゴール"
    gen.all_data["realtime_report"]["teams"][2]["finishDay"] = 2
    
    gen.narrative_state["runner_threads"] = [
        {
            "runner": "北原",
            "team": "琉球大学",
            "summary": "快走",
            "started_day": 1,
            "last_updated_day": 1
        }
    ]
    
    metrics = gen.calculate_race_metrics()
    gen.update_narrative_state(metrics, [])
    
    threads = gen.narrative_state["runner_threads"]
    resolved = gen.narrative_state["resolved_stories"]
    
    assert not any(t["runner"] == "北原" for t in threads), "Error: ゴールしたチームの走者が残っています"
    assert any("北原" in r["summary"] for r in resolved), "Error: ゴールした走者が resolved_stories にありません"
    print("✅ Pass: ゴールしたチームの走者が正しく resolved_stories へ移行されました。")

def test_momentum_management():
    print("--- Test 3: momentum_management ---")
    gen = setup_mock_generator()
    
    # 既存の momentum。金沢大学（6位->2位で+4なので本日も上昇中）、別の「過去上昇校」（今日は変化なしとする）
    gen.narrative_state["momentum"] = [
        {
            "team": "金沢大学",
            "summary": "急浮上",
            "started_day": 1,
            "last_updated_day": 1,
            "previous_rank": 6,
            "current_rank": 2,
            "diff": 4
        },
        {
            "team": "過去上昇校",
            "summary": "急浮上",
            "started_day": 1,
            "last_updated_day": 1,
            "previous_rank": 5,
            "current_rank": 5,
            "diff": 0
        }
    ]
    
    metrics = gen.calculate_race_metrics()
    # 琉球大学も 11位->3位で+8上昇した新規 momentum
    gen.update_narrative_state(metrics, [])
    
    momentum = gen.narrative_state["momentum"]
    resolved = gen.narrative_state["resolved_stories"]
    
    # 「過去上昇校」は上昇していないので momentum から消え、resolved_stories に入るはず
    assert not any(m["team"] == "過去上昇校" for m in momentum), "Error: 上昇が止まったチームが momentum に残っています"
    assert any("過去上昇校" in r["summary"] for r in resolved), "Error: 勢いが落ち着いたチームが resolved_stories にありません"
    
    # 琉球大学（+8）と金沢大学（+4）が残り、順位変動幅の降順で琉球大学が最初に来るはず
    assert len(momentum) == 2, "Error: momentum の数がおかしいです"
    assert momentum[0]["team"] == "琉球大学", "Error: 変動幅の大きいチームが優先されていません"
    print("✅ Pass: momentum の寿命、更新、およびソート順が正しく処理されました。")

def test_resolved_stories_deduplication():
    print("--- Test 4: resolved_stories_deduplication ---")
    gen = setup_mock_generator()
    
    # 既に resolved_stories に登録されていると仮定
    gen.narrative_state["resolved_stories"] = [
        {
            "summary": "勢い落ち着く：過去上昇校の急浮上（本日5位）",
            "resolved_day": 2,
            "reason": "勢い低下"
        }
    ]
    
    gen.narrative_state["momentum"] = [
        {
            "team": "過去上昇校",
            "summary": "急浮上",
            "started_day": 1,
            "last_updated_day": 1,
            "previous_rank": 5,
            "current_rank": 5,
            "diff": 0
        }
    ]
    
    metrics = gen.calculate_race_metrics()
    gen.update_narrative_state(metrics, [])
    
    resolved = gen.narrative_state["resolved_stories"]
    # 同じ resolved_entry が重複登録されないはず
    match_count = sum(1 for r in resolved if "過去上昇校" in r["summary"])
    assert match_count == 1, f"Error: 重複登録が発生しています (count={match_count})"
    print("✅ Pass: resolved_stories の重複登録防止が正しく動作しました。")

def test_validation_noun_exclusion():
    print("--- Test 5: validation_noun_exclusion (P1-1) ---")
    gen = setup_mock_generator()
    metrics = gen.calculate_race_metrics()

    # 1. 正常な実況表現（一般修飾語や大会正式名が含まれていても、マスタにあるものだけを検証し、通過する。太字付き）
    article_good = "全国大学対抗高温駅伝で両選手が激走。注目選手は首位を守る**名古屋大学**の**美濃加茂君**が快走。後ろからは**金沢大学**の**秋ヶ島君**と、本日+8の大幅ジャンプアップを遂げた**琉球大学**の**北原君**が猛追します。"
    assert gen.validate_generated_article(article_good, metrics), "Error: 正常な一般名詞の混ざった記事がバリデーション失敗しました"

    # 2. 太字なしの正常表現の通過確認
    article_good_no_bold = "名古屋大学の美濃加茂君が快走。"
    assert gen.validate_generated_article(article_good_no_bold, metrics), "Error: 太字なしの正常表現がバリデーション失敗しました"

    # 3. 架架空大学名や架空選手名（太字なし・助詞境界あり）
    article_bad_uni = "架空大学が本日急浮上しました。"
    assert not gen.validate_generated_article(article_bad_uni, metrics), "Error: 存在しない大学名（架空大学）がパスしてしまいました"

    article_bad_runner = "架空太郎君が快走を見せました。"
    assert not gen.validate_generated_article(article_bad_runner, metrics), "Error: 存在しない選手名（架空太郎君）がパスしてしまいました"

    # 4. 太字で装飾された架空大学名や架空選手名
    article_bad_uni_bold = "**架空大学**が本日急浮上しました。"
    assert not gen.validate_generated_article(article_bad_uni_bold, metrics), "Error: 太字付きの存在しない大学名（**架空大学**）がパスしてしまいました"

    article_bad_runner_bold = "**架空太郎君**が快走しました。"
    assert not gen.validate_generated_article(article_bad_runner_bold, metrics), "Error: 太字付きの存在しない選手名（**架空太郎君**）がパスしてしまいました"

    print("✅ Pass: 一般名詞の除外と、太字装飾（**）有無両方での架空固有名詞の検知が正しく動作しました。")

def test_validation_winner_check():
    print("--- Test 6: validation_winner_check (P1-2) ---")
    gen = setup_mock_generator()
    metrics = gen.calculate_race_metrics()

    # シナリオ1: 未ゴール首位を優勝と書いた場合（太字装飾あり） -> 失敗
    article_win1 = "**名古屋大学**が今大会の優勝を決めた。"
    assert not gen.validate_generated_article(article_win1, metrics), "Error: 未ゴール首位の優勝判定がパスしてしまいました"

    # シナリオ2: 首位ゴール後に2位校を優勝と書いた場合 -> 失敗
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "ゴール"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = 2
    article_win2 = "**金沢大学**が優勝を決めた。"
    assert not gen.validate_generated_article(article_win2, metrics), "Error: 首位以外の優勝記述がパスしてしまいました"

    # シナリオ3: 首位ゴール後に首位校を優勝と書いた場合（太字装飾あり） -> 成功
    article_win3 = "**名古屋大学**が今大会の優勝を決めた。"
    assert gen.validate_generated_article(article_win3, metrics), "Error: 首位ゴール校の正当な優勝記述が失敗しました"

    # シナリオ4: 未ゴール中に「過去に優勝経験」と歴史的記述を書いた場合 -> 成功
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "美濃加茂"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = None
    article_win4 = "過去に優勝経験のある**名古屋大学**は、連覇を目指して戦います。"
    assert gen.validate_generated_article(article_win4, metrics), "Error: 過去の優勝に関する記述が誤検知で失敗しました"

    # 【追加テスト P1-1】
    # 1. 「第2日目、金沢大学が優勝を決めた」 -> 失敗
    article_win_p1_1 = "第2日目、**金沢大学**が優勝を決めた。"
    assert not gen.validate_generated_article(article_win_p1_1, metrics), "Error: 第2日目の金沢大優勝（未ゴール）がパスしてしまいました"

    # 2. 「第2日目、名古屋大学が優勝を決めた」 -> 未ゴール失敗、1位ゴール後成功
    article_win_p1_2 = "第2日目、**名古屋大学**が優勝を決めた。"
    assert not gen.validate_generated_article(article_win_p1_2, metrics), "Error: 第2日目の未ゴール名古屋大優勝がパスしてしまいました"
    
    # 1位ゴール後に設定
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "ゴール"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = 2
    assert gen.validate_generated_article(article_win_p1_2, metrics), "Error: 第2日目のゴール後名古屋大優勝が失敗しました"
    
    # 状態を未ゴールに戻す
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "美濃加茂"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = None

    # 3. 「第15回大会で名古屋大学が優勝した実績がある」 -> 成功
    article_win_p1_3 = "第15回大会で**名古屋大学**が優勝した実績がある。"
    assert gen.validate_generated_article(article_win_p1_3, metrics), "Error: 過去の優勝実績記述が失敗しました"

    # 4. 「連覇経験を持つ名古屋大学」 -> 成功
    article_win_p1_4 = "連覇経験を持つ**名古屋大学**が好走。"
    assert gen.validate_generated_article(article_win_p1_4, metrics), "Error: 連覇経験記述が失敗しました"

    # 5. 「3連覇となる優勝を決めた」 -> 1位ゴールなら成功、それ以外は失敗
    article_win_p1_5 = "3連覇となる優勝を決めたのは、**名古屋大学**だ。"
    assert not gen.validate_generated_article(article_win_p1_5, metrics), "Error: 3連覇での未ゴール優勝がパスしました"
    
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "ゴール"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = 2
    assert gen.validate_generated_article(article_win_p1_5, metrics), "Error: 3連覇でのゴール後優勝が失敗しました"
    
    # 状態を未ゴールに戻す
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "美濃加茂"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = None

    # 【追加テスト P1-2】
    # 1. 1位ゴール後、「金沢大学の追撃を振り切り名古屋大学が優勝」 -> 成功
    gen.all_data["realtime_report"]["teams"][0]["runner"] = "ゴール"
    gen.all_data["realtime_report"]["teams"][0]["finishDay"] = 2
    article_win_p1_2_1 = "**金沢大学**の追撃を振り切り**名古屋大学**が優勝した。"
    assert gen.validate_generated_article(article_win_p1_2_1, metrics), "Error: 複数校混在の正当な優勝判定が失敗しました"

    # 2. 1位ゴール後、「名古屋大学を追い金沢大学が優勝」 -> 失敗
    article_win_p1_2_2 = "**名古屋大学**を追い**金沢大学**が優勝した。"
    assert not gen.validate_generated_article(article_win_p1_2_2, metrics), "Error: 複数校混在の誤った優勝判定がパスしてしまいました"

    # 3. 「優勝は名古屋大学」 -> 対象照合
    article_win_p1_2_3 = "今大会の優勝は**名古屋大学**だ。"
    assert gen.validate_generated_article(article_win_p1_2_3, metrics), "Error: 『優勝はX』形式の正当な判定が失敗しました"

    print("✅ Pass: 優勝の対象チーム照合（太字対応、複数校混在対応）と歴史記述の除外がすべて正しく動作しました。")

if __name__ == "__main__":
    try:
        test_runner_threads_resolution()
        test_runner_threads_goal()
        test_momentum_management()
        test_resolved_stories_deduplication()
        test_validation_noun_exclusion()
        test_validation_winner_check()
        print("\n🎉 全ての追加テストを含むテストケースに合格しました！")
    except AssertionError as e:
        print(f"\n❌ テスト失敗: {e}")
        sys.exit(1)
