const ROOT = new URL('./', self.registration.scope);
const PREFIX = 'sideband:' + ROOT.pathname + ':';
const CACHE = PREFIX + '__VERSION__';
const SHELL = __SHELL__;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await cache.addAll(SHELL.map(file => new URL(file, ROOT).href));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(PREFIX) && key !== CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== ROOT.origin || !url.pathname.startsWith(ROOT.pathname)) return;
  const relative = url.pathname.slice(ROOT.pathname.length);
  if (relative.startsWith('api/')) return;
  const file = relative === '' ? 'index.html' : relative;
  if (!SHELL.includes(file)) return;
  const key = new URL(file, ROOT).href;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(key);
    // A cached worker response has the prefetch URL without its query. Giving it
    // a fresh Response keeps Worker.location on the requested URL, with engine
    // version, relay and Pyodide settings intact.
    if (cached) return new Response(cached.body, {
      status: cached.status, statusText: cached.statusText, headers: cached.headers,
    });
    const response = await fetch(event.request);
    if (response.ok) await cache.put(key, response.clone());
    return response;
  })());
});
