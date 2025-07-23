let stationsData = [];

// アメダス観測所データを読み込み
async function loadStationsData() {
    try {
        const response = await fetch('amedas_stations.json');
        stationsData = await response.json();
        console.log('観測所データを読み込みました:', stationsData.length, '件');
    } catch (error) {
        console.error('観測所データの読み込みに失敗:', error);
    }
}

// 地点名から観測所情報を検索
function findStationByName(name) {
    return stationsData.find(station => station.name === name);
}

// 気温データを取得（CORS制限のため、プロキシサーバーを使用）
async function fetchMaxTemperature(prefCode, stationCode) {
    const url = `https://weather.yahoo.co.jp/weather/amedas/${prefCode}/${stationCode}.html`;
    
    // CORS制限を回避するため、プロキシサービスを使用
    const proxyUrl = `https://api.allorigins.win/get?url=${encodeURIComponent(url)}`;
    
    try {
        const response = await fetch(proxyUrl);
        const data = await response.json();
        
        if (!data.contents) {
            throw new Error('データの取得に失敗しました');
        }
        
        // HTMLを解析
        const parser = new DOMParser();
        const doc = parser.parseFromString(data.contents, 'text/html');
        
        // recordHighクラスのli要素を探す
        const recordHighLi = doc.querySelector('li.recordHigh');
        if (!recordHighLi) {
            throw new Error('最高気温データが見つかりません');
        }
        
        // dtが「最高」であることを確認
        const dt = recordHighLi.querySelector('dt');
        if (!dt || dt.textContent.trim() !== '最高') {
            throw new Error('最高気温のラベルが見つかりません');
        }
        
        // dd要素から温度情報を取得
        const dd = recordHighLi.querySelector('dd');
        if (!dd) {
            throw new Error('最高気温情報の解析に失敗しました');
        }
        
        // dd要素から各パーツを個別に取得して、より確実に情報を組み立てる
        const tempValue = dd.firstChild?.textContent?.trim();
        const tempUnit = dd.querySelector('.tempUnit')?.textContent;
        const recordTime = dd.querySelector('.recordTime')?.textContent;

        if (!tempValue) {
            throw new Error('最高気温の値が見つかりませんでした。');
        }

        // 取得したパーツを結合。単位や時刻がない場合も考慮する。
        const parts = [tempValue];
        if (tempUnit) parts.push(tempUnit);
        if (recordTime) parts.push(recordTime);
        const tempInfo = parts.join(' ');
        return tempInfo;
    } catch (error) {
        console.error('最高気温取得エラー:', error);
        throw error;
    }
}

// 検索実行
async function searchTemperature() {
    const locationInput = document.getElementById('locationInput');
    const resultDiv = document.getElementById('result');
    const locationName = locationInput.value.trim();
    
    if (!locationName) {
        showResult('地点名を入力してください', 'error');
        return;
    }
    
    // ローディング表示
    showResult('検索中...', 'loading');
    
    try {
        // 観測所を検索
        const station = findStationByName(locationName);
        if (!station) {
            showResult(`地点名「${locationName}」が見つかりません`, 'error');
            return;
        }
        
        // 気温を取得
        const tempInfo = await fetchMaxTemperature(station.pref_code, station.code);
        showResult(`${locationName}の最高気温は ${tempInfo} です`, 'success');
        
    } catch (error) {
        showResult(`エラーが発生しました: ${error.message}`, 'error');
    }
}

// 結果表示
function showResult(message, type) {
    const resultDiv = document.getElementById('result');
    resultDiv.textContent = message;
    resultDiv.className = `result ${type}`;
}

// 候補地点をクリックした時の処理
function searchLocation(locationName) {
    document.getElementById('locationInput').value = locationName;
    searchTemperature();
}

// Enterキーで検索
document.addEventListener('DOMContentLoaded', function() {
    loadStationsData();
    
    document.getElementById('locationInput').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchTemperature();
        }
    });
});