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
async function fetchTemperature(prefCode, stationCode) {
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
        
        // mainDataクラスの要素を探す
        const mainData = doc.querySelector('p.mainData');
        if (!mainData) {
            throw new Error('気温データが見つかりません');
        }
        
        // span要素から温度を取得
        const tempSpan = mainData.querySelector('span');
        if (!tempSpan) {
            throw new Error('温度情報の解析に失敗しました');
        }
        
        const tempText = tempSpan.textContent.trim();
        const tempValue = tempText.replace('℃', '').trim();
        const temperature = parseFloat(tempValue);
        
        if (isNaN(temperature)) {
            throw new Error('温度の変換に失敗しました');
        }
        
        return temperature;
    } catch (error) {
        console.error('気温取得エラー:', error);
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
        const temperature = await fetchTemperature(station.pref_code, station.code);
        showResult(`${locationName}の現在気温は ${temperature.toFixed(1)}℃ です`, 'success');
        
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