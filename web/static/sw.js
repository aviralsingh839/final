/* CHRONO PCOD/PMOS companion — offline service worker.
   Cache-first for the shell so the app opens with no network at all;
   network-first for /api so data is always live when the server is up. */

const CACHE = 'chrono-pmos-v9.0.0';
const SHELL = [
  '/',
  '/index.html',
  '/static/styles.css',
  '/static/app.js',
  '/manifest.webmanifest',
  '/favicon.svg'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(SHELL).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // API calls: always try the network first; only fall back when offline.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => new Response(
        JSON.stringify({offline: true, error: 'server unreachable'}),
        {headers: {'Content-Type': 'application/json'}}
      ))
    );
    return;
  }

  // Shell: cache-first, then network, then cached index for navigation.
  event.respondWith(
    caches.match(req).then(hit => {
      if (hit) {
        // Refresh the cache in the background.
        fetch(req).then(res => {
          if (res && res.ok) caches.open(CACHE).then(c => c.put(req, res.clone()));
        }).catch(() => {});
        return hit;
      }
      return fetch(req)
        .then(res => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then(c => c.put(req, copy));
          }
          return res;
        })
        .catch(() => req.mode === 'navigate' ? caches.match('/index.html') : Response.error());
    })
  );
});
