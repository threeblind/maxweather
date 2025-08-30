import os
import requests
import json
import time
from dotenv import load_dotenv
import argparse
from pathlib import Path

# --- ディレクトリ定義 ---
CONFIG_DIR = Path('config')
AMEDAS_DIR = Path('amedas')

# --- 設定 ---
STATIONS_FILE = CONFIG_DIR / 'amedas_stations.json'
OUTPUT_DIR = AMEDAS_DIR / 'jpg'
IMAGE_SIZE = '600x400'

# .envファイルから環境変数を読み込む
load_dotenv()
# APIキーは環境変数から読み込む
API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

def get_map_image(lat, lon):
    """
    Maps Static APIを使用して地図画像（航空写真）を取得する
    """
    base_url = "https://maps.googleapis.com/maps/api/staticmap"
    if not API_KEY:
        return None
    params = {
        'center': f'{lat},{lon}',
        'zoom': 17,
        'size': IMAGE_SIZE,
        'maptype': 'satellite',
        'markers': f'color:red|{lat},{lon}',
        'key': API_KEY
    }
    try:
        response = requests.get(base_url, params=params, timeout=20)
        # ステータスコードが403の場合、APIキーの問題である可能性が高い
        if response.status_code == 403:
            print(f"  - APIリクエストエラー: 403 Forbidden. APIキーが有効か、またはMaps Static APIが有効になっているか確認してください。")
            return None
        response.raise_for_status()
        return response.content
    except requests.RequestException as e:
        print(f"  - APIリクエストエラー: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description='Google Street Viewからアメダス観測所の画像を取得します。')
    parser.add_argument('--limit', type=int, help='取得する画像の最大数を指定します（テスト用）。')
    args = parser.parse_args()

    if not API_KEY:
        print("エラー: 環境変数 'GOOGLE_MAPS_API_KEY' が設定されていません。")
        print("プロジェクトのルートに .env ファイルを作成し、'GOOGLE_MAPS_API_KEY=YOUR_API_KEY' のようにキーを設定してください。")
        return

    try:
        with open(STATIONS_FILE, 'r', encoding='utf-8') as f:
            stations = json.load(f)
    except FileNotFoundError:
        print(f"エラー: 観測所ファイル '{STATIONS_FILE}' が見つかりません。")
        return

    # 出力ディレクトリが存在しない場合は作成
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.limit:
        stations = stations[:args.limit]

    print(f"全 {len(stations)} 地点の地図画像取得を開始します...")
    for i, station in enumerate(stations):
        print(f"({i+1}/{len(stations)}) 処理中: {station['name']} ({station['code']})")
        image_path = OUTPUT_DIR / f"{station['code']}.jpg"
        if os.path.exists(image_path):
            print("  - 画像は既に存在します。スキップします。")
            continue

        # 緯度経度が存在するかチェック
        if 'latitude' not in station or 'longitude' not in station:
            print(f"  - 緯度経度情報がありません。スキップします。")
            continue

        image_data = get_map_image(station['latitude'], station['longitude'])
        if image_data:
            with open(image_path, 'wb') as img_f:
                img_f.write(image_data)
            print(f"  - {image_path} に画像を保存しました。")
        else:
            print(f"  - 画像の取得に失敗しました。")
        time.sleep(0.2) # APIへの負荷を軽減

    print("\n全地点の処理が完了しました。")

if __name__ == '__main__':
    main()
