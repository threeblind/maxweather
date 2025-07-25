import unittest
import json
from unittest.mock import patch, mock_open
import generate_report

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        """テスト用の模擬（モック）データを準備します。"""
        # 模擬の観測所データ。同名の可能性がある地点をすべて含める。
        self.mock_stations_data = [
            # テスト対象: 佐賀
            {"name": "佐賀（佐賀）", "code": "85142", "pref_code": "41"},
            {"name": "佐賀（高知）", "code": "74436", "pref_code": "39"},
            # テスト対象: 白石
            {"name": "白石（佐賀）", "code": "85166", "pref_code": "41"},
            {"name": "白石（宮城）", "code": "34461", "pref_code": "4"},
            # テスト対象: 高松
            {"name": "高松（香川）", "code": "72086", "pref_code": "37"},
            {"name": "高松（北海道）", "code": "23281", "pref_code": "1d"},
            # テスト対象: 清水
            {"name": "清水（静岡）", "code": "50261", "pref_code": "22"},
            {"name": "清水（和歌山）", "code": "65121", "pref_code": "30"},
            {"name": "清水（高知）", "code": "74516", "pref_code": "39"},
            # テスト対象: 山口
            {"name": "山口（山口）", "code": "81286", "pref_code": "35"},
            {"name": "山口（北海道）", "code": "14116", "pref_code": "1b"},
            # テスト対象: 府中
            {"name": "府中（東京）", "code": "44116", "pref_code": "13"},
            {"name": "府中（広島）", "code": "67326", "pref_code": "34"},
            # テスト対象: 大野
            {"name": "大野（福井）", "code": "57121", "pref_code": "18"},
            {"name": "大野（岩手）", "code": "33086", "pref_code": "3"},
            # テスト対象: 山形
            {"name": "山形（山形）", "code": "35426", "pref_code": "6"},
            {"name": "山形（岩手）", "code": "33136", "pref_code": "3"},
            # その他のダミーデータ
            {"name": "ダミー地点", "code": "99999", "pref_code": "99"},
        ]

    @patch("builtins.open")
    @patch("generate_report.fetch_max_temperature")
    def test_finds_correct_station_for_runners_with_duplicate_names(self, mock_fetch_temp, mock_file_open):
        """
        同名の観測所名を持つ選手が複数いる場合でも、
        各チームの選手が正しい観測所コードでデータ取得されることをテストします。
        """
        test_cases = [
            {"runner_name": "佐賀（佐賀）", "team_id": 3, "leg": 7, "expected_pref": "41", "expected_code": "85142"},
            {"runner_name": "白石（佐賀）", "team_id": 3, "leg": 8, "expected_pref": "41", "expected_code": "85166"},
            {"runner_name": "高松（香川）", "team_id": 8, "leg": 6, "expected_pref": "37", "expected_code": "72086"},
            {"runner_name": "清水（静岡）", "team_id": 10, "leg": 4, "expected_pref": "22", "expected_code": "50261"},
            {"runner_name": "山口（山口）", "team_id": 11, "leg": 9, "expected_pref": "35", "expected_code": "81286"},
            {"runner_name": "府中（東京）", "team_id": 13, "leg": 8, "expected_pref": "13", "expected_code": "44116"},
            {"runner_name": "大野（福井）", "team_id": 17, "leg": 10, "expected_pref": "18", "expected_code": "57121"},
            {"runner_name": "山形（山形）", "team_id": 18, "leg": 2, "expected_pref": "6", "expected_code": "35426"},
        ]

        for case in test_cases:
            with self.subTest(runner=case["runner_name"]):
                # --- テストデータの準備 ---
                mock_fetch_temp.reset_mock() # 各テストケースの前にモックをリセット

                # テストケースごとに動的に駅伝・状態データを生成
                mock_ekiden_data = {
                    "leg_boundaries": [100] * 10,
                    "teams": [{
                        "id": case["team_id"], "name": f"Test University {case['team_id']}",
                        "runners": ["ダミー地点"] * (case["leg"] - 1) + [case["runner_name"]],
                        "substitutes": []
                    }]
                }
                mock_state_data = [{
                    "id": case["team_id"], "name": f"Test University {case['team_id']}",
                    "totalDistance": 0, "currentLeg": case["leg"], "overallRank": 1
                }]

                # open()が呼ばれた際に、ファイル名に応じて模擬データを返すように設定
                def open_side_effect(file, *args, **kwargs):
                    if file == generate_report.AMEDAS_STATIONS_FILE:
                        return mock_open(read_data=json.dumps(self.mock_stations_data))()
                    if file == generate_report.EKIDEN_DATA_FILE:
                        return mock_open(read_data=json.dumps(mock_ekiden_data))()
                    if file == 'ekiden_state.json':
                        return mock_open(read_data=json.dumps(mock_state_data))()
                    if file == 'individual_results.json':
                        return mock_open(read_data=json.dumps({}))()
                    return mock_open()()

                mock_file_open.side_effect = open_side_effect
                mock_fetch_temp.return_value = {'temperature': 30.0, 'error': None}

                # --- スクリプト実行 ---
                with patch('sys.argv', ['generate_report.py', '--realtime']):
                    generate_report.main()

                # --- 検証 ---
                print(f"\n[テスト検証] 選手: {case['runner_name']}")
                mock_fetch_temp.assert_called_once_with(case["expected_pref"], case["expected_code"])
                print(f"=> OK: 正しい観測所コード ('{case['expected_pref']}', '{case['expected_code']}') で呼び出されました。")

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)