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
    
    # mainDataクラスのp要素を探す
    main_data = soup.find("p", class_="mainData")
    if not main_data:
        return None
    
    # span要素から温度を取得
    temp_span = main_data.find("span")
    if not temp_span:
        return None
    
    temp_text = temp_span.get_text(strip=True)
    
    # 数値部分のみを抽出（℃を除去）
    try:
        temp_value = temp_text.replace('℃', '').strip()
        temp = float(temp_value)
        return temp
    except ValueError:
        return None

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

    temp = get_max_temp(station["pref_code"], station["code"])
    if temp is not None:
        print(f"{name}の最高気温は {temp:.1f}℃ です")
    else:
        print(f"{name}の最高気温を取得できませんでした")

if __name__ == "__main__":
    main()

