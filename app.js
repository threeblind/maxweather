let stationsData = [];
let allIndividualData = {}; // 選手個人の全記録を保持するグローバル変数

// CORS制限を回避するためのプロキシサーバーURLのテンプレート
const PROXY_URL_TEMPLATE = 'https://api.allorigins.win/get?url=%URL%';

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
        // 4. Fetch course path and relay points data in parallel
        const [coursePathRes, relayPointsRes] = await Promise.all([
            fetch(`course_path.json?_=${new Date().getTime()}`),
            fetch(`relay_points.json?_=${new Date().getTime()}`)
        ]);

        if (!coursePathRes.ok || !relayPointsRes.ok) {
            throw new Error('Failed to fetch map data.');
        }

        const coursePath = await coursePathRes.json();
        const relayPoints = await relayPointsRes.json();

        // 5. Draw the course path
        if (coursePath && coursePath.length > 0) {
            const latlngs = coursePath.map(p => [p.lat, p.lon]);
            coursePolyline = L.polyline(latlngs, { color: '#007bff', weight: 5, opacity: 0.7 }).addTo(map);
            // 初期表示では、コース全体が収まるようにズームします。
            // これにより、データ取得までの間、ユーザーはコースの全体像を把握できます。
            // 実際の先頭集団へのズームは、この後の fetchEkidenData -> updateRunnerMarkers で行われます。
            map.fitBounds(coursePolyline.getBounds().pad(0.1)); // .pad(0.1)で少し余白を持たせる
        }

        // 6. Draw relay point markers
        if (relayPoints && relayPoints.length > 0) {
            relayPoints.forEach(point => {
                L.marker([point.latitude, point.longitude])
                    .addTo(map)
                    .bindPopup(`<b>${point.name}</b><br>${point.target_distance_km} km地点`);
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
        const teamInitial = runner.team_short_name || '??';
        const icon = createRunnerIcon(teamInitial, color);
        const latLng = [runner.latitude, runner.longitude];
        const marker = L.marker(latLng, { icon: icon });

        const popupContent = `
            <b>${runner.rank}位: ${runner.team_short_name} (${runner.team_name})</b><br>
            走者: ${formatRunnerName(runner.runner_name)}<br>
            総距離: ${runner.total_distance_km.toFixed(1)} km
        `;
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
    } else if (trackedTeamName && trackedTeamName !== "lead_group") {
        // --- Track a specific team ---
        const trackedRunner = runnerLocations.find(r => r.team_name === trackedTeamName);
        if (trackedRunner) {
            map.setView([trackedRunner.latitude, trackedRunner.longitude], 14, {
                animate: true,
                pan: {
                    duration: 1
                }
            });
        }
    } else { // Default is "lead_group"
        // --- 先頭集団を追跡（動的ロジック） ---

        // 「走行中」の選手を、最終ゴール距離に到達していない選手として定義する
        // リストは既に順位でソート済み
        const activeRunners = runnerLocations.filter(runner => {
            return runner.total_distance_km < finalGoalDistance;
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
        row.innerHTML = `
            <td>${lastRank}</td>
            <td class="runner-name" onclick="showPlayerRecords('${record.runnerName}')">${medal} ${formattedRunnerName}</td>
            <td class="team-name">${teamNameHtml}</td>
            <td>${record.averageDistance.toFixed(3)} km</td>
        `;
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
            row.innerHTML = `
                <td>${lastRank}</td>
                <td class="runner-name" onclick="showPlayerRecords('${record.runnerName}')">${formattedRunnerName}</td>
                <td class="team-name">${teamNameHtml}</td>
                <td>${record.legDistance.toFixed(1)} km</td>
            `;
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
 */
const updateIndividualSections = (realtimeData, individualData) => {
    const teamsInfoMap = new Map(realtimeData.teams.map(t => [t.id, { name: t.name, short_name: t.short_name }]));
    const legPrizeWinnerDiv = document.getElementById('legPrizeWinner');
    const tabsContainer = document.getElementById('leg-tabs-container');

    if (!legPrizeWinnerDiv || !tabsContainer) return;

    // 1. Identify and sort active legs
    const activeLegs = [...new Set(realtimeData.teams.map(t => t.currentLeg))].sort((a, b) => b - a);

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
            fetch(`rank_history.json?_=${new Date().getTime()}`),
            fetch(`ekiden_data.json?_=${new Date().getTime()}`)
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
    const headEl = document.getElementById('legRankHistoryHead');
    const bodyEl = document.getElementById('legRankHistoryBody');
    const statusEl = document.getElementById('legRankHistoryStatus');
    const tableEl = document.getElementById('legRankHistoryTable');

    if (!headEl || !bodyEl || !statusEl || !tableEl) return;

    statusEl.textContent = '区間通過順位を読み込み中...';
    statusEl.className = 'result loading';
    statusEl.style.display = 'block';

    try {
        // 必要なデータを並行して取得
        const [historyRes, ekidenDataRes, realtimeRes] = await Promise.all([
            fetch(`leg_rank_history.json?_=${new Date().getTime()}`),
            fetch(`ekiden_data.json?_=${new Date().getTime()}`),
            fetch(`realtime_report.json?_=${new Date().getTime()}`)
        ]);

        if (!historyRes.ok || !ekidenDataRes.ok || !realtimeRes.ok) {
            throw new Error('区間通過順位データの取得に失敗しました。');
        }

        const historyData = await historyRes.json();
        const ekidenData = await ekidenDataRes.json();
        const realtimeData = await realtimeRes.json();

        if (!historyData || !historyData.teams) {
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
            return `<tr><td class="team-name">${teamNameHtml}</td>${cellsHtml}</tr>`;
        }).join('');

        statusEl.style.display = 'none';

    } catch (error) {
        console.error('区間通過順位テーブルの描画に失敗:', error);
        statusEl.textContent = `区間通過順位の表示に失敗: ${error.message}`;
        statusEl.className = 'result error';
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

    const topDistance = realtimeData.teams[0]?.totalDistance || 0;
    const currentRaceDay = realtimeData.raceDay;
    const finalGoalDistance = ekidenData.leg_boundaries[ekidenData.leg_boundaries.length - 1];

    realtimeData.teams.forEach(team => {
        const row = document.createElement('tr');
        row.id = `team-rank-row-${team.overallRank}`; // Add a unique ID for each row

        const isFinishedPreviously = team.finishDay && team.finishDay < currentRaceDay;
        const hasReachedGoal = team.totalDistance >= finalGoalDistance;
        let finishIcon = '';

        if (isFinishedPreviously) { // 昨日までにゴール（順位確定）
            if (team.overallRank === 1) finishIcon = '🏆 ';
            else if (team.overallRank === 2) finishIcon = '🥈 ';
            else if (team.overallRank === 3) finishIcon = '🥉 ';
            else finishIcon = '🏁 ';
        } else if (hasReachedGoal) { // 本日ゴール（順位未確定）
            finishIcon = '🏁 ';
        }

        const createCell = (text, className = '') => {
            const cell = document.createElement('td');
            cell.className = className;
            cell.textContent = text;
            return cell;
        };

        // トップとの差を計算
        const gap = topDistance - team.totalDistance;
        const gapDisplay = team.overallRank === 1 ? '----' : `-${gap.toFixed(1)}km`;

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

        // スマホ表示の時だけ、クリックで詳細モーダルを開くイベントリスナーを追加
        teamNameCell.addEventListener('click', () => {
            if (window.innerWidth <= 768) {
                showTeamDetailsModal(team, topDistance);
            }
        });
        row.appendChild(teamNameCell);

        row.appendChild(createCell(formatRunnerName(team.runner), 'runner'));

        // 本日距離セル。スマホでは単位(km)を非表示
        const todayCell = document.createElement('td');
        todayCell.className = 'today-distance';
        todayCell.innerHTML = `${team.todayDistance.toFixed(1)}<span class="hide-on-mobile">km</span> (${team.todayRank})`;
        row.appendChild(todayCell);

        // 総合距離セル。スマホでは単位(km)を非表示
        const totalCell = document.createElement('td');
        totalCell.className = 'distance';
        totalCell.innerHTML = `${team.totalDistance.toFixed(1)}<span class="hide-on-mobile">km</span>`;
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
        const [realtimeRes, individualRes, runnerLocationsRes, ekidenDataRes] = await Promise.all([
            fetch(`realtime_report.json?_=${new Date().getTime()}`),
            fetch(`individual_results.json?_=${new Date().getTime()}`),
            fetch(`runner_locations.json?_=${new Date().getTime()}`),
            fetch(`ekiden_data.json?_=${new Date().getTime()}`)
        ]);

        if (!realtimeRes.ok || !individualRes.ok || !runnerLocationsRes.ok || !ekidenDataRes.ok) {
            throw new Error(`HTTP error! One or more data files failed to load.`);
        }

        const realtimeData = await realtimeRes.json();
        const individualData = await individualRes.json();
        const runnerLocations = await runnerLocationsRes.json();
        const ekidenData = await ekidenDataRes.json();

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
        updateIndividualSections(realtimeData, individualData);
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
 * 選手名がクリックされたときに、その選手の全記録をポップアップで表示します。
 * @param {string} runnerName - 表示する選手名
 */
function showPlayerRecords(runnerName) {
    const runnerData = allIndividualData[runnerName];
    if (!runnerData || !runnerData.records) return;

    const modal = document.getElementById('playerRecordsModal');
    const modalTitle = document.getElementById('modalPlayerName');
    const modalBody = document.getElementById('modalRecordsBody');

    if (!modal || !modalTitle || !modalBody) return;

    modalTitle.textContent = `${formatRunnerName(runnerName)} の全記録`;
    modalBody.innerHTML = ''; // 以前の記録をクリア

    if (runnerData.records.length === 0) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 3;
        cell.textContent = '記録がありません。';
        row.appendChild(cell);
        modalBody.appendChild(row);
    } else {
        // 日付でソートして表示
        const sortedRecords = [...runnerData.records].sort((a, b) => a.day - b.day);
        sortedRecords.forEach((record, index) => {
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${record.leg}区</td>
                <td>${index + 1}日目</td>
                <td>${record.distance.toFixed(1)} km</td>
            `;
            modalBody.appendChild(row);
        });
    }

    modal.style.display = 'block';
}

/**
 * 選手の記録ポップアップを閉じます。
 */
function closePlayerRecordsModal() {
    const modal = document.getElementById('playerRecordsModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * ekiden_data.json をもとにエントリーリストを生成して表示します。
 */
async function displayEntryList() {
    const entryListDiv = document.getElementById('entryList');
    if (!entryListDiv) return;

    try {
        const response = await fetch('ekiden_data.json');
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
                runnerSpan.className = 'runner-item';
                // 数字を全角に変換
                const fullWidthNumber = String(index + 1).replace(/[0-9]/g, s => String.fromCharCode(s.charCodeAt(0) + 0xFEE0));
                const formattedName = formatRunnerName(runner);
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
                    subSpan.className = 'runner-item';
                    const formattedName = formatRunnerName(substitute);
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
        const response = await fetch('outline.json');
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
 * 監督の夜間コメントを談話室形式で表示します。
 */
async function displayManagerComments() {
    const loungeContent = document.getElementById('manager-lounge-content');
    const statusEl = document.getElementById('manager-lounge-status');
    const navLink = document.querySelector('a[href="#section-manager-lounge"]');

    if (!loungeContent || !statusEl || !navLink) return;

    try {
        const response = await fetch(`manager_comments.json?_=${new Date().getTime()}`);
        if (!response.ok) {
            // 404 Not Foundはファイルがまだない場合なので、静かに処理
            if (response.status === 404) {
                throw new Error('コメントファイルがまだ生成されていません。');
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const comments = await response.json();

        if (comments.length === 0) {
            statusEl.textContent = '現在、表示できる監督コメントはありません。';
            statusEl.className = 'result loading';
            statusEl.style.display = 'block';
            loungeContent.style.display = 'none';
            navLink.parentElement.style.display = 'none'; // コメントがなければナビゲーションリンクも非表示
        } else {
            statusEl.style.display = 'none';
            loungeContent.style.display = 'flex';
            navLink.parentElement.style.display = ''; // コメントがあれば表示

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
        // エラー時やファイルがない場合はセクション全体を非表示にする
        statusEl.style.display = 'none';
        loungeContent.style.display = 'none';
        navLink.parentElement.style.display = 'none';
    }
}
// --- 初期化処理 ---

document.addEventListener('DOMContentLoaded', function() {
    // アメダス機能の初期化
    loadStationsData();
    loadSearchHistory();
    loadRanking();

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
    displayManagerComments(); // 監督談話室
    displayEntryList(); // エントリーリスト
    displayLegRankHistoryTable(); // 順位推移テーブル
    displayOutline(); // 大会概要
    // ページ読み込み時に一度、即座にデータを取得して表示
    fetchEkidenData();
    // 30秒ごとにデータを自動更新
    setInterval(fetchEkidenData, 30000);

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

    // モーダルを閉じるイベントリスナーを設定
    const modal = document.getElementById('playerRecordsModal');
    const closeButton = modal.querySelector('.close-button'); // このモーダル内の閉じるボタンを特定
    if (modal && closeButton) {
        closeButton.onclick = closePlayerRecordsModal;
        // モーダルの外側をクリックしたときも閉じる
        window.addEventListener('click', function(event) {
            if (event.target == modal) {
                closePlayerRecordsModal();
            }
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

    // --- キャプチャ機能 ---
    const captureBtn = document.getElementById('capture-ranking-btn');
    if (captureBtn) {
        captureBtn.addEventListener('click', async () => {
            const rankingSection = document.getElementById('section-overall-ranking');
            if (!rankingSection) return;

            // キャプチャ画像にボタンが写り込まないように、処理中は非表示にする
            captureBtn.textContent = '処理中...';
            captureBtn.disabled = true;
            captureBtn.style.visibility = 'hidden';

            try {
                const canvas = await html2canvas(rankingSection, {
                    useCORS: true,
                    backgroundColor: '#f5f5f5', // 背景色を指定
                    windowWidth: window.innerWidth,
                    windowHeight: rankingSection.scrollHeight // 縦方向のスクロール全体をキャプチャ
                });

                const response = await fetch(`realtime_report.json?_=${new Date().getTime()}`);
                const data = await response.json();
                const timeStr = data.updateTime.replace(/[\/:\s]/g, '');
                const fileName = `EkidenRanking_Day${data.raceDay}_${timeStr}.png`;

                const link = document.createElement('a');
                link.download = fileName;
                link.href = canvas.toDataURL('image/png');
                link.click();

            } catch (error) {
                console.error('キャプチャに失敗しました:', error);
                alert('キャプチャに失敗しました。');
            } finally {
                // ボタンを元に戻す
                captureBtn.style.visibility = 'visible';
                captureBtn.textContent = '📷 キャプチャ';
                captureBtn.disabled = false;
            }
        });
    }
});