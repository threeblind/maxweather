import unittest
import json
from unittest.mock import patch, mock_open
import generate_report

class TestGenerateReport(unittest.TestCase):

    def setUp(self):
        """テスト用の模擬（モック）データを準備します。"""
        # 模擬の観測所データ。テストに必要な部分のみを抜粋。
        self.mock_stations_data = [
            {"name": "久留米", "code": "82306", "pref_code": "40"},
            {"name": "佐賀（佐賀）", "code": "85142", "pref_code": "41"}, # 福岡大学が使用する正しい観測所
            {"name": "佐賀（高知）", "code": "74436", "pref_code": "39"}, # 同名の別の観測所
        ]

        # 模擬の駅伝データ
        self.mock_ekiden_data = {
            "leg_boundaries": [100, 210],
            "teams": [
                {
                    "id": 3,
                    "name": "福岡大学",
                    "runners": ["久留米", "佐賀（佐賀）"], # 2区に「佐賀（佐賀）」を配置
                    "substitutes": []
                }
            ]
        }

        # 模擬の駅伝状態データ（2区を走行中と仮定）
        self.mock_state_data = [
            {"id": 3, "name": "福岡大学", "totalDistance": 100, "currentLeg": 2, "overallRank": 1}
        ]

    @patch("builtins.open")
    @patch("generate_report.fetch_max_temperature")
    def test_finds_correct_station_with_duplicate_name(self, mock_fetch_temp, mock_file_open):
        """
        同名の観測所が存在する場合に、スクリプトが正しい観測所コードを選択して
        気温取得関数を呼び出すことをテストします。
        """
        # open()が呼ばれた際に、ファイル名に応じて模擬データを返すように設定
        def open_side_effect(file, *args, **kwargs):
            if file == generate_report.AMEDAS_STATIONS_FILE:
                return mock_open(read_data=json.dumps(self.mock_stations_data))()
            if file == generate_report.EKIDEN_DATA_FILE:
                return mock_open(read_data=json.dumps(self.mock_ekiden_data))()
            # argparseで指定されるデフォルトのファイル名
            if file == 'ekiden_state.json':
                 return mock_open(read_data=json.dumps(self.mock_state_data))()
            if file == 'individual_results.json':
                 return mock_open(read_data=json.dumps({}))() # 個人成績は空で開始
            return mock_open()() # その他のファイル（書き込み用など）

        mock_file_open.side_effect = open_side_effect

        # fetch_max_temperatureが呼ばれたら、固定の気温を返すように設定
        mock_fetch_temp.return_value = {'temperature': 35.0, 'error': None}

        # スクリプトのメイン処理を実行
        with patch('sys.argv', ['generate_report.py', '--realtime']):
             generate_report.main()

        # --- 検証 ---
        # fetch_max_temperatureが、佐賀県(pref_code: 41)の佐賀観測所(code: 85142)の
        # コードで呼び出されたことを確認します。
        print("\n[テスト検証] fetch_max_temperatureが呼ばれた際の引数を確認します...")
        try:
            mock_fetch_temp.assert_called_once_with("41", "85142")
            print("=> OK: 正しい観測所コード ('41', '85142') で呼び出されました。")
        except AssertionError as e:
            print(f"=> NG: テストに失敗しました。{e}")
            raise

if __name__ == '__main__':
    unittest.main(argv=['first-arg-is-ignored'], exit=False)