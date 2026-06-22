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

    # 2.5 接頭辞（「位」「首位」）付きの正常大学名の通過確認
    article_prefix_uni1 = "1位名古屋大学が激走。"
    assert gen.validate_generated_article(article_prefix_uni1, metrics), "Error: 『1位名古屋大学』がバリデーション失敗しました"
    article_prefix_uni2 = "首位名古屋大学がリード。"
    assert gen.validate_generated_article(article_prefix_uni2, metrics), "Error: 『首位名古屋大学』がバリデーション失敗しました"

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

def test_select_today_themes():
    print("--- Test 7: select_today_themes ---")
    gen = setup_mock_generator()

    # 1. テストデータの構築
    teams_report = [
        {"name": "名古屋大学", "runner": "1美濃加茂", "overallRank": 1, "todayDistance": 34.1, "totalDistance": 65.7, "previousRank": 1},
        {"name": "立命館大学", "runner": "1東近江", "overallRank": 2, "todayDistance": 32.5, "totalDistance": 62.6, "previousRank": 10},
        {"name": "鳥取大学", "runner": "1川本", "overallRank": 3, "todayDistance": 30.8, "totalDistance": 62.4, "previousRank": 1},
        {"name": "三重大学", "runner": "1粥見", "overallRank": 3, "todayDistance": 32.2, "totalDistance": 62.4, "previousRank": 9},
        {"name": "広島経済大学", "runner": "1三次", "overallRank": 5, "todayDistance": 30.7, "totalDistance": 62.0, "previousRank": 4},
        {"name": "関西大学", "runner": "1福崎", "overallRank": 6, "todayDistance": 30.5, "totalDistance": 61.9, "previousRank": 3},
        {"name": "福岡大学", "runner": "1久留米", "overallRank": 7, "todayDistance": 30.3, "totalDistance": 61.6, "previousRank": 4},
        {"name": "金沢大学", "runner": "1秋ヶ島", "overallRank": 8, "todayDistance": 30.4, "totalDistance": 61.5, "previousRank": 6},
        {"name": "山梨学院大学", "runner": "1長野", "overallRank": 9, "todayDistance": 30.5, "totalDistance": 61.1, "previousRank": 7},
        {"name": "琉球大学", "runner": "1北原", "overallRank": 10, "todayDistance": 30.1, "totalDistance": 60.1, "previousRank": 11},
        {"name": "日本大学", "runner": "1大子", "overallRank": 11, "todayDistance": 30.4, "totalDistance": 59.8, "previousRank": 12},
        {"name": "上武大学", "runner": "1佐野", "overallRank": 12, "todayDistance": 31.5, "totalDistance": 59.2, "previousRank": 14},
        {"name": "四国大学", "runner": "1穴吹", "overallRank": 13, "todayDistance": 28.1, "totalDistance": 58.7, "previousRank": 7},
        {"name": "学連選抜", "runner": "1美幌", "overallRank": 14, "todayDistance": 26.5, "totalDistance": 55.6, "previousRank": 13},
        {"name": "熊本学園大学", "runner": "1甲佐", "overallRank": 15, "todayDistance": 27.7, "totalDistance": 55.1, "previousRank": 15},
        {"name": "福島大学", "runner": "1梁川", "overallRank": 16, "todayDistance": 27.3, "totalDistance": 53.3, "previousRank": 17},
        {"name": "東北大学", "runner": "1帯広", "overallRank": 17, "todayDistance": 25.1, "totalDistance": 51.6, "previousRank": 16},
        {"name": "鹿児島大学", "runner": "1東市来", "overallRank": 18, "todayDistance": 25.5, "totalDistance": 51.0, "previousRank": 18}
    ]
    gen.all_data["realtime_report"]["teams"] = teams_report

    # metricsを計算
    metrics = gen.calculate_race_metrics()

    # zones 候補を生成
    selected_zones = gen.select_today_themes(metrics)

    # 2. アサーション
    zones_map = {z["zone"]: z for z in selected_zones}

    # A. 首位状況
    assert "首位状況" in zones_map, "Error: 首位状況が生成されていません"
    lead_zone = zones_map["首位状況"]
    assert "名古屋大学" in lead_zone["teams"], "Error: 首位チームが名古屋大学になっていません"
    assert "立命館大学" in lead_zone["teams"], "Error: 2位チームが立命館大学になっていません"
    assert lead_zone["gaps"].get("gap_1st_to_2nd_km") == 3.1, f"Error: 首位差が3.1kmではありません ({lead_zone['gaps'].get('gap_1st_to_2nd_km')})"

    # B. 上位状況
    assert "上位状況" in zones_map, "Error: 上位状況が生成されていません"
    chase_zone = zones_map["上位状況"]
    assert len(chase_zone["teams"]) > 1, "Error: 上位・追走集団が正しくマージされていません"

    # C. シード境界状況
    assert "シード境界状況" in zones_map, "Error: シード境界状況が生成されていません"
    seed_zone = zones_map["シード境界状況"]
    assert seed_zone["gaps"].get("gap_10th_to_11th_km") == 0.3, f"Error: 10位と11位の差が0.3kmではありません ({seed_zone['gaps'].get('gap_10th_to_11th_km')})"

    # D. シード圏外状況の特筆検証
    if "シード圏外状況" in zones_map:
        lower_zone = zones_map["シード圏外状況"]
        assert "東北大学" not in lower_zone["teams"], "Error: 特筆性のない東北大学が注目走に選ばれています"
        assert "鹿児島大学" not in lower_zone["teams"], "Error: 特筆性のない鹿児島大学が注目走に選ばれています"

    print("✅ Pass: select_today_themes の順位帯別候補データ構造が正しく生成されました。")

def test_dynamic_rank_and_last_observed_gap():
    print("--- Test 8: test_dynamic_rank_and_last_observed_gap (P1 & P2) ---")
    gen = setup_mock_generator()

    # ongoing_battles の rendering 確認 (P1)
    gen.narrative_state["ongoing_battles"] = [
        {
            "teams": ["名古屋大学", "金沢大学"],
            "last_observed_gap_km": 1.3,
            "previous_gap_km": 1.5,
            "started_day": 1,
            "last_updated_day": 1
        }
    ]
    metrics = gen.calculate_race_metrics()
    prompt = gen.build_user_prompt(metrics)

    # プロンプトの出力に「前回観測時点の差: 1.3km」が含まれていることを検証
    assert "前回観測時点の差: 1.3km" in prompt, "Error: プロンプト内に前回観測時点の差が表示されていません"
    assert "前日の差" not in prompt, "Error: プロンプト内に古い『前日の差』表記が残っています"

    # select_today_themes での動的順位 (P2)
    teams_report_test = [
        {"name": "名古屋大学", "runner": "1美濃加茂", "overallRank": 1, "todayDistance": 34.1, "totalDistance": 65.7, "previousRank": 1},
        {"name": "立命館大学", "runner": "1東近江", "overallRank": 2, "todayDistance": 32.5, "totalDistance": 62.6, "previousRank": 10},
        {"name": "鳥取大学", "runner": "1川本", "overallRank": 3, "todayDistance": 30.8, "totalDistance": 62.4, "previousRank": 1},
        {"name": "三重大学", "runner": "1粥見", "overallRank": 4, "todayDistance": 32.2, "totalDistance": 62.4, "previousRank": 9},
        {"name": "広島経済大学", "runner": "1三次", "overallRank": 5, "todayDistance": 30.7, "totalDistance": 62.0, "previousRank": 4},
        {"name": "関西大学", "runner": "1福崎", "overallRank": 6, "todayDistance": 30.5, "totalDistance": 61.9, "previousRank": 3},
        {"name": "福岡大学", "runner": "1久留米", "overallRank": 7, "todayDistance": 30.3, "totalDistance": 61.6, "previousRank": 4},
        {"name": "金沢大学", "runner": "1秋ヶ島", "overallRank": 8, "todayDistance": 30.4, "totalDistance": 61.5, "previousRank": 6},
        {"name": "山梨学院大学", "runner": "1長野", "overallRank": 9, "todayDistance": 30.5, "totalDistance": 61.1, "previousRank": 7},
        {"name": "琉球大学", "runner": "1北原", "overallRank": 10, "todayDistance": 30.1, "totalDistance": 60.1, "previousRank": 11},
        {"name": "日本大学", "runner": "1大子", "overallRank": 11, "todayDistance": 30.4, "totalDistance": 59.8, "previousRank": 12},
        {"name": "上武大学", "runner": "1佐野", "overallRank": 12, "todayDistance": 31.5, "totalDistance": 59.2, "previousRank": 14},
    ]
    gen.all_data["realtime_report"]["teams"] = teams_report_test
    selected_zones = gen.select_today_themes(metrics)
    zones_map = {z["zone"]: z for z in selected_zones}

    # 上位状況
    chase_zone = zones_map["上位状況"]
    assert "総合2位から5位" in chase_zone["reason"], f"Error: 上位状況の動的順位範囲が不正です ({chase_zone['reason']})"

    # 中位状況
    mid_zone = zones_map["中位状況"]
    assert "総合4位〜8位" in mid_zone["reason"], f"Error: 中位状況の動的順位範囲が不正です ({mid_zone['reason']})"

    # シード境界状況 (t10, t11 がいないような想定で fallback テスト)
    gen.all_data["realtime_report"]["teams"] = [
        {"name": "山梨学院大学", "runner": "1長野", "overallRank": 9, "todayDistance": 30.5, "totalDistance": 61.1, "previousRank": 7},
        {"name": "日本大学", "runner": "1大子", "overallRank": 12, "todayDistance": 30.4, "totalDistance": 59.8, "previousRank": 12},
    ]
    metrics_fallback = gen.calculate_race_metrics()
    selected_zones_fallback = gen.select_today_themes(metrics_fallback)
    zones_map_fallback = {z["zone"]: z for z in selected_zones_fallback}
    seed_zone_fallback = zones_map_fallback["シード境界状況"]
    assert "総合9位から12位" in seed_zone_fallback["reason"], f"Error: シード境界状況（fallback）の動的順位範囲が不正です ({seed_zone_fallback['reason']})"

    print("✅ Pass: 前回観測時点の差表記、および各候補ゾーン reason 内の動的順位表記が正しく動作することを確認しました。")

def test_lead_battle_non_resolved_on_large_gap():
    print("--- Test 9: test_lead_battle_non_resolved_on_large_gap (P1 large gap) ---")
    gen = setup_mock_generator()

    # ongoing_battles に既存の首位争い（名古屋大学と金沢大学）が存在する
    gen.narrative_state["ongoing_battles"] = [
        {
            "id": "lead_battle",
            "kind": "lead",
            "teams": ["名古屋大学", "金沢大学"],
            "summary": "名古屋大学と金沢大学による首位争い",
            "started_day": 1,
            "last_updated_day": 1,
            "last_observed_gap_km": 1.0,
            "previous_gap_km": 1.0
        }
    ]

    # 二校の差が 5.5km (>= 5.0km) に広がった（未ゴール）とするデータを設定
    gen.all_data["realtime_report"]["teams"] = [
        {"name": "名古屋大学", "runner": "美濃加茂", "overallRank": 1, "todayDistance": 30.0, "totalDistance": 70.0, "previousRank": 1},
        {"name": "金沢大学", "runner": "秋ヶ島", "overallRank": 2, "todayDistance": 25.0, "totalDistance": 64.5, "previousRank": 2},
        {"name": "琉球大学", "runner": "北原", "overallRank": 3, "todayDistance": 20.0, "totalDistance": 50.0, "previousRank": 3}
    ]

    metrics = gen.calculate_race_metrics()
    gen.update_narrative_state(metrics, [])

    # gapが5.5kmに広がったが、未ゴールのため resolved_stories に入らず ongoing_battles に残っているはず
    ongoing = gen.narrative_state["ongoing_battles"]
    resolved = gen.narrative_state["resolved_stories"]

    assert any(b.get("id") == "lead_battle" for b in ongoing), "Error: 5km以上の差で首位争いが ongoing_battles から削除されてしまいました"
    assert not any("首位攻防決着" in r.get("summary", "") for r in resolved), "Error: 未ゴールなのに首位攻防が決着扱いになっています"

    # 差が正しく 5.5km に更新されていることを確認
    lead_b = next(b for b in ongoing if b.get("id") == "lead_battle")
    assert lead_b.get("last_observed_gap_km") == 5.5, f"Error: last_observed_gap_km が 5.5km に更新されていません ({lead_b.get('last_observed_gap_km')})"

    print("✅ Pass: 首位差が5km以上になっても未ゴールなら ongoing_battles が維持・更新されることを確認しました。")

if __name__ == "__main__":
    try:
        test_runner_threads_resolution()
        test_runner_threads_goal()
        test_momentum_management()
        test_resolved_stories_deduplication()
        test_validation_noun_exclusion()
        test_validation_winner_check()
        test_select_today_themes()
        test_dynamic_rank_and_last_observed_gap()
        test_lead_battle_non_resolved_on_large_gap()
        print("\n🎉 全ての追加テストを含むテストケースに合格しました！")
    except AssertionError as e:
        print(f"\n❌ テスト失敗: {e}")
        sys.exit(1)
