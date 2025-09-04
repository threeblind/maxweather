let stationsData = [];
let allIndividualData = {}; // 選手個人の全記録を保持するグローバル変数
let playerProfiles = {}; // 選手名鑑データを保持
let lastRealtimeData = null; // 最新のrealtime_report.jsonを保持する
let ekidenDataCache = null; // ekiden_data.jsonをキャッシュする
let intramuralDataCache = null; // 学内ランキングデータを保持する
let dailyTemperaturesCache = null; // daily_temperatures.jsonをキャッシュする
let dailyRunnerChartInstance = null; // 選手の日次推移グラフのインスタンス
let summaryChartInstance = null; // 選手の大会サマリーグラフのインスタンス
let playerTotalChartInstance = null; // 選手の大会全記録グラフのインスタンス (これは別機能なのでそのまま)
let logFileExists = false; // ログファイルの存在を管理するフラグ

// CORS制限を回避するためのプロキシサーバーURLのテンプレート
const PROXY_URL_TEMPLATE = 'https://api.allorigins.win/get?url=%URL%';
const EKIDEN_START_DATE = '2025-09-01'; // Python側と合わせる
const CURRENT_EDITION = 16; // 今大会の大会番号

/**
 * 選手名から括弧で囲まれた都道府県名を取り除く
 * @param {string} name - 元の選手名 (e.g., "山形（山形）", "2山形（山形）")
 * @returns {string} - 整形された選手名 (e.g., "山形", "2山形")
 */
const formatRunnerName = (name) => {
    if (!name) return '';
    // 正規表現で末尾の「（...）」とその前の空白を削除
    return name.replace(/\s*（[^）]+）\s*$/, '');
};

/**
 * ランクに応じてメダル絵文字を返します。
 * @param {number} rank - 順位
 * @returns {string} - メダル絵文字または空文字列
 */
const getMedalEmoji = (rank) => {
    if (rank === 1) return '🥇';
    if (rank === 2) return '🥈';
    if (rank === 3) return '🥉';
    return '';
};

// アメダス観測所データを読み込み
async function loadStationsData() {
    try {
        const response = await fetch('config/amedas_stations.json');
        stationsData = await response.json();
        console.log('観測所データを読み込みました:', stationsData.length, '件');
    } catch (error) {
        console.error('観測所データの読み込みに失敗:', error);
    }
}

// 選手名鑑データを読み込み
async function loadPlayerProfiles() {
    try {
        const response = await fetch('config/player_profiles.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        playerProfiles = await response.json();
        console.log('選手名鑑データを読み込みました。');
    } catch (error) {
        console.error('選手名鑑データの読み込みに失敗:', error);
    }
}

// 地点名から観測所情報を検索
function findStationByName(name) {
    return stationsData.find(station => station.name === name);
}

// 気温データを取得（CORS制限のため、プロキシサーバーを使用）
async function fetchMaxTemperature(prefCode, stationCode) {
    const url = `https://weather.yahoo.co.jp/weather/amedas/${prefCode}/${stationCode}.html`;
    const proxyUrl = PROXY_URL_TEMPLATE.replace('%URL%', encodeURIComponent(url));
    
    try {
        const response = await fetch(proxyUrl, { cache: 'no-store' });
        if (!response.ok) {
            throw new Error(`プロキシサーバーからの応答が異常です (HTTP ${response.status})`);
        }
        const data = await response.json();
        const html = data.contents;

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
    history = history.slice(0, 18);
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
    const proxyUrl = PROXY_URL_TEMPLATE.replace('%URL%', encodeURIComponent(url));
    let response;
    try {
        response = await fetch(proxyUrl, { cache: 'no-store' });
    } catch (error) {
        console.error('ランキング取得ネットワークエラー:', error);
        throw new Error('ネットワークエラー、またはプロキシサーバーに接続できませんでした。');
    }

    if (!response.ok) {
        throw new Error(`プロキシサーバーからの応答が異常です (HTTP ${response.status})`);
    }

    const data = await response.json();
    const html = data.contents;
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
        const locationUrl = locationLink?.href;X
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

        const createCell = (text) => {
            const cell = document.createElement('td');
            cell.textContent = text;
            return cell;
        };

        row.appendChild(createCell(item.rank));

        const locationCell = document.createElement('td');
        locationCell.className = 'location';
        const link = document.createElement('a');
        link.href = item.locationUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = item.location;
        locationCell.appendChild(link);
        row.appendChild(locationCell);

        row.appendChild(createCell(item.temperature));
        row.appendChild(createCell(item.time));

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

// --- 駅伝ランキング表示機能 ---

// --- Map Variables ---
let map = null;
let runnerMarkersLayer = null;
let teamColorMap = new Map();
let trackedTeamName = "lead_group"; // デフォルトは先頭集団を追跡
let coursePolyline = null; // コースのポリラインをグローバルに保持

/**
 * Initializes the interactive map, draws the course, and places relay point markers.
 */
async function initializeMap() {
    // 1. Initialize the map if it hasn't been already
    if (map) return;
    map = L.map('map');

    // 2. Add the base map layer (OpenStreetMap)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);

    // 3. Create a layer group for runner markers that can be easily cleared and updated
    runnerMarkersLayer = L.layerGroup().addTo(map);

    try {
        // 4. Fetch course path, relay points, and leg best records data in parallel
        const [coursePathRes, relayPointsRes, legBestRecordsRes] = await Promise.all([
            fetch(`config/course_path.json?_=${new Date().getTime()}`),
            fetch(`config/relay_points.json?_=${new Date().getTime()}`),
            fetch(`history_data/leg_best_records.json?_=${new Date().getTime()}`) // 区間記録データをここで取得
        ]);

        if (!coursePathRes.ok || !relayPointsRes.ok) {
            throw new Error('Failed to fetch map data.');
        }

        const coursePath = await coursePathRes.json();
        const relayPoints = await relayPointsRes.json();
        // 区間記録データは任意。取得できなくてもエラーにしない
        const legBestRecords = legBestRecordsRes.ok ? await legBestRecordsRes.json() : null;

        // 5. Draw the course path
        if (coursePath && coursePath.length > 0) {
            const latlngs = coursePath.map(p => [p.lat, p.lon]);
            coursePolyline = L.polyline(latlngs, { color: '#007bff', weight: 5, opacity: 0.7 }).addTo(map);
            map.fitBounds(coursePolyline.getBounds().pad(0.1));
        }

        // 6. Draw relay point markers with leg record info
        if (relayPoints && relayPoints.length > 0) {
            // 区間記録を検索しやすいようにMapに変換
            const legRecordsMap = new Map();
            if (legBestRecords && legBestRecords.leg_records) {
                legBestRecords.leg_records.forEach(record => {
                    if (record.top10 && record.top10.length > 0) {
                        legRecordsMap.set(record.leg, record.top10[0]);
                    }
                });
            }

            relayPoints.forEach(point => {
                let popupContent = `<b>${point.name}</b><br>${point.target_distance_km} km地点`;
                
                // point.leg は中継所の「到着区間」を指す
                const legRecord = legRecordsMap.get(point.leg);
                if (legRecord) {
                    popupContent += `
                        <hr style="margin: 5px 0; border-top: 1px solid #eee;">
                        <div style="font-size: 0.9em;">
                            <b>区間記録:</b> ${legRecord.record.toFixed(3)} km/日<br>
                            <span>(${legRecord.team_name}: ${formatRunnerName(legRecord.runner_name)} / 第${legRecord.edition}回)</span>
                        </div>
                    `;
                }

                L.marker([point.latitude, point.longitude])
                    .addTo(map)
                    .bindPopup(popupContent);
            });
        }
    } catch (error) {
        console.error('Error initializing map:', error);
        document.getElementById('map').innerHTML = `<p class="result error">マップの読み込みに失敗しました: ${error.message}</p>`;
    }
}

/**
 * Creates a custom HTML icon for a runner's map marker.
 * @param {string} teamInitial - The first character of the team name.
 * @param {string} color - The team's color.
 * @returns {L.DivIcon} - A Leaflet DivIcon object.
 */
function createRunnerIcon(teamInitial, color) {
    const iconHtml = `
        <div class="runner-marker" style="background-color: ${color}; border-color: ${color};">
            <span class="rank-number">${teamInitial}</span>
        </div>
    `;
    return L.divIcon({
        html: iconHtml,
        className: 'runner-icon',
        iconSize: [32, 44], // アイコン全体のサイズ (幅, 高さ)
        iconAnchor: [16, 44], // アイコンの先端の位置 (X, Y)
        popupAnchor: [0, -46] // ポップアップの表示位置
    });
}

/**
 * Populates the team tracker dropdown and sets up its event listener.
 * @param {Array} teams - The list of teams from ekiden_data.json.
 */
function setupTeamTracker(teams) {
    const selectEl = document.getElementById('team-tracker-select');
    if (!selectEl) return;

    // 1. 最初に「先頭集団を追跡」オプションのみを設定
    selectEl.innerHTML = `<option value="lead_group">先頭集団を追跡</option>`;

    // 2. 各大学をオプションとして追加
    teams.forEach(team => {
        const option = document.createElement('option');
        option.value = team.name;
        option.textContent = team.name;
        selectEl.appendChild(option);
    });

    // 3. 全体表示オプションを最後に追加
    const allTeamsOption = document.createElement('option');
    allTeamsOption.value = 'all_teams';
    allTeamsOption.textContent = '全大学を表示';
    selectEl.appendChild(allTeamsOption);

    const courseOption = document.createElement('option');
    courseOption.value = 'full_course';
    courseOption.textContent = 'コース全体を表示';
    selectEl.appendChild(courseOption);

    // 「区間記録連合」追跡オプションを追加
    const shadowOption = document.createElement('option');
    shadowOption.value = 'shadow_confederation';
    shadowOption.textContent = '区間最高記録';
    selectEl.appendChild(shadowOption);

    // Add event listener
    selectEl.addEventListener('change', (event) => {
        trackedTeamName = event.target.value;
        // Immediately update the map view without waiting for the next 30-second interval
        // We can do this by re-fetching the data, which will trigger the map update logic.
        fetchEkidenData(); 
    });
}

/**
 * Updates the runner markers on the map with the latest locations.
 * @param {Array} runnerLocations - runner_locations.json のデータ。rankでソート済み。
 * @param {object} ekidenData - ekiden_data.json のデータ。ゴール距離の判定に使用。
 */
function updateRunnerMarkers(runnerLocations, ekidenData) {
    if (!map || !runnerMarkersLayer) return;
    runnerMarkersLayer.clearLayers(); // Remove old markers

    if (!runnerLocations || runnerLocations.length === 0) {
        return; // 表示するランナーがいない場合は何もしない
    }

    // ゴール距離を特定
    const finalGoalDistance = ekidenData.leg_boundaries[ekidenData.leg_boundaries.length - 1];

    runnerLocations.forEach(runner => {
        const color = teamColorMap.get(runner.team_name) || '#808080'; // Default to grey

        // マーカーに表示する文字を決定
        // is_shadow_confederation フラグが true の場合（区間記録連合）は「最高」と表示
        let teamInitial;
        if (runner.is_shadow_confederation) {
            teamInitial = '最高';
        } else {
            teamInitial = runner.team_short_name || '??';
        }

        const icon = createRunnerIcon(teamInitial, color);
        const latLng = [runner.latitude, runner.longitude];
        const marker = L.marker(latLng, { icon: icon });
        
        let popupContent;
        if (runner.is_shadow_confederation) {
            // 区間記録連合用のポップアップ内容
            const editionText = runner.edition ? `：第${runner.edition}回` : '';
            popupContent = `
                <b>区間記録${editionText}</b><br>
                走者: ${formatRunnerName(runner.runner_name)}<br>
                総距離: ${runner.total_distance_km.toFixed(1)} km
            `;
        } else {
            // 通常チーム用のポップアップ内容
            popupContent = `
                <b>${runner.rank}位: ${runner.team_short_name} (${runner.team_name})</b><br>
                走者: ${formatRunnerName(runner.runner_name)}<br>
                総距離: ${runner.total_distance_km.toFixed(1)} km
            `;
        }
        marker.bindPopup(popupContent);

        // Add click event to scroll to the ranking table and highlight the row
        marker.on('click', () => {
            const teamRow = document.getElementById(`team-rank-row-${runner.rank}`);
            if (teamRow) {
                teamRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                highlightRow(teamRow);
            }
        });

        runnerMarkersLayer.addLayer(marker);
    });

    // --- Map View Update Logic ---
    if (trackedTeamName === "full_course") {
        // --- Show the entire course ---
        if (coursePolyline) {
            map.fitBounds(coursePolyline.getBounds().pad(0.1));
        }
    } else if (trackedTeamName === "all_teams") {
        // --- Show all teams ---
        const allRunnerLatLngs = runnerLocations.map(r => [r.latitude, r.longitude]);
        const bounds = L.latLngBounds(allRunnerLatLngs);
        map.fitBounds(bounds.pad(0.1)); // .pad(0.1) for some margin
    } else if (trackedTeamName === "shadow_confederation") {
        // --- 「区間記録連合」と「先頭走者」を追跡 ---
        const shadowRunner = runnerLocations.find(r => r.is_shadow_confederation);

        // 正規の走行中トップ選手を探す (ゴール済みと区間記録連合は除く)
        const activeTopRunner = runnerLocations.find(runner => {
            return runner.total_distance_km < finalGoalDistance && !runner.is_shadow_confederation;
        });

        const trackingGroup = [];
        if (shadowRunner) trackingGroup.push(shadowRunner);
        if (activeTopRunner) trackingGroup.push(activeTopRunner);

        if (trackingGroup.length > 0) {
            const groupLatLngs = trackingGroup.map(r => [r.latitude, r.longitude]);
            const bounds = L.latLngBounds(groupLatLngs);
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
        }
    } else if (trackedTeamName && trackedTeamName !== "lead_group") {
        // --- Track a specific team ---
        const trackedRunner = runnerLocations.find(r => r.team_name === trackedTeamName);
        if (trackedRunner) {
            map.setView([trackedRunner.latitude, trackedRunner.longitude], 14);
        }
    } else { // Default is "lead_group"
        // --- 先頭集団を追跡（動的ロジック） ---

        // 「走行中」の選手を、ゴールしておらず、かつ区間記録連合ではない正規選手として定義する
        // リストは既に順位でソート済み
        const activeRunners = runnerLocations.filter(runner => {
            return runner.total_distance_km < finalGoalDistance && !runner.is_shadow_confederation;
        });

        // 走行中の選手がいる場合、先頭の1〜2名に焦点を当てる
        if (activeRunners.length > 0) {
            const leadGroup = activeRunners.slice(0, 2);
            if (leadGroup.length > 1) {
                const leadGroupLatLngs = leadGroup.map(r => [r.latitude, r.longitude]);
                const bounds = L.latLngBounds(leadGroupLatLngs);
                map.fitBounds(bounds, { padding: [30, 30], maxZoom: 14 });
            } else { // 走行中の選手が残り1人の場合
                map.setView([leadGroup[0].latitude, leadGroup[0].longitude], 13);
            }
        } else {
            // 全選手がゴールした場合、コース全体を表示
            if (coursePolyline) {
                map.fitBounds(coursePolyline.getBounds().pad(0.1));
            }
        }
    }
}

/**
 * 駅伝用のテーブルヘッダーを生成します。
 */
const createEkidenHeader = () => {
    const rankingHead = document.getElementById('ekidenRankingHead');
    if (!rankingHead) return;
    rankingHead.innerHTML = `
        <tr>
            <th>順位</th>
            <th>大学名</th>
            <th>現在<br>走者</th>
            <th>本日距離<br>(順位)</th>
            <th>総合距離</th>
            <th class="hide-on-mobile">トップ差</th>
            <th class="hide-on-mobile">順位変動<br>(前日)</th>
            <th class="hide-on-mobile">次走者</th>
        </tr>
    `;
};

/**
 * 区間記録用のテーブルヘッダーを生成します。
 */
const createLegRankingHeader = () => {
    const rankingHead = document.getElementById('legRankingHead');
    if (!rankingHead) return;
    rankingHead.innerHTML = `
        <tr>
            <th>順位</th>
            <th>走者</th>
            <th>大学名</th>
            <th>区間距離</th>
        </tr>
    `;
};

/**
 * 区間賞用のトップ3テーブルを生成するヘルパー関数
 * @param {Array} records - 表示する記録の配列
 * @returns {HTMLTableElement} - 生成されたテーブル要素
 */
const createPrizeTable = (records) => {
    const table = document.createElement('table');
    // ID is now set dynamically by the caller, class is used for styling

    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr>
            <th>順位</th>
            <th>走者</th>
            <th>大学名</th>
            <th>平均距離</th>
        </tr>
    `;

    const tbody = document.createElement('tbody');
    let lastDistance = -1;
    let lastRank = 0;
    records.forEach((record, index) => {
        // 同順位処理
        if (record.averageDistance !== lastDistance) {
            lastRank = index + 1;
            lastDistance = record.averageDistance;
        }
        const medal = getMedalEmoji(lastRank);
        const formattedRunnerName = formatRunnerName(record.runnerName);
        const teamNameHtml = `<span class="full-name">${record.teamDetails.name}</span><span class="short-name">${record.teamDetails.short_name}</span>`;
        const row = document.createElement('tr');
        row.innerHTML = `<td>${lastRank}</td>
            <td class="runner-name player-profile-trigger" data-runner-name="${record.runnerName}">${medal} ${formattedRunnerName}</td>
            <td class="team-name">${teamNameHtml}</td>
            <td>${record.averageDistance.toFixed(3)} km</td>`;
        tbody.appendChild(row);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return table;
};

/**
 * Renders the individual ranking table for a specific leg.
 * @param {number} legNumber - The leg to display rankings for.
 * @param {object} realtimeData - The data from realtime_report.json.
 * @param {object} individualData - The data from individual_results.json.
 * @param {Map<number, object>} teamsInfoMap - A map of team IDs to team details {name, short_name}.
 */
const displayLegRankingFor = (legNumber, realtimeData, individualData, teamsInfoMap) => {
    const legRankingBody = document.getElementById('legRankingBody');
    const legRankingTitle = document.getElementById('legRankingTitle');
    const legRankingStatus = document.getElementById('legRankingStatus');

    if (!legRankingBody || !legRankingTitle || !legRankingStatus) return;

    // Find teams currently in this leg
    const teamsInThisLeg = new Set(realtimeData.teams.filter(t => t.currentLeg === legNumber).map(t => t.id));

    const runnersToShow = [];
    for (const runnerName in individualData) {
        const runnerData = individualData[runnerName];
        // Check if this runner's team is currently in the selected leg
        if (teamsInThisLeg.has(runnerData.teamId)) {
            // Find the runner's record for this specific leg
            const recordsForLeg = runnerData.records.filter(r => r.leg === legNumber);
            if (recordsForLeg.length > 0) {
                const legTotalDistance = recordsForLeg.reduce((sum, record) => sum + record.distance, 0);
                const teamDetails = teamsInfoMap.get(runnerData.teamId) || { name: 'N/A', short_name: 'N/A' };
                runnersToShow.push({
                    runnerName,
                    teamDetails: teamDetails,
                    legDistance: legTotalDistance
                });
            }
        }
    }

    // Sort and display
    runnersToShow.sort((a, b) => b.legDistance - a.legDistance);

    legRankingBody.innerHTML = '';
    if (runnersToShow.length > 0) {
        legRankingStatus.style.display = 'none';
        let lastDistance = -1;
        let lastRank = 0;
        runnersToShow.forEach((record, index) => {
            // 同順位処理
            if (record.legDistance !== lastDistance) {
                lastRank = index + 1;
                lastDistance = record.legDistance;
            }
            const formattedRunnerName = formatRunnerName(record.runnerName);
            const teamNameHtml = `<span class="full-name">${record.teamDetails.name}</span><span class="short-name">${record.teamDetails.short_name}</span>`;
            const row = document.createElement('tr');
            row.innerHTML = `<td>${lastRank}</td>
                <td class="runner-name player-profile-trigger" data-runner-name="${record.runnerName}">${formattedRunnerName}</td>
                <td class="team-name">${teamNameHtml}</td>
                <td>${record.legDistance.toFixed(1)} km</td>`;
            legRankingBody.appendChild(row);
        });
    } else {
        legRankingStatus.textContent = `本日、${legNumber}区の記録はまだありません。`;
        legRankingStatus.className = 'result loading';
        legRankingStatus.style.display = 'block';
    }
};

/**
 * Handles the click event for a leg tab.
 * @param {number} legNumber - The leg number of the clicked tab.
 * @param {object} realtimeData - The data from realtime_report.json.
 * @param {object} individualData - The data from individual_results.json.
 * @param {Map<number, object>} teamsInfoMap - A map of team IDs to team details {name, short_name}.
 */
const switchLegTab = (legNumber, realtimeData, individualData, teamsInfoMap) => {
    document.querySelectorAll('.leg-tab').forEach(tab => {
        tab.classList.toggle('active', parseInt(tab.dataset.leg, 10) === legNumber);
    });
    displayLegRankingFor(legNumber, realtimeData, individualData, teamsInfoMap);
};

/**
 * Updates the individual records section, including tabs and leg prize.
 * @param {object} realtimeData - realtime_report.json のデータ
 * @param {object} individualData - individual_results.json のデータ
 * @param {object} ekidenData - ekiden_data.json のデータ
 */
const updateIndividualSections = (realtimeData, individualData, ekidenData) => {
    const teamsInfoMap = new Map(realtimeData.teams.map(t => [t.id, { name: t.name, short_name: t.short_name }]));
    const legPrizeWinnerDiv = document.getElementById('legPrizeWinner');
    const tabsContainer = document.getElementById('leg-tabs-container');

    if (!legPrizeWinnerDiv || !tabsContainer) return;

    // ekiden_data.json から最大区間数を取得
    const maxLegs = ekidenData.leg_boundaries.length;

    // 1. Identify and sort active legs
    const activeLegs = [...new Set(realtimeData.teams.map(t => t.currentLeg))]
        .filter(leg => leg <= maxLegs) // ゴール済み(11区)など、最大区間数より大きい区間を除外
        .sort((a, b) => b - a);

    // 2. Generate and display tabs
    tabsContainer.innerHTML = ''; // Clear old tabs
    activeLegs.forEach((leg, index) => {
        const tab = document.createElement('button');
        tab.className = 'leg-tab';
        if (index === 0) {
            tab.classList.add('active'); // First tab is active by default
        }
        tab.textContent = `${leg}区`;
        tab.dataset.leg = leg; // Store leg number in data attribute
        tab.onclick = () => switchLegTab(leg, realtimeData, individualData, teamsInfoMap);
        tabsContainer.appendChild(tab);
    });

    // 3. Display the ranking for the default (leading) leg
    if (activeLegs.length > 0) {
        displayLegRankingFor(activeLegs[0], realtimeData, individualData, teamsInfoMap);
    }

    // 4. Handle Leg Prize
    legPrizeWinnerDiv.innerHTML = ''; // 以前の内容をクリア
    legPrizeWinnerDiv.style.display = 'none'; // Hide by default

    // Find the minimum current leg across all teams. This determines which legs are fully completed.
    let minCurrentLeg = Math.min(...realtimeData.teams.map(t => t.currentLeg));

    // --- 表示テスト用 ---
    // 以下の行を有効にすると、3区が進行中（1区と2区の記録が確定済み）の状態をシミュレートできます。
    // テストが終わったら、この行を削除またはコメントアウトしてください。
    // minCurrentLeg = 3;

    // Identify all legs that are fully finished (from leg 1 up to minCurrentLeg - 1)
    const finishedLegs = [];
    for (let leg = 1; leg < minCurrentLeg; leg++) {
        finishedLegs.push(leg);
    }

    // If there are any finished legs, show the section container.
    if (finishedLegs.length > 0) {
        legPrizeWinnerDiv.style.display = 'block';
    }

    // Loop through the finished legs in ascending order (1, 2, 3...).
    finishedLegs.sort((a, b) => a - b).forEach(finishedLeg => {
        const legPerformances = [];

        for (const runnerName in individualData) {
            const runnerData = individualData[runnerName];
            // Find all records for this specific leg
            const recordsForLeg = runnerData.records.filter(r => r.leg === finishedLeg);

            if (recordsForLeg.length > 0) {
                const totalDistance = recordsForLeg.reduce((sum, r) => sum + r.distance, 0);
                const averageDistance = totalDistance / recordsForLeg.length;

                legPerformances.push({
                    runnerName,
                    teamDetails: teamsInfoMap.get(runnerData.teamId) || { name: 'N/A', short_name: 'N/A' },
                    averageDistance: averageDistance
                });
            }
        }

        if (legPerformances.length > 0) {
            // Sort by average distance
            legPerformances.sort((a, b) => b.averageDistance - a.averageDistance);

            const legContainer = document.createElement('div');
            legContainer.className = 'leg-prize-item';

            const title = document.createElement('h4');
            title.textContent = `${finishedLeg}区`;
            legContainer.appendChild(title);

            const prizeTable = createPrizeTable(legPerformances);
            prizeTable.classList.add('leg-prize-table'); // Use a class for common styling
            prizeTable.id = `legPrizeTable-${finishedLeg}`; // Unique ID for each table
            legContainer.appendChild(prizeTable);

            // Add a "show more" button if there are more than 3 records
            if (legPerformances.length > 3) {
                prizeTable.classList.add('collapsed');

                const toggleContainer = document.createElement('div');
                toggleContainer.className = 'toggle-prize-view';

                const toggleButton = document.createElement('button');
                toggleButton.textContent = '全員の記録を見る ▼';
                toggleButton.onclick = () => {
                    prizeTable.classList.remove('collapsed');
                    toggleContainer.innerHTML = ''; // Remove the button after click
                };
                toggleContainer.appendChild(toggleButton);
                legContainer.appendChild(toggleContainer);
            }

            legPrizeWinnerDiv.appendChild(legContainer);
        }
    });

    // Toggle visibility of the navigation link based on whether any prize sections are displayed
    const legPrizeNavLink = document.querySelector('a[href="#section-leg-prize"]');
    if (legPrizeNavLink) {
        if (legPrizeWinnerDiv.style.display === 'block') {
            legPrizeNavLink.parentElement.style.display = '';
        } else {
            legPrizeNavLink.parentElement.style.display = 'none';
        }
    }
};

let rankHistoryChartInstance = null; // グラフのインスタンスを保持する変数

/**
 * Renders a line chart for rank history.
 */
async function displayRankHistoryChart() {
    const canvas = document.getElementById('rankHistoryChart');
    const statusEl = document.getElementById('rankHistoryStatus');

    // 既存のチャートインスタンスがあれば破棄して、再描画に備える
    if (rankHistoryChartInstance) {
        rankHistoryChartInstance.destroy();
    }

    if (!canvas || !statusEl) return;

    statusEl.textContent = 'Loading rank fluctuation chart...';
    statusEl.className = 'result loading';
    statusEl.style.display = 'block';

    try {
        // Fetch history data and team color info in parallel
        const [historyRes, ekidenDataRes] = await Promise.all([
            fetch(`data/rank_history.json?_=${new Date().getTime()}`),
            fetch(`config/ekiden_data.json?_=${new Date().getTime()}`)
        ]);

        if (!historyRes.ok || !ekidenDataRes.ok) {
            throw new Error('Failed to fetch data for the chart.');
        }

        const historyData = await historyRes.json();
        const ekidenData = await ekidenDataRes.json();

        if (!historyData || !historyData.dates || historyData.dates.length === 0) {
            throw new Error('No rank history available to display.');
        }

        // Create a map of team IDs to colors
        const teamColorMap = new Map(ekidenData.teams.map(t => [t.id, t.color]));

        const datasets = historyData.teams.map(team => {
            return {
                label: team.name,
                data: team.ranks,
                borderColor: teamColorMap.get(team.id) || '#cccccc',
                backgroundColor: (teamColorMap.get(team.id) || '#cccccc') + '33', // Add transparency
                fill: false,
                tension: 0.1,
                borderWidth: 2,
                pointRadius: 3,
                pointHoverRadius: 6
            };
        });
        
        // Dynamically set the chart width
        const chartWrapper = canvas.parentElement;
        const chartWidth = Math.max(400, historyData.dates.length * 20); // 最小幅を400pxに、1日あたりの幅を20pxに調整
        chartWrapper.style.width = `${chartWidth}px`;

        rankHistoryChartInstance = new Chart(canvas, {
            type: 'line',
            data: {
                labels: historyData.dates.map((_, index) => `${index + 1}日目`), // X軸を経過日数に変更
                datasets: datasets
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        reverse: true, // Rank 1 should be at the top
                        min: 0.5, // グラフ上部の余白を確保
                        max: historyData.teams.length + 0.5, // グラフ下部の余白を確保
                        ticks: {
                            stepSize: 1, // Integer steps for rank
                            callback: function(value) {
                                if (Math.floor(value) === value) {
                                    return value;
                                }
                            }
                        },
                        title: {
                            display: true,
                            text: '総合順位'
                        }
                    },
                    x: {
                         title: {
                            display: true,
                            text: '経過日数'
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        onClick: (e, legendItem, legend) => {
                            const chart = legend.chart;
                            const index = legendItem.datasetIndex;

                            // Check if the clicked item is already highlighted (borderWidth > 2)
                            const isAlreadyHighlighted = chart.data.datasets[index].borderWidth > 2;

                            // First, reset all datasets to their default style
                            chart.data.datasets.forEach((dataset, i) => {
                                const teamId = historyData.teams[i].id;
                                dataset.borderColor = teamColorMap.get(teamId) || '#cccccc';
                                dataset.borderWidth = 2;
                            });

                            // If it was not a "reset" click, highlight the new one and dim others
                            if (!isAlreadyHighlighted) {
                                chart.data.datasets.forEach((dataset, i) => {
                                    if (i === index) {
                                        dataset.borderWidth = 4; // Highlight selected
                                    } else {
                                        dataset.borderColor = '#e0e0e0'; // Dim others
                                        dataset.borderWidth = 1;
                                    }
                                });
                            }
                            chart.update();
                        }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: function(tooltipItems) {
                                const day = tooltipItems[0].dataIndex + 1;
                                return `${day}日目 (${historyData.dates[tooltipItems[0].dataIndex]})`;
                            },
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += `Rank ${context.parsed.y}`;
                                }
                                return label;
                            }
                        }
                    }
                },
                interaction: {
                    mode: 'index',
                    intersect: false,
                }
            }
        });

        statusEl.style.display = 'none';

    } catch (error) {
        console.error('Failed to render rank history chart:', error);
        statusEl.textContent = `Failed to display chart: ${error.message}`;
        statusEl.className = 'result error';
    }
}

/**
 * 区間通過順位のテーブルを生成・表示します。
 */
async function displayLegRankHistoryTable() {
    const sectionEl = document.getElementById('section-leg-rank-history');
    const headEl = document.getElementById('legRankHistoryHead');
    const bodyEl = document.getElementById('legRankHistoryBody');
    const statusEl = document.getElementById('legRankHistoryStatus');
    const tableEl = document.getElementById('legRankHistoryTable');
    const openRankHistoryModalBtn = document.getElementById('openRankHistoryModalBtn');

    if (!sectionEl || !headEl || !bodyEl || !statusEl || !tableEl || !openRankHistoryModalBtn) return;

    // ボタンを一旦非表示にする
    openRankHistoryModalBtn.style.display = 'none';

    statusEl.textContent = '区間通過順位を読み込み中...';
    statusEl.className = 'result loading';
    statusEl.style.display = 'block';
    tableEl.style.display = 'none';

    try {
        // 必要なデータを並行して取得 (グラフ用のrank_history.jsonもここでチェック)
        const [legHistoryRes, rankHistoryRes, ekidenDataRes, realtimeRes, intramuralRes] = await Promise.all([
            fetch(`data/leg_rank_history.json?_=${new Date().getTime()}`),
            fetch(`data/rank_history.json?_=${new Date().getTime()}`),
            fetch(`config/ekiden_data.json?_=${new Date().getTime()}`),
            fetch(`data/realtime_report.json?_=${new Date().getTime()}`),
            fetch(`data/intramural_rankings.json?_=${new Date().getTime()}`) // 学内ランキングデータの有無を確認するために取得
        ]);

        // グラフ用のデータが存在する場合のみボタンを表示
        if (rankHistoryRes.ok) {
            const rankHistoryData = await rankHistoryRes.json();
            if (rankHistoryData && rankHistoryData.dates && rankHistoryData.dates.length > 0) {
                openRankHistoryModalBtn.style.display = 'block';
            }
        }

        // leg_rank_history.json (推移表のデータ) がない場合はメッセージを表示して終了
        if (legHistoryRes.status === 404) {
            statusEl.textContent = '順位推移の記録はまだありません。';
            return;
        }

        // 他の必須ファイルがない場合はエラー表示
        if (!legHistoryRes.ok || !ekidenDataRes.ok || !realtimeRes.ok) {
            throw new Error('表示に必要な基本データの取得に失敗しました。');
        }

        const historyData = await legHistoryRes.json();
        const ekidenData = await ekidenDataRes.json();
        const realtimeData = await realtimeRes.json();
        const intramuralData = intramuralRes.ok ? await intramuralRes.json() : null;

        if (!historyData || !historyData.teams || historyData.teams.length === 0) {
            throw new Error('表示する区間通過順位データがありません。');
        }

        // ヘッダーを日本語化し、往路・復路のグループ化を追加
        const numLegs = ekidenData.leg_boundaries.length;
        const outwardLegs = 5; // 往路は5区間
        const returnLegs = numLegs - outwardLegs; // 復路は残り

        let headerHtml = `
            <tr>
                <th class="team-name" rowspan="2">大学名</th>
                <th colspan="${outwardLegs}">往路</th>
                <th colspan="${returnLegs}">復路</th>
            </tr>
            <tr>
        `;
        for (let i = 1; i <= numLegs; i++) {
            headerHtml += `<th>${i}区</th>`;
        }
        headerHtml += '</tr>';
        headEl.innerHTML = headerHtml;

        // 現在の総合順位でチームをソートするためのMapを作成
        const rankMap = new Map(realtimeData.teams.map(t => [t.id, t.overallRank]));
        const teamInfoMap = new Map(realtimeData.teams.map(t => [t.id, { name: t.name, short_name: t.short_name }]));
        const sortedTeams = [...historyData.teams].sort((a, b) => (rankMap.get(a.id) || 999) - (rankMap.get(b.id) || 999));

        // 学内ランキングデータが存在するチームIDのセットを作成
        const intramuralTeamIds = new Set(intramuralData?.teams?.map(t => t.id) || []);

        // テーブルボディを生成
        bodyEl.innerHTML = sortedTeams.map(team => {
            const teamDetails = teamInfoMap.get(team.id) || { name: team.name, short_name: team.name }; // フォールバック
            const teamNameHtml = `<span class="full-name">${teamDetails.name}</span><span class="short-name">${teamDetails.short_name}</span>`;
            const cellsHtml = team.leg_ranks.map(rank => {
                const isFirst = rank === 1;
                const cellClass = isFirst ? 'class="rank-first"' : '';
                const displayRank = rank !== null ? rank : '-';
                return `<td ${cellClass}>${displayRank}</td>`;
            }).join('');
            const hasIntramuralData = intramuralTeamIds.has(team.id);
            const tdClass = hasIntramuralData ? 'team-name intramural-ranking-trigger' : 'team-name';
            const dataAttr = hasIntramuralData ? `data-team-id="${team.id}"` : '';
            return `<tr><td class="${tdClass}" ${dataAttr}>${teamNameHtml}</td>${cellsHtml}</tr>`;
        }).join('');

        statusEl.style.display = 'none';
        tableEl.style.display = '';
        sectionEl.style.display = 'block';

    } catch (error) {
        console.error('区間通過順位テーブルの描画に失敗:', error);
        statusEl.textContent = `区間通過順位の表示に失敗: ${error.message}`;
        statusEl.className = 'result error';
        tableEl.style.display = 'none';
    }
}

/**
 * Displays a modal with detailed information for a specific team.
 * This is intended for mobile view where some columns are hidden.
 * @param {object} team - The team data object from the report.
 * @param {number} topDistance - The total distance of the leading team.
 */
function showTeamDetailsModal(team, topDistance) {
    const modal = document.getElementById('teamDetailsModal');
    const modalTitle = document.getElementById('modalTeamName');
    const modalBody = document.getElementById('modalTeamDetailsBody');

    if (!modal || !modalTitle || !modalBody) return;

    // モーダルのタイトルに順位と大学名を設定
    modalTitle.textContent = `${team.overallRank}位 ${team.name}`;

    // トップとの差を計算
    const gap = topDistance - team.totalDistance;
    const gapDisplay = team.overallRank === 1 ? '----' : `-${gap.toFixed(1)}km`;

    // 順位変動のテキストを生成
    let rankChangeText = 'ー';
    if (team.previousRank > 0) {
        if (team.overallRank < team.previousRank) { rankChangeText = `▲ (${team.previousRank}位から)`; }
        else if (team.overallRank > team.previousRank) { rankChangeText = `▼ (${team.previousRank}位から)`; }
        else { rankChangeText = `ー (${team.previousRank}位)`; }
    } else { rankChangeText = `ー (前日記録なし)`; }

    // 走者名を整形
    const currentRunnerDisplay = formatRunnerName(team.runner);
    const nextRunnerDisplay = formatRunnerName(team.nextRunner);

    // 距離表示に "km" を追加
    const todayDistanceDisplay = `${team.todayDistance.toFixed(1)}km (${team.todayRank}位)`;
    const totalDistanceDisplay = `${team.totalDistance.toFixed(1)}km`;

    // モーダルの中身を生成
    modalBody.innerHTML = `
        <table class="modal-details-table">
            <tr><th>現在走者</th><td>${currentRunnerDisplay}</td></tr>
            <tr><th>本日距離 (順位)</th><td>${todayDistanceDisplay}</td></tr>
            <tr><th>総合距離</th><td>${totalDistanceDisplay}</td></tr>
            <tr><th>トップ差</th><td>${gapDisplay}</td></tr>
            <tr><th>順位変動 (前日比)</th><td>${rankChangeText}</td></tr>
            <tr><th>次走者</th><td>${nextRunnerDisplay}</td></tr>
        </table>
    `;
    modal.style.display = 'block';
}

/**
 * 取得した駅伝データで順位表を更新します。
 * @param {object} realtimeData - realtime_report.json から取得したデータ
 * @param {object} ekidenData - ekiden_data.json から取得したデータ
 */
const updateEkidenRankingTable = (realtimeData, ekidenData) => {
    const rankingBody = document.getElementById('ekidenRankingBody');
    const rankingStatus = document.getElementById('ekidenRankingStatus');
    if (!rankingBody || !rankingStatus) return;

    if (!realtimeData || !realtimeData.teams || !ekidenData || !ekidenData.leg_boundaries) {
        rankingStatus.textContent = '駅伝ランキングデータを読み込めませんでした。';
        rankingStatus.className = 'result error';
        rankingStatus.style.display = 'block';
        rankingBody.innerHTML = '';
        return;
    }

    rankingStatus.style.display = 'none';
    rankingBody.innerHTML = ''; // テーブルをクリア

    const currentRaceDay = realtimeData.raceDay;
    const finalGoalDistance = ekidenData.leg_boundaries[ekidenData.leg_boundaries.length - 1];

    // トップ差の基準となるチームを決定する
    // 1. まだ走行中のチーム（前日までにゴールしていない）のうち、最上位のチームを探す
    const activeTopTeam = realtimeData.teams.find(t => !(t.finishDay && t.finishDay < currentRaceDay));

    // 2. 基準となる距離と順位を設定
    //    走行中のチームがいればそのチームを基準に、全員がゴール済みなら総合1位を基準にする
    const referenceDistance = activeTopTeam ? activeTopTeam.totalDistance : (realtimeData.teams[0]?.totalDistance || 0);
    const referenceTeamRank = activeTopTeam ? activeTopTeam.overallRank : 1;

    realtimeData.teams.forEach(team => {
        // 総合順位(overallRank)が null または undefined のチーム（例: 区間記録連合）は表示しない
        if (team.overallRank == null) {
            return; // このチームの処理をスキップして次のチームへ
        }

        const row = document.createElement('tr');
        row.id = `team-rank-row-${team.overallRank}`; // Add a unique ID for each row

        const isFinishedPreviously = team.finishDay && team.finishDay < currentRaceDay;
        let finishIcon = '';

        if (isFinishedPreviously) { // 昨日までにゴール（順位確定）
            if (team.overallRank === 1) finishIcon = '🏆 ';
            else if (team.overallRank === 2) finishIcon = '🥈 ';
            else if (team.overallRank === 3) finishIcon = '🥉 ';
            else finishIcon = '🏁 ';
        }

        const createCell = (text, className = '') => {
            const cell = document.createElement('td');
            cell.className = className;
            cell.innerHTML = text; // Allow HTML content like spans
            return cell;
        };

        // トップとの差を計算
        const gap = referenceDistance - team.totalDistance;
        const gapDisplay = (team.overallRank === referenceTeamRank || isFinishedPreviously) ? '----' : `-${gap.toFixed(1)}km`;

        const createRankChangeCell = (team) => {
            const cell = document.createElement('td');
            cell.className = 'rank-change hide-on-mobile';

            let rankChangeIcon = 'ー';
            let rankChangeClass = 'rank-stay';
            if (team.previousRank > 0) {
                if (team.overallRank < team.previousRank) {
                    rankChangeIcon = '▲';
                    rankChangeClass = 'rank-up';
                } else if (team.overallRank > team.previousRank) {
                    rankChangeIcon = '▼';
                    rankChangeClass = 'rank-down';
                }
            }

            const iconSpan = document.createElement('span');
            iconSpan.className = rankChangeClass;
            iconSpan.textContent = rankChangeIcon;

            cell.appendChild(iconSpan);
            cell.append(` (${team.previousRank > 0 ? team.previousRank : '－'})`);
            return cell;
        };

        row.appendChild(createCell(team.overallRank, 'rank'));
        
        // 大学名セルは、フルネームと短縮名を切り替えるために特別なHTML構造を持つ
        const teamNameCell = document.createElement('td');
        teamNameCell.className = 'team-name';
        teamNameCell.innerHTML = `${finishIcon}<span class="full-name">${team.name}</span><span class="short-name">${team.short_name}</span>`;
        row.appendChild(teamNameCell);

        // ログファイルの存在に応じて、クリック可能にするかを決定
        const runnerCellClass = 'runner runner-name player-profile-trigger';
        const runnerCell = createCell(formatRunnerName(team.runner), runnerCellClass); // 常にクリック可能に
        // ログファイルがある場合のみ、グラフ表示用のdata属性を設定
        // 選手名鑑と統合したので、常に選手名(キー)を渡す
        const runnerKey = team.runner.replace(/^\d+/, '');
        runnerCell.dataset.runnerName = runnerKey;

        row.appendChild(runnerCell);

        // 本日距離セル。スマホでは単位(km)を非表示
        const todayCell = document.createElement('td');
        todayCell.className = 'today-distance';
        if (isFinishedPreviously) {
            todayCell.innerHTML = '-';
        } else {
            todayCell.innerHTML = `${team.todayDistance.toFixed(1)}<span class="hide-on-mobile">km</span> (${team.todayRank})`;
        }
        row.appendChild(todayCell);

        // 総合距離セル。スマホでは単位(km)を非表示
        const totalCell = document.createElement('td');
        totalCell.className = 'distance';
        if (isFinishedPreviously) {
            const finishScore = team.finishDay - (team.totalDistance - finalGoalDistance) / 100;
            totalCell.textContent = finishScore.toFixed(3);
        } else {
            totalCell.innerHTML = `${team.totalDistance.toFixed(1)}<span class="hide-on-mobile">km</span>`;
        }
        row.appendChild(totalCell);

        row.appendChild(createCell(gapDisplay, 'gap hide-on-mobile'));
        row.appendChild(createRankChangeCell(team));
        row.appendChild(createCell(formatRunnerName(team.nextRunner), 'next-runner hide-on-mobile'));

        rankingBody.appendChild(row);
    });
};

let isTrackerInitialized = false; // Flag to ensure the tracker is only set up once

/**
 * サーバーから駅伝の最新データを取得します。
 */
const fetchEkidenData = async () => {
    const titleEl = document.getElementById('ekidenRankingTitle');
    const updateTimeEl = document.getElementById('ekidenRankingUpdateTime');
    const statusEl = document.getElementById('ekidenRankingStatus');
    const bodyEl = document.getElementById('ekidenRankingBody');

    if (!titleEl || !updateTimeEl || !statusEl || !bodyEl) {
        console.error("Ekiden ranking elements not found in the DOM.");
        return;
    }

    try {
        // Fetch all necessary data in parallel
        const [realtimeRes, individualRes, runnerLocationsRes, ekidenDataRes, logFileRes] = await Promise.all([
            fetch(`data/realtime_report.json?_=${new Date().getTime()}`),
            fetch(`data/individual_results.json?_=${new Date().getTime()}`),
            fetch(`data/runner_locations.json?_=${new Date().getTime()}`),
            fetch(`config/ekiden_data.json?_=${new Date().getTime()}`),
            fetch(`data/realtime_log.jsonl?_=${new Date().getTime()}`) // ログファイルの存在確認
        ]);

        // ログファイルの存在をチェックしてフラグを更新
        logFileExists = logFileRes.ok;

        // ログファイル以外の必須ファイルを確認
        if (!realtimeRes.ok || !individualRes.ok || !runnerLocationsRes.ok || !ekidenDataRes.ok) {
            throw new Error(`HTTP error! One or more data files failed to load.`);
        }

        const realtimeData = await realtimeRes.json();
        const individualData = await individualRes.json();
        const runnerLocations = await runnerLocationsRes.json();
        const ekidenData = await ekidenDataRes.json();

        // グローバルキャッシュに保存
        ekidenDataCache = ekidenData;

        // --- 今大会の区間順位を計算して individualData に付与する ---
        const dailyLegPerformances = {}; // { day: { leg: [dist1, dist2, ...] } }
        // 1. 日ごと・区間ごとの全記録を収集
        for (const runnerName in individualData) {
            const runner = individualData[runnerName];
            if (runner.records) {
                runner.records.forEach(record => {
                    const { day, leg, distance } = record;
                    if (day === undefined || leg === undefined || distance === undefined) return;

                    if (!dailyLegPerformances[day]) {
                        dailyLegPerformances[day] = {};
                    }
                    if (!dailyLegPerformances[day][leg]) {
                        dailyLegPerformances[day][leg] = [];
                    }
                    dailyLegPerformances[day][leg].push(distance);
                });
            }
        }

        // 2. 各区間の記録を降順ソート
        for (const day in dailyLegPerformances) {
            for (const leg in dailyLegPerformances[day]) {
                dailyLegPerformances[day][leg].sort((a, b) => b - a);
            }
        }

        // 3. 各記録に区間順位を付与
        for (const runnerName in individualData) {
            const runner = individualData[runnerName];
            if (runner.records) {
                runner.records.forEach(record => {
                    const { day, leg, distance } = record;
                    if (day !== undefined && leg !== undefined && distance !== undefined) {
                        const sortedDistances = dailyLegPerformances[day][leg];
                        // 同順位を考慮
                        const rank = sortedDistances.indexOf(distance) + 1;
                        record.legRank = rank;
                    } else {
                        record.legRank = null;
                    }
                });
            }
        }

        lastRealtimeData = realtimeData; // 最新データをグローバル変数に保存

        // データソースの順序に依存しないように、ここで必ずランク順にソートする
        runnerLocations.sort((a, b) => a.rank - b.rank);

        allIndividualData = individualData; // Store data in global variable

        // Populate team tracker dropdown if it hasn't been initialized
        if (!isTrackerInitialized && ekidenData.teams) {
            setupTeamTracker(ekidenData.teams);
            isTrackerInitialized = true;
        }

        // Populate team color map if it's empty
        if (teamColorMap.size === 0) {
            ekidenData.teams.forEach(team => {
                teamColorMap.set(team.name, team.color);
            });
        }

        // Update title and update time
        titleEl.textContent = `🏆 ${realtimeData.raceDay}日目 総合順位`;
        updateTimeEl.textContent = `(更新: ${realtimeData.updateTime})`;

        // Update breaking news comment from realtime_report.json
        const newsContainer = document.getElementById('breaking-news-container');
        if (newsContainer && realtimeData.breakingNewsComment && realtimeData.breakingNewsTimestamp) {
            const comment = realtimeData.breakingNewsComment;
            const date = new Date(realtimeData.breakingNewsTimestamp);
            const timeStr = date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
            newsContainer.textContent = `${comment} (${timeStr}時点)`;
            newsContainer.style.display = 'block';

            // Check for full text and make it clickable
            if (realtimeData.breakingNewsFullText) {
                newsContainer.classList.add('clickable');
                newsContainer.onclick = () => showBreakingNewsModal(realtimeData.breakingNewsFullText);
            } else {
                newsContainer.classList.remove('clickable');
                newsContainer.onclick = null; // Remove click listener if no full text
            }

        } else if (newsContainer) {
            newsContainer.style.display = 'none';
            newsContainer.classList.remove('clickable');
            newsContainer.onclick = null;
        }

        updateEkidenRankingTable(realtimeData, ekidenData);
        updateIndividualSections(realtimeData, individualData, ekidenData);
        updateRunnerMarkers(runnerLocations, ekidenData); // Update map markers

    } catch (error) {
        console.error('Error fetching ekiden data:', error);
        statusEl.textContent = '駅伝関連データの取得に失敗しました。';
        statusEl.className = 'result error';
        statusEl.style.display = 'block';
        bodyEl.innerHTML = '';
    }
};

/**
 * Highlights a table row for a short duration.
 * @param {HTMLElement} row - The table row element to highlight.
 */
function highlightRow(row) {
    // Remove highlight from any other row first
    document.querySelectorAll('#ekidenRankingTable tr.highlighted').forEach(r => {
        r.classList.remove('highlighted');
    });

    // Add highlight to the target row
    row.classList.add('highlighted');

    // Remove the highlight after 2.5 seconds
    setTimeout(() => {
        row.classList.remove('highlighted');
    }, 2500);
}

// --- ポップアップ（モーダル）機能 ---

/**
 * Displays the full breaking news text in a modal.
 * @param {string} fullText - The full text of the breaking news comment.
 */
function showBreakingNewsModal(fullText) {
    const modal = document.getElementById('breakingNewsModal');
    const modalBody = document.getElementById('modalBreakingNewsBody');
    if (modal && modalBody) {
        modalBody.textContent = fullText;
        modal.style.display = 'block';
    }
}

/**
 * ekiden_data.json をもとにエントリーリストを生成して表示します。
 */
async function displayEntryList() {
    const entryListDiv = document.getElementById('entryList');
    if (!entryListDiv) return;

    try {
        const response = await fetch('config/ekiden_data.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();

        entryListDiv.innerHTML = ''; // Clear previous content

        data.teams.forEach(team => {
            const card = document.createElement('div');
            card.className = 'team-card';

            // ゼッケン番号は削除し、タイトルに統合
            const title = document.createElement('h4');
            title.style.borderBottomColor = team.color;
            const titleText = `No.${team.id} ${team.status_symbol || ''} ${team.name} ${team.prefectures || ''}`.trim();
            title.textContent = titleText;
            card.appendChild(title);

            if (team.manager) {
                const manager = document.createElement('span');
                manager.className = 'manager-name';
                manager.textContent = team.manager;
                card.appendChild(manager);
            }

            // 正規メンバー
            const runnersContainer = document.createElement('div');
            runnersContainer.className = 'runners-container';
            team.runners.forEach((runner, index) => {
                const runnerSpan = document.createElement('span');
                runnerSpan.className = 'runner-item player-profile-trigger'; // クリック用のクラスを追加
                runnerSpan.dataset.runnerName = runner.name; // 生の選手名をdata属性に保存
                // 数字を全角に変換
                const fullWidthNumber = String(index + 1).replace(/[0-9]/g, s => String.fromCharCode(s.charCodeAt(0) + 0xFEE0));
                const formattedName = formatRunnerName(runner.name);
                runnerSpan.textContent = `${fullWidthNumber}${formattedName}`;
                runnersContainer.appendChild(runnerSpan);
            });
            card.appendChild(runnersContainer);

            // 補欠メンバー
            if (team.substitutes && team.substitutes.length > 0) {
                const substitutesContainer = document.createElement('div');
                substitutesContainer.className = 'substitutes-container';
                
                const label = document.createElement('div');
                label.className = 'substitutes-label';
                label.textContent = '補欠';
                substitutesContainer.appendChild(label);

                team.substitutes.forEach(substitute => {
                    const subSpan = document.createElement('span');
                    subSpan.className = 'runner-item player-profile-trigger'; // クリック用のクラスを追加
                    subSpan.dataset.runnerName = substitute.name; // 生の選手名をdata属性に保存
                    const formattedName = formatRunnerName(substitute.name);
                    subSpan.textContent = formattedName;
                    substitutesContainer.appendChild(subSpan);
                });
                card.appendChild(substitutesContainer);
            }

            // チーム紹介文
            if (team.description) {
                const descriptionP = document.createElement('p');
                descriptionP.className = 'team-description';
                descriptionP.textContent = team.description;
                card.appendChild(descriptionP);
            }

            entryListDiv.appendChild(card);
        });

    } catch (error) {
        console.error('エントリーリストの生成に失敗:', error);
        entryListDiv.innerHTML = '<p class="result error">エントリーリストの読み込みに失敗しました。</p>';
    }
}

/**
 * outline.json を読み込み、大会概要をページに表示します。
 */
async function displayOutline() {
    const container = document.getElementById('outlineContainer');
    const linkContainer = document.getElementById('main-thread-link-container');
    const mapFrame = document.getElementById('courseMapFrame');
    if (!container) return;

    try {
        const response = await fetch('config/outline.json');
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();

        // 本スレリンクを設定
        if (linkContainer && data.mainThreadUrl) {
            linkContainer.innerHTML = ''; // Clear previous content
            const link = document.createElement('a');
            link.href = data.mainThreadUrl;
            link.className = 'main-thread-link';
            link.textContent = data.mainThreadText || '本スレはこちら';
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            linkContainer.appendChild(link);
        }

        // マップのURLを設定
        if (mapFrame && data.courseMapUrl) {
            mapFrame.src = data.courseMapUrl;
        }

        let html = '<h2>大会開催概要</h2>';

        // 関連リンク
        html += '<h3>関連リンク</h3><ul>';
        data.links.forEach(link => {
            html += `<li><a href="${link.url}" target="_blank" rel="noopener noreferrer">${link.text}</a></li>`;
        });
        html += '</ul>';

        // 大会要項
        html += `<h3>${data.title}</h3>`;
        html += `<p><strong>スタート日:</strong> ${data.details.startDate}</p>`;
        html += `<p><strong>コース:</strong> ${data.details.course}</p>`;

        // 区間
        html += '<h4>区間</h4><ul>';
        data.legs.forEach(leg => {
            html += `<li>${leg}</li>`;
        });
        html += '</ul>';

        // 出場校
        html += '<h4>出場校</h4>';
        html += `<p>${data.teams.description}</p><ul>`;
        data.teams.list.forEach(team => {
            html += `<li>${team}</li>`;
        });
        html += `</ul><p><small>${data.teams.legend}</small></p>`;

        // ルール
        data.rules.forEach(rule => {
            html += `<h4>${rule.title}</h4><p>${rule.content.replace(/\n/g, '<br>')}</p>`;
        });

        // スケジュール
        html += `<h4>${data.schedule.title}</h4><ul>`;
        data.schedule.items.forEach(item => {
            html += `<li>${item}</li>`;
        });
        html += '</ul>';

        // 監督ルール
        html += `<h4>${data.managerRules.title}</h4><p>${data.managerRules.content}</p>`;

        container.innerHTML = html;
    } catch (error) {
        console.error('開催概要の生成に失敗:', error);
        container.innerHTML = '<p class="result error">開催概要の読み込みに失敗しました。</p>';
    }
}

/**
 * daily_summary.jsonを読み込み、本日の総括記事を表示します。
 */
async function displayDailySummary() {
    const container = document.getElementById('daily-summary-container');
    if (!container) return;

    try {
        const response = await fetch(`data/daily_summary.json?_=${new Date().getTime()}`);
        if (!response.ok) {
            // 404 Not Foundはファイルがまだない場合なので、コンテナを非表示にして静かに処理
            container.style.display = 'none';
            return;
        }
        const data = await response.json();

        if (data && data.article) {
            // 日付をフォーマット (YYYY/MM/DD -> YYYY年M月D日)
            const dateParts = data.date.split('/');
            const formattedDate = `${dateParts[0]}年${parseInt(dateParts[1], 10)}月${parseInt(dateParts[2], 10)}日`;

            // 記事をセクション（見出し＋本文）ごとに解析し、適切なHTMLタグに変換
            const sections = data.article.split(/^(?=#)/m); // 行頭の#で見出しセクションを分割
            const htmlParts = sections.map(section => {
                const trimmedSection = section.trim();
                if (!trimmedSection) return '';

                const lines = trimmedSection.split('\n');
                const firstLine = lines.shift();
                const bodyText = lines.join('\n').trim();

                // テキスト内の太字を処理するヘルパー関数
                const processBold = (text) => text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

                if (firstLine.startsWith('##')) {
                    const headingHtml = `<h4>${processBold(firstLine.substring(2).trim())}</h4>`;
                    const bodyHtml = bodyText ? `<p>${processBold(bodyText.replace(/\n/g, '<br>'))}</p>` : '';
                    // 本文がある場合のみ区切り線を追加
                    const separatorHtml = bodyText ? '<hr class="article-separator">' : '';
                    return `${headingHtml}${bodyHtml}${separatorHtml}`;
                } else if (firstLine.startsWith('#')) {
                    const headingHtml = `<h3>${processBold(firstLine.substring(1).trim())}</h3>`;
                    const bodyHtml = bodyText ? `<p>${processBold(bodyText.replace(/\n/g, '<br>'))}</p>` : '';
                    return `${headingHtml}${bodyHtml}`; // 見出し1には区切り線なし
                }
                // 見出しで始まらないセクション（記事の冒頭など）
                return `<p>${processBold(trimmedSection.replace(/\n/g, '<br>'))}</p>`;
            });
            const formattedArticle = htmlParts.join('');

            container.innerHTML = `
                <h3>${formattedDate}のレースハイライト</h3>
                <div class="summary-article">${formattedArticle}</div>
            `;
            container.style.display = 'block';
        } else {
            container.style.display = 'none';
        }
    } catch (error) {
        console.error('日次サマリーの表示に失敗:', error);
        container.style.display = 'none';
    }
}

/**
 * 監督の夜間コメントを談話室形式で表示します。
 */
async function displayManagerComments() {
    const loungeContainer = document.getElementById('manager-lounge-container');
    const loungeContent = document.getElementById('manager-lounge-content');
    const statusEl = document.getElementById('manager-lounge-status');

    if (!loungeContainer || !loungeContent || !statusEl) return;

    try {
        const response = await fetch(`data/manager_comments.json?_=${new Date().getTime()}`);
        if (!response.ok) {
            // 404 Not Foundはファイルがまだない場合なので、静かに処理
            if (response.status === 404) {
                throw new Error('コメントファイルがまだ生成されていません。');
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const comments = await response.json();

        if (comments.length === 0) {
            loungeContainer.style.display = 'none'; // コメントがなければコンテナを非表示
        } else {
            loungeContainer.style.display = 'block'; // コメントがあれば表示
            statusEl.style.display = 'none';
            loungeContent.style.display = 'flex';

            loungeContent.innerHTML = ''; // 以前のコメントをクリア
            
            // 時系列（古い順）で表示するため、取得した配列（新しい順）を逆順にする
            comments.reverse().forEach(comment => {
                const postDiv = document.createElement('div');
                
                // Normalize names for comparison: remove leading '■', trim whitespace,
                // and convert full-width parentheses to half-width.
                const normalizeName = (name) => {
                    if (!name) return '';
                    return name
                        .replace(/^■/, '')
                        .replace(/（/g, '(')
                        .replace(/）/g, ')')
                        .trim();
                };

                const normalizedPostedName = normalizeName(comment.posted_name);
                const normalizedOfficialName = normalizeName(comment.official_name);

                // 正規化された名前が異なる場合のみ、実況担当者とみなす
                const isAnnouncer = normalizedPostedName !== normalizedOfficialName;

                postDiv.className = isAnnouncer ? 'lounge-post announcer' : 'lounge-post manager';

                const postDate = new Date(comment.timestamp);
                const timeStr = postDate.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });

                // 表示には投稿された名前(posted_name)を使用する
                postDiv.innerHTML = `
                    <div class="lounge-post-header">
                        <span class="manager-name">${comment.posted_name}</span>
                        <span class="manager-tripcode">${comment.tripcode}</span>
                    </div>
                    <div class="lounge-post-bubble">
                        <div class="lounge-post-content">${comment.content_html}</div>
                        <div class="lounge-post-time">${timeStr}</div>
                    </div>
                `;
                loungeContent.appendChild(postDiv);
            });
            // 自動で一番下の最新コメントまでスクロール
            loungeContent.scrollTop = loungeContent.scrollHeight;
        }
    } catch (error) {
        // エラー時やファイルがない場合は監督コメント部分を非表示にする
        loungeContainer.style.display = 'none';
    }
}

// --- 学内ランキング機能 ---

/**
 * 学内ランキングをモーダルで表示します。
 * 距離と順位は昨日時点のデータ、ステータスはリアルタイムデータを使用します。
 * @param {number} teamId 表示するチームのID
 */
async function showIntramuralRankingModal(teamId) {
    const modal = document.getElementById('intramuralRankingModal');
    const modalTitle = document.getElementById('modalIntramuralTeamName');
    const updateTimeEl = document.getElementById('modalIntramuralUpdateTime');
    const tableBody = document.getElementById('modalIntramuralRankingBody');
    const statusEl = document.getElementById('modalIntramuralRankingStatus');

    if (!modal || !modalTitle || !updateTimeEl || !tableBody || !statusEl) return;

    // モーダルを準備
    modal.style.display = 'block';
    tableBody.innerHTML = '';
    statusEl.textContent = 'ランキングデータを読み込み中...';
    statusEl.className = 'result loading';
    statusEl.style.display = 'block';

    try {
        // 1. 昨日時点の学内ランキングデータを取得 (キャッシュ or フェッチ)
        if (!intramuralDataCache) {
            const response = await fetch(`data/intramural_rankings.json?_=${new Date().getTime()}`);
            if (!response.ok) throw new Error('学内ランキングデータ(昨日時点)の取得に失敗しました。');
            intramuralDataCache = await response.json();
        }

        // 2. リアルタイムデータと駅伝設定データを取得 (キャッシュから)
        if (!lastRealtimeData || !ekidenDataCache) {
            throw new Error('リアルタイムデータまたは駅伝設定データが読み込まれていません。');
        }

        // 3. 必要なデータを抽出
        const intramuralTeamData = intramuralDataCache.teams.find(t => t.id === teamId);
        const realtimeTeamData = lastRealtimeData.teams.find(t => t.id === teamId);
        const ekidenConfigTeamData = ekidenDataCache.teams.find(t => t.id === teamId);

        if (!intramuralTeamData || !realtimeTeamData || !ekidenConfigTeamData) {
            throw new Error('チーム情報が見つかりませんでした。');
        }

        // 4. モーダルのヘッダー情報を設定
        modalTitle.textContent = `${intramuralTeamData.name} 学内ランキング`;
        updateTimeEl.textContent = `距離・順位は ${intramuralDataCache.updateTime} 時点`;

        // 5. リアルタイムの選手ステータスを決定するための情報を準備
        const currentLeg = realtimeTeamData.currentLeg;
        const activeRunners = ekidenConfigTeamData.runners.map(r => r.name);
        const substitutedOutRunners = realtimeTeamData.substituted_out || [];

        // 6. テーブルを生成
        intramuralTeamData.daily_results.forEach((result, index) => {
            const runnerName = result.runner_name;

            // --- リアルタイムステータスの決定 ---
            let currentStatus = "補欠";
            let statusClass = 'status-sub';
            let rowClass = '';

            if (substitutedOutRunners.includes(runnerName)) {
                currentStatus = "交代済";
                statusClass = 'status-substituted';
                rowClass = 'row-inactive';
            } else if (activeRunners.includes(runnerName)) {
                const runnerLeg = activeRunners.indexOf(runnerName) + 1;
                if (runnerLeg < currentLeg) {
                    currentStatus = "走行済";
                    statusClass = 'status-finished';
                    rowClass = 'row-inactive';
                } else if (runnerLeg === currentLeg) {
                    currentStatus = "走行中";
                    statusClass = 'status-running';
                    rowClass = 'row-active';
                } else {
                    currentStatus = "走行前";
                    statusClass = 'status-upcoming';
                }
            }

            const row = document.createElement('tr');
            if (rowClass) row.className = rowClass;

            row.innerHTML = `
            <td>${index + 1}</td>
            <td class="runner-name player-profile-trigger" data-runner-name="${runnerName}">${formatRunnerName(runnerName)}</td>
            <td>${result.distance.toFixed(1)} km</td>
            <td><span class="status-badge ${statusClass}">${currentStatus}</span></td>
        `;
            tableBody.appendChild(row);
        });

        statusEl.style.display = 'none';

    } catch (error) {
        console.error('学内ランキングモーダルの表示に失敗:', error);
        statusEl.textContent = `エラー: ${error.message}`;
        statusEl.className = 'result error';
    }
}

/**
 * 「たられば」オーダーシミュレーターを管理するクラス
 */
class EkidenSimulator {
    /**
     * コンストラクタ
     * @param {string} modalId - モーダルウィンドウのID
     * @param {string} openBtnId - モーダルを開くボタンのID
     * @param {string} closeBtnId - モーダルを閉じるボタンのID
     * @param {string} universitySelectId - 大学選択セレクトボックスのID
     * @param {string} runBtnId - シミュレーション実行ボタンのID
     * @param {string} orderEditorId - オーダー編集エリアのID
     * @param {string} regularListId - 正規メンバーリストのID
     * @param {string} subListId - 補欠メンバーリストのID
     * @param {string} resultsContainerId - 結果表示コンテナのID
     */
    constructor(modalId, openBtnId, closeBtnId, universitySelectId, runBtnId, orderEditorId, regularListId, subListId, resultsContainerId) {
        // DOM要素のキャッシュ
        this.modal = document.getElementById(modalId);
        this.openBtn = document.getElementById(openBtnId);
        this.closeBtn = document.getElementById(closeBtnId);
        this.universitySelect = document.getElementById(universitySelectId);
        this.runBtn = document.getElementById(runBtnId);
        this.orderEditor = document.getElementById(orderEditorId);
        this.regularList = document.getElementById(regularListId);
        this.subList = document.getElementById(subListId);
        this.resultsContainer = document.getElementById(resultsContainerId);
        this.resultsStatus = document.getElementById('simulator-results-status');
        this.resultsContent = document.getElementById('simulator-results-content');

        // データ
        this.ekidenData = null;
        this.dailyTemperatures = null;
        this.originalTeamState = null; // 比較用の実際の結果

        // 状態
        this.selectedTeamId = null;
        this.isDataLoaded = false;
        this.draggedItem = null;
    }

    /**
     * シミュレーターを初期化する
     */
    async init() {
        this.setupEventListeners();
        // 必要なデータを非同期で読み込む
        await this.fetchData();
    }

    /**
     * イベントリスナーをセットアップする
     */
    setupEventListeners() {
        if (!this.modal || !this.openBtn || !this.closeBtn) return;

        // モーダルを開く
        this.openBtn.addEventListener('click', (e) => {
            e.preventDefault();
            this.openModal();
        });

        // モーダルを閉じる
        this.closeBtn.addEventListener('click', () => this.closeModal());
        window.addEventListener('click', (event) => {
            if (event.target === this.modal) {
                this.closeModal();
            }
        });
        
        // 大学が選択されたらオーダー編集画面を表示
        this.universitySelect.addEventListener('change', () => this.handleUniversityChange());
        
        // シミュレーション実行ボタン
        this.runBtn.addEventListener('click', () => this.runSimulation());
    }

    /**
     * シミュレーションに必要なデータをフェッチする
     */
    async fetchData() {
        try {
            const [ekidenRes, dailyTempRes, stateRes] = await Promise.all([
                fetch(`config/ekiden_data.json?_=${new Date().getTime()}`),
                fetch(`data/daily_temperatures.json?_=${new Date().getTime()}`),
                fetch(`data/ekiden_state.json?_=${new Date().getTime()}`) // 比較用の実際の結果
            ]);

            if (!ekidenRes.ok || !dailyTempRes.ok || !stateRes.ok) {
                throw new Error('シミュレーションに必要なデータの読み込みに失敗しました。');
            }

            this.ekidenData = await ekidenRes.json();
            this.dailyTemperatures = await dailyTempRes.json();
            this.originalTeamState = await stateRes.json();
            
            this.isDataLoaded = true;
            this.populateUniversitySelect();
            console.log('シミュレーター用のデータを読み込みました。');

        } catch (error) {
            console.error('Simulator data fetch error:', error);
            // エラーが発生した場合、シミュレーターボタンを無効化する
            if (this.openBtn) {
                this.openBtn.style.display = 'none';
            }
        }
    }

    /**
     * モーダルを開く処理
     */
    openModal() {
        if (!this.isDataLoaded) {
            alert('シミュレーターのデータがまだ読み込まれていません。しばらく待ってから再度お試しください。');
            return;
        }
        this.modal.style.display = 'block';
    }

    /**
     * モーダルを閉じる処理 (イベントリスナーから呼ばれる)
     */
    closeModal() {
        this.modal.style.display = 'none';
        // 閉じる時に表示状態をリセット
        this.orderEditor.style.display = 'none';
        this.resultsContainer.style.display = 'none';
        this.universitySelect.value = "";
        this.runBtn.disabled = true;
    }

    /**
     * 大学選択のプルダウンメニューを生成する
     */
    populateUniversitySelect() {
        if (!this.ekidenData || !this.ekidenData.teams) return;
        
        // 既存の選択肢をクリア（プレースホルダーは残す）
        this.universitySelect.innerHTML = '<option value="">大学を選んでください</option>';

        this.ekidenData.teams.forEach(team => {
            const option = document.createElement('option');
            option.value = team.id;
            option.textContent = team.name;
            this.universitySelect.appendChild(option);
        });
    }
    
    // --- 以下のメソッドは後のステップで実装します ---
    handleUniversityChange() {
        this.selectedTeamId = parseInt(this.universitySelect.value, 10);
        this.resultsContainer.style.display = 'none'; // 結果を隠す

        if (this.selectedTeamId) {
            this.runBtn.disabled = false;
            this.displayOrderEditor(this.selectedTeamId);
        } else {
            this.runBtn.disabled = true;
            this.orderEditor.style.display = 'none';
        }
    }

    displayOrderEditor(teamId) {
        const team = this.ekidenData.teams.find(t => t.id === teamId);
        if (!team) return;

        this.regularList.innerHTML = '';
        this.subList.innerHTML = '';

        // 正規メンバーリストを生成
        team.runners.forEach((runnerName, index) => {
            const li = document.createElement('li');
            li.dataset.runnerName = runnerName;
            li.draggable = true;
            li.innerHTML = `
                <span>
                    <span class="runner-leg-number">${index + 1}区</span>
                    ${formatRunnerName(runnerName)}
                </span>
            `;
            this.regularList.appendChild(li);
        });

        // 補欠メンバーリストを生成
        (team.substitutes || []).forEach(runnerName => {
            const li = document.createElement('li');
            li.dataset.runnerName = runnerName;
            li.draggable = true;
            li.innerHTML = `<span>${formatRunnerName(runnerName)}</span>`;
            this.subList.appendChild(li);
        });

        this.orderEditor.style.display = 'grid';
        
        // 次のステップで実装するドラッグ＆ドロップ機能をセットアップ
        this.setupDragAndDrop();
    }

    setupDragAndDrop() { console.log('Drag and drop setup will be implemented next.'); }
    runSimulation() { /* シミュレーションの実行 */ console.log('Running simulation!'); }
    displayResults(simulationResult) { /* 結果の表示 */ }
}

/**
 * 選手プロファイルモーダル内のグラフを描画・更新するヘルパー関数
 * @param {string} rawRunnerName - 生の選手名 (e.g., "山形（山形）")
 * @param {number} raceDay - 現在の大会日数
 */
async function renderProfileCharts(rawRunnerName, raceDay) {
    const summaryCanvas = document.getElementById('profileSummaryChart');
    const dailyCanvas = document.getElementById('profileDailyChart');
    const statusEl = document.getElementById('profileChartStatus');

    if (!summaryCanvas || !dailyCanvas || !statusEl) return;

    // 既存のグラフインスタンスを破棄
    if (summaryChartInstance) summaryChartInstance.destroy();
    if (dailyRunnerChartInstance) dailyRunnerChartInstance.destroy();

    try {
        // --- 0. デフォルトで表示する日を決定する ---
        const runnerRecords = allIndividualData[rawRunnerName]?.records;
        if (!runnerRecords || runnerRecords.length === 0) {
            // 今大会の記録がない場合は、グラフ描画処理を中断
            summaryCanvas.style.display = 'none';
            dailyCanvas.style.display = 'none';
            statusEl.style.display = 'none';
            return;
        }

        // 選手が走った最終日をデフォルト表示日とする
        // これにより、走行中の選手は本日が、走り終えた選手は最後の走行日が選択される
        const lastDayRun = Math.max(...runnerRecords.map(r => r.day));
        let selectedDayForDetail = lastDayRun;

        // --- 1. 必要なデータを準備 ---
        const runnerData = allIndividualData[rawRunnerName];
        const teamId = runnerData.teamId;
        const sortedRecords = [...runnerData.records].sort((a, b) => a.day - b.day);

        // --- 2. 下段：日次詳細グラフを更新する内部関数 ---
        const updateDailyDetailChart = async (targetDay) => {
            if (dailyRunnerChartInstance) dailyRunnerChartInstance.destroy();

            // 選手がその日に走った記録があるか確認
            const recordForDay = sortedRecords.find(r => r.day === targetDay);
            if (!recordForDay) {
                dailyCanvas.style.display = 'none'; // 記録がなければグラフを非表示
                return;
            }

            const targetDate = new Date(EKIDEN_START_DATE);
            targetDate.setDate(targetDate.getDate() + targetDay - 1);
            const targetDateStr = targetDate.toISOString().split('T')[0];
            
            const logFilePath = (targetDay === raceDay) 
                ? `data/realtime_log.jsonl` 
                : `data/archive/realtime_log_${targetDateStr}.jsonl`;

            let allLogLines = [];
            try {
                const logResponse = await fetch(`${logFilePath}?_=${new Date().getTime()}`);
                if (logResponse.ok) {
                    const logText = await logResponse.text();
                    if (logText.trim()) {
                        allLogLines = logText.trim().split('\n').map(line => JSON.parse(line));
                    }
                }
            } catch (e) { console.error(`ログファイル ${logFilePath} の読み込みエラー:`, e); }

            const dailyChartData = { labels: [], distances: [] };
            const runnerKeyForLog = `${recordForDay.leg}${rawRunnerName}`;

            allLogLines.forEach(log => {
                if (log.team_id == teamId && log.runner_name === runnerKeyForLog && log.timestamp.startsWith(targetDateStr)) {
                    dailyChartData.labels.push(new Date(log.timestamp));
                    dailyChartData.distances.push(log.distance);
                }
            });

            if (dailyChartData.labels.length === 0) {
                dailyCanvas.style.display = 'none';
                return;
            }
            dailyCanvas.style.display = 'block';

            dailyRunnerChartInstance = new Chart(dailyCanvas, {
                type: 'line',
                data: {
                    labels: dailyChartData.labels,
                    datasets: [{
                        label: `${targetDay}日目 走行距離の推移 (km)`,
                        data: dailyChartData.distances,
                        borderColor: '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.1)',
                        fill: true, tension: 0.1
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    scales: {
                        y: { beginAtZero: false, title: { display: true, text: '距離 (km)' } },
                        x: { type: 'time', time: { unit: 'hour', displayFormats: { hour: 'H:mm' } }, title: { display: true, text: '時刻' }, adapters: { date: { locale: window.dateFns.locale.ja } } }
                    },
                    plugins: {
                        tooltip: { callbacks: { label: (context) => ` ${context.dataset.label}: ${context.parsed.y.toFixed(1)} km` } },
                        datalabels: { display: false }
                    }
                }
            });
        };

        // --- 3. 上段：サマリー棒グラフを描画 ---
        const summaryLabels = sortedRecords.map(r => `${r.day}日目`);
        const summaryData = sortedRecords.map(r => r.distance);
        const initialSelectedIndex = sortedRecords.findIndex(r => r.day === selectedDayForDetail);

        const backgroundColors = summaryLabels.map((_, index) => index === initialSelectedIndex ? 'rgba(255, 99, 132, 0.6)' : 'rgba(54, 162, 235, 0.2)');
        const borderColors = summaryLabels.map((_, index) => index === initialSelectedIndex ? 'rgba(255, 99, 132, 1)' : 'rgba(54, 162, 235, 0.5)');

        summaryChartInstance = new Chart(summaryCanvas, {
            type: 'bar',
            data: {
                labels: summaryLabels,
                datasets: [{
                    label: '日次走行距離 (km)',
                    data: summaryData,
                    backgroundColor: backgroundColors,
                    borderColor: borderColors,
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: { display: true, text: '各日の走行距離 (クリックで推移を表示)', padding: { bottom: 16 } },
                    datalabels: {
                        anchor: 'end', align: 'top',
                        color: (context) => context.dataset.borderColor[context.dataIndex],
                        font: { weight: 'bold' },
                        formatter: (value, context) => {
                            const record = sortedRecords[context.dataIndex];
                            return record.legRank ? `${value.toFixed(1)}km (${record.legRank}位)` : `${value.toFixed(1)}km`;
                        }
                    }
                },
                scales: { y: { beginAtZero: true, title: { display: true, text: '走行距離(km)' } } },
                onClick: async (evt) => {
                    const points = summaryChartInstance.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true);
                    if (points.length) {
                        const clickedIndex = points[0].index;
                        selectedDayForDetail = sortedRecords[clickedIndex].day;
                        summaryChartInstance.data.datasets[0].backgroundColor = summaryLabels.map((_, index) => index === clickedIndex ? 'rgba(255, 99, 132, 0.6)' : 'rgba(54, 162, 235, 0.2)');
                        summaryChartInstance.data.datasets[0].borderColor = summaryLabels.map((_, index) => index === clickedIndex ? 'rgba(255, 99, 132, 1)' : 'rgba(54, 162, 235, 0.5)');
                        summaryChartInstance.update();
                        await updateDailyDetailChart(selectedDayForDetail);
                    }
                }
            }
        });

        statusEl.style.display = 'none';
        summaryCanvas.style.display = 'block';

        // --- 4. 初期表示として、決定された日の詳細グラフを描画 ---
        await updateDailyDetailChart(selectedDayForDetail);

    } catch (error) {
        console.error('選手プロファイルグラフの描画エラー:', error);
        statusEl.textContent = `グラフの描画に失敗しました: ${error.message}`;
        statusEl.className = 'result error';
        statusEl.style.display = 'block';
    }
}

/**
 * 選手名鑑と走行記録を統合した新しいモーダルを表示する
 * @param {string} rawRunnerName - 表示する選手名 (ekiden_data.json に記載の生の名前, e.g., "山形（山形）")
 */
async function showPlayerProfileModal(rawRunnerName) {
    const modal = document.getElementById('playerProfileModal');
    const contentDiv = document.getElementById('playerProfileContent');

    if (!modal || !contentDiv) {
        console.error('モーダル要素が見つかりません。');
        return;
    }

    modal.style.display = 'block';
    contentDiv.innerHTML = '<p class="result loading">選手データを読み込み中...</p>';

    try {
        const profile = playerProfiles[rawRunnerName];
        if (!profile) throw new Error('選手名鑑に情報が見つかりません。');

        const currentPerformance = allIndividualData[rawRunnerName];
        const teamColor = teamColorMap.get(profile.team_name) || '#6c757d';

        const createSectionTitle = (title) => `<h4 style="border-bottom-color: ${teamColor}; color: ${teamColor};">${title}</h4>`;

        let currentPerformanceHtml = '';
        if (currentPerformance && currentPerformance.records && currentPerformance.records.length > 0) {
            currentPerformanceHtml = `
                <div class="profile-section">
                    ${createSectionTitle(`今大会の成績 (第${CURRENT_EDITION}回)`)}
                    <div class="profile-chart-container" style="height: 250px;">
                        <canvas id="profileSummaryChart"></canvas>
                    </div>
                    <div class="profile-chart-container" style="height: 280px;">
                        <canvas id="profileDailyChart"></canvas>
                    </div>
                    <div id="profileChartStatus" class="result loading" style="display: none;"></div>
                </div>`;
        } else {
            currentPerformanceHtml = `
                <div class="profile-section">
                    ${createSectionTitle(`今大会の成績 (第${CURRENT_EDITION}回)`)}
                    <p>今大会の出場記録はありません。</p>
                </div>`;
        }

        const pastEditions = Object.keys(profile.performance || {}).filter(e => parseInt(e, 10) !== CURRENT_EDITION).sort((a, b) => b - a);
        const pastPerformanceHtml = pastEditions.length > 0 ? `
            <div class="profile-section">
                ${createSectionTitle('過去大会成績')}
                <div style="overflow-x: auto;">
                    <table class="profile-table">
                        <thead><tr><th>大会</th><th>区間</th><th>区間順位</th><th>総距離</th><th>平均距離</th></tr></thead>
                        <tbody>
                            ${pastEditions.map(edition => {
                                const perf = profile.performance[edition].summary;
                                return `<tr>
                                    <td>第${edition}回</td>
                                    <td>${perf.legs_run.map(l => `${l}区`).join(', ') || '-'}</td>
                                    <td>${perf.best_leg_rank ? `${perf.best_leg_rank}位` : '-'}</td>
                                    <td>${perf.total_distance.toFixed(1)} km</td>
                                    <td>${perf.average_distance.toFixed(3)} km</td>
                                </tr>`;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            </div>` : '';

        const personalBestHtml = (profile.personal_best && profile.personal_best.length > 0) ? `
            <div class="profile-section">
                ${createSectionTitle('主な区間賞')}
                <div style="overflow-x: auto;">
                    <table class="profile-table">
                        <thead><tr><th>大会</th><th>区間</th><th>記録</th><th>備考</th></tr></thead>
                        <tbody>
                            ${[...profile.personal_best].sort((a, b) => b.edition - a.edition).map(best => `
                                <tr>
                                    <td>第${best.edition}回</td>
                                    <td>${best.leg}区</td>
                                    <td>${best.record.toFixed(3)}</td>
                                    <td>${best.notes.join(', ') || '-'}</td>
                                </tr>`).join('')}
                        </tbody>
                    </table>
                </div>
            </div>` : '';

        contentDiv.innerHTML = `
            <div class="profile-header" style="border-bottom-color: ${teamColor};">
                <h3 class="profile-name">${profile.name}</h3>
                <p class="profile-team" style="color: ${teamColor};">${profile.team_name}</p>
            </div>
            <div class="profile-section">
                <blockquote class="profile-comment" style="border-left-color: ${teamColor};">
                    "${profile.comment || 'コメントはありません。'}"
                </blockquote>
            </div>
            ${currentPerformanceHtml}
            <div class="profile-image-container">
                <img src="${profile.image_url}" alt="${profile.name}" class="profile-image">
            </div>
            <div class="profile-meta-info">
                <p>出身都道府県: ${profile.prefecture || '未設定'}</p>
                <p>観測地点: ${profile.address} (標高: ${profile.elevation}m)</p>
                <p>観測開始: ${profile.start_date}</p>
            </div>
            ${pastPerformanceHtml}
            ${personalBestHtml}
        `;

        // グラフデータがあれば描画
        if (currentPerformance && currentPerformance.records && currentPerformance.records.length > 0) {
            const raceDay = lastRealtimeData ? lastRealtimeData.raceDay : 1;
            await renderProfileCharts(rawRunnerName, raceDay);
        }

    } catch (error) {
        contentDiv.innerHTML = `<p class="result error">データの表示に失敗しました: ${error.message}</p>`;
        console.error('選手プロファイルモーダルの表示エラー:', error);
    }
}

// --- 初期化処理 ---

document.addEventListener('DOMContentLoaded', function() {
    // chartjs-plugin-datalabels が読み込まれていれば、グローバルに登録
    if (window.ChartDataLabels) {
        Chart.register(window.ChartDataLabels);
    }

    // アメダス機能の初期化
    loadStationsData();
    loadPlayerProfiles();
    loadSearchHistory(); // アメダス検索履歴の読み込み
    // loadRanking(); // 全国ランキングは index_16.html には無いためコメントアウト

    document.getElementById('locationInput').addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchTemperature();
        }
    });

    // 駅伝機能の初期化
    createEkidenHeader();
    createLegRankingHeader();

    // --- ページの主要コンテンツを非同期で読み込み ---
    // 1. マップを初期化
    initializeMap();
    // 2. 最も重要な速報データを最初に取得して表示（マップのズームもここで行われる）
    fetchEkidenData();
    // 3. その他のコンテンツを読み込む
    displayDailySummary(); // ★ 新しく追加: 日次サマリー記事
    displayManagerComments(); // 監督談話室
    displayEntryList(); // エントリーリスト
    displayLegRankHistoryTable(); // 順位推移テーブル
    displayOutline(); // 大会概要
    // ページ読み込み時に一度、即座にデータを取得して表示
    fetchEkidenData();
    // 90秒ごとにデータを自動更新
    setInterval(fetchEkidenData, 90000);

    // スマホ表示でのPC/SP版表示切り替えボタンのイベントリスナー
    const toggleBtn = document.getElementById('toggle-ranking-view-btn');
    const rankingContainer = document.querySelector('.ekiden-ranking-container');

    if (toggleBtn && rankingContainer) {
        toggleBtn.addEventListener('click', () => {
            rankingContainer.classList.toggle('show-full-view');
            if (rankingContainer.classList.contains('show-full-view')) {
                toggleBtn.textContent = 'SP版';
            } else {
                toggleBtn.textContent = 'PC版';
            }
        });
    }

    // 総合順位のキャプチャ機能
    const captureBtn = document.getElementById('capture-ranking-btn');
    if (captureBtn) {
        captureBtn.addEventListener('click', () => {
            const targetElement = document.getElementById('section-overall-ranking');
            if (!targetElement) {
                alert('キャプチャ対象が見つかりません。');
                return;
            }

            captureBtn.textContent = 'キャプチャ中...';
            captureBtn.disabled = true;

            html2canvas(targetElement, {
                backgroundColor: '#f8f9fa', // ページの背景色に合わせる
                useCORS: true,
                onclone: (clonedDoc) => {
                    // クローンされたDOM内でキャプチャ不要な要素（操作ボタン）を非表示にする
                    const controls = clonedDoc.querySelector('#section-overall-ranking .header-controls');
                    if (controls) {
                        controls.style.display = 'none';
                    }
                }
            }).then(canvas => {
                const link = document.createElement('a');
                const now = new Date();
                const timestamp = `${now.getFullYear()}${(now.getMonth() + 1).toString().padStart(2, '0')}${now.getDate().toString().padStart(2, '0')}_${now.getHours().toString().padStart(2, '0')}${now.getMinutes().toString().padStart(2, '0')}`;
                link.download = `ekiden_ranking_${timestamp}.png`;
                link.href = canvas.toDataURL('image/png');
                document.body.appendChild(link); // Firefoxでの動作を確実にするため
                link.click();
                document.body.removeChild(link); // 後片付け
            }).catch(err => {
                console.error('キャプチャに失敗しました:', err);
                alert('画像のキャプチャに失敗しました。コンソールを確認してください。');
            }).finally(() => {
                captureBtn.textContent = '📷 キャプチャ';
                captureBtn.disabled = false;
            });
        });
    }

    // チーム詳細モーダルを閉じるイベントリスナー
    const teamModal = document.getElementById('teamDetailsModal');
    const closeTeamButton = document.getElementById('closeTeamModal');
    if (teamModal && closeTeamButton) {
        closeTeamButton.onclick = () => teamModal.style.display = 'none';
        window.addEventListener('click', (event) => {
            if (event.target == teamModal) {
                teamModal.style.display = 'none';
            }
        });
    }

    // Breaking Newsモーダルを閉じるイベントリスナー
    const breakingNewsModal = document.getElementById('breakingNewsModal');
    const closeBreakingNewsBtn = document.getElementById('closeBreakingNewsModal');
    if (breakingNewsModal && closeBreakingNewsBtn) {
        closeBreakingNewsBtn.onclick = () => breakingNewsModal.style.display = 'none';
        window.addEventListener('click', (event) => {
            if (event.target == breakingNewsModal) {
                breakingNewsModal.style.display = 'none';
            }
        });
    }

    // 順位変動グラフモーダルのイベントリスナー
    const rankHistoryModal = document.getElementById('rankHistoryModal');
    const openBtn = document.getElementById('openRankHistoryModalBtn');
    const closeBtn = document.getElementById('closeRankHistoryModal');

    if (openBtn && rankHistoryModal && closeBtn) {
        openBtn.onclick = () => {
            rankHistoryModal.style.display = 'block';
            // モーダルが開かれたときにグラフを描画
            displayRankHistoryChart();
        };
        closeBtn.onclick = () => {
            rankHistoryModal.style.display = 'none';
        };
        window.addEventListener('click', (event) => {
            if (event.target == rankHistoryModal) {
                rankHistoryModal.style.display = 'none';
            }
        });
    }
    // --- 横スクロールのグラデーション制御 ---
    const scrollContainer = document.querySelector('.ekiden-ranking-container');
    if (scrollContainer) {
        const scrollWrapper = scrollContainer.closest('.table-scroll-wrapper');
        if (scrollWrapper) {
            const checkScroll = () => {
                // スクロール位置をチェック (2pxの許容範囲)
                const isAtEnd = scrollContainer.scrollLeft + scrollContainer.clientWidth >= scrollContainer.scrollWidth - 2;
                // scrolled-to-end クラスを付け外しする
                scrollWrapper.classList.toggle('scrolled-to-end', isAtEnd);
            };
            // スクロール時にチェック
            scrollContainer.addEventListener('scroll', checkScroll);
            // 初期表示時とウィンドウリサイズ時にもチェックを実行
            window.addEventListener('resize', checkScroll);
            checkScroll();
        }
    }

    // イベント委譲を使って、選手名鑑モーダルを開くトリガーをまとめて処理
    // (個人記録、区間記録、学内ランキング、エントリーリスト)
    const container = document.querySelector('.container');
    if (container) {
        container.addEventListener('click', (event) => {
            const target = event.target.closest('.player-profile-trigger');
            if (target) {
                const runnerName = target.dataset.runnerName;
                if (runnerName) {
                    showPlayerProfileModal(runnerName);
                }
            }

            const intramuralTarget = event.target.closest('.intramural-ranking-trigger');
            if (intramuralTarget) {
                const teamId = parseInt(intramuralTarget.dataset.teamId, 10);
                showIntramuralRankingModal(teamId);
            }
        });
    }

    // 選手プロフィールモーダルを閉じるイベントリスナー
    const profileModal = document.getElementById('playerProfileModal');
    const closeProfileBtn = document.getElementById('closePlayerProfileModal');
    if (profileModal && closeProfileBtn) {
        const closeProfileModal = () => {
            profileModal.style.display = 'none';
            // モーダルを閉じる際にグラフインスタンスを破棄してメモリリークを防ぐ
            if (summaryChartInstance) {
                summaryChartInstance.destroy();
                summaryChartInstance = null;
            }
            if (dailyRunnerChartInstance) {
                dailyRunnerChartInstance.destroy();
                dailyRunnerChartInstance = null;
            }
        };
        closeProfileBtn.onclick = closeProfileModal;
        window.addEventListener('click', (event) => {
            if (event.target == profileModal) { closeProfileModal(); }
        });
    }

    // 学内ランキングモーダルを閉じるイベントリスナー
    const intramuralModal = document.getElementById('intramuralRankingModal');
    const closeIntramuralBtn = document.getElementById('closeIntramuralRankingModal');
    if (intramuralModal && closeIntramuralBtn) {
        closeIntramuralBtn.onclick = () => intramuralModal.style.display = 'none';
        window.addEventListener('click', (event) => {
            if (event.target == intramuralModal) {
                intramuralModal.style.display = 'none';
            }
        });
    }
    // --- Order Simulator Initialization (このページでは使用しないため無効化) ---
    // const simulator = new EkidenSimulator(...)
    // simulator.init();

    // --- Smooth Scrolling for Page Navigation ---
    // href属性を持つリンクのみを対象にし、ドロップダウンのトグルボタンなどを除外
    document.querySelectorAll('.page-nav a[href]').forEach(anchor => {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');

            try {
                const targetElement = document.querySelector(targetId);
                if (targetElement) {
                    targetElement.scrollIntoView({ behavior: 'smooth' });
                }
            } catch (error) {
                console.error(`Smooth scroll target not found for ${targetId}`, error);
            }

            // モバイル表示でメニューが開いている場合、リンククリック後に閉じる
            const hamburgerBtn = document.getElementById('hamburger-btn');
            const navList = document.getElementById('main-nav-list');
            if (hamburgerBtn && navList && hamburgerBtn.classList.contains('active')) {
                hamburgerBtn.classList.remove('active');
                navList.classList.remove('active');
            }
        });
    });

    // --- Back to Top Button ---
    const backToTopButton = document.getElementById('back-to-top');
    let hideButtonTimer;

    if (backToTopButton) {
        // スクロールイベントでボタンの表示/非表示を制御
        window.addEventListener('scroll', () => {
            // ページ上部では常に非表示
            if (window.scrollY <= 400) {
                backToTopButton.classList.remove('show');
                return;
            }

            // スクロール中は表示し、既存のタイマーをクリア
            backToTopButton.classList.add('show');
            clearTimeout(hideButtonTimer);

            // 1.5秒間スクロールがなければ非表示にする
            hideButtonTimer = setTimeout(() => {
                backToTopButton.classList.remove('show');
            }, 1500);
        });

        // ボタンにマウスが乗っている間は消さない
        backToTopButton.addEventListener('mouseenter', () => {
            clearTimeout(hideButtonTimer);
        });

        // クリックでトップにスムーズスクロール
        backToTopButton.addEventListener('click', (e) => {
            e.preventDefault();
            const targetElement = document.getElementById('page-top');
            if (targetElement) {
                targetElement.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    // --- Hamburger Menu for Mobile ---
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const navList = document.getElementById('main-nav-list');

    if (hamburgerBtn && navList) {
        hamburgerBtn.addEventListener('click', () => {
            hamburgerBtn.classList.toggle('active');
            navList.classList.toggle('active');
        });
    }

    // --- Mobile Dropdown Menu in Navigation ---
    document.querySelectorAll('.page-nav .dropbtn').forEach(button => {
        button.addEventListener('click', function(e) {
            // <a>タグのデフォルト動作をキャンセル
            e.preventDefault();

            // ホバーが効かないモバイル表示の時だけ、クリックで開閉を制御
            if (window.innerWidth <= 768) {
                const dropdown = this.parentElement; // 親要素である li.dropdown を取得
                dropdown.classList.toggle('open'); // openクラスを付け外しする
            }
        });
    });
});