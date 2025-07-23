import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

def load_station_list(path="amedas_stations.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def get_station_by_name(name, stations):
    for s in stations:
        if s["name"] == name:
            return s
    return None

def get_max_temp(pref_code, station_code):
    url = f"https://weather.yahoo.co.jp/weather/amedas/{pref_code}/{station_code}.html"
    
    try:
        res = requests.get(url)
        res.raise_for_status()
    except requests.RequestException as e:
        print(f"[ERROR] データ取得失敗: {e}")
        return None

    soup = BeautifulSoup(res.content, "html.parser")
    
    # <li class="recordHigh"> (最高気温) を探す
    record_high_li = soup.find("li", class_="recordHigh")
    if not record_high_li:
        return None
    
    # <dt>が「最高」であることを確認
    dt = record_high_li.find("dt")
    if not dt or dt.get_text(strip=True) != "最高":
        return None

    # <dd>からテキストを取得
    dd = record_high_li.find("dd")
    if not dd:
        return None

    # dd要素内のテキストをスペース区切りで結合して返す (例: '34.3 ℃ (12:45)')
    return dd.get_text(separator=' ', strip=True)

def main():
    if len(sys.argv) < 2:
        print("使用法: python get_max_temp_by_name.py 地点名（例: 東京）")
        return

    name = sys.argv[1]
    stations = load_station_list()
    station = get_station_by_name(name, stations)

    if not station:
        print(f"[ERROR] 地点名が見つかりません: {name}")
        return

    temp_info = get_max_temp(station["pref_code"], station["code"])
    if temp_info is not None:
        print(f"{name}の最高気温は {temp_info} です")
    else:
        print(f"{name}の最高気温を取得できませんでした")

if __name__ == "__main__":
    main()
