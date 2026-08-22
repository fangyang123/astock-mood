// 盯盘情绪捕获页 Service Worker
// 作用域为根（/），仅缓存 /m 与 manifest，使页面可离线打开；
// 不缓存 /api/* 与主应用，保证数据实时与后台不受影响。
const CACHE = 'mood-v1';
const PRECACHE = ['/', '/m', '/static/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((c) => c.addAll(PRECACHE).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;          // POST 等一律走网络
  let u;
  try { u = new URL(req.url); } catch (e) { return; }
  if (u.origin !== self.location.origin) return; // 跨域不处理

  // 仅对 /m 做「网络优先、失败回退缓存」，保证离线可开
  if (u.pathname === '/m') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const cp = res.clone();
          caches.open(CACHE).then((c) => c.put(req, cp));
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }
  if (u.pathname === '/static/manifest.webmanifest') {
    event.respondWith(
      caches.match(req).then((cached) =>
        cached || fetch(req).then((res) => {
          const cp = res.clone();
          caches.open(CACHE).then((c) => c.put(req, cp));
          return res;
        })
      )
    );
    return;
  }
  // 其余（含 /api/*、主应用 /）走网络，不缓存
});
