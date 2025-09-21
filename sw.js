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
   event.respondWith(
     caches.match(event.request)
       .then((response) => {
         // キャッシュ内にリクエストされたリソースがあれば、それを返す
         if (response) {
           return response;
         }
         // なければ、通常通りネットワークから取得しにいく
         return fetch(event.request);
       })
   );
 });