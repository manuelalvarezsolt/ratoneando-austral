const CACHE = 'ratoneando-v1.1';

// Assets to precache on install
const PRECACHE_URLS = [
  '/static/css/main.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

// ── Install: precache static assets ──────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

// ── Activate: remove old caches ───────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ──────────────────────────────────────────────────────
self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);

  // Only handle GET
  if (req.method !== 'GET') return;

  // Own static assets: network-first so deploys are picked up immediately;
  // falls back to cache only when offline.
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // CDN resources (Bootstrap, fonts): stale-while-revalidate
  if (url.origin !== self.location.origin) {
    e.respondWith(
      caches.match(req).then(hit => {
        const fresh = fetch(req).then(res => {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
          return res;
        }).catch(() => hit);
        return hit || fresh;
      })
    );
    return;
  }

  // HTML navigation: network-first, cached fallback
  e.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});
