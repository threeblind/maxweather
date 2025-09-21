 const CACHE_NAME = 'ekiden-sokuhou-cache-v2';
 // オフライン時に利用できるようにキャッシュするファイルのリスト
 const urlsToCache = [
   './', // ルートURL
   'index_16.html',
   'app_16.js',
   // 'style.css' のようなCSSファイルがあればここに追加します
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
         console.log('Opened cache');
         return cache.addAll(urlsToCache);
       })
   );
 });
 
 // 2. リクエストがあった場合に、キャッシュから返す処理 (Cache First戦略)
self.addEventListener('fetch', (event) => {
    const { request } = event;
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
                    // キャッシュがあればそれを返し、裏でネットワークリクエストを実行。
                    // キャッシュがなければネットワークリクエストの結果を待つ。
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
                // ネットワークから取得したリソースをキャッシュに追加
                return caches.open(CACHE_NAME).then((cache) => {
                    cache.put(request, networkResponse.clone());
                    return networkResponse;
                });
            });
        })
    );
});