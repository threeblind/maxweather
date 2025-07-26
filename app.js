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
    // インラインスタイルで簡易的にデザインを調整
    table.style.width = '100%';
    table.style.marginTop = '10px';
    table.style.borderCollapse = 'collapse';

    const thead = document.createElement('thead');
    thead.innerHTML = `
        <tr>
            <th style="width: 15%; text-align: center; padding: 6px; border: 1px solid #ddd; background-color: #f2f2f2;">順位</th>
            <th style="text-align: left; padding: 6px; border: 1px solid #ddd; background-color: #f2f2f2;">走者</th>
            <th style="text-align: left; padding: 6px; border: 1px solid #ddd; background-color: #f2f2f2;">大学名</th>
            <th style="width: 25%; text-align: center; padding: 6px; border: 1px solid #ddd; background-color: #f2f2f2;">平均距離</th>
        </tr>
    `;

    const tbody = document.createElement('tbody');
    records.forEach((record, index) => {
        const formattedRunnerName = formatRunnerName(record.runnerName);
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="text-align: center; padding: 6px; border: 1px solid #ddd;">${index + 1}</td>
            <td class="runner-name" style="text-align: left; padding: 6px; border: 1px solid #ddd;" onclick="showPlayerRecords('${record.runnerName}')">${formattedRunnerName}</td>
            <td style="text-align: left; padding: 6px; border: 1px solid #ddd;">${record.teamName}</td>
            <td style="text-align: center; padding: 6px; border: 1px solid #ddd;">${record.averageDistance.toFixed(3)} km</td>
        `;
        tbody.appendChild(row);
    });

    table.appendChild(thead);
    table.appendChild(tbody);
    return table;
};

/**
 * 取得した個人記録データで個人総合順位と前日の区間賞を更新します。
 * @param {object} realtimeData - realtime_report.json のデータ
 * @param {object} individualData - individual_results.json のデータ
 */
const updateLegRankingAndPrize = (realtimeData, individualData) => {
    const { raceDay } = realtimeData;
    const teamsMap = new Map(realtimeData.teams.map(t => [t.id, t.name]));

    const legRankingBody = document.getElementById('legRankingBody');
    const legPrizeWinnerDiv = document.getElementById('legPrizeWinner');
    const legRankingTitle = document.getElementById('legRankingTitle');
    const legRankingStatus = document.getElementById('legRankingStatus');

    if (!legRankingBody || !legPrizeWinnerDiv || !legRankingTitle || !legRankingStatus) return;

    // --- ① 現在区間の個人記録 ---
    // ステップ1: 「現在の区間」を特定する (総合1位のチームの区間)
    const topTeam = realtimeData.teams[0];
    if (!topTeam || !topTeam.currentLeg) {
        legRankingStatus.textContent = '現在の区間を特定できませんでした。';
        legRankingStatus.style.display = 'block';
        legRankingBody.innerHTML = '';
        return;
    }
    const raceCurrentLeg = topTeam.currentLeg;

    // ステップ2: 表示する選手を絞り込む
    const currentLegRunners = [];
    for (const runnerName in individualData) {
        const runnerData = individualData[runnerName];
        const todayRecord = runnerData.records.find(r => r.day === raceDay);

        // 今日の記録があり、かつその区間がレースの現在の区間と一致する選手のみを対象
        if (todayRecord && todayRecord.leg === raceCurrentLeg) {
            // その選手が現在の区間を走った記録をすべて抽出
            const recordsForCurrentLeg = runnerData.records.filter(r => r.leg === raceCurrentLeg);
            // 区間内での合計距離を計算
            const legTotalDistance = recordsForCurrentLeg.reduce((sum, record) => sum + record.distance, 0);

            currentLegRunners.push({
                runnerName,
                teamName: teamsMap.get(runnerData.teamId) || 'N/A',
                legDistance: legTotalDistance
            });
        }
    }

    // ステップ3: ランキングを作成・表示する
    currentLegRunners.sort((a, b) => b.legDistance - a.legDistance);

    legRankingTitle.textContent = `${raceCurrentLeg}区個人区間記録`;
    legRankingBody.innerHTML = '';
    if (currentLegRunners.length > 0) {
        legRankingStatus.style.display = 'none';
        currentLegRunners.forEach((record, index) => {
            const formattedRunnerName = formatRunnerName(record.runnerName);
            const row = document.createElement('tr');
            row.innerHTML = `
                <td>${index + 1}</td>
                <td class="runner-name" onclick="showPlayerRecords('${record.runnerName}')">${formattedRunnerName}</td>
                <td class="team-name">${record.teamName}</td>
                <td>${record.legDistance.toFixed(1)} km</td>
            `;
            legRankingBody.appendChild(row);
        });
    } else {
        legRankingStatus.textContent = `本日、${raceCurrentLeg}区の記録はまだありません。`;
        legRankingStatus.className = 'result loading';
        legRankingStatus.style.display = 'block';
    }

    // --- ② 前区間の区間賞 ---
    legPrizeWinnerDiv.innerHTML = ''; // 以前の内容をクリア
    legPrizeWinnerDiv.style.display = 'none'; // Hide by default

    if (raceCurrentLeg && raceCurrentLeg > 1) {
        const previousLeg = raceCurrentLeg - 1;

        // 全チームが前区間を走り終えたかチェック
        const allTeamsFinishedPreviousLeg = realtimeData.teams.every(team => team.currentLeg > previousLeg);

        if (allTeamsFinishedPreviousLeg) {
            const previousLegPerformances = [];

            for (const runnerName in individualData) {
                const runnerData = individualData[runnerName];
                // 特定の区間の記録をすべて抽出
                const recordsForLeg = runnerData.records.filter(r => r.leg === previousLeg);

                if (recordsForLeg.length > 0) {
                    const totalDistance = recordsForLeg.reduce((sum, r) => sum + r.distance, 0);
                    const averageDistance = totalDistance / recordsForLeg.length;

                    previousLegPerformances.push({
                        runnerName,
                        teamName: teamsMap.get(runnerData.teamId) || 'N/A',
                        averageDistance: averageDistance
                    });
                }
            }

            if (previousLegPerformances.length > 0) {
                // 平均距離でソートし、上位3名を取得
                previousLegPerformances.sort((a, b) => b.averageDistance - a.averageDistance);
                const top3 = previousLegPerformances.slice(0, 3);

                const title = document.createElement('h4');
                title.textContent = `${previousLeg}区 区間賞`;
                legPrizeWinnerDiv.appendChild(title);

                legPrizeWinnerDiv.appendChild(createPrizeTable(top3));
                legPrizeWinnerDiv.style.display = 'block';
            }
        }
    }
};

/**
 * 取得した駅伝データで順位表を更新します。
 * @param {object} data - realtime_report.json から取得したデータ
 */
const updateEkidenRankingTable = (data) => {
    const rankingBody = document.getElementById('ekidenRankingBody');
    const rankingStatus = document.getElementById('ekidenRankingStatus');
    if (!rankingBody || !rankingStatus) return;

    if (!data || !data.teams || data.teams.length === 0) {
        rankingStatus.textContent = '駅伝ランキングデータを読み込めませんでした。';
        rankingStatus.className = 'result error';
        rankingStatus.style.display = 'block';
        rankingBody.innerHTML = '';
        return;
    }

    rankingStatus.style.display = 'none';
    rankingBody.innerHTML = ''; // テーブルをクリア

    const topDistance = data.teams[0]?.totalDistance || 0;

    data.teams.forEach(team => {
        const row = document.createElement('tr');

        // トップとの差を計算
        const gap = topDistance - team.totalDistance;
        const gapDisplay = team.overallRank === 1 ? '----' : `-${gap.toFixed(1)}km`;

        const createCell = (text, className = '') => {
            const cell = document.createElement('td');
            cell.className = className;
            cell.textContent = text;
            return cell;
        };

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
        row.appendChild(createCell(team.name, 'team-name'));
        row.appendChild(createCell(formatRunnerName(team.runner), 'runner'));
        row.appendChild(createCell(`${team.todayDistance.toFixed(1)} km (${team.todayRank})`, 'today-distance'));
        row.appendChild(createCell(`${team.totalDistance.toFixed(1)} km`, 'distance'));
        row.appendChild(createCell(gapDisplay, 'gap hide-on-mobile'));
        row.appendChild(createRankChangeCell(team));
        row.appendChild(createCell(formatRunnerName(team.nextRunner), 'next-runner hide-on-mobile'));

        rankingBody.appendChild(row);
    });
};

/**
 * サーバーから駅伝の最新データを取得します。
 */
const fetchEkidenData = async () => {
    const titleContainer = document.getElementById('ekidenRankingTitleContainer');
    const updateTimeEl = document.getElementById('ekidenRankingUpdateTime');
    const statusEl = document.getElementById('ekidenRankingStatus');
    const bodyEl = document.getElementById('ekidenRankingBody');

    if (!titleContainer || !updateTimeEl || !statusEl || !bodyEl) {
        console.error("Ekiden ranking elements not found in the DOM.");
        return;
    }

    try {
        // Promise.allで両方のファイルを並行して取得（キャッシュ無効化）
        const [realtimeRes, individualRes] = await Promise.all([
            fetch(`realtime_report.json?_=${new Date().getTime()}`),
            fetch(`individual_results.json?_=${new Date().getTime()}`)
        ]);

        if (!realtimeRes.ok || !individualRes.ok) {
            throw new Error(`HTTP error! status: ${realtimeRes.status} or ${individualRes.status}`);
        }

        const realtimeData = await realtimeRes.json();
        const individualData = await individualRes.json();
        allIndividualData = individualData; // データをグローバル変数に保存

        // タイトルと更新日時を更新
        titleContainer.querySelector('h3').textContent = `高温大学駅伝 ${realtimeData.raceDay}日目 総合順位`;
        updateTimeEl.textContent = `(更新: ${realtimeData.updateTime})`;

        updateEkidenRankingTable(realtimeData);
        updateLegRankingAndPrize(realtimeData, individualData);

    } catch (error) {
        console.error('Error fetching ekiden data:', error);
        statusEl.textContent = '駅伝関連データの取得に失敗しました。';
        statusEl.className = 'result error';
        statusEl.style.display = 'block';
        bodyEl.innerHTML = '';
    }
};

// --- ポップアップ（モーダル）機能 ---

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

            const title = document.createElement('h4');
            title.textContent = `No.${team.id} ${team.name}`;
            card.appendChild(title);

            if (team.manager) {
                const manager = document.createElement('span');
                manager.className = 'manager-name';
                manager.textContent = team.manager;
                card.appendChild(manager);
            }

            // Regular runners
            const runnersList = document.createElement('ul');
            team.runners.forEach((runner, index) => {
                const li = document.createElement('li');
                const formattedName = formatRunnerName(runner);
                li.textContent = `${index + 1}区: ${formattedName}`;
                runnersList.appendChild(li);
            });
            card.appendChild(runnersList);

            // Substitutes
            if (team.substitutes && team.substitutes.length > 0) {
                const substitutesList = document.createElement('ul');
                substitutesList.innerHTML = '<li style="margin-top:10px; font-weight:bold; color:#555;">補欠</li>';
                team.substitutes.forEach(substitute => {
                    const li = document.createElement('li');
                    const formattedName = formatRunnerName(substitute);
                    li.textContent = formattedName;
                    substitutesList.appendChild(li);
                });
                card.appendChild(substitutesList);
            }

            entryListDiv.appendChild(card);
        });

    } catch (error) {
        console.error('エントリーリストの生成に失敗:', error);
        entryListDiv.innerHTML = '<p class="result error">エントリーリストの読み込みに失敗しました。</p>';
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
    displayEntryList();
    fetchEkidenData();
    // 30秒ごとにデータを自動更新
    setInterval(fetchEkidenData, 30000);

    // モーダルを閉じるイベントリスナーを設定
    const modal = document.getElementById('playerRecordsModal');
    const closeButton = document.querySelector('.close-button');
    if (modal && closeButton) {
        closeButton.onclick = closePlayerRecordsModal;
        // モーダルの外側をクリックしたときも閉じる
        window.onclick = function(event) {
            if (event.target == modal) {
                closePlayerRecordsModal();
            }
        };
    }
});