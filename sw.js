/*
 * Offline Audio Player - service worker
 *
 * Strategy:
 *   - On install: pre-cache the shell (index.html, manifest, sw itself).
 *   - On fetch: network-first for HTML / manifest / version.json so updates
 *     reach the user as soon as they're online; cache fallback for offline.
 *     Cache-first for static assets.
 *   - On activate: drop old caches, claim clients immediately.
 *
 * Bump CACHE_VERSION whenever the shell changes; clients pick it up on next load.
 */
const CACHE_VERSION = 'v22';
const CACHE = `offline-audio-player-${CACHE_VERSION}`;

const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/headphones.svg',
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

// Allows the page to nudge a waiting SW into activating immediately, used
// by the in-app "update vX.Y.Z" chip so the new SW takes control before the
// page reloads (otherwise the first reload is still served by the old SW).
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING'){
    self.skipWaiting();
  }
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Only handle same-origin requests; let cross-origin requests hit network.
  if (url.origin !== self.location.origin) return;

  // Don't intercept the version-check at all. The in-app updater adds a
  // cache-bust query string and we want the response uncontaminated by
  // any caching layer, including the SW's own cache.
  if (url.pathname.endsWith('/version.json')) return;

  const isShell =
    req.mode === 'navigate' ||
    url.pathname.endsWith('/') ||
    url.pathname.endsWith('/index.html') ||
    url.pathname.endsWith('/manifest.webmanifest');

  if (isShell){
    // Network-first: pull updates eagerly when online; fall back to cache when not.
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req, { cache: 'no-store' });
        const clone = fresh.clone();
        caches.open(CACHE).then(c => c.put(req, clone)).catch(() => {});
        return fresh;
      } catch(_) {
        const cached = await caches.match(req);
        if (cached) return cached;
        return caches.match('./index.html');
      }
    })());
  } else {
    // Cache-first for static assets.
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const fresh = await fetch(req);
        const clone = fresh.clone();
        caches.open(CACHE).then(c => c.put(req, clone)).catch(() => {});
        return fresh;
      } catch(_) {
        return cached || Response.error();
      }
    })());
  }
});
