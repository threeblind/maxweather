const CACHE_NAME = 'ekiden-sokuhou-cache-v2';
// オフライン時に利用できるようにキャッシュするファイルのリスト
const urlsToCache = [
  './', // ルートURL
  'index_16.html',
  'app_16.js',
  'images/icon-192x192.png',
  'images/icon-512x512.png',
  'config/ekiden_data.json',
  'config/amedas_stations.json',
  'config/player_profiles.json',
  'config/course_path.json',
  'config/relay_points.json',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css',
  'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js',
  'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png'
];

// 1. インストール処理
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[Service Worker] Opened cache');
        return cache.addAll(urlsToCache);
      })
  );
});

// 2. リクエストがあった場合に、キャッシュから返す処理 (Cache First戦略)
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // http/https以外のスキーム(例: chrome-extension://)のリクエストは無視する
  if (!request.url.startsWith('http')) {
    return;
  }

  // 動的なデータ(json)と主要なページ(html)はStale-While-Revalidate戦略
  if (request.url.includes('.json') || request.destination === 'document') {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) => {
        return cache.match(request).then((cachedResponse) => {
          const fetchedResponsePromise = fetch(request).then((networkResponse) => {
            // ネットワークから取得した新しいレスポンスをキャッシュに保存
            cache.put(request, networkResponse.clone());
            return networkResponse;
          });
          return cachedResponse || fetchedResponsePromise;
        });
      })
    );
    return;
  }

  // その他の静的リソース（CSS, JS, 画像など）はCache First戦略
  event.respondWith(
    caches.match(request).then((response) => {
      if (response) {
        return response;
      }
      return fetch(request).then((networkResponse) => {
        return caches.open(CACHE_NAME).then((cache) => {
          cache.put(request, networkResponse.clone());
          return networkResponse;
        });
      });
    })
  );
});

// 3. プッシュ通知を受け取った時の処理
self.addEventListener('push', (event) => {
  console.log('[Service Worker] Push event received:', event);

  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (e) {
      console.warn('[Service Worker] Failed to parse push data as JSON, using text');
      data = { title: '通知', body: event.data.text() };
    }
  }

  console.log('[Service Worker] Push data parsed:', data);

  const title = data.title || '高温大学駅伝速報';
  const options = {
    body: data.body,
    icon: 'images/icon-192x192.png',
    badge: 'images/icon-192x192.png',
  };

  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});