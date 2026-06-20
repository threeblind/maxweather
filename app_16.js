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
let legAverageRankingsCache = new Map(); // 区間別平均距離ランキングのキャッシュ
let legRankHistoryData = null; // leg_rank_history.json の内容を保持
let legBestRecordByLeg = new Map(); // 区間最高記録のキャッシュ
let goalLatLng = null; // ゴール地点の座標を保持

// --- 順位変動タイムライン用状態変数 ---
let rankTimelineEvents = [];
let rankTimelineFilter = 'all';
let isRankTimelineExpanded = false;
const SHADOW_TEAM_ID = 99; // マジックナンバー99を排除するための定数

// --- 注目チーム用状態変数 ---
let favoriteTeamIds = new Set();          // 注目中の team.id セット
const FAVORITE_TEAMS_KEY = 'favoriteTeams';
const FAVORITE_MAX = 3;

// CORS制限を回避するためのプロキシサーバーURLのテンプレート
const PROXY_URL_TEMPLATE = 'https://api.allorigins.win/get?url=%URL%';
let EKIDEN_START_DATE = '2026-03-08'; // outline.json で上書き
let CURRENT_EDITION = 16; // outline.json で上書き

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
 * 次走者の表示用テキストを整形する
 * @param {string} currentRunner - 現在走者の名前
 * @param {string} nextRunner - 次走者の名前
 * @returns {string} 表示用の次走者テキスト
 */
const formatNextRunnerDisplay = (currentRunner, nextRunner) => {
    const normalizedCurrent = formatRunnerName(currentRunner || '').trim();
    const normalizedNext = formatRunnerName(nextRunner || '').trim();
    const rawNext = (nextRunner || '').trim();

    if (!rawNext) return 'ー';
    if (normalizedCurrent === 'ゴール') return 'ー';
    if (rawNext === '----') return 'ー';
    if (normalizedNext === 'ゴール') return 'ー';

    return formatRunnerName(nextRunner);
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
let shouldAutoFollowMap = true; // ユーザーが地図を触るまでは追跡を維持する
let startLatLng = null; // スタート地点の緯度経度

/**
 * Initializes the interactive map, draws the course, and places relay point markers.
 */
async function initializeMap() {
    // 1. Initialize the map if it hasn't been already
    if (map) return;
    const mapContainer = document.getElementById('map');
    if (!mapContainer) {
        console.error("Map container #map not found. Aborting map initialization.");
        return;
    }
    map = L.map(mapContainer);
    mapContainer.addEventListener('pointerdown', () => {
        shouldAutoFollowMap = false;
    });
    mapContainer.addEventListener('wheel', () => {
        shouldAutoFollowMap = false;
    }, { passive: true });
    // Leafletのアイコンパスが自動検出できない問題への対処 (マップ初期化後に実行)
    try {
        delete L.Icon.Default.prototype._getIconUrl;
        L.Icon.Default.mergeOptions({
            iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
            iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
            shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
        });
    } catch (e) { console.error("Leaflet icon path fix failed:", e); }

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
            goalLatLng = latlngs[latlngs.length - 1] || null;
            startLatLng = latlngs[0] || null;
        }

        // 6. Draw relay point markers with leg record info
        if (legBestRecords && legBestRecords.leg_records) {
            legBestRecordByLeg = new Map();
            legBestRecords.leg_records.forEach(record => {
                if (record.top10 && record.top10.length > 0) {
                    legBestRecordByLeg.set(record.leg, record.top10[0]);
                }
            });
        }

        if (relayPoints && relayPoints.length > 0) {
            const legRecordsMap = legBestRecordByLeg;

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
        mapContainer.innerHTML = `<p class="result error">マップの読み込みに失敗しました: ${error.message}</p>`;
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
 * ゴールチーム用マーカーを生成する。
 * @param {string} color - チームカラー
 * @returns {L.DivIcon}
 */
function createGoalIcon(color) {
    const iconHtml = `
        <div class="runner-marker goal-marker" style="border-color: ${color}; color: ${color};">
            <span class="rank-number">🏁</span>
        </div>
    `;
    return L.divIcon({
        html: iconHtml,
        className: 'runner-icon',
        iconSize: [32, 44],
        iconAnchor: [16, 44],
        popupAnchor: [0, -46]
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

    selectEl.value = trackedTeamName;

    // Add event listener
    selectEl.addEventListener('change', (event) => {
        trackedTeamName = event.target.value;
        shouldAutoFollowMap = true;
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

    // 古いマーカーをクリア
    runnerMarkersLayer.clearLayers();

    if ((!runnerLocations || runnerLocations.length === 0) && startLatLng) {
        const fallbackTeams = lastRealtimeData && Array.isArray(lastRealtimeData.teams) && lastRealtimeData.teams.length > 0
            ? lastRealtimeData.teams
            : (ekidenData && Array.isArray(ekidenData.teams) ? ekidenData.teams : []);

        runnerLocations = fallbackTeams.map((team, index) => {
            const legRecord = team.is_shadow_confederation ? legBestRecordByLeg.get(team.currentLeg) : null;
            return {
                rank: team.overallRank ?? index + 1,
                team_name: team.name,
                team_short_name: team.short_name || team.name,
                runner_name: team.runner || (team.runners && team.runners[0] ? team.runners[0].name : "第1走者"),
                total_distance_km: team.totalDistance ?? 0.0,
                latitude: startLatLng[0],
                longitude: startLatLng[1],
                is_shadow_confederation: team.is_shadow_confederation === true,
                current_leg: team.currentLeg ?? 1,
                edition: legRecord?.edition ?? null,
                leg_record: legRecord?.record ?? (team.todayDistance ?? null)
            };
        });
    }

    const leadLeg = lastRealtimeData && Array.isArray(lastRealtimeData.teams)
        ? Math.min(...lastRealtimeData.teams
            .filter(team => team && team.is_shadow_confederation !== true && Number.isFinite(team.currentLeg))
            .map(team => team.currentLeg))
        : null;

    if (!runnerLocations || runnerLocations.length === 0) {
        return; // 表示するランナーがいない場合は何もしない
    }

    // ゴール距離を特定
    const finalGoalDistance = ekidenData.leg_boundaries[ekidenData.leg_boundaries.length - 1];
    const goalTolerance = 0.01; // 浮動小数点誤差を吸収する許容値

    const displayedLatLngs = [];
    const teamDisplayLatLngMap = new Map();

    runnerLocations.forEach(runner => {
        const color = teamColorMap.get(runner.team_name) || '#808080'; // Default to grey
        // 区間記録連合は currentLeg の更新より先に次区間へ進むことがあるため、
        // マーカーの総距離から現在区間を判定する。境界と記録の両方が揃わない場合は表示しない。
        const shadowLegFromDistance = runner.is_shadow_confederation
            && Number.isFinite(runner.total_distance_km)
            && Array.isArray(ekidenData.leg_boundaries)
            ? ekidenData.leg_boundaries.findIndex(boundary => runner.total_distance_km < boundary) + 1
            : null;
        const shadowLegForPopup = shadowLegFromDistance > 0
            ? shadowLegFromDistance
            : null;
        const shadowLegRecord = runner.is_shadow_confederation
            ? legBestRecordByLeg.get(shadowLegForPopup)
            : null;

        // マーカーに表示する文字を決定
        // is_shadow_confederation フラグが true の場合（区間記録連合）は「最高」と表示
        let teamInitial;
        if (runner.is_shadow_confederation) {
            teamInitial = '最高';
        } else {
            teamInitial = runner.team_short_name || '??';
        }

        // 注目チームかどうかを team_name から ekidenDataCache で teamId を解決して判定
        const teamConfig = ekidenDataCache && Array.isArray(ekidenDataCache.teams)
            ? ekidenDataCache.teams.find(t => t.name === runner.team_name)
            : null;
        const teamIdForFav = teamConfig ? teamConfig.id : null;
        const isTeamFavorite = teamIdForFav != null && isFavoriteTeam(teamIdForFav);

        const isGoalReached = !runner.is_shadow_confederation && runner.total_distance_km >= (finalGoalDistance - goalTolerance);
        const markerLatLng = (isGoalReached && goalLatLng)
            ? goalLatLng
            : [runner.latitude, runner.longitude];

        displayedLatLngs.push(markerLatLng);
        if (!runner.is_shadow_confederation) {
            teamDisplayLatLngMap.set(runner.team_name, markerLatLng);
        }

        let icon;
        if (isGoalReached) {
            icon = createGoalIcon(color);
        } else if (isTeamFavorite && !runner.is_shadow_confederation) {
            icon = createFavoriteMarkerIcon(teamInitial, color);
        } else {
            icon = createRunnerIcon(teamInitial, color);
        }

        const markerOptions = { icon };
        if (isTeamFavorite && !runner.is_shadow_confederation) {
            markerOptions.zIndexOffset = 500; // 注目チームは前面に
        }
        const marker = L.marker(markerLatLng, markerOptions);

        let popupContent;
        if (runner.is_shadow_confederation) {
            // 区間記録連合用のポップアップ内容
            const editionText = shadowLegRecord?.edition ? `：第${shadowLegRecord.edition}回` : '';
            if (Number.isFinite(shadowLegForPopup) && shadowLegRecord) {
                popupContent = `
                    <b>区間最高記録${editionText}</b><br>
                    区間: 第${shadowLegForPopup}区<br>
                    走者: ${formatRunnerName(shadowLegRecord.runner_name)}<br>
                    ${shadowLegRecord.record != null ? `記録: ${Number(shadowLegRecord.record).toFixed(3)} km/日<br>` : ''}
                    総合距離: ${runner.total_distance_km.toFixed(1)} km
                `;
            }
        } else {
            // 通常チーム用のポップアップ内容
            popupContent = `
                <b>${runner.rank}位: ${runner.team_short_name} (${runner.team_name})</b><br>
                走者: ${formatRunnerName(runner.runner_name)}<br>
                総合距離: ${runner.total_distance_km.toFixed(1)} km
            `;
            if (isGoalReached) {
                popupContent += `<br><strong>ゴール済</strong>`;
            }
        }
        if (popupContent) {
            marker.bindPopup(popupContent, { closeButton: false });
        }

        // Add click event to scroll to the ranking table and highlight the row
        marker.on('click', () => {
            const teamRow = document.getElementById(`team-rank-row-${runner.rank}`);
            if (teamRow) {
                teamRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                highlightRow(teamRow);
            }
        });

        // マーカーをレイヤーに追加
        runnerMarkersLayer.addLayer(marker);

        runner.display_lat_lng = markerLatLng;
    });

    if (!shouldAutoFollowMap) {
        return;
    }

    // --- Map View Update Logic ---
    if (trackedTeamName === "full_course") {
        // --- Show the entire course ---
        if (coursePolyline) {
            map.fitBounds(coursePolyline.getBounds().pad(0.1));
        }
    } else if (trackedTeamName === "all_teams") {
        // --- Show all teams ---
        const allRunnerLatLngs = displayedLatLngs;
        const bounds = L.latLngBounds(allRunnerLatLngs);
        map.fitBounds(bounds.pad(0.1)); // .pad(0.1) for some margin
    } else if (trackedTeamName === "shadow_confederation") {
        // --- 「区間記録連合」と「先頭走者」を追跡 ---
        // 現在見ている区間番号と区間最高の現在区間がずれている場合は、誤った区間表示を避けるため
        // 区間最高の追跡を行わず、先頭走者側の表示に寄せる。
        const realtimeShadowTeam = lastRealtimeData && Array.isArray(lastRealtimeData.teams)
            ? lastRealtimeData.teams.find(team => team.is_shadow_confederation)
            : null;
        const shadowRunner = runnerLocations.find(r => r.is_shadow_confederation);

        // 正規の走行中トップ選手を探す (ゴール済みと区間記録連合は除く)
        const activeTopRunner = runnerLocations.find(runner => {
            return runner.total_distance_km < finalGoalDistance && !runner.is_shadow_confederation;
        });

        const trackingGroup = [];
        const shadowLeg = realtimeShadowTeam && Number.isFinite(realtimeShadowTeam.currentLeg)
            ? realtimeShadowTeam.currentLeg
            : null;
        const canShowShadow = shadowRunner && shadowLeg != null && leadLeg != null && shadowLeg === leadLeg;

        if (canShowShadow) trackingGroup.push(shadowRunner);
        if (activeTopRunner) trackingGroup.push(activeTopRunner);

        if (trackingGroup.length > 0) {
            const groupLatLngs = trackingGroup.map(r => [r.latitude, r.longitude]);
            const bounds = L.latLngBounds(groupLatLngs);
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
        }
    } else if (trackedTeamName && trackedTeamName !== "lead_group") {
        // --- Track a specific team ---
        const trackedLatLng = teamDisplayLatLngMap.get(trackedTeamName);
        if (trackedLatLng) {
            map.setView(trackedLatLng, 14);
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
            <th class="fav-col" title="注目チーム登録">★</th>
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
            <th>区間平均距離</th>
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
    let lastDistance = null;
    let lastRank = 0;
    const useProvidedRank = records.some(record => record.rank != null);
    records.forEach((record, index) => {
        let rankToDisplay;
        if (useProvidedRank && record.rank != null) {
            rankToDisplay = record.rank;
        } else {
            const roundedDistance = record.averageDistance.toFixed(3);
            if (roundedDistance !== lastDistance) {
                lastRank = index + 1;
                lastDistance = roundedDistance;
            }
            rankToDisplay = lastRank;
        }
        const medal = getMedalEmoji(rankToDisplay);
        const formattedRunnerName = formatRunnerName(record.runnerName);
        const teamNameHtml = `<span class="full-name">${record.teamDetails.name}</span><span class="short-name">${record.teamDetails.short_name}</span>`;
        const row = document.createElement('tr');
        row.innerHTML = `<td>${rankToDisplay}</td>
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

    const currentRaceDay = realtimeData.raceDay;
    const legKey = String(legNumber);
    const defaultTeamDetails = { name: 'N/A', short_name: 'N/A' };

    const runnersToShow = [];

    for (const runnerName in individualData) {
        const runnerData = individualData[runnerName];
        if (runnerData.teamId === 99) continue; // 区間記録連合（シャドーチーム）は除外

        const legSummaries = runnerData.legSummaries || {};
        const summary = legSummaries[legKey];
        if (!summary || summary.days === 0) continue;

        const averageDistance = Number(summary.averageDistance);
        if (!Number.isFinite(averageDistance)) continue;

        const teamDetails = teamsInfoMap.get(runnerData.teamId) || defaultTeamDetails;
        if (teamDetails.is_shadow_confederation) continue; // 区間記録連合は除外
        let status = 'past';
        const realtimeTeam = realtimeData.teams.find(t => t.id === runnerData.teamId);
        if (realtimeTeam) {
            if (realtimeTeam.currentLeg === legNumber) {
                status = 'running';
            } else if (
                realtimeTeam.currentLeg > legNumber &&
                summary.status === 'final' &&
                summary.finalDay === currentRaceDay
            ) {
                status = 'finished_today';
            }
        }

        const displayRank = summary.status === 'final'
            ? (summary.finalRank ?? summary.rank ?? null)
            : (summary.rank ?? null);

        runnersToShow.push({
            runnerName,
            teamDetails,
            averageDistance,
            status,
            rank: displayRank,
            isFinal: summary.status === 'final'
        });
    }

    legRankingBody.innerHTML = '';
    if (runnersToShow.length === 0) {
        legRankingStatus.textContent = `(Result: 0) 本日、${legNumber}区の走行データは未達です。`;
        legRankingStatus.className = 'result loading';
        legRankingStatus.style.display = 'block';
        return;
    }

    legRankingStatus.style.display = 'none';

    runnersToShow.sort((a, b) => {
        if (a.rank != null && b.rank != null && a.rank !== b.rank) {
            return a.rank - b.rank;
        }
        if (a.rank != null && b.rank != null) {
            return b.averageDistance - a.averageDistance;
        }
        if (a.rank != null) return -1;
        if (b.rank != null) return 1;
        return b.averageDistance - a.averageDistance;
    });

    let lastComparable = null;
    let fallbackRank = 0;
    const fragment = document.createDocumentFragment();
    runnersToShow.forEach((record, index) => {
        let rankToDisplay;
        if (record.rank != null) {
            rankToDisplay = record.rank;
        } else {
            const rounded = record.averageDistance.toFixed(3);
            if (rounded !== lastComparable) {
                fallbackRank = index + 1;
                lastComparable = rounded;
            }
            rankToDisplay = fallbackRank;
        }

        const formattedRunnerName = formatRunnerName(record.runnerName);
        const teamNameHtml = `<span class="full-name">${record.teamDetails.name}</span><span class="short-name">${record.teamDetails.short_name}</span>`;

        let rowClass = 'leg-runner-past';
        if (record.status === 'running') {
            rowClass = 'leg-runner-running';
        } else if (record.status === 'finished_today') {
            rowClass = 'leg-runner-finished-today';
        }

        const row = document.createElement('tr');
        row.className = rowClass;
        const rankLabel = record.isFinal && rankToDisplay != null ? `${rankToDisplay}` : `${rankToDisplay ?? '-'}`;
        row.innerHTML = `<td>${rankLabel}</td>
            <td class="runner-name player-profile-trigger" data-runner-name="${record.runnerName}">${formattedRunnerName}</td>
            <td class="team-name">${teamNameHtml}</td>
            <td>${record.averageDistance.toFixed(3)} km</td>`;
        fragment.appendChild(row);
    });
    legRankingBody.appendChild(fragment);
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
    const legRankingBody = document.getElementById('legRankingBody');
    const legRankingStatus = document.getElementById('legRankingStatus');
    const legPrizeWinnerDiv = document.getElementById('legPrizeWinner');
    const tabsContainer = document.getElementById('leg-tabs-container');

    if (!legPrizeWinnerDiv || !tabsContainer) return;

    const hasTeams = realtimeData && Array.isArray(realtimeData.teams) && realtimeData.teams.length > 0;
    const legPrizeNavLink = document.querySelector('a[href="#section-leg-prize"]');

    if (!hasTeams) {
        tabsContainer.innerHTML = '';
        if (legRankingBody) legRankingBody.innerHTML = '';
        if (legRankingStatus) {
            legRankingStatus.style.display = 'none';
        }
        legPrizeWinnerDiv.innerHTML = '';
        legPrizeWinnerDiv.style.display = 'none';
        if (legPrizeNavLink) {
            legPrizeNavLink.parentElement.style.display = 'none';
        }
        return;
    }

    if (legRankingStatus) {
        legRankingStatus.style.display = 'none';
    }

    const teamsInfoMap = new Map(realtimeData.teams.map(t => [t.id, { name: t.name, short_name: t.short_name, is_shadow_confederation: t.is_shadow_confederation }]));

    // ekiden_data.json から最大区間数を取得
    const maxLegs = Array.isArray(ekidenData.leg_boundaries) ? ekidenData.leg_boundaries.length : 0;

    // 1. Identify and sort active legs
    const activeLegs = [...new Set(realtimeData.teams.map(t => t.currentLeg).filter(leg => typeof leg === 'number'))]
        .filter(leg => maxLegs === 0 || leg <= maxLegs) // ゴール済み(11区)など、最大区間数より大きい区間を除外
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
    let minCurrentLeg = Math.min(...realtimeData.teams.map(t => t.currentLeg).filter(leg => typeof leg === 'number'));
    if (!Number.isFinite(minCurrentLeg)) {
        minCurrentLeg = maxLegs || 1;
    }

    // --- 表示テスト用 ---
    // 以下の行を有効にすると、3区が進行中（1区と2区の記録が確定済み）の状態をシミュレートできます。
    // テストが終わったら、この行を削除またはコメントアウトしてください。
    // minCurrentLeg = 3;

    const cachedFinishedLegs = Array.from(legAverageRankingsCache.keys())
        .filter(leg => leg < minCurrentLeg)
        .sort((a, b) => a - b);
    const useCachedLegData = cachedFinishedLegs.length > 0;

    if (useCachedLegData) {
        legPrizeWinnerDiv.style.display = 'block';
        cachedFinishedLegs.forEach(finishedLeg => {
            const legRankingMap = legAverageRankingsCache.get(finishedLeg);
            if (!legRankingMap || legRankingMap.size === 0) return;

            const rankingsForLeg = Array.from(legRankingMap.values()).sort((a, b) => {
                if (a.rank != null && b.rank != null && a.rank !== b.rank) {
                    return a.rank - b.rank;
                }
                if (a.rank != null && b.rank != null) {
                    return b.averageDistance - a.averageDistance;
                }
                return b.averageDistance - a.averageDistance;
            });

            const legContainer = document.createElement('div');
            legContainer.className = 'leg-prize-item';

            const title = document.createElement('h4');
            title.textContent = `${finishedLeg}区`;
            legContainer.appendChild(title);

            const prizeTable = createPrizeTable(rankingsForLeg);
            prizeTable.classList.add('leg-prize-table');
            prizeTable.id = `legPrizeTable-${finishedLeg}`;
            legContainer.appendChild(prizeTable);

            if (rankingsForLeg.length > 3) {
                prizeTable.classList.add('collapsed');
                const toggleContainer = document.createElement('div');
                toggleContainer.className = 'toggle-prize-view';
                const toggleButton = document.createElement('button');
                toggleButton.textContent = '全員の記録を見る ▼';
                toggleButton.onclick = () => {
                    prizeTable.classList.remove('collapsed');
                    toggleContainer.innerHTML = '';
                };
                toggleContainer.appendChild(toggleButton);
                legContainer.appendChild(toggleContainer);
            }

            legPrizeWinnerDiv.appendChild(legContainer);
        });
    } else {
        const finishedLegs = [];
        for (let leg = 1; leg < minCurrentLeg; leg++) {
            finishedLegs.push(leg);
        }

        if (finishedLegs.length > 0) {
            legPrizeWinnerDiv.style.display = 'block';
        }

        finishedLegs.sort((a, b) => a - b).forEach(finishedLeg => {
            const legPerformances = [];

            for (const runnerName in individualData) {
                const runnerData = individualData[runnerName];
                if (runnerData.teamId === 99) continue; // 区間記録連合（シャドーチーム）は除外

                const teamDetails = teamsInfoMap.get(runnerData.teamId) || { name: 'N/A', short_name: 'N/A' };
                if (teamDetails.is_shadow_confederation) continue; // 区間記録連合は除外

                const recordsForLeg = runnerData.records.filter(r => r.leg === finishedLeg);

                if (recordsForLeg.length > 0) {
                    const totalDistance = recordsForLeg.reduce((sum, r) => sum + r.distance, 0);
                    const averageDistance = totalDistance / recordsForLeg.length;

                    legPerformances.push({
                        runnerName,
                        teamId: runnerData.teamId,
                        teamDetails: teamDetails,
                        averageDistance: averageDistance
                    });
                }
            }

            if (legPerformances.length > 0) {
                legPerformances.sort((a, b) => b.averageDistance - a.averageDistance);

                const rankingsForLeg = [];
                const legRankingMap = new Map();
                let lastAvgDistance = null;
                let lastRank = 0;
                legPerformances.forEach((record, index) => {
                    const roundedDistance = record.averageDistance.toFixed(3);
                    if (roundedDistance !== lastAvgDistance) {
                        lastRank = index + 1;
                        lastAvgDistance = roundedDistance;
                    }
                    const rankingEntry = {
                        runnerName: record.runnerName,
                        teamId: record.teamId,
                        teamDetails: record.teamDetails,
                        averageDistance: record.averageDistance,
                        rank: lastRank
                    };
                    rankingsForLeg.push(rankingEntry);
                    legRankingMap.set(record.runnerName, rankingEntry);
                });
                legAverageRankingsCache.set(finishedLeg, legRankingMap);

                const legContainer = document.createElement('div');
                legContainer.className = 'leg-prize-item';

                const title = document.createElement('h4');
                title.textContent = `${finishedLeg}区`;
                legContainer.appendChild(title);

                const prizeTable = createPrizeTable(rankingsForLeg);
                prizeTable.classList.add('leg-prize-table');
                prizeTable.id = `legPrizeTable-${finishedLeg}`;
                legContainer.appendChild(prizeTable);

                if (legPerformances.length > 3) {
                    prizeTable.classList.add('collapsed');

                    const toggleContainer = document.createElement('div');
                    toggleContainer.className = 'toggle-prize-view';

                    const toggleButton = document.createElement('button');
                    toggleButton.textContent = '全員の記録を見る ▼';
                    toggleButton.onclick = () => {
                        prizeTable.classList.remove('collapsed');
                        toggleContainer.innerHTML = '';
                    };
                    toggleContainer.appendChild(toggleButton);
                    legContainer.appendChild(toggleContainer);
                }

                legPrizeWinnerDiv.appendChild(legContainer);
            }
        });
    }

    // Toggle visibility of the navigation link based on whether any prize sections are displayed
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

        const hasFavorites = favoriteTeamIds.size > 0;
        const datasets = historyData.teams
            .filter(team => team.id !== 99 && team.name !== '区間記録連合')
            .map(team => {
            const color = teamColorMap.get(team.id) || '#cccccc';
            const isFav = isFavoriteTeam(team.id);
            // 注目チームがあれば、非注目を薄く表示
            const effectiveColor = hasFavorites && !isFav ? color + '33' : color;
            return {
                label: team.name,
                data: team.ranks,
                borderColor: effectiveColor,
                backgroundColor: color + '33',
                fill: false,
                tension: 0.1,
                borderWidth: isFav ? 4 : (hasFavorites ? 1 : 2),
                pointRadius: isFav ? 5 : (hasFavorites ? 2 : 3),
                pointHoverRadius: isFav ? 8 : 6,
                order: isFav ? 0 : 1 // 注目チームを前面に描画
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
                            callback: function (value) {
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
                            title: function (tooltipItems) {
                                const day = tooltipItems[0].dataIndex + 1;
                                return `${day}日目 (${historyData.dates[tooltipItems[0].dataIndex]})`;
                            },
                            label: function (context) {
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
                    },
                    datalabels: {
                        // ポイントに順位の数字が表示されないように無効化
                        display: false
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

    statusEl.textContent = '(Loading) 通過順位データ解析中...';
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

        // leg_rank_history.json (推移表のデータ) がない場合は非表示にして終了
        if (legHistoryRes.status === 404) {
            statusEl.style.display = 'none';
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
        const sortedTeams = [...historyData.teams].filter(team => team.name !== '区間記録連合') // チーム名で「区間記録連合」を直接除外
            .sort((a, b) => (rankMap.get(a.id) || 999) - (rankMap.get(b.id) || 999));

        // 学内ランキングデータが存在するチームIDのセットを作成
        const intramuralTeamIds = new Set(intramuralData?.teams?.map(t => t.id) || []);

        // テーブルボディを生成
        bodyEl.innerHTML = sortedTeams.map(team => {
            const teamDetails = teamInfoMap.get(team.id) || { name: team.name, short_name: team.name }; // フォールバック
            const teamNameHtml = `<span class="full-name">${teamDetails.name}</span><span class="short-name">${teamDetails.short_name}</span>`;

            const teamColor = teamColorMap.get(team.id) || teamColorMap.get(team.name) || '#cccccc';
            const teamNameTdStyle = `border-left: 4px solid ${teamColor}; padding-left: 0.7rem;`;

            const cellsHtml = team.leg_ranks.map(rank => {
                const isFirst = rank === 1;
                const cellClass = isFirst ? 'class="rank-first"' : '';
                const displayRank = rank !== null ? rank : '-';
                return `<td ${cellClass}>${displayRank}</td>`;
            }).join('');
            return `<tr><td class="team-name" style="${teamNameTdStyle}">${teamNameHtml}</td>${cellsHtml}</tr>`;
        }).join('');

        statusEl.style.display = 'none';
        tableEl.style.display = '';
        sectionEl.style.display = 'block';

    } catch (error) {
        console.error('区間通過順位テーブルの描画に失敗:', error);
        statusEl.textContent = `(Error) 通過順位データ解析失敗: ${error.message}`;
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
    const nextRunnerDisplay = formatNextRunnerDisplay(team.runner, team.nextRunner);

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

    const hasTeams = realtimeData && Array.isArray(realtimeData.teams) && realtimeData.teams.length > 0;
    const hasLegBoundaries = ekidenData && Array.isArray(ekidenData.leg_boundaries) && ekidenData.leg_boundaries.length > 0;

    if (!hasTeams || !hasLegBoundaries) {
        rankingBody.innerHTML = '';
        rankingStatus.style.display = 'none';
        return;
    }

    rankingStatus.style.display = 'none';

    rankingBody.innerHTML = ''; // テーブルをクリア
    const fragment = document.createDocumentFragment();

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
        row.dataset.teamId = team.id; // 注目チーム機能で使用
        if (isFavoriteTeam(team.id)) row.classList.add('is-favorite');

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

        const rankCell = createCell(team.overallRank, 'rank');
        const teamColor = teamColorMap.get(team.name) || '#cccccc';
        rankCell.style.borderLeft = `5px solid ${teamColor}`;
        row.appendChild(rankCell);

        // 大学名セルは、フルネームと短縮名を切り替えるために特別なHTML構造を持つ
        const teamNameCell = document.createElement('td');
        teamNameCell.className = 'team-name';
        teamNameCell.innerHTML = `${finishIcon}<span class="full-name">${team.name}</span><span class="short-name">${team.short_name}</span>`;
        teamNameCell.title = 'クリックで注目チームに登録/解除';
        teamNameCell.addEventListener('click', () => {
            const result = toggleFavoriteTeam(team.id);
            if (result === 'full') {
                return;
            }
            applyFavoriteHighlights();
        });
        row.appendChild(teamNameCell);

        // ログファイルの存在に応じて、クリック可能にするかを決定
        const runnerText = formatRunnerName(team.runner);
        if (team.runner === 'ゴール') {
            const runnerCell = createCell(runnerText, 'runner');
            row.appendChild(runnerCell);
        } else {
            const runnerCellClass = 'runner runner-name player-profile-trigger';
            const runnerCell = createCell(runnerText, runnerCellClass);
            const runnerKey = team.runner.replace(/^\d+/, '');
            runnerCell.dataset.runnerName = runnerKey;
            row.appendChild(runnerCell);
        }

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

        // 次走者セル。選手名鑑を呼び出せるようにする
        const nextRunnerName = team.nextRunner;
        const nextRunnerCell = createCell('', 'next-runner hide-on-mobile');
        const nextRunnerDisplay = formatNextRunnerDisplay(team.runner, nextRunnerName);
        if (nextRunnerDisplay === 'ー') {
            nextRunnerCell.textContent = 'ー';
        } else {
            const nextRunnerKey = nextRunnerName ? nextRunnerName.replace(/^\d+/, '') : '';
            nextRunnerCell.textContent = nextRunnerDisplay;
            if (nextRunnerKey && playerProfiles[nextRunnerKey]) {
                nextRunnerCell.classList.add('player-profile-trigger');
                nextRunnerCell.classList.add('runner-name');
                nextRunnerCell.dataset.runnerName = nextRunnerKey;
            }
        }
        row.appendChild(nextRunnerCell);

        // 注目ボタンセル（大学名セルに統合せず独立列として追加）
        const favCell = document.createElement('td');
        favCell.className = 'fav-col';
        favCell.appendChild(createFavoriteButton(team.id));
        row.appendChild(favCell);

        fragment.appendChild(row);
    });
    rankingBody.appendChild(fragment);
    applyFavoriteHighlights();
};

/**
 * 定期的に速報マップと総合順位のみを更新します。
 */
async function refreshRealtimeData() {
    try {
        // Fetch only the data needed for map and overall ranking
        const [realtimeRes, runnerLocationsRes] = await Promise.all([
            fetch(`data/realtime_report.json?_=${new Date().getTime()}`),
            fetch(`data/runner_locations.json?_=${new Date().getTime()}`)
        ]);

        if (!realtimeRes.ok || !runnerLocationsRes.ok) {
            console.error('Failed to fetch realtime data for refresh.');
            return;
        }

        const realtimeData = await realtimeRes.json();
        const runnerLocations = await runnerLocationsRes.json();

        // Use cached ekidenData
        if (!ekidenDataCache) {
            console.error('Ekiden data cache is not available for refresh.');
            return;
        }

        lastRealtimeData = realtimeData; // Update global cache

        // Sort runner locations
        runnerLocations.sort((a, b) => a.rank - b.rank);

        // Update title and update time
        const titleEl = document.getElementById('ekidenRankingTitle');
        const updateTimeEl = document.getElementById('ekidenRankingUpdateTime');
        if (titleEl) titleEl.textContent = `🏆 ${realtimeData.raceDay}日目 総合順位`;
        if (updateTimeEl) updateTimeEl.textContent = `(更新: ${realtimeData.updateTime})`;

        // Update breaking news
        const newsContainer = document.getElementById('breaking-news-container');
        if (newsContainer && realtimeData.breakingNewsComment && realtimeData.breakingNewsTimestamp) {
            const comment = realtimeData.breakingNewsComment;
            const date = new Date(realtimeData.breakingNewsTimestamp);
            const timeStr = date.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
            newsContainer.textContent = `${comment} (${timeStr}時点)`;
            newsContainer.style.display = 'block';

            if (realtimeData.breakingNewsFullText) {
                newsContainer.classList.add('clickable');
                newsContainer.onclick = () => showBreakingNewsModal(realtimeData.breakingNewsFullText);
            } else {
                newsContainer.classList.remove('clickable');
                newsContainer.onclick = null;
            }
        } else if (newsContainer) {
            newsContainer.style.display = 'none';
            newsContainer.classList.remove('clickable');
            newsContainer.onclick = null;
        }

        // Update the two required sections
        updateEkidenRankingTable(realtimeData, ekidenDataCache);
        updateRunnerMarkers(runnerLocations, ekidenDataCache);

        // タイムラインを更新
        loadRankTimeline({ force: true }).catch(err => console.error('Failed to load timeline on refresh', err));

    } catch (error) {
        console.error('Error during realtime data refresh:', error);
    }
}

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
        const [realtimeRes, individualRes, runnerLocationsRes, ekidenDataRes, legRankHistoryRes, logFileRes] = await Promise.all([
            fetch(`data/realtime_report.json?_=${new Date().getTime()}`),
            fetch(`data/individual_results.json?_=${new Date().getTime()}`),
            fetch(`data/runner_locations.json?_=${new Date().getTime()}`),
            fetch(`config/ekiden_data.json?_=${new Date().getTime()}`),
            fetch(`data/leg_rank_history.json?_=${new Date().getTime()}`),
            fetch(`data/realtime_log.jsonl?_=${new Date().getTime()}`) // ログファイルの存在確認
        ]);

        // ログファイルの存在をチェックしてフラグを更新
        logFileExists = logFileRes.ok;

        let realtimeData = realtimeRes.ok ? await realtimeRes.json() : {};
        let individualData = individualRes.ok ? await individualRes.json() : {};
        let runnerLocations = runnerLocationsRes.ok ? await runnerLocationsRes.json() : [];
        let ekidenData = ekidenDataRes.ok ? await ekidenDataRes.json() : {};
        legRankHistoryData = legRankHistoryRes.ok ? await legRankHistoryRes.json() : null;

        if (!realtimeRes.ok) {
            console.warn('realtime_report.json が見つかりません。初期状態として扱います。');
        }
        if (!individualRes.ok) {
            console.warn('individual_results.json が見つかりません。初期状態として扱います。');
        }
        if (!runnerLocationsRes.ok) {
            console.warn('runner_locations.json が見つかりません。初期状態として扱います。');
        }
        if (!ekidenDataRes.ok) {
            console.warn('ekiden_data.json が見つかりません。最低限の設定で処理を続行します。');
        }

        // データの既定値を整える
        realtimeData = realtimeData && typeof realtimeData === 'object' ? realtimeData : {};
        realtimeData.teams = Array.isArray(realtimeData.teams) ? realtimeData.teams : [];
        realtimeData.raceDay = realtimeData.raceDay ?? 0;
        realtimeData.updateTime = realtimeData.updateTime ?? '未更新';

        individualData = individualData && typeof individualData === 'object' ? individualData : {};

        runnerLocations = Array.isArray(runnerLocations)
            ? runnerLocations.filter(r => r && (typeof r.rank === 'number' || r.is_shadow_confederation === true))
            : [];

        ekidenData = ekidenData && typeof ekidenData === 'object' ? ekidenData : {};
        ekidenData.teams = Array.isArray(ekidenData.teams) ? ekidenData.teams : [];
        ekidenData.leg_boundaries = Array.isArray(ekidenData.leg_boundaries) ? ekidenData.leg_boundaries : [];

        // グローバルキャッシュに保存
        ekidenDataCache = ekidenData;

        // --- 今大会の区間順位データを準備する ---
        legAverageRankingsCache = new Map();
        const hasLegSummaries = Object.values(individualData).some(
            runner => runner.legSummaries && Object.keys(runner.legSummaries).length > 0
        );

        if (hasLegSummaries) {
            const teamDetailsMap = new Map(
                (ekidenData.teams || []).map(team => [
                    team.id,
                    { name: team.name, short_name: team.short_name || team.name }
                ])
            );

            const legEntryMap = new Map(); // leg -> [{ runnerName, teamId, teamDetails, averageDistance }]

            Object.entries(individualData).forEach(([runnerName, runner]) => {
                if (runner.teamId === 99) return; // 区間記録連合（シャドーチーム）は除外

                const legSummaries = runner.legSummaries || {};
                Object.entries(legSummaries).forEach(([legKey, summary]) => {
                    if (!summary) return;
                    const legNumber = Number(legKey);
                    if (!Number.isFinite(legNumber)) return;
                    if (summary.status !== 'final') return;
                    const average = Number(summary.averageDistance);
                    if (!Number.isFinite(average)) return;

                    const entryList = legEntryMap.get(legNumber) || [];
                    entryList.push({
                        runnerName,
                        teamId: runner.teamId,
                        teamDetails: teamDetailsMap.get(runner.teamId) || { name: 'N/A', short_name: 'N/A' },
                        averageDistance: average
                    });
                    legEntryMap.set(legNumber, entryList);
                });

                if (runner.records) {
                    runner.records.forEach(record => {
                        if (record.legRank === undefined) record.legRank = null;
                        if (!record.legRankStatus) record.legRankStatus = 'provisional';
                        if (!record.legAverageStatus) record.legAverageStatus = 'provisional';
                    });
                }
            });

            legEntryMap.forEach((entries, legNumber) => {
                entries.sort((a, b) => b.averageDistance - a.averageDistance);
                let lastAvg = null;
                let currentRank = 0;
                const legRankingMap = new Map();
                entries.forEach((entry, index) => {
                    const roundedAvg = Number(entry.averageDistance.toFixed(3));
                    if (lastAvg === null || roundedAvg !== lastAvg) {
                        currentRank = index + 1;
                        lastAvg = roundedAvg;
                    }
                    const rankingEntry = { ...entry, rank: currentRank };
                    legRankingMap.set(entry.runnerName, rankingEntry);
                });
                legAverageRankingsCache.set(legNumber, legRankingMap);
            });
        } else {
            // レガシーデータ互換: フロント側で暫定順位を算出
            const dailyLegPerformances = {}; // { day: { leg: [dist1, dist2, ...] } }
            for (const runnerName in individualData) {
                const runner = individualData[runnerName];
                if (runner.records) {
                    runner.records.forEach(record => {
                        const { day, leg, distance } = record;
                        if (day === undefined || leg === undefined || distance === undefined) return;
                        dailyLegPerformances[day] = dailyLegPerformances[day] || {};
                        dailyLegPerformances[day][leg] = dailyLegPerformances[day][leg] || [];
                        dailyLegPerformances[day][leg].push(distance);
                    });
                }
            }

            for (const day in dailyLegPerformances) {
                for (const leg in dailyLegPerformances[day]) {
                    dailyLegPerformances[day][leg].sort((a, b) => b - a);
                }
            }

            for (const runnerName in individualData) {
                const runner = individualData[runnerName];
                if (runner.records) {
                    runner.records.forEach(record => {
                        const { day, leg, distance } = record;
                        if (day !== undefined && leg !== undefined && distance !== undefined) {
                            const sortedDistances = dailyLegPerformances[day][leg];
                            record.legRank = sortedDistances.indexOf(distance) + 1;
                        } else {
                            record.legRank = null;
                        }
                        if (!record.legRankStatus) record.legRankStatus = 'provisional';
                        if (!record.legAverageStatus) record.legAverageStatus = 'provisional';
                    });
                }
            }
        }

        lastRealtimeData = realtimeData; // 最新データをグローバル変数に保存

        // データソースの順序に依存しないように、ここで必ずランク順にソートする。
        // 区間記録連合は最後に描画して、他マーカーに埋もれないようにする。
        runnerLocations.sort((a, b) => {
            if (a.is_shadow_confederation === true && b.is_shadow_confederation !== true) return 1;
            if (a.is_shadow_confederation !== true && b.is_shadow_confederation === true) return -1;
            const rankA = typeof a.rank === 'number' ? a.rank : Number.POSITIVE_INFINITY;
            const rankB = typeof b.rank === 'number' ? b.rank : Number.POSITIVE_INFINITY;
            return rankA - rankB;
        });

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
        const raceDayLabel = realtimeData.teams.length > 0 ? `${realtimeData.raceDay}日目 ` : '';
        const updateTimeLabel = realtimeData.updateTime || '未更新';
        titleEl.textContent = `🏆 ${raceDayLabel}総合順位`;
        updateTimeEl.textContent = `(更新: ${updateTimeLabel})`;

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
        await setupResponsiveSelectors();

        // タイムラインを更新 (非同期かつエラー分離)
        loadRankTimeline().catch(err => console.error('Failed to load timeline in fetchEkidenData', err));

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
 * outline.json を読み込み、大会概要をページに表示します。
 */
async function displayOutline() {
    const container = document.getElementById('outlineContainer');
    const linkContainer = document.getElementById('main-thread-link-container');
    const mapFrame = document.getElementById('courseMapFrame');
    const pageTopHeading = document.getElementById('page-top');
    if (!container) return;

    try {
        const response = await fetch(`config/outline.json?_=${Date.now()}`, { cache: 'no-store' });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data = await response.json();

        const metadata = data.metadata || {};
        const details = data.details || {};
        const site = data.site || {};
        const startDateLabel = details.startDateLabel || details.startDate || metadata.startDate || '未設定';

        if (data.metadata) {
            const editionValue = parseInt(metadata.edition, 10);
            if (!Number.isNaN(editionValue)) {
                CURRENT_EDITION = editionValue;
            }
            if (metadata.startDate) {
                EKIDEN_START_DATE = metadata.startDate;
            }
        }

        if (data.site) {
            if (site.pageTitle) {
                document.title = site.pageTitle;
            }
            if (pageTopHeading && site.headerTitle) {
                pageTopHeading.textContent = site.headerTitle;
            }
        }

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
        html += `<p><strong>スタート日:</strong> ${startDateLabel}</p>`;
        html += `<p><strong>コース:</strong> ${details.course || '未設定'}</p>`;

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
            let titleLabel = 'レースハイライト';

            const articleWithoutTitle = data.article.replace(/^#\s+(.+)\n+/, (_, title) => {
                titleLabel = title.trim();
                return '';
            });
            const normalizedArticle = articleWithoutTitle.replace(/^\*\*■\s*(.+?)\*\*$/gm, '### $1');

            // 選手名の先頭に付与されてしまった数字（例: 1甲佐君 -> 甲佐君）を取り除く安全策
            const safeArticle = normalizedArticle.replace(/(?<!\d)(?<!第)\d+([^\d位区日時間]+?)(君|選手)/g, '$1$2');

            // 記事をセクション（見出し＋本文）ごとに解析し、適切なHTMLタグに変換
            const sections = safeArticle.split(/^(?=#)/m); // 行頭の#で見出しセクションを分割
            const processBold = (text) => text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            const formatParagraph = (text) => `<p>${processBold(text).replace(/\n/g, '<br>')}</p>`;

            const htmlParts = sections.map(section => {
                const trimmedSection = section.trim();
                if (!trimmedSection) return '';

                const lines = trimmedSection.split('\n');
                const firstLine = lines.shift();
                const bodyText = lines.join('\n').trim();

                const headingMatch = firstLine.match(/^(#{1,6})\s*(.*)$/);
                if (headingMatch) {
                    const level = headingMatch[1].length;
                    const headingContent = headingMatch[2].trim();
                    const headingLevel = Math.min(6, Math.max(3, level)); // 記事本文の見出しは h3 以上で表示
                    const headingHtml = `<h${headingLevel}>${processBold(headingContent)}</h${headingLevel}>`;
                    const bodyHtml = bodyText ? formatParagraph(bodyText) : '';
                    const separatorHtml = level > 1 && bodyText ? '<hr class="article-separator">' : '';
                    return `${headingHtml}${bodyHtml}${separatorHtml}`;
                }

                // 見出しで始まらないセクション（記事の冒頭など）
                return formatParagraph(trimmedSection);
            });
            const formattedArticle = htmlParts.join('');

            container.innerHTML = `
                <h3><span class="summary-date-label">${formattedDate}のレースハイライト</span><span class="summary-title-label">${processBold(titleLabel)}</span></h3>
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

// --- 学内ランキング機能 (セクション版) ---

/**
 * 学内ランキングデータをもとに、大学選択のプルダウンメニューを生成します。
 */
async function setupResponsiveSelectors() {
    const intramuralNav = document.getElementById('intramural-team-nav');
    const intramuralSelect = document.getElementById('intramural-team-select');
    const directoryNav = document.getElementById('team-directory-nav');
    const directorySelect = document.getElementById('team-directory-select');
    const directoryContent = document.getElementById('team-directory-content');

    // --- データ取得 ---
    if (!intramuralDataCache) {
        try {
            const response = await fetch(`data/intramural_rankings.json?_=${new Date().getTime()}`);
            if (!response.ok) {
                if (response.status !== 404) {
                    console.error(`学内ランキングデータの取得に失敗: HTTP ${response.status}`);
                }
                const section = document.getElementById('section-intramural-ranking');
                if (section) section.style.display = 'none';
                const navLink = document.querySelector('a[href="#section-intramural-ranking"]');
                if (navLink) navLink.parentElement.style.display = 'none';
            } else {
                intramuralDataCache = await response.json();
            }
        } catch (error) {
            console.error('UI生成のための学内ランキングデータ取得に失敗:', error);
            const section = document.getElementById('section-intramural-ranking');
            if (section) section.style.display = 'none';
        }
    }

    // --- UI生成 ---
    // ekidenDataCache からチームカラー情報を取得してマージするための準備
    const teamInfoMap = ekidenDataCache ? new Map(ekidenDataCache.teams.map(t => [t.id, { color: t.color, short_name: t.short_name }])) : new Map();

    // 学内ランキングデータにチームカラーと短縮名をマージ
    if (intramuralDataCache && intramuralDataCache.teams) {
        intramuralDataCache.teams.forEach(team => {
            const info = teamInfoMap.get(team.id);
            if (info) {
                team.color = team.color || info.color;
                team.short_name = team.short_name || info.short_name;
            }
        });
    }

    const createSelectors = (teams, navEl, selectEl, callback) => {
        if (!navEl || !selectEl) return;
        navEl.innerHTML = '';
        selectEl.innerHTML = '';
        const sortedTeams = [...teams].sort((a, b) => a.id - b.id);

        sortedTeams.forEach(team => {
            const teamColor = team.color || '#6c757d';
            // PC用ボタン
            const button = document.createElement('button');
            button.className = 'team-logo-btn';
            button.textContent = team.short_name || team.name;
            button.dataset.teamId = team.id;
            button.style.borderColor = teamColor;
            button.style.color = teamColor;
            button.addEventListener('click', () => callback(team.id));
            navEl.appendChild(button);
            // SP用セレクト
            const option = document.createElement('option');
            option.value = team.id;
            option.textContent = team.name;
            selectEl.appendChild(option);
        });
        selectEl.onchange = (e) => callback(parseInt(e.target.value, 10));
    };

    if (intramuralDataCache) {
        createSelectors(intramuralDataCache.teams, intramuralNav, intramuralSelect, displayIntramuralRanking);
        const defaultIntramuralTeamId = 1;
        intramuralSelect.value = defaultIntramuralTeamId;
        updateActiveButton('intramural-team-nav', defaultIntramuralTeamId);
    }

    if (ekidenDataCache) {
        const regularTeams = ekidenDataCache.teams.filter(t => !t.is_shadow_confederation);
        const previouslySelectedTeamId = parseInt(directorySelect?.value, 10);
        createSelectors(regularTeams, directoryNav, directorySelect, displayTeamDetails);
        const selectedTeamId = regularTeams.some(t => t.id === previouslySelectedTeamId)
            ? previouslySelectedTeamId
            : (regularTeams.length > 0 ? regularTeams[0].id : null);
        if (selectedTeamId) {
            directorySelect.value = selectedTeamId;
            updateActiveButton('team-directory-nav', selectedTeamId);
            displayTeamDetails(selectedTeamId);
        } else if (directoryContent) {
            directoryContent.innerHTML = '';
        }
    }
}


/**
 * 学内ランキングをセクション内に表示します。
 * 距離と順位は昨日時点のデータ、ステータスはリアルタイムデータを使用します。
 * @param {number} teamId 表示するチームのID
 */
async function displayIntramuralRanking(teamId) {
    updateActiveButton('intramural-team-nav', teamId);
    const container = document.getElementById('intramural-ranking-container');
    const contentDiv = document.getElementById('intramural-ranking-content');
    const statusEl = document.getElementById('intramural-ranking-status');
    const teamNameEl = document.getElementById('intramural-ranking-team-name');
    const updateTimeEl = document.getElementById('intramural-ranking-update-time');
    const tableBody = document.getElementById('intramural-ranking-body');

    if (!container || !contentDiv || !statusEl || !teamNameEl || !updateTimeEl || !tableBody) return;

    // 表示を準備
    contentDiv.style.display = 'none';
    tableBody.innerHTML = '';
    statusEl.textContent = '(Loading) ランキングデータ解析中...';
    statusEl.className = 'result loading';
    statusEl.style.display = 'block';

    try {
        // 1. 昨日時点の学内ランキングデータを取得 (キャッシュから)
        if (!intramuralDataCache) {
            // populateIntramuralSelect でキャッシュされているはずだが、念のため
            const response = await fetch(`data/intramural_rankings.json?_=${new Date().getTime()}`);
            if (!response.ok) throw new Error('学内ランキングデータ(昨日時点)の取得に失敗しました。');
            intramuralDataCache = await response.json();
        }

        // 2. リアルタイムデータと駅伝設定データを取得 (キャッシュから)
        if (!lastRealtimeData || !ekidenDataCache) {
            await fetchEkidenData(); // なければ取得を試みる
            if (!lastRealtimeData || !ekidenDataCache) {
                throw new Error('リアルタイムデータまたは駅伝設定データが読み込まれていません。');
            }
        }

        // 3. 必要なデータを抽出
        const intramuralTeamData = intramuralDataCache.teams.find(t => t.id === teamId);
        const realtimeTeamData = lastRealtimeData.teams.find(t => t.id === teamId);
        const ekidenConfigTeamData = ekidenDataCache.teams.find(t => t.id === teamId);

        if (!intramuralTeamData || !realtimeTeamData || !ekidenConfigTeamData) {
            throw new Error('チーム情報が見つかりませんでした。');
        }

        // 4. ヘッダー情報を設定
        teamNameEl.textContent = `${intramuralTeamData.name} 学内ランキング`;
        updateTimeEl.textContent = `総距離は ${intramuralDataCache.updateTime} 時点のものです`;

        // 5. リアルタイムの選手ステータスを決定するための情報を準備
        const currentLeg = realtimeTeamData.currentLeg;
        const activeRunners = ekidenConfigTeamData.runners.map(r => r.name);
        const substitutedOutRunners = realtimeTeamData.substituted_out || [];

        // 6. テーブルを生成
        const fragment = document.createDocumentFragment();
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
            fragment.appendChild(row);
        });
        tableBody.appendChild(fragment);

        statusEl.style.display = 'none';
        contentDiv.style.display = 'block';

    } catch (error) {
        console.error('学内ランキングの表示に失敗:', error);
        statusEl.textContent = `エラー: ${error.message}`;
        statusEl.className = 'result error';
        contentDiv.style.display = 'none';
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
            // 今大会の記録がない場合は、グラフ描画処理を中断しコンテナごと非表示にする
            if (summaryCanvas.parentElement) summaryCanvas.parentElement.style.display = 'none';
            if (dailyCanvas.parentElement) dailyCanvas.parentElement.style.display = 'none';
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
                if (dailyCanvas.parentElement) dailyCanvas.parentElement.style.display = 'none';
                return;
            }
            if (dailyCanvas.parentElement) dailyCanvas.parentElement.style.display = 'block';

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

        const currentPerformanceData = allIndividualData[rawRunnerName];
        const teamColor = teamColorMap.get(profile.team_name) || '#6c757d';

        const createSectionTitle = (title) => `<h4 style="border-bottom-color: ${teamColor}; color: ${teamColor};">${title}</h4>`;

        // コメントが存在する場合のみ blockquote を生成
        const commentHtml = profile.comment
            ? `<blockquote class="profile-comment" style="border-left-color: ${teamColor}; margin-top: 0.5rem; padding: 0.5rem 0.8rem;">
                   "${profile.comment}"
               </blockquote>`
            : '';

        // --- 各セクションのHTMLを生成 ---
        let currentPerformanceHtml = createSectionTitle('今大会の成績');
        if (currentPerformanceData && currentPerformanceData.records && currentPerformanceData.records.length > 0) {
            currentPerformanceHtml = `
                <div id="profile-panel-current" class="profile-tab-panel active">
                    <div class="profile-chart-container" style="height: 250px;">
                        <canvas id="profileSummaryChart"></canvas>
                    </div>
                    <div class="profile-chart-container" style="height: 280px;">
                        <canvas id="profileDailyChart"></canvas>
                    </div>
                    <div id="profileChartStatus" class="result loading" style="display: none;"></div>
                </div>`;
        } else {
            currentPerformanceHtml += `<p>今大会の出場記録はありません。</p>`;
        }

        const pastEditions = Object.keys(profile.performance || {}).filter(e => parseInt(e, 10) !== CURRENT_EDITION).sort((a, b) => b - a);
        let pastPerformanceHtml = '';
        if (pastEditions.length > 0) {
            pastPerformanceHtml = `
                ${createSectionTitle('過去大会の成績')}
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
                </div>`;
        }

        let personalBestHtml = '';
        if (profile.personal_best && profile.personal_best.length > 0) {
            personalBestHtml = `
                ${createSectionTitle('区間賞・自己ベスト')}
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
                </div>`;
        }

        const textColor = getContrastingTextColor(teamColor);

        // クローズボタンの色も背景に合わせて変更
        const closeBtn = document.getElementById('closePlayerProfileModal');
        if (closeBtn) {
            closeBtn.style.color = textColor;
            closeBtn.style.textShadow = textColor === '#ffffff' ? '0 1px 3px rgba(0,0,0,0.3)' : 'none';
        }

        // --- モーダル全体のHTMLを組み立て ---
        contentDiv.innerHTML = `
            <div class="profile-header" style="--team-color: ${teamColor}; --text-color: ${textColor}; background-color: var(--team-color); color: var(--text-color);">
                <h3 class="profile-name">${profile.name}</h3>
                <p class="profile-team" style="opacity: 0.9;">${profile.team_name}</p>
            </div>
            <div class="profile-main-info-wrapper">
                <div class="profile-image-container">
                    <img src="${profile.image_url}" alt="${profile.name}" class="profile-image">
                </div>
                <div class="profile-meta-info">
                    <p><b>出身:</b> ${profile.prefecture || '未設定'}</p>
                    <p><b>地点:</b> ${profile.address} (標高: ${profile.elevation}m)</p>
                    <p><b>開始:</b> ${profile.start_date}</p>
                    ${commentHtml}
                </div>
            </div>
            ${currentPerformanceHtml}
            ${pastPerformanceHtml}
            ${personalBestHtml}
        `;

        // グラフデータがあれば描画
        if (currentPerformanceData && currentPerformanceData.records && currentPerformanceData.records.length > 0) {
            const raceDay = lastRealtimeData ? lastRealtimeData.raceDay : 1;
            await renderProfileCharts(rawRunnerName, raceDay);
        }

    } catch (error) {
        contentDiv.innerHTML = `<p class="result error">データの表示に失敗しました: ${error.message}</p>`;
        console.error('選手プロファイルモーダルの表示エラー:', error);
    }
}

/**
 * 出場校一覧セクションを初期化する
 */
async function initializeTeamDirectory() {
    // この関数は setupResponsiveSelectors に統合されたため、内容は不要になります。
    // 呼び出し元で setupResponsiveSelectors が呼ばれることを確認してください。
}

/**
 * 大学選択ボタンのアクティブ状態のスタイルを更新する
 * @param {number} activeTeamId - アクティブにするチームのID
 */
function updateActiveButton(containerId, activeTeamId) {
    const buttons = document.querySelectorAll(`#${containerId} .team-logo-btn`);

    const dataSource = containerId === 'intramural-team-nav' ? intramuralDataCache?.teams : ekidenDataCache?.teams;
    if (!dataSource) return;

    buttons.forEach(btn => {
        const buttonTeamId = parseInt(btn.dataset.teamId, 10);
        const team = dataSource.find(t => t.id === buttonTeamId);
        if (!team) return;

        const teamColor = team.color || '#6c757d';

        if (buttonTeamId === activeTeamId) {
            btn.classList.add('active');
            btn.style.backgroundColor = teamColor;
            btn.style.color = getContrastingTextColor(teamColor);
        } else {
            btn.classList.remove('active');
            btn.style.backgroundColor = 'transparent';
            btn.style.color = teamColor;
        }
    });
}

/**
 * 背景色に応じて、コントラストが十分な文字色（白または黒）を返します。
 * @param {string} hexColor - 背景色の16進数カラーコード (e.g., "#RRGGBB")
 * @returns {string} - "#ffffff" (白) または "#000000" (黒)
 */
function getContrastingTextColor(hexColor) {
    if (!hexColor) return '#000000';
    const r = parseInt(hexColor.substr(1, 2), 16);
    const g = parseInt(hexColor.substr(3, 2), 16);
    const b = parseInt(hexColor.substr(5, 2), 16);
    // YIQ 色空間の輝度を計算
    const yiq = ((r * 299) + (g * 587) + (b * 114)) / 1000;
    // 輝度が128以上なら黒、未満なら白を返す
    return (yiq >= 128) ? '#000000' : '#ffffff';
}

function hexToRgba(hex, alpha = 0.1) {
    const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
/**
 * 指定されたチームの詳細情報を表示する
 * @param {number} teamId - 表示するチームのID
 */
function displayTeamDetails(teamId) {
    updateActiveButton('team-directory-nav', teamId);
    const contentContainer = document.getElementById('team-directory-content');
    if (!contentContainer) return;

    const teamConfig = ekidenDataCache.teams.find(t => t.id === teamId);
    const realtimeTeamData = lastRealtimeData ? lastRealtimeData.teams.find(t => t.id === teamId) : null;

    if (!teamConfig) {
        contentContainer.innerHTML = '<p class="result error">チーム情報が見つかりません。</p>';
        return;
    }

    const currentLeg = realtimeTeamData ? realtimeTeamData.currentLeg : 1;

    // 区間エントリー選手のHTMLを生成
    const kukanEntriesHtml = teamConfig.runners.map((runnerObj, index) => {
        const runnerName = runnerObj.name;
        const isSubstitutedIn = runnerObj.is_substitute_in === true;
        const runnerLeg = index + 1;
        const profile = playerProfiles[runnerName] || {};
        const formattedRunnerName = formatRunnerName(runnerName);
        const runnerImage = profile.image_url || 'https://via.placeholder.com/60';
        // コメントが存在する場合のみpタグを生成
        const runnerCommentHtml = profile.comment
            ? `<p class="runner-comment">"${profile.comment}"</p>`
            : '';

        const runnerMeta = `${profile.grade || ''} / ${profile.prefecture || ''} / ${profile.address || ''}`;

        // --- ステータスと今大会成績の計算 ---
        let statusHtml = '';
        let substitutionLabelHtml = isSubstitutedIn ? `<span class="runner-substitution-label">エントリー変更</span>` : '';
        let currentPerformanceHtml = '';

        if (realtimeTeamData) {
            let statusText = '';
            let statusClass = '';

            if (runnerLeg < currentLeg) {
                statusText = '走行済';
                statusClass = 'status-finished';

                // 走行済の場合、区間順位と平均距離を表示
                const legRankingMap = legAverageRankingsCache.get(runnerLeg);
                const rankingEntry = legRankingMap ? legRankingMap.get(runnerName) : null;

                if (rankingEntry) {
                    currentPerformanceHtml = `<span class="runner-current-perf">区間順位 ${rankingEntry.rank}位｜平均 ${rankingEntry.averageDistance.toFixed(3)}km</span>`;
                } else {
                    const performance = allIndividualData[runnerName];
                    if (performance && performance.records) {
                        const legRecords = performance.records.filter(r => r.leg === runnerLeg);
                        if (legRecords.length > 0) {
                            const totalDistance = legRecords.reduce((sum, r) => sum + r.distance, 0);
                            const avgDistance = totalDistance / legRecords.length;
                            currentPerformanceHtml = `<span class="runner-current-perf">平均 ${avgDistance.toFixed(3)}km</span>`;
                        }
                    }
                }
            } else if (runnerLeg === currentLeg) {
                statusText = '走行中';
                statusClass = 'status-running';
            } else {
                statusText = '走行前';
                statusClass = 'status-upcoming';
            }
            statusHtml = `<span class="runner-status ${statusClass}">${statusText}</span>`;
        }

        return `
            <tr>
                <th>${runnerLeg}区 ${statusHtml}</th>
                <td>
                    <div class="runner-info">
                        <img src="${runnerImage}" alt="${formattedRunnerName}" class="runner-image">
                        <div class="runner-details">
                            <div class="runner-name-details">
                                <a href="#" class="runner-name player-profile-trigger" data-runner-name="${runnerName}" onclick="event.preventDefault()" style="color: #007bff;">${formattedRunnerName}</a>${substitutionLabelHtml}${currentPerformanceHtml}
                                <div class="runner-meta">${runnerMeta}</div>
                            </div>
                            ${runnerCommentHtml}
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    // 補欠選手のHTMLを生成
    const substitutesHtml = (teamConfig.substitutes && teamConfig.substitutes.length > 0)
        ? `
            <div class="team-substitutes-container">
                <h4>補欠</h4>
                <ul class="team-substitutes-list">
                    ${teamConfig.substitutes.map(sub => {
            return `<li><a href="#" class="runner-name player-profile-trigger" data-runner-name="${sub.name}" onclick="event.preventDefault()" style="color: #007bff;">${formatRunnerName(sub.name)}</a></li>`;
        }).join('')}
                </ul>
            </div>
        `
        : '';

    // 全体のHTMLを組み立て
    const teamColor = teamConfig.color || '#6c757d';
    const textColor = getContrastingTextColor(teamColor);
    const descriptionBgColor = hexToRgba(teamColor, 0.1);

    contentContainer.innerHTML = `
        <div class="team-details-container">
            <div class="team-details-description-wrapper">
                <div class="team-details-title" style="background-color: ${teamColor}; color: ${textColor};">
                    ${teamConfig.name} <span>${teamConfig.manager || ''}</span>
                </div>
                <div class="team-details-text" style="background-color: ${descriptionBgColor};">${teamConfig.description || 'チーム紹介はありません。'}</div>
            </div>
            
            <table class="team-kukan-table">
                <tbody>
                    ${kukanEntriesHtml}
                </tbody>
            </table>

            ${substitutesHtml}
        </div>
    `;

    // 注目ボタンをタイトルバー右端に追加（innerHTML に直接埋め込まずDOMで挿入）
    const titleEl = contentContainer.querySelector('.team-details-title');
    if (titleEl) {
        const favBtn = createFavoriteButton(teamId);
        favBtn.classList.add('fav-btn--in-title');
        titleEl.appendChild(favBtn);
    }
}
// --- 初期化処理 ---

document.addEventListener('DOMContentLoaded', async function () {
    // --- iOS PWA Install Banner Logic ---
    // isIOS と isStandalone を早期に定義して ReferenceError を解決
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    const isStandalone = window.navigator.standalone || window.matchMedia('(display-mode: standalone)').matches;

    function setupIosBanner() {
        const iosInstallBanner = document.getElementById('ios-install-banner');
        const closeIosBannerBtn = document.getElementById('close-ios-banner');
        const showIosGuideLink = document.getElementById('show-ios-install-guide');

        if (!iosInstallBanner || !closeIosBannerBtn || !showIosGuideLink) return;

        const isBannerClosed = localStorage.getItem('iosPwaBannerClosed') === 'true';

        // iOSで、スタンドアロンでなく、まだバナーを閉じていない場合に表示
        if (isIOS && !isStandalone && !isBannerClosed) {
            iosInstallBanner.style.display = 'block';
            requestAnimationFrame(() => {
                document.body.style.paddingTop = `${iosInstallBanner.offsetHeight}px`;
            });
        }

        // iOS以外ではフッターのリンクを非表示にする
        if (!isIOS || isStandalone) {
            showIosGuideLink.style.display = 'none';
        }

        // 閉じるボタンのイベントリスナー
        closeIosBannerBtn.addEventListener('click', () => {
            iosInstallBanner.style.display = 'none';
            document.body.style.paddingTop = '0';
            localStorage.setItem('iosPwaBannerClosed', 'true');
        });

        // フッターのリンクから案内を再表示するイベントリスナー
        showIosGuideLink.addEventListener('click', (e) => {
            e.preventDefault();
            if (isIOS && !isStandalone) {
                localStorage.removeItem('iosPwaBannerClosed'); // 閉じた記録を削除
                location.reload(); // ページをリロードしてバナーを再表示させる
            }
        });
    }

    // chartjs-plugin-datalabels が読み込まれていれば、グローバルに登録
    if (window.ChartDataLabels) {
        Chart.register(window.ChartDataLabels);
    }

    // アメダス機能の初期化
    loadStationsData();
    loadPlayerProfiles();
    loadSearchHistory(); // アメダス検索履歴の読み込み
    // loadRanking(); // 全国ランキングは index_16.html には無いためコメントアウト

    document.getElementById('locationInput').addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
            searchTemperature();
        }
    });

    // 駅伝機能の初期化
    createEkidenHeader();
    createLegRankingHeader();

    // --- ページの主要コンテンツを非同期で読み込み ---
    // 1. 最初にマップを初期化
    await initializeMap();
    // 2. 最も重要な速報データを取得して表示
    await fetchEkidenData();

    // 注目チームの状態を localStorage から復元
    loadFavoriteTeams();
    updateFavoriteCounter();
    applyFavoriteHighlights();

    // 3. 順位変動タイムラインの初期化とデータロード
    initRankTimeline();
    loadRankTimeline().catch(err => console.error('Failed to load timeline on startup', err));
    // 3. レスポンシブセレクターをセットアップ
    await setupResponsiveSelectors();
    const defaultIntramuralTeamId = 1;
    await displayIntramuralRanking(defaultIntramuralTeamId);
    // 4. その他のコンテンツを読み込む
    displayDailySummary(); // 記事
    displayManagerComments(); // 監督談話室
    displayLegRankHistoryTable(); // 順位推移テーブル
    displayOutline(); // 大会概要
    // 90秒ごとにマップと総合順位を自動更新 -> ユーザーの地図操作を妨げるため停止
    // setInterval(refreshRealtimeData, 90000);

    // スマホ表示でのPC/SP版表示切り替えボタンのイベントリスナー
    const toggleBtn = document.getElementById('toggle-ranking-view-btn');
    const rankingContainer = document.querySelector('.ekiden-ranking-container');

    if (toggleBtn && rankingContainer) {
        toggleBtn.addEventListener('click', () => {
            rankingContainer.classList.toggle('show-full-view');
            if (rankingContainer.classList.contains('show-full-view')) {
                toggleBtn.textContent = '簡易表示';
            } else {
                toggleBtn.textContent = '詳細表示 (フルビュー)';
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
                // aタグのデフォルトの動作を防ぐ
                if (event.target.tagName === 'A') {
                    event.preventDefault();
                }
                if (runnerName) {
                    showPlayerProfileModal(runnerName);
                }
            }

            const intramuralTarget = event.target.closest('.intramural-ranking-trigger');
            if (intramuralTarget) {
                const teamId = parseInt(intramuralTarget.dataset.teamId, 10);
                // showIntramuralRankingModal(teamId); // この行は次のステップで新しい関数に置き換えます
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

    // --- Hamburger Menu & Mobile Dropdown ---
    const hamburgerBtn = document.getElementById('hamburger-btn');
    const navList = document.getElementById('main-nav-list');

    if (hamburgerBtn && navList) {
        hamburgerBtn.addEventListener('click', () => {
            hamburgerBtn.classList.toggle('active');
            navList.classList.toggle('active');
        });
    }

    // SP版のドロップダウンメニューをタップで開閉
    document.querySelectorAll('.page-nav .dropbtn').forEach(button => {
        button.addEventListener('click', function (e) {
            // PC版ではホバーで開くので、SP版でのみ動作させる
            if (window.innerWidth <= 768) {
                // aタグのデフォルトのページ遷移をキャンセル
                e.preventDefault();
                const dropdown = this.parentElement; // li.dropdown
                dropdown.classList.toggle('open');
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

    setupIosBanner();

    // --- PWA Install Button Logic ---
    let deferredPrompt;
    const installButton = document.getElementById('install-btn');

    window.addEventListener('beforeinstallprompt', (e) => {
        // デフォルトのミニ情報バーの表示をキャンセル
        e.preventDefault();
        // イベントを後で使うために保存
        deferredPrompt = e;
        // インストールボタンを表示
        if (installButton) {
            installButton.style.display = 'inline-block';
        }
    });

    if (installButton) {
        installButton.addEventListener('click', async () => {
            if (deferredPrompt) {
                // インストールプロンプトを表示
                deferredPrompt.prompt();
                // ユーザーの選択結果を待つ
                const { outcome } = await deferredPrompt.userChoice;
                console.log(`User response to the install prompt: ${outcome}`);
                // 一度使うと再利用できないので、変数をクリア
                deferredPrompt = null;
                // ボタンを非表示にする
                installButton.style.display = 'none';
            }
        });
    }

    // --- Push Notification Permission Logic ---
    const notificationButton = document.getElementById('notification-btn');
    if ('Notification' in window && 'serviceWorker' in navigator) {
        // 既に許可されている場合は、すぐに購読処理を試みる
        if (Notification.permission === 'granted') {
            console.log('Notification permission is already granted.');
            // ページロード時に自動で購読処理を走らせることも可能ですが、
            // ユーザーが明示的にアクションした時に実行する方が安全なため、一旦コメントアウトします。
            // subscribeUserToPush();
        } else {
            // それ以外の場合は、許可を求めるボタンを表示
            notificationButton.style.display = 'inline-block';
        }

        notificationButton.addEventListener('click', async () => {
            try {
                const permission = await Notification.requestPermission();
                if (permission === 'granted') {
                    console.log('通知が許可されました！');
                    notificationButton.style.display = 'none'; // ボタンを隠す
                    await subscribeUserToPush(); // 購読処理を実行
                } else {
                    console.log('通知が拒否されました。');
                }
            } catch (error) {
                console.error('Error requesting notification permission:', error);
            }
        });
    } else {
        // ブラウザが通知に対応していない場合はボタンを非表示
        notificationButton.style.display = 'none';
    }

    // --- PWA Service Worker Registration ---
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('./sw.js').then(registration => {
            console.log('ServiceWorker registration successful with scope: ', registration.scope);
        }).catch(err => {
            console.log('ServiceWorker registration failed: ', err);
        });

        // --- バッジ更新のリスナーを追加 ---
        if ('setAppBadge' in navigator) {
            navigator.serviceWorker.addEventListener('message', (event) => {
                console.log('Message from SW:', event.data);
                if (event.data && 'badge_count' in event.data) {
                    navigator.setAppBadge(event.data.badge_count)
                        .catch(err => console.error('Failed to set badge', err));
                }
            });
        }

        // === 起動時にバッジをリセット ===
        if ('serviceWorker' in navigator) {
            try {
                const apiBaseUrl = getApiBaseUrl();
                const response = await fetch(`${apiBaseUrl}/api/reset-badge`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    }
                });

                if (response.ok) {
                    console.log("Badge reset request sent to server.");
                    if ('clearAppBadge' in navigator) {
                        await navigator.clearAppBadge();
                        console.log("Local badge cleared on startup.");
                    }
                } else {
                    console.error("Failed to reset badge on server:", await response.text());
                }
            } catch (err) {
                console.error("Error resetting badge:", err);
            }
        }
        // --- アプリ起動時にバッジをリセット ---
        clearBadge();
    }
});

/**
 * URL-safeなBase64文字列をUint8Arrayに変換します。
 * @param {string} base64String
 * @returns {Uint8Array}
 */
function urlBase64ToUint8Array(base64String) {
    const padding = '='.repeat((4 - base64String.length % 4) % 4);
    const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
}

/**
 * APIサーバーのベースURLを環境に応じて返します。
 * @returns {string} APIのベースURL
 */
function getApiBaseUrl() {
    const isDevelopment = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
    const DEV_API_URL = 'http://localhost:5000';
    const PROD_API_URL = 'https://ekiden-push-server.onrender.com';
    return isDevelopment ? DEV_API_URL : PROD_API_URL;
}

/**
 * APIサーバーから設定情報（VAPID公開鍵など）を取得します。
 * @returns {Promise<object>} 設定情報オブジェクト
 */
async function fetchConfig() {
    const response = await fetch(`${getApiBaseUrl()}/api/config`);
    if (!response.ok) {
        throw new Error('Failed to fetch configuration from server.');
    }
    return response.json();
}

/**
 * ユーザーをプッシュ通知に購読させ、サーバーに情報を送信します。
 */
async function subscribeUserToPush() {

    // Service WorkerとPushManagerのサポートを確認
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
        console.warn('Push messaging is not supported');
        return;
    }

    try {
        // Service Workerがアクティブになるのを待つ
        const registration = await navigator.serviceWorker.ready;

        // サーバーから設定情報を取得
        const config = await fetchConfig();
        console.log("Fetched config:", config);
        const applicationServerKey = urlBase64ToUint8Array(config.vapidPublicKey);

        // 購読情報を取得
        const subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true, // ユーザーに見える通知を送るという約束
            applicationServerKey: applicationServerKey
        });

        console.log('Push Subscription:', JSON.stringify(subscription));
        // 取得した 'subscription' オブジェクトをサーバーに送信して保存します。
        await sendSubscriptionToServer(subscription);

    } catch (error) {
        console.error('Failed to subscribe to push notifications:', error);
    }
}


/**
 * 購読情報をサーバーに送信します。
 * @param {PushSubscription} subscription
 */
async function sendSubscriptionToServer(subscription) {
    const apiBaseUrl = getApiBaseUrl();
    const apiUrl = `${apiBaseUrl}/api/save-subscription`;

    console.log("送信先URL:", apiUrl);
    console.log("送信データ:", JSON.stringify(subscription));

    try {
        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(subscription),
        });

        console.log("サーバーのレスポンス:", response.status, response.statusText);
        const text = await response.text();
        console.log("レスポンス本文:", text);

        if (!response.ok) {
            throw new Error('Failed to send subscription to server.');
        }

        console.log('Successfully sent subscription to server.');
    } catch (error) {
        console.error('Error sending subscription to server:', error);
    }
}

/**
 * バッジをリセットする（0にする）
 */
function clearBadge() {
    if ('clearAppBadge' in navigator) {
        navigator.clearAppBadge()
            .then(() => console.log("Badge cleared on startup"))
            .catch(err => console.error("Failed to clear badge", err));
    } else {
        console.log("clearAppBadge not supported");
    }
}


// ============================================================
// 注目チーム機能
// ============================================================

/**
 * localStorage から注目チームを読み込み、favoriteTeamIds に反映します。
 */
function loadFavoriteTeams() {
    try {
        const raw = localStorage.getItem(FAVORITE_TEAMS_KEY);
        const arr = raw ? JSON.parse(raw) : [];
        favoriteTeamIds = new Set(Array.isArray(arr) ? arr.map(Number).filter(Number.isFinite) : []);
    } catch (e) {
        favoriteTeamIds = new Set();
    }
}

/**
 * favoriteTeamIds を localStorage に保存します。
 */
function saveFavoriteTeams() {
    try {
        localStorage.setItem(FAVORITE_TEAMS_KEY, JSON.stringify([...favoriteTeamIds]));
    } catch (e) {
        console.warn('favoriteTeams save failed:', e);
    }
}

/**
 * 指定 teamId の注目状態をトグルします。
 * @param {number} teamId
 * @returns {'added'|'removed'|'full'} 操作結果
 */
function toggleFavoriteTeam(teamId) {
    const id = Number(teamId);
    if (favoriteTeamIds.has(id)) {
        favoriteTeamIds.delete(id);
        saveFavoriteTeams();
        return 'removed';
    }
    if (favoriteTeamIds.size >= FAVORITE_MAX) {
        return 'full';
    }
    favoriteTeamIds.add(id);
    saveFavoriteTeams();
    return 'added';
}

/**
 * 指定 teamId が注目中かどうかを返します。
 */
function isFavoriteTeam(teamId) {
    return favoriteTeamIds.has(Number(teamId));
}

/**
 * 注目ボタン DOM を生成して返します。
 * @param {number} teamId
 * @returns {HTMLButtonElement}
 */
function createFavoriteButton(teamId) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'fav-btn';
    btn.dataset.teamId = teamId;
    btn.setAttribute('aria-label', isFavoriteTeam(teamId) ? '注目解除' : '注目登録');

    const updateBtnState = () => {
        const isFav = isFavoriteTeam(teamId);
        const isFull = !isFav && favoriteTeamIds.size >= FAVORITE_MAX;
        btn.textContent = isFav ? '★' : '☆';
        btn.classList.toggle('is-favorite', isFav);
        btn.classList.toggle('is-full', isFull);
        btn.title = isFav ? '注目解除' : (isFull ? `すでに${FAVORITE_MAX}校登録中` : '注目登録');
        btn.setAttribute('aria-pressed', isFav ? 'true' : 'false');
    };
    updateBtnState();

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const result = toggleFavoriteTeam(teamId);
        if (result === 'full') {
            // 軽くシェイクして上限を伝える
            btn.classList.add('fav-btn--shake');
            setTimeout(() => btn.classList.remove('fav-btn--shake'), 400);
            return;
        }
        // 全ての注目ボタンの状態を更新
        applyFavoriteHighlights();
    });

    return btn;
}

/**
 * 注目チームのマーカーアイコン（輪郭リング付き）を生成します。
 * @param {string} teamInitial
 * @param {string} color
 * @returns {L.DivIcon}
 */
function createFavoriteMarkerIcon(teamInitial, color) {
    const iconHtml = `
        <div class="runner-marker fav-marker" style="background-color: ${color}; border-color: ${color};">
            <span class="rank-number">${teamInitial}</span>
        </div>
    `;
    return L.divIcon({
        html: iconHtml,
        className: 'runner-icon runner-icon--favorite',
        iconSize: [38, 52],
        iconAnchor: [19, 52],
        popupAnchor: [0, -54]
    });
}

/**
 * 注目チームカウンターバッジ（「注目 N/3」）を更新します。
 */
function updateFavoriteCounter() {
    const el = document.getElementById('favorite-team-counter');
    if (!el) return;
    const count = favoriteTeamIds.size;
    if (count === 0) {
        el.textContent = '注目チームはありません';
        el.className = 'favorite-counter favorite-counter--empty';
    } else {
        el.textContent = `★ 注目チーム ${count}/${FAVORITE_MAX}`;
        el.className = 'favorite-counter';
    }
}

/**
 * 注目状態を全 UI（ボタン・順位表行・タイムライン・カウンター）に反映します。
 * マーカーは updateRunnerMarkers() を呼んで再描画します。
 */
function applyFavoriteHighlights() {
    // 1. 全ての注目ボタンの表示を更新
    document.querySelectorAll('.fav-btn').forEach(btn => {
        const id = Number(btn.dataset.teamId);
        const isFav = isFavoriteTeam(id);
        const isFull = !isFav && favoriteTeamIds.size >= FAVORITE_MAX;
        btn.textContent = isFav ? '★' : '☆';
        btn.classList.toggle('is-favorite', isFav);
        btn.classList.toggle('is-full', isFull);
        btn.title = isFav ? '注目解除' : (isFull ? `すでに${FAVORITE_MAX}校登録中` : '注目登録');
        btn.setAttribute('aria-pressed', isFav ? 'true' : 'false');
        btn.setAttribute('aria-label', isFav ? '注目解除' : '注目登録');
    });

    // 2. 順位表の行ハイライトを更新
    document.querySelectorAll('#ekidenRankingBody tr[data-team-id]').forEach(row => {
        const id = Number(row.dataset.teamId);
        row.classList.toggle('is-favorite', isFavoriteTeam(id));
    });

    // 3. タイムラインを再描画（注目フィルター反映 + ボタン表示更新）
    updateFavoriteFilterButton();
    renderRankTimeline();

    // 4. カウンター更新
    updateFavoriteCounter();

    // 5. マーカー再描画（lastRealtimeData があれば）
    if (typeof runnerMarkersLayer !== 'undefined' && runnerMarkersLayer && ekidenDataCache) {
        // runner_locations は別変数で保持していないので、キャッシュから再取得
        fetch(`data/runner_locations.json?_=${Date.now()}`, { cache: 'no-store' })
            .then(r => r.ok ? r.json() : null)
            .then(locs => { if (locs) updateRunnerMarkers(locs, ekidenDataCache); })
            .catch(() => {});
    }
}

/**
 * タイムラインの「注目」フィルターボタンの表示/非表示を制御します。
 */
function updateFavoriteFilterButton() {
    const btn = document.getElementById('rank-timeline-filter-favorites');
    if (!btn) return;
    btn.hidden = favoriteTeamIds.size === 0;
    // 注目が0になったのに注目フィルター中なら全件に戻す
    if (favoriteTeamIds.size === 0 && rankTimelineFilter === 'favorites') {
        rankTimelineFilter = 'all';
        document.querySelectorAll('.rank-timeline-filter').forEach(b => {
            b.classList.toggle('active', b.dataset.filter === 'all');
            b.setAttribute('aria-pressed', b.dataset.filter === 'all' ? 'true' : 'false');
        });
    }
}

/**
 * タイムライン用のタイムスタンプを解釈します。
 * ログのタイムスタンプはタイムゾーンなしのJST（日本時間）として記録されているため、
 * +09:00 を付加してUTCへ正しく変換します。
 * @param {string} value - タイムスタンプ文字列
 * @returns {Date} 解釈されたDateオブジェクト
 */
function parseRealtimeLogTimestamp(value) {
    // タイムゾーン指定がない場合は JST（+09:00）として扱う
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}+09:00`;
    return new Date(normalized);
}

/**
 * タイムライン用の選手ラベルを「大学名 N区 選手名」形式で生成します。
 * @param {string} rawRunnerName - ログの runner_name（例: "1甲佐"）
 * @param {string} teamName - 大学名（例: "熊本学園大学"）
 * @returns {string} 表示用ラベル（例: "熊本学園大学 1区 甲佐"）
 */
function buildRankTimelineRunnerLabel(rawRunnerName, teamName) {
    if (!rawRunnerName) return teamName || '';
    // 先頭の数字を区間番号として取り出す
    const match = rawRunnerName.match(/^(\d+)(.+)$/);
    if (!match) {
        // 数字接頭辞なし → そのまま選手名のみ
        return rawRunnerName;
    }
    const legNum = match[1];
    const runnerOnly = match[2].trim();
    const teamPart = teamName ? `${teamName} ` : '';
    return `${teamPart}${legNum}区 ${runnerOnly}`;
}

/**
 * jsonl テキストを行ごとに安全にパースします。
 * @param {string} text - JSONL形式の文字列
 * @returns {Array} パースされたオブジェクトの配列
 */
function parseRealtimeLogJsonl(text) {
    if (!text) return [];
    const lines = text.split('\n');
    const records = [];
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) return;
        try {
            const record = JSON.parse(trimmed);
            if (record && typeof record === 'object') {
                records.push(record);
            }
        } catch (e) {
            console.warn('JSONL parse warning: line skipped due to error', e);
        }
    });
    return records;
}

/**
 * レコードをタイムスタンプ毎にグループ化してスナップショットを構築します。
 * @param {Array} records - レコード配列
 * @returns {Array} スナップショット配列
 */
function buildRankSnapshots(records) {
    const groups = new Map();
    records.forEach(r => {
        if (!r.timestamp || r.team_id === undefined || r.total_distance === undefined) return;
        const ts = r.timestamp;
        if (!groups.has(ts)) {
            groups.set(ts, new Map());
        }
        // 同一タイムスタンプ内で同一team_idが出現した場合は後勝ち
        groups.get(ts).set(r.team_id, r);
    });

    const snapshots = [];
    groups.forEach((teamMap, timestamp) => {
        snapshots.push({
            timestamp: parseRealtimeLogTimestamp(timestamp),
            rawTimestamp: timestamp,
            teams: Array.from(teamMap.values())
        });
    });

    // タイムスタンプ昇順でソート
    snapshots.sort((a, b) => a.timestamp - b.timestamp);
    return snapshots;
}

/**
 * 各スナップショットの順位を計算します。
 * 不完全なスナップショットは計算対象外（daily_record用を除き順位計算からスキップ）にします。
 * @param {Array} snapshots - スナップショットの配列
 * @param {number} expectedTeamCount - 期待される通常チーム数
 * @returns {Array} 順位付きスナップショットの配列
 */
function calculateSnapshotRanks(snapshots, expectedTeamCount) {
    let lastRanksMap = new Map(); // teamId -> rank
    const rankedSnapshots = [];
    let isFullyInitialized = false;

    snapshots.forEach(snapshot => {
        const teams = snapshot.teams;
        // シャドーチーム（ID 99）などの対象外チームを除外した、通常チームだけを抽出
        const regularTeams = teams.filter(t => t.team_id !== SHADOW_TEAM_ID && Number.isFinite(t.total_distance) && Number.isFinite(t.distance));
        
        // 最初の完全なスナップショットが現れるまで初期化しない
        if (!isFullyInitialized) {
            if (regularTeams.length >= expectedTeamCount) {
                isFullyInitialized = true;
            } else {
                // 初期化前でチーム数が足りない場合は、順位計算用としてはスキップ。ただしdaily_record用は保持したいので ranked: false
                rankedSnapshots.push({
                    ...snapshot,
                    ranked: false,
                    regularTeams: regularTeams
                });
                return;
            }
        }

        // 一度完全になった後に一部チームが欠けたスナップショットは、順位変動計算から除外
        if (regularTeams.length < expectedTeamCount) {
            rankedSnapshots.push({
                ...snapshot,
                ranked: false,
                regularTeams: regularTeams
            });
            return;
        }

        // 順位ソート: 1.距離降順 2.前回順位昇順 3.teamId昇順
        regularTeams.sort((a, b) => {
            if (b.total_distance !== a.total_distance) {
                return b.total_distance - a.total_distance;
            }
            const prevRankA = lastRanksMap.get(a.team_id) ?? Number.POSITIVE_INFINITY;
            const prevRankB = lastRanksMap.get(b.team_id) ?? Number.POSITIVE_INFINITY;
            if (prevRankA !== prevRankB) {
                return prevRankA - prevRankB;
            }
            return a.team_id - b.team_id;
        });

        // 順位付け (同距離でも一意な順位にする)
        const teamRanks = regularTeams.map((t, idx) => {
            const rank = idx + 1;
            lastRanksMap.set(t.team_id, rank);
            return {
                ...t,
                overallRank: rank
            };
        });

        rankedSnapshots.push({
            ...snapshot,
            ranked: true,
            teams: teamRanks,
            leaderDistance: teamRanks[0]?.total_distance || 0
        });
    });

    return rankedSnapshots;
}

/**
 * 順位変動タイムラインのイベントを生成します。
 * @param {Array} rankedSnapshots - 順位付きスナップショット配列
 * @returns {Array} イベントオブジェクトの配列
 */
function generateRankTimelineEvents(rankedSnapshots) {
    const events = [];
    let lastValidSnapshot = null;
    let dailyMaxRecord = 0.0;
    let hasDailyRecordStarted = false;

    // 同一チーム・同一種類・同一新順位の重複発生防止用マップ
    // キー: `${teamId}-${type}-${newRank}` -> 直近のタイムスタンプ
    const lastEventMap = new Map();

    rankedSnapshots.forEach(snapshot => {
        // --- 1. 本日最高記録更新の検出 (スナップショットの完全性によらず検出して良い) ---
        const activeRunners = snapshot.regularTeams || snapshot.teams;
        activeRunners.forEach(r => {
            const dist = Number(r.distance);
            if (!Number.isFinite(dist)) return;

            if (!hasDailyRecordStarted) {
                // 初回は基準値とし、イベントは生成しない
                if (dist > dailyMaxRecord) {
                    dailyMaxRecord = dist;
                }
            } else {
                // 基準値を超えて 0.1km 以上更新された場合
                if (dist >= dailyMaxRecord + 0.1) {
                    dailyMaxRecord = dist;

                    const legNumber = parseInt(r.runner_name, 10);
                    const historicalRecordObj = Number.isFinite(legNumber) ? legBestRecordByLeg.get(legNumber) : null;
                    console.log('DEBUG: runner_name:', r.runner_name, 'legNumber:', legNumber, 'historicalRecordObj:', historicalRecordObj, 'dist:', dist, 'legBestRecordByLeg keys:', Array.from(legBestRecordByLeg.keys()));
                    const isHistoricalLegRecord = historicalRecordObj && dist > Number(historicalRecordObj.record);

                    events.push({
                        id: `${snapshot.rawTimestamp}-record-${r.team_id}-${dist.toFixed(1)}`,
                        timestamp: snapshot.timestamp,
                        type: 'daily_record',
                        category: 'record',
                        teamId: r.team_id,
                        runnerName: r.runner_name,
                        distance: dist,
                        isHistoricalLegRecord: !!isHistoricalLegRecord,
                        legNumber: legNumber
                    });
                } else if (dist > dailyMaxRecord) {
                    // 0.1km未満の微増でも基準値としては更新する
                    dailyMaxRecord = dist;
                }
            }
        });
        if (activeRunners.length > 0) {
            hasDailyRecordStarted = true;
        }

        // --- 2. 順位関連イベントの検出 (完全なスナップショット間でのみ比較) ---
        if (!snapshot.ranked) return;

        if (lastValidSnapshot) {
            const prevTeamsMap = new Map(lastValidSnapshot.teams.map(t => [t.team_id, t]));
            const leaderChanged = snapshot.teams[0]?.team_id !== lastValidSnapshot.teams[0]?.team_id;

            snapshot.teams.forEach(team => {
                const prevTeam = prevTeamsMap.get(team.team_id);
                if (!prevTeam) return;

                const oldRank = prevTeam.overallRank;
                const newRank = team.overallRank;
                const rankDelta = oldRank - newRank; // 順位が上がる (数値が小さくなる) と正

                let eventType = null;
                if (newRank === 1 && leaderChanged) {
                    eventType = 'leader_change';
                } else if (rankDelta > 0) {
                    eventType = 'rank_up';
                } else if (rankDelta < 0) {
                    eventType = 'rank_down';
                }

                if (eventType) {
                    const eventKey = `${team.team_id}-${eventType}-${newRank}`;
                    // 重複イベント (連続2スナップショットで発生した同じ新順位イベント) は除外
                    const lastEventTs = lastEventMap.get(eventKey);
                    const isDuplicate = lastEventTs && (snapshot.timestamp - lastEventTs < 120000); // 2分以内の重複

                    if (!isDuplicate) {
                        lastEventMap.set(eventKey, snapshot.timestamp);

                        const leaderGap = snapshot.leaderDistance - team.total_distance;
                        events.push({
                            id: `${snapshot.rawTimestamp}-${eventType}-${team.team_id}`,
                            timestamp: snapshot.timestamp,
                            type: eventType,
                            category: 'rank',
                            teamId: team.team_id,
                            runnerName: team.runner_name,
                            oldRank: oldRank,
                            newRank: newRank,
                            rankDelta: rankDelta,
                            distance: team.distance,
                            totalDistance: team.total_distance,
                            leaderGap: leaderGap
                        });
                    }
                }
            });
        }

        lastValidSnapshot = snapshot;
    });

    // 仕様に従った並び順ソート
    // 1. timestamp 降順
    // 2. leader_change
    // 3. daily_record
    // 4. rank_up (上昇幅の大きい順)
    // 5. rank_down (下降幅の大きい順)
    // 6. teamId 昇順
    events.sort((a, b) => {
        if (b.timestamp - a.timestamp !== 0) {
            return b.timestamp - a.timestamp;
        }
        
        const getPriority = (type) => {
            if (type === 'leader_change') return 1;
            if (type === 'daily_record') return 2;
            if (type === 'rank_up') return 3;
            if (type === 'rank_down') return 4;
            return 5;
        };

        const pA = getPriority(a.type);
        const pB = getPriority(b.type);
        if (pA !== pB) {
            return pA - pB;
        }

        if (a.type === 'rank_up' && b.type === 'rank_up') {
            return b.rankDelta - a.rankDelta; // 上昇幅の大きい順
        }
        if (a.type === 'rank_down' && b.type === 'rank_down') {
            return a.rankDelta - b.rankDelta; // 下降幅の大きい順 (より下降した順)
        }

        return a.teamId - b.teamId;
    });

    // 最大保持件数は当日200件
    return events.slice(0, 200);
}

/**
 * 順位変動タイムラインのUIをDOMに描画します。
 */
function renderRankTimeline() {
    const listEl = document.getElementById('rank-timeline-list');
    const toggleBtn = document.getElementById('rank-timeline-toggle');
    const statusEl = document.getElementById('rank-timeline-status');
    const updateTimeEl = document.getElementById('rank-timeline-update-time');

    if (!listEl || !toggleBtn || !statusEl || !updateTimeEl) return;

    // 1. フィルターに合わせたイベントの抽出
    const filteredEvents = rankTimelineEvents.filter(event => {
        if (rankTimelineFilter === 'all') return true;
        if (rankTimelineFilter === 'rank') {
            return event.type === 'leader_change' || event.type === 'rank_up' || event.type === 'rank_down';
        }
        if (rankTimelineFilter === 'record') {
            return event.type === 'daily_record';
        }
        if (rankTimelineFilter === 'favorites') {
            return isFavoriteTeam(event.teamId);
        }
        return false;
    });

    // 2. 件数ゼロ時の処理
    if (filteredEvents.length === 0) {
        listEl.innerHTML = '';
        toggleBtn.hidden = true;
        statusEl.textContent = '該当する順位変動はまだありません。';
        statusEl.style.display = 'block';
        return;
    }

    statusEl.style.display = 'none';

    // 3. 表示件数の決定 (PC: 3件, スマホ: 1件, 展開時: 全件)
    const isMobile = window.innerWidth <= 768;
    const initialLimit = isMobile ? 1 : 3;
    const displayLimit = isRankTimelineExpanded ? filteredEvents.length : initialLimit;
    const eventsToShow = filteredEvents.slice(0, displayLimit);

    // 4. リストの構築 (XSS対策のため textContent と createElement を利用)
    listEl.innerHTML = '';
    const fragment = document.createDocumentFragment();

    eventsToShow.forEach(event => {
        // マスタ情報から大学名などを引く
        const teamObj = ekidenDataCache && Array.isArray(ekidenDataCache.teams)
            ? ekidenDataCache.teams.find(t => t.id === event.teamId)
            : null;
        const teamName = teamObj ? teamObj.name : 'N/A';
        const teamShortName = teamObj ? teamObj.short_name || teamName : teamName;

        const itemTypeClass = event.isHistoricalLegRecord 
            ? 'historical-record' 
            : (event.type === 'leader_change' ? 'leader' : event.type === 'rank_up' ? 'up' : event.type === 'rank_down' ? 'down' : 'record');
        const li = document.createElement('li');
        li.className = `rank-timeline-item rank-timeline-item--${itemTypeClass}`;
        li.dataset.teamId = event.teamId;

        // 時間要素
        const timeEl = document.createElement('time');
        timeEl.className = 'rank-timeline-time';
        timeEl.dateTime = event.timestamp.toISOString();
        timeEl.textContent = event.timestamp.toLocaleTimeString('ja-JP', { 
            hour: '2-digit', 
            minute: '2-digit', 
            timeZone: 'Asia/Tokyo' 
        });
        li.appendChild(timeEl);

        // アイコン要素
        const iconEl = document.createElement('span');
        iconEl.className = 'rank-timeline-icon';
        iconEl.setAttribute('aria-hidden', 'true');
        let iconText = '';
        if (event.isHistoricalLegRecord) iconText = '✨';
        else if (event.type === 'leader_change') iconText = '👑';
        else if (event.type === 'rank_up') iconText = '▲';
        else if (event.type === 'rank_down') iconText = '▼';
        else if (event.type === 'daily_record') iconText = '🔥';
        iconEl.textContent = iconText;
        li.appendChild(iconEl);

        // コンテンツ要素
        const contentDiv = document.createElement('div');
        contentDiv.className = 'rank-timeline-content';

        // タイトルボタン/テキスト
        const teamBtn = document.createElement('button');
        teamBtn.type = 'button';
        teamBtn.className = 'rank-timeline-team';
        
        let titleText = '';
        let detailText = '';

        // 「大学名 N区 選手名」形式のラベル（記録更新イベント用）
        const runnerLabel = buildRankTimelineRunnerLabel(event.runnerName, teamName);

        if (event.type === 'leader_change') {
            titleText = `${teamName}が首位に浮上`;
            detailText = `${event.oldRank}位 → 1位、総合${event.totalDistance.toFixed(1)}km`;
        } else if (event.type === 'rank_up') {
            titleText = `${teamName} ${event.oldRank}位 → ${event.newRank}位`;
            const suffix = event.leaderGap === 0 ? '首位と同距離' : `首位との差は${event.leaderGap.toFixed(1)}km`;
            detailText = `${event.rankDelta}ランクアップ。${suffix}`;
        } else if (event.type === 'rank_down') {
            titleText = `${teamName} ${event.oldRank}位 → ${event.newRank}位`;
            detailText = `${Math.abs(event.rankDelta)}ランクダウン、総合${event.totalDistance.toFixed(1)}km`;
        } else if (event.type === 'daily_record') {
            if (event.isHistoricalLegRecord) {
                titleText = `✨${runnerLabel}が第${event.legNumber}区の歴代最高記録を更新！✨`;
                detailText = `本日走行距離: ${event.distance.toFixed(1)}km`;
            } else {
                titleText = `${runnerLabel}が本日最高記録を更新`;
                detailText = `本日走行距離: ${event.distance.toFixed(1)}km`;
            }
        }

        teamBtn.textContent = titleText;
        
        // ボタンクリック時に、対象チームのマーカーへ移動するか、詳細モーダルを開く
        teamBtn.addEventListener('click', () => {
            if (typeof trackedTeamName !== 'undefined') {
                // 1. マップが利用可能なら、該当チームを追跡モードにし、マーカーポップアップを開く
                const selectEl = document.getElementById('team-tracker-select');
                if (selectEl) {
                    const teamOption = Array.from(selectEl.options).find(opt => opt.value === teamName);
                    if (teamOption) {
                        selectEl.value = teamName;
                        trackedTeamName = teamName;
                        shouldAutoFollowMap = true;
                        
                        // マップ表示更新＆ポップアップ表示
                        fetchEkidenData().then(() => {
                            if (typeof runnerMarkersLayer !== 'undefined' && runnerMarkersLayer) {
                                runnerMarkersLayer.eachLayer(marker => {
                                    const popup = marker.getPopup();
                                    if (popup && popup.getContent().includes(teamName)) {
                                        marker.openPopup();
                                        map.setView(marker.getLatLng(), 14);
                                    }
                                });
                            }
                        });
                        
                        // マップセクションへスムーズスクロール
                        const mapSec = document.getElementById('section-course-map');
                        if (mapSec) {
                            mapSec.scrollIntoView({ behavior: 'smooth' });
                        }
                        return;
                    }
                }
            }
            
            // 2. マップが利用できない場合はチーム詳細モーダルを開く
            if (typeof showTeamDetailsModal === 'function') {
                const team = lastRealtimeData && Array.isArray(lastRealtimeData.teams)
                    ? lastRealtimeData.teams.find(t => t.id === event.teamId)
                    : null;
                const topDistance = lastRealtimeData && Array.isArray(lastRealtimeData.teams) && lastRealtimeData.teams[0]
                    ? lastRealtimeData.teams[0].totalDistance
                    : 0;
                if (team) {
                    showTeamDetailsModal(team, topDistance);
                }
            }
        });

        contentDiv.appendChild(teamBtn);

        const detailP = document.createElement('p');
        detailP.className = 'rank-timeline-detail';
        detailP.textContent = detailText;
        contentDiv.appendChild(detailP);

        li.appendChild(contentDiv);
        fragment.appendChild(li);
    });

    listEl.appendChild(fragment);

    // 5. 展開トグルの更新
    if (filteredEvents.length <= initialLimit) {
        toggleBtn.hidden = true;
    } else {
        toggleBtn.hidden = false;
        toggleBtn.setAttribute('aria-expanded', isRankTimelineExpanded ? 'true' : 'false');
        toggleBtn.textContent = isRankTimelineExpanded ? '折りたたむ' : `すべて見る（${filteredEvents.length}件）`;
    }
}

/**
 * データを読み込んで順位変動タイムラインをロードします。
 * @param {object} options - オプション
 * @param {boolean} options.force - 強制更新フラグ
 */
async function loadRankTimeline({ force = false } = {}) {
    const statusEl = document.getElementById('rank-timeline-status');
    const updateTimeEl = document.getElementById('rank-timeline-update-time');
    const toggleBtn = document.getElementById('rank-timeline-toggle');

    if (!statusEl || !updateTimeEl || !toggleBtn) return;

    // データがすでにあり、強制更新でない場合は再読み込みしない
    if (rankTimelineEvents.length > 0 && !force) {
        renderRankTimeline();
        return;
    }

    try {
        const response = await fetch(`data/realtime_log.jsonl?_=${Date.now()}`, { cache: 'no-store' });
        
        // 404は「開始前またはログ未生成」として扱う
        if (response.status === 404) {
            statusEl.textContent = '本日の順位変動はまだありません。';
            statusEl.style.display = 'block';
            document.getElementById('rank-timeline-list').innerHTML = '';
            toggleBtn.hidden = true;
            updateTimeEl.textContent = '';
            return;
        }

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        const text = await response.text();
        const records = parseRealtimeLogJsonl(text);

        if (records.length === 0) {
            statusEl.textContent = '本日の順位変動はまだありません。';
            statusEl.style.display = 'block';
            document.getElementById('rank-timeline-list').innerHTML = '';
            toggleBtn.hidden = true;
            updateTimeEl.textContent = '';
            return;
        }

        // 大会日をまたいだデータが混在した場合は、最新の raceDay (最新ログ日付) に対応する当日ログだけに絞る
        // タイムスタンプの日付の最大値を取得し、その日付のレコードのみを処理対象にする
        const dates = records.map(r => r.timestamp ? r.timestamp.substring(0, 10) : '').filter(d => d !== '');
        if (dates.length > 0) {
            const latestDateStr = dates.reduce((max, d) => d > max ? d : max, dates[0]);
            const filteredRecords = records.filter(r => r.timestamp && r.timestamp.startsWith(latestDateStr));
            
            const snapshots = buildRankSnapshots(filteredRecords);
            
            // 期待する通常チーム数 (シャドーチームを除外した数) を取得
            const expectedTeamCount = ekidenDataCache && Array.isArray(ekidenDataCache.teams)
                ? ekidenDataCache.teams.filter(t => !t.is_shadow_confederation).length
                : 0;

            const rankedSnapshots = calculateSnapshotRanks(snapshots, expectedTeamCount);
            rankTimelineEvents = generateRankTimelineEvents(rankedSnapshots);
        } else {
            rankTimelineEvents = [];
        }

        // スナップショットが1件のみなどの場合
        if (rankTimelineEvents.length === 0) {
            const snapshotsCount = buildRankSnapshots(records).length;
            if (snapshotsCount === 1) {
                statusEl.textContent = '比較できる次回更新を待っています。';
            } else {
                statusEl.textContent = '本日の順位変動はまだありません。';
            }
            statusEl.style.display = 'block';
            document.getElementById('rank-timeline-list').innerHTML = '';
            toggleBtn.hidden = true;
            updateTimeEl.textContent = '';
            return;
        }

        // 描画
        renderRankTimeline();

        // 更新時刻の表示 (日本時間形式)
        const now = new Date();
        updateTimeEl.textContent = `${now.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}更新`;

    } catch (error) {
        console.error('Error loading rank timeline:', error);
        
        // 過去の表示がある場合は維持
        if (rankTimelineEvents.length > 0) {
            if (!updateTimeEl.textContent.includes('更新に失敗しました')) {
                updateTimeEl.textContent += ' (更新に失敗しました)';
            }
        } else {
            statusEl.innerHTML = `タイムラインを取得できませんでした。 <button type="button" onclick="loadRankTimeline({ force: true })" style="padding: 0.2rem 0.5rem; font-size: 0.8rem; cursor: pointer;">再読み込み</button>`;
            statusEl.style.display = 'block';
            document.getElementById('rank-timeline-list').innerHTML = '';
            toggleBtn.hidden = true;
        }
    }
}

/**
 * 順位変動タイムラインの初期化を行います。
 */
function initRankTimeline() {
    // 展開ボタンのクリックハンドラ
    const toggleBtn = document.getElementById('rank-timeline-toggle');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            isRankTimelineExpanded = !isRankTimelineExpanded;
            renderRankTimeline();
        });
    }

    // フィルターボタンのクリックハンドラ（注目フィルターも同じハンドラで処理）
    const filterButtons = document.querySelectorAll('.rank-timeline-filter');
    filterButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            filterButtons.forEach(b => {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            const filter = e.target.dataset.filter;
            rankTimelineFilter = filter;
            e.target.classList.add('active');
            e.target.setAttribute('aria-pressed', 'true');
            renderRankTimeline();
        });
    });

    // 注目フィルターボタンの初期表示状態を設定
    updateFavoriteFilterButton();

    // ウィンドウリサイズ時の対応 (閉じている時のみ件数調整)
    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            if (!isRankTimelineExpanded) {
                renderRankTimeline();
            }
        }, 150);
    });
}
