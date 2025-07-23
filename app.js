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
    // allorigins.winが不安定なため、thingproxy.freeboard.ioに変更
    const proxyUrl = `https://thingproxy.freeboard.io/fetch/${url}`;
    
    try {
        const response = await fetch(proxyUrl);
        if (!response.ok) {
            throw new Error(`プロキシサーバーからの応答が異常です (HTTP ${response.status})`);
        }
        const html = await response.text();

        if (!html) {
            throw new Error('データの取得に失敗しました');
        }
        
        // HTMLを解析
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');
        
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
        saveToSearchHistory(locationName);
        
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

// 検索履歴をlocalStorageに保存する
function saveToSearchHistory(locationName) {
    let history = JSON.parse(localStorage.getItem('searchHistory')) || [];
    // 既存の履歴から同じ地点を削除（先頭に移動するため）
    history = history.filter(item => item !== locationName);
    // 新しい地点を先頭に追加
    history.unshift(locationName);
    // 履歴を最新8件に保つ
    history = history.slice(0, 8);
    // localStorageに保存
    localStorage.setItem('searchHistory', JSON.stringify(history));
    // 表示を更新
    loadSearchHistory();
}

// 検索履歴を読み込んで表示する
function loadSearchHistory() {
    const history = JSON.parse(localStorage.getItem('searchHistory')) || [];
    const suggestionListDiv = document.querySelector('.suggestion-list');
    const suggestionsDiv = document.querySelector('.suggestions');

    if (!suggestionListDiv || !suggestionsDiv) return;

    suggestionListDiv.innerHTML = ''; // 現在のリストをクリア

    if (history.length === 0) {
        suggestionsDiv.style.display = 'none'; // 履歴がなければセクションごと非表示
    } else {
        suggestionsDiv.style.display = 'block';
        history.forEach(locationName => {
            const span = document.createElement('span');
            span.className = 'suggestion';
            span.textContent = locationName;
            span.onclick = () => searchLocation(locationName);
            suggestionListDiv.appendChild(span);
        });
    }
}

// --- ランキング表示機能 ---

// Yahoo!天気からランキングデータを取得
async function fetchRankingData() {
    const url = 'https://weather.yahoo.co.jp/weather/amedas/ranking/?rank=high_temp';
    // CORS制限を回避するため、プロキシサービスを使用
    // allorigins.winが不安定なため、thingproxy.freeboard.ioに変更
    const proxyUrl = `https://thingproxy.freeboard.io/fetch/${url}`;
    let response;
    try {
        response = await fetch(proxyUrl);
    } catch (error) {
        console.error('ランキング取得ネットワークエラー:', error);
        throw new Error('ネットワークエラー、またはプロキシサーバーに接続できませんでした。');
    }

    if (!response.ok) {
        throw new Error(`プロキシサーバーからの応答が異常です (HTTP ${response.status})`);
    }

    const html = await response.text();
    if (!html) {
        throw new Error('プロキシ経由でのランキングデータ取得に失敗しました。');
    }

    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    // タイトルと更新時刻を取得
    const title = doc.querySelector('.yjw_title_h2 .yjM')?.textContent.trim() || '全国最高気温ランキング';
    const updateTime = doc.querySelector('.yjw_title_h2 .yjSt')?.textContent.trim() || '';

    const rows = doc.querySelectorAll('.yjw_table tbody tr');
    if (rows.length < 2) { // ヘッダ行＋データ行が最低でも必要
        throw new Error('ランキングテーブルが見つかりません');
    }

    // ヘッダー行を解析
    const headerCells = rows[0].querySelectorAll('td');
    const headers = Array.from(headerCells).map(cell => cell.textContent.trim());

    const rankingList = [];
    // 最初の行(ヘッダ)をスキップ
    for (let i = 1; i < rows.length; i++) {
        const cells = rows[i].querySelectorAll('td');
        if (cells.length < 4) continue;
        
        const locationLink = cells[1]?.querySelector('a');
        const rank = cells[0]?.textContent.trim();
        const location = locationLink?.textContent.trim().replace(/\s+/g, ' ');
        const locationUrl = locationLink?.href;
        const temperature = cells[2]?.textContent.trim();
        const time = cells[3]?.textContent.trim();

        if (rank && location && locationUrl && temperature && time) {
            rankingList.push({ rank, location, locationUrl, temperature, time });
        }
    }
    return { title, updateTime, headers, rankingList };
}

// 取得したランキングデータをテーブルに表示
function displayRanking({ title, updateTime, headers, rankingList }) {
    // タイトルと更新時刻を更新
    const rankingTitleH3 = document.querySelector('.ranking-container h3');
    const rankingUpdateTimeP = document.getElementById('rankingUpdateTime');
    if (rankingTitleH3) rankingTitleH3.textContent = title;
    if (rankingUpdateTimeP) rankingUpdateTimeP.textContent = updateTime;

    // ヘッダーを動的に生成
    const rankingHead = document.getElementById('rankingHead');
    if (rankingHead) {
        rankingHead.innerHTML = ''; // Clear previous content
        const headerRow = document.createElement('tr');
        if (headers && headers.length > 0) {
            headers.forEach(headerText => {
                const th = document.createElement('th');
                th.textContent = headerText;
                headerRow.appendChild(th);
            });
        }
        rankingHead.appendChild(headerRow);
    }

    const rankingBody = document.getElementById('rankingBody');
    rankingBody.innerHTML = ''; // Clear previous content

    rankingList.forEach(item => {
        const row = document.createElement('tr');
        
        row.innerHTML = `
            <td>${item.rank}</td>
            <td class="location"><a href="${item.locationUrl}" target="_blank" rel="noopener noreferrer">${item.location}</a></td>
            <td>${item.temperature}</td>
            <td>${item.time}</td>
        `;
        rankingBody.appendChild(row);
    });
}

// ランキングの読み込みと表示を実行
async function loadRanking() {
    const rankingStatus = document.getElementById('rankingStatus');
    rankingStatus.textContent = 'ランキングを読み込み中...';
    rankingStatus.style.display = 'block';
    try {
        const rankingInfo = await fetchRankingData();
        displayRanking(rankingInfo);
        rankingStatus.style.display = 'none'; // 成功したらメッセージを隠す
    } catch (error) {
        rankingStatus.textContent = `ランキングの読み込みに失敗しました: ${error.message}`;
        rankingStatus.className = 'result error';
    }
}

// Enterキーで検索
document.addEventListener('DOMContentLoaded', function() {
    loadStationsData();
    loadSearchHistory();
    loadRanking();
    
    document.getElementById('locationInput').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchTemperature();
        }
    });
});