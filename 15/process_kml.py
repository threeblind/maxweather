import json
import xml.etree.ElementTree as ET
from geopy.distance import geodesic
import re
import unicodedata

# --- 定数 ---
KML_FILE = 'ekiden_map.kml'
COURSE_PATH_OUTPUT_FILE = 'course_path.json'
RELAY_POINTS_OUTPUT_FILE = 'config/relay_points.json'

def get_leg_number_from_name(name, pattern=r'第(\d+)'):
    """'第1区'、'第一中継所'のような名前から区間番号を抽出します。"""
    # 漢数字をアラビア数字に変換するテーブル
    kanji_to_arabic = str.maketrans('一二三四五六七八九', '123456789')

    # 漢数字を変換し、さらに全角数字を半角に正規化
    normalized_name = name.translate(kanji_to_arabic)
    normalized_name = unicodedata.normalize('NFKC', normalized_name)

    match = re.search(pattern, normalized_name)
    if match:
        return int(match.group(1))
    # Sort placemarks without numbers (like Start/Goal) to the ends
    if 'スタート' in name:
        return 0
    if 'ゴール' in name:
        return float('inf')
    return float('inf')

def get_points_from_linestring(placemark, ns):
    """LineStringを持つPlacemarkから座標リストを抽出します。"""
    points = []
    coord_tag = placemark.find('.//kml:coordinates', ns)
    if coord_tag is not None:
        coord_text = coord_tag.text.strip()
        points_str = re.split(r'\s+', coord_text)
        for p_str in points_str:
            if p_str:
                lon, lat, _ = map(float, p_str.split(','))
                points.append({'lat': lat, 'lon': lon})
    return points

def get_point_from_point(placemark, ns):
    """Pointを持つPlacemarkから単一の座標を抽出します。"""
    coord_tag = placemark.find('.//kml:Point/kml:coordinates', ns)
    if coord_tag is not None:
        coord_text = coord_tag.text.strip()
        if coord_text:
            lon, lat, _ = map(float, coord_text.split(','))
            return {'lat': lat, 'lon': lon}
    return None

def process_kml_data():
    """
    KMLファイルを解析し、中継所の座標とコース全体のパスを生成します。
    1. KMLから「点」として登録された中継所を直接抽出します。
    2. 抽出した中継所を基準に、各区間の「線」の向きを判定し、結合します。
    """
    # ekiden_data.jsonから区間距離を読み込む
    try:
        with open('ekiden_data.json', 'r', encoding='utf-8') as f:
            ekiden_data = json.load(f)
        leg_boundaries = ekiden_data.get('leg_boundaries', [])
        if not leg_boundaries:
            print(f"エラー: 'ekiden_data.json' に 'leg_boundaries' が見つかりません。")
            return
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"エラー: ekiden_data.json の読み込みに失敗しました: {e}")
        return

    # 1. KMLファイルを解析
    try:
        tree = ET.parse(KML_FILE)
        root = tree.getroot()
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
    except (FileNotFoundError, ET.ParseError) as e:
        print(f"エラー: {KML_FILE} の解析に失敗しました: {e}")
        return

    all_placemarks = root.findall('.//kml:Placemark', ns)
    
    # 2. 中継所（Point）とコース区間（LineString）を分離して抽出
    point_placemarks = {}
    linestring_placemarks = {}

    for pm in all_placemarks:
        name_tag = pm.find('kml:name', ns)
        if name_tag is None:
            continue
        name = name_tag.text
        
        # 中継所、スタート、ゴールを抽出
        if pm.find('kml:Point', ns) is not None:
            if '中継所' in name or 'スタート' in name or 'ゴール' in name:
                point_placemarks[name] = pm
        
        # コース区間を抽出
        if pm.find('kml:LineString', ns) is not None:
            if '区' in name:
                leg_num = get_leg_number_from_name(name)
                # Only add the leg if it hasn't been added before (deduplication)
                if leg_num != float('inf') and leg_num not in linestring_placemarks:
                    linestring_placemarks[leg_num] = pm

    # 3. 中継所の座標を直接抽出し、relay_points.json を生成
    relay_points_data = []
    sorted_point_names = sorted(point_placemarks.keys(), key=get_leg_number_from_name)
    
    start_point = None
    goal_point = None
    relay_points_coords = []

    print("中継所の座標をKMLから直接抽出中...")
    for name in sorted_point_names:
        pm = point_placemarks[name]
        point_coord = get_point_from_point(pm, ns)
        if not point_coord:
            continue
            
        if 'スタート' in name:
            start_point = point_coord
            print(f"  発見: スタート地点 -> ({start_point['lat']:.6f}, {start_point['lon']:.6f})")
        elif 'ゴール' in name:
            goal_point = point_coord
            print(f"  発見: ゴール地点 -> ({goal_point['lat']:.6f}, {goal_point['lon']:.6f})")
        elif '中継所' in name:
            leg_num = get_leg_number_from_name(name)
            target_distance = leg_boundaries[leg_num - 1] if 0 < leg_num <= len(leg_boundaries) else None
            station_info = {
                "leg": leg_num,
                "name": name,
                "target_distance_km": target_distance,
                "latitude": point_coord['lat'],
                "longitude": point_coord['lon']
            }
            relay_points_data.append(station_info)

    # Sort relay points by leg number and then extract coordinates
    relay_points_data.sort(key=lambda x: x['leg'])
    relay_points_coords = [{'lat': p['latitude'], 'lon': p['longitude']} for p in relay_points_data]
    for p in relay_points_data:
        print(f"  Found: {p['name']} -> ({p['latitude']:.6f}, {p['longitude']:.6f})")
        
    if not start_point or not relay_points_coords or not goal_point:
        print("\nError: Could not find all required Start, Goal, or Relay Station <Point> placemarks in the KML file.")
        return

    with open(RELAY_POINTS_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(relay_points_data, f, indent=2, ensure_ascii=False)
    print(f"Successfully saved relay station data to {RELAY_POINTS_OUTPUT_FILE}")

    # 4. Combine course lines into course_path.json using the extracted stations as anchors
    all_points = []
    anchor_points = [start_point] + relay_points_coords + [goal_point]
    sorted_linestring_keys = sorted(linestring_placemarks.keys())

    # --- Defensive Check ---
    # The number of line segments must be one less than the number of anchor points.
    if len(sorted_linestring_keys) != len(anchor_points) - 1:
        print(f"\nエラー: コース区間の数と、目印となる点の数が一致しません。")
        print(f"  - 発見したコース区間 (LineStrings): {len(sorted_linestring_keys)}個")
        print(f"  - Found {len(anchor_points)} anchor points (Start + {len(relay_points_coords)} Stations + Goal).")
        print(f"  - Expected {len(anchor_points) - 1} course legs.")
        print("Please check your KML file for missing or extra <Placemark> elements for legs or stations.")
        return
    # --- End Check ---

    print("\n中継所を基準にコースの向きを判定し、結合中...")
    for i, leg_num in enumerate(sorted_linestring_keys):
        pm = linestring_placemarks[leg_num]
        name = pm.find('kml:name', ns).text
        leg_points = get_points_from_linestring(pm, ns)
        if not leg_points:
            continue

        # 区間の始点と終点を定義
        leg_start, leg_end = leg_points[0], leg_points[-1]
        
        # この区間が接続すべきアンカーポイント（例: 2区なら第1中継所と第2中継所）
        anchor_start = anchor_points[i]
        anchor_end = anchor_points[i+1]

        # 距離を比較して向きを判定
        # (leg_start -> anchor_start) + (leg_end -> anchor_end) vs (leg_start -> anchor_end) + (leg_end -> anchor_start)
        dist_forward = geodesic((leg_start['lat'], leg_start['lon']), (anchor_start['lat'], anchor_start['lon'])).m + \
                       geodesic((leg_end['lat'], leg_end['lon']), (anchor_end['lat'], anchor_end['lon'])).m
        dist_backward = geodesic((leg_start['lat'], leg_start['lon']), (anchor_end['lat'], anchor_end['lon'])).m + \
                        geodesic((leg_end['lat'], leg_end['lon']), (anchor_start['lat'], anchor_start['lon'])).m

        if dist_backward < dist_forward:
            print(f"  {name} の向きが逆と判断し、反転します。")
            leg_points.reverse()

        # 最初の区間はそのまま追加
        if not all_points:
            all_points.extend(leg_points)
        else:
            # 結合する際、重複する始点を削除
            if geodesic((all_points[-1]['lat'], all_points[-1]['lon']), (leg_points[0]['lat'], leg_points[0]['lon'])).m < 1:
                all_points.extend(leg_points[1:])
            else:
                all_points.extend(leg_points)

    with open(COURSE_PATH_OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_points, f, indent=2, ensure_ascii=False)
    print(f"コースパス情報を {COURSE_PATH_OUTPUT_FILE} に保存しました。")

    # 5. 距離の再計算（確認用）
    cumulative_distance_km = 0.0
    for i in range(1, len(all_points)):
        p1 = (all_points[i-1]['lat'], all_points[i-1]['lon'])
        p2 = (all_points[i]['lat'], all_points[i]['lon'])
        cumulative_distance_km += geodesic(p1, p2).kilometers
    print(f"\n再計算した総コース距離: {cumulative_distance_km:.2f} km")


if __name__ == '__main__':
    process_kml_data()