import json
import xml.etree.ElementTree as ET
from geopy.distance import geodesic
import re

# --- 定数 ---
KML_FILE = 'ekiden_map.kml'
REALTIME_REPORT_FILE = 'realtime_report.json'
OUTPUT_FILE = 'runner_locations.json'

def get_leg_number_from_name(name):
    """'第１区'のようなPlacemark名から区間番号を抽出します。"""
    match = re.search(r'第(\d+)区', name)
    if match:
        return int(match.group(1))
    return float('inf') # マッチしない場合は最後にソートされるように大きな数を返す

def calculate_runner_locations():
    """
    KMLファイルとリアルタイムレポートから、各チームの現在位置（緯度経度）を計算する。
    """
    # 1. リアルタイムレポートを読み込み
    try:
        with open(REALTIME_REPORT_FILE, 'r', encoding='utf-8') as f:
            realtime_data = json.load(f)
        teams_data = realtime_data.get('teams', [])
        if not teams_data:
            print(f"エラー: '{REALTIME_REPORT_FILE}' にチームデータが見つかりません。")
            return
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: {REALTIME_REPORT_FILE} の読み込みに失敗しました: {e}")
        return

    # 2. KMLファイルを解析
    try:
        tree = ET.parse(KML_FILE)
        root = tree.getroot()
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

    # 5. 各チームの距離に基づいて座標を特定
    runner_locations = []
    print("各チームの現在位置を計算中...")

    for team in teams_data:
        target_distance_km = team.get('totalDistance', 0)
        cumulative_distance_km = 0.0
        team_lat, team_lon = all_points[0]['lat'], all_points[0]['lon']

        for i in range(1, len(all_points)):
            p1 = (all_points[i-1]['lat'], all_points[i-1]['lon'])
            p2 = (all_points[i]['lat'], all_points[i]['lon'])
            segment_distance_km = geodesic(p1, p2).kilometers

            if cumulative_distance_km <= target_distance_km < cumulative_distance_km + segment_distance_km:
                distance_into_segment = target_distance_km - cumulative_distance_km
                fraction = distance_into_segment / segment_distance_km if segment_distance_km > 0 else 0
                team_lat = p1[0] + fraction * (p2[0] - p1[0])
                team_lon = p1[1] + fraction * (p2[1] - p1[1])
                break
            cumulative_distance_km += segment_distance_km
        
        runner_locations.append({
            "rank": team.get('overallRank'), "team_name": team.get('name'),
            "runner_name": team.get('runner'), "total_distance_km": team.get('totalDistance'),
            "latitude": team_lat, "longitude": team_lon
        })
        print(f"  {team.get('overallRank')}位 {team.get('name'):<10} @ {team.get('totalDistance'):.1f} km -> ({team_lat:.6f}, {team_lon:.6f})")

    # 6. 結果をJSONファイルに保存
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(runner_locations, f, indent=2, ensure_ascii=False)

    print(f"\n計算完了: {len(runner_locations)}チームの位置を特定しました。")
    print(f"結果を {OUTPUT_FILE} に保存しました。")

if __name__ == '__main__':
    calculate_runner_locations()