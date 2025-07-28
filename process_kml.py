import json
import xml.etree.ElementTree as ET
from geopy.distance import geodesic
import re

# --- 定数 ---
KML_FILE = 'ekiden_map.kml'
EKIDEN_DATA_FILE = 'ekiden_data.json'
OUTPUT_FILE = 'relay_points.json'

def get_leg_number_from_name(name):
    """'第１区'のようなPlacemark名から区間番号を抽出します。"""
    match = re.search(r'第(\d+)区', name)
    if match:
        return int(match.group(1))
    return float('inf') # マッチしない場合は最後にソートされるように大きな数を返す

def parse_kml_and_calculate_stations():
    """
    KMLファイルを解析してコースの座標を抽出し、
    区間の境界距離に基づいて各中継所の緯度経度を計算します。
    """
    # 1. 駅伝データを読み込み
    try:
        with open(EKIDEN_DATA_FILE, 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        leg_boundaries = ekiden_data.get('leg_boundaries', [])
        if not leg_boundaries:
            print(f"エラー: '{EKIDEN_DATA_FILE}' に 'leg_boundaries' が見つかりません。")
            return
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {EKIDEN_DATA_FILE} の読み込みに失敗しました: {e}")
        return

    # 2. KMLファイルを解析
    try:
        tree = ET.parse(KML_FILE)
        root = tree.getroot()
        # KMLは名前空間を使用するため、ここで定義します
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    except (FileNotFoundError, ET.ParseError) as e:
        print(f"エラー: {KML_FILE} の解析に失敗しました: {e}")
        return

    # 3. LineStringを持つPlacemarkを抽出し、区間番号でソート
    placemarks = root.findall('.//kml:Placemark', ns)
    linestring_placemarks = []
    for pm in placemarks:
        name_tag = pm.find('kml:name', ns)
        if name_tag is not None and '区' in name_tag.text:
             linestring_placemarks.append(pm)

    linestring_placemarks.sort(key=lambda pm: get_leg_number_from_name(pm.find('kml:name', ns).text))

    # 4. 全ての座標を一つのリストに結合
    all_points = []
    for pm in linestring_placemarks:
        coord_tag = pm.find('.//kml:coordinates', ns)
        if coord_tag is not None:
            coord_text = coord_tag.text.strip()
            points_str = re.split(r'\s+', coord_text)
            for p_str in points_str:
                if p_str:
                    lon, lat, _ = map(float, p_str.split(','))
                    all_points.append({'lat': lat, 'lon': lon})

    if not all_points:
        print("エラー: KMLファイル内にコースの座標データが見つかりませんでした。")
        return

    # 5. 距離を積算しながら中継所の座標を特定
    relay_points = []
    cumulative_distance_km = 0.0
    boundary_index = 0

    print("中継所の位置を計算中...")

    for i in range(1, len(all_points)):
        p1 = (all_points[i-1]['lat'], all_points[i-1]['lon'])
        p2 = (all_points[i]['lat'], all_points[i]['lon'])
        segment_distance_km = geodesic(p1, p2).kilometers

        while boundary_index < len(leg_boundaries) and leg_boundaries[boundary_index] <= cumulative_distance_km + segment_distance_km:
            target_distance_km = leg_boundaries[boundary_index]
            distance_into_segment = target_distance_km - cumulative_distance_km
            fraction = distance_into_segment / segment_distance_km if segment_distance_km > 0 else 0
            interp_lat = p1[0] + fraction * (p2[0] - p1[0])
            interp_lon = p1[1] + fraction * (p2[1] - p1[1])
            station_info = {"leg": boundary_index + 1, "name": f"第{boundary_index + 1}中継所", "target_distance_km": target_distance_km, "latitude": interp_lat, "longitude": interp_lon}
            relay_points.append(station_info)
            print(f"  発見: {station_info['name']} @ {target_distance_km} km -> ({interp_lat:.6f}, {interp_lon:.6f})")
            boundary_index += 1
        cumulative_distance_km += segment_distance_km

    # 6. 結果をJSONファイルに保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(relay_points, f, indent=2, ensure_ascii=False)

    print(f"\n計算完了: {len(relay_points)}箇所の中継所を特定しました。")
    print(f"計算上の総コース距離: {cumulative_distance_km:.2f} km")
    print(f"結果を {OUTPUT_FILE} に保存しました。")

if __name__ == '__main__':
    parse_kml_and_calculate_stations()