import requests
from bs4 import BeautifulSoup
import time
import json

# 北海道だけ特別対応
def get_pref_codes():
    return ['1a', '1b', '1c', '1d'] + [str(i) for i in range(2, 48)]

def get_yahoo_amedas_station_map(pref_code):
    url = f"https://weather.yahoo.co.jp/weather/amedas/{pref_code}/?m=temp"
    try:
        res = requests.get(url)
        res.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(res.content, "html.parser")
    area = soup.find("div", id="yjw_kakuchi_area")
    if area is None:
        return []

    station_list = []
    for a in area.select("ul li a"):
        href = a.get("href", "")
        if ".html" in href:
            code = href.split(".html")[0]
            name = a.text.strip()
            station_list.append({
                "name": name,
                "code": code,
                "pref_code": pref_code
            })
    return station_list

def get_all_pref_amedas_stations():
    all_stations = []
    for pref_code in get_pref_codes():
        print(f"取得中: 都道府県コード {pref_code}")
        stations = get_yahoo_amedas_station_map(pref_code)
        all_stations.extend(stations)
        time.sleep(1)
    return all_stations

# 実行
if __name__ == "__main__":
    station_data = get_all_pref_amedas_stations()
    with open("amedas_stations.json", "w", encoding="utf-8") as f:
        json.dump(station_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 全国{len(station_data)}地点を amedas_stations.json に保存しました")

