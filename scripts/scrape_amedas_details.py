import json
import requests
from bs4 import BeautifulSoup
import time
import re

AMEDAS_STATIONS_FILE = 'amedas_stations.json'
OUTPUT_FILE = 'amedas_details.json'
BASE_URL = 'http://amedas.log-life.net/station.php'

def load_stations():
    """amedas_stations.jsonを読み込む"""
    with open(AMEDAS_STATIONS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def scrape_station_details(station_code, pref_num):
    """指定された観測所の詳細ページから情報をスクレイピングする"""
    url = f"{BASE_URL}?sn={station_code}&p={pref_num}"
    print(f"Scraping: {url}")
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        details = {}

        # 歴代記録テーブル
        record_table = soup.find('table', class_='record_table')
        if record_table:
            rows = record_table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 3:
                    item_name = cells[0].text.strip()
                    record_value = cells[1].text.strip()
                    record_date = cells[2].text.strip()
                    
                    # 正規表現で不要な文字を除去
                    record_date_clean = re.sub(r'\[.*?\]', '', record_date).strip()

                    if '最高気温' in item_name:
                        details['record_high_temp'] = f"{record_value} ({record_date_clean})"
                    elif '最低気温' in item_name:
                        details['record_low_temp'] = f"{record_value} ({record_date_clean})"

        return details
    except requests.RequestException as e:
        print(f"  Error fetching {url}: {e}")
        return None

def main():
    stations = load_stations()
    all_details = {}

    for station in stations:
        # pref_codeから数字部分のみを抽出
        pref_num = re.search(r'\d+', station['pref_code']).group(0)
        details = scrape_station_details(station['code'], pref_num)
        if details:
            all_details[station['code']] = details
        time.sleep(0.5) # サーバー負荷軽減のため待機

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_details, f, ensure_ascii=False, indent=2)
    print(f"\n完了: {len(all_details)}件の観測所詳細データを {OUTPUT_FILE} に保存しました。")

if __name__ == '__main__':
    main()