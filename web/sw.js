// JacobAI service worker: opens the app instantly, keeps the shell + your recent chats available offline.
// The AI itself runs on the Mac, so sending messages, making music or editing pictures needs the Mac to be reachable.
const V = 'jacobai-v1';
const SHELL = ['/static/app.css', '/static/chat.js', '/static/store.js', '/static/ui.js', '/offline.html', '/manifest.webmanifest', '/icons/icon-192.png', '/icons/favicon.png'];
const PRIVATE = ['jacobai-pages', 'jacobai-data', 'jacobai-img'];  // cleared on sign-out

self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k.startsWith('jacobai-') && k !== V && !PRIVATE.includes(k)).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('message', e => { if (e.data === 'clear') e.waitUntil(Promise.all(PRIVATE.map(k => caches.delete(k)))); });

const timeout = (p, ms) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))]);
const cacheable = r => r.ok && r.headers.get('X-Cache-OK') === '1';  // the server marks only signed-in (non-guest) responses

async function networkFirst(req, cacheName, ms) {
  try {
    const r = await timeout(fetch(req), ms);
    if (cacheable(r)) { const c = await caches.open(cacheName); c.put(req, r.clone()); }
    return r;
  } catch (e) {
    const hit = await caches.match(req, { cacheName });
    if (hit) return hit;
    throw e;
  }
}

self.addEventListener('fetch', e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;
  const p = url.pathname;
  if (req.mode === 'navigate') {
    e.respondWith(networkFirst(req, 'jacobai-pages', 4000).catch(() => caches.match('/offline.html')));
  } else if (p.startsWith('/static/') || p.startsWith('/icons/') || p === '/manifest.webmanifest') {
    e.respondWith(caches.match(req).then(hit => { const net = fetch(req).then(r => { if (r.ok) caches.open(V).then(c => c.put(req, r.clone())); return r; }).catch(() => hit); return hit || net; }));
  } else if (p === '/api/chat/list' || p === '/api/chat/get' || p === '/api/img/history' || p === '/api/samples') {
    e.respondWith(networkFirst(req, 'jacobai-data', 5000));
  } else if (p.startsWith('/img/')) {
    e.respondWith(caches.match(req, { cacheName: 'jacobai-img' }).then(hit => hit || fetch(req).then(r => { if (cacheable(r)) caches.open('jacobai-img').then(c => c.put(req, r.clone())); return r; })));
  }
});
