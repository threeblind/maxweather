import json
import pandas as pd
import re
from pathlib import Path

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')

# --- ファイル定義 ---
CSV_FILE_PATH = CONFIG_DIR / 'ame_master_20250807.csv'  # ユーザー提供のCSVファイル
STATIONS_JSON_PATH = CONFIG_DIR / 'amedas_stations.json'
OUTPUT_JSON_PATH = CONFIG_DIR / 'amedas_stations.json' # 同じファイルに上書き保存

def dms_to_decimal(degrees, minutes):
    """度分形式を十進数に変換"""
    return degrees + minutes / 60.0

def convert_japanese_era_to_gregorian(era_date_str):
    """
    和暦の日付文字列（例: '昭53.10.30', '#昭50.4.1', '(昭50.5.22)昭51.12.13'）をdatetimeオブジェクトに変換します。
    """
    if pd.isna(era_date_str):
        return None

    # 文字列に変換し、不要な部分を前処理
    date_str = str(era_date_str).strip()
    
    # 例: (昭50.5.22)昭51.12.13 の場合、括弧とその中身を削除して後続の文字列を優先する
    date_str = re.sub(r'\(.+?\)', '', date_str).strip()

    # 先頭の'#'を削除
    date_str = date_str.lstrip('#')
    era_map = {
        '明': 1868, '明治': 1868,
        '大': 1912, '大正': 1912,
        '昭': 1926, '昭和': 1926,
        '平': 1989, '平成': 1989,
        '令': 2019, '令和': 2019
    }

    # 和暦のフォーマットにマッチするか試す (例: 昭53.10.30)
    match = re.match(r'([明治大正昭和平成令和明大昭平令])(\d+)\.(\d+)\.(\d+)', date_str)

    if match:
        era_char, year_str, month_str, day_str = match.groups()
        era_start_year = era_map.get(era_char)
        if era_start_year is None: return None # 不明な元号
        gregorian_year = era_start_year + int(year_str) - 1
        try:
            return pd.to_datetime(f'{gregorian_year}-{month_str}-{day_str}')
        except (ValueError, TypeError): return None
    else:  # 和暦でなければ、pandasの標準パーサーで試す
        try: return pd.to_datetime(date_str)
        except (ValueError, TypeError): return None

def main():
    """
    気象庁のマスターCSVを読み込み、amedas_stations.jsonに緯度・経度・標高・所在地・観測開始日をマージする
    """
    try:
        # Shift-JISでCSVを読み込む
        df = pd.read_csv(CSV_FILE_PATH, encoding='cp932', header=0)
        print(f"'{CSV_FILE_PATH}' を読み込みました。")
        # デバッグ用にCSVの列名を出力します。
        print(f"デバッグ情報: CSVファイルの列名は次の通りです -> {df.columns.tolist()}")
    except FileNotFoundError:
        print(f"エラー: '{CSV_FILE_PATH}' が見つかりません。")
        return
    except Exception as e:
        print(f"エラー: CSVファイルの読み込み中にエラーが発生しました: {e}")
        return

    # CSVの列名をプログラムで扱いやすい名前にマッピング
    columns_map = {
        '観測所番号': 'code',
        '観測所名': 'name_kanji',
        '緯度(度)': 'lat_deg',
        '緯度(分)': 'lat_min',
        '経度(度)': 'lon_deg',
        '経度(分)': 'lon_min',
        '海面上の高さ(ｍ)': 'elevation',
        '所在地': 'address',
        '観測開始年月日': 'start_date'
    }
    df.rename(columns=columns_map, inplace=True)

    # 観測所番号(code)を文字列型に変換して、先行ゼロが消えないようにする
    # これにより、'11001' のようなコードで正しくマッチングできる
    if 'code' in df.columns:
        df['code'] = df['code'].astype(str).str.zfill(5)
    else:
        print("エラー: CSVに '観測所番号' 列が見つかりませんでした。")
        return

    # 観測所番号(code)をキーにして高速に検索できるように、DataFrameをインデックス化
    df.set_index('code', inplace=True)

    # 既存のJSONファイルを読み込む
    try:
        with open(STATIONS_JSON_PATH, 'r', encoding='utf-8') as f:
            stations_data = json.load(f)
    except FileNotFoundError:
        print(f"エラー: '{STATIONS_JSON_PATH}' が見つかりません。")
        return

    # マージ処理
    updated_count = 0
    not_found_count = 0
    for station in stations_data:
        station_code = station['code']
        if station_code not in df.index:
            not_found_count += 1
            continue

        # 観測所番号が重複している場合、df.locはDataFrameを返すため、最初の行を取得する
        lookup_result = df.loc[station_code]
        if isinstance(lookup_result, pd.DataFrame):
            master_row = lookup_result.iloc[0]
        else: # Seriesの場合
            master_row = lookup_result

        is_updated = False
        # 緯度・経度・標高を更新
        if pd.notna(master_row['elevation']):
            station['latitude'] = round(dms_to_decimal(master_row['lat_deg'], master_row['lat_min']), 6)
            station['longitude'] = round(dms_to_decimal(master_row['lon_deg'], master_row['lon_min']), 6)
            # pandas/numpyの数値型をPython標準のfloatに変換してJSONシリアライズエラーを回避
            station['elevation'] = float(master_row['elevation'])
            is_updated = True
        
        # 所在地を追加/更新
        if 'address' in master_row and pd.notna(master_row['address']):
            station['address'] = master_row['address']
            is_updated = True

        # 観測開始年月日を追加/更新
        if 'start_date' in master_row and pd.notna(master_row['start_date']):
            start_datetime = convert_japanese_era_to_gregorian(master_row['start_date'])
            # NaT (Not a Time) を正しく判定するために pd.notna() を使用
            if pd.notna(start_datetime):
                station['start_date'] = start_datetime.strftime('%Y/%m/%d')
                is_updated = True
        
        if is_updated:
            updated_count += 1

    if not_found_count > 0:
        print(f"  - 警告: {not_found_count}件の地点がマスターCSVに見つかりませんでした。")

    # 更新されたJSONを保存
    # configディレクトリが存在することを確認（なければ作成）
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(stations_data, f, ensure_ascii=False, indent=2)

    print(f"\n完了: {len(stations_data)}件中、{updated_count}件の観測所情報が更新されました。")
    print(f"結果を '{OUTPUT_JSON_PATH}' に保存しました。")

if __name__ == '__main__':
    main()