const CACHE_NAME = 'ghostly-v2.0.0';
const STATIC_CACHE = 'ghostly-static-v2';
const OFFLINE_URL = '/offline.html';

const PRECACHE_URLS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  'https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== STATIC_CACHE && name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const cloned = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, cloned);
            });
          }
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            return cached || new Response(
              JSON.stringify({ error: 'Offline', message: 'You are currently offline. Data may be outdated.' }),
              { headers: { 'Content-Type': 'application/json' }, status: 503 }
            );
          });
        })
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        event.waitUntil(
          fetch(request).then((response) => {
            if (response.ok) {
              caches.open(STATIC_CACHE).then((cache) => {
                cache.put(request, response);
              });
            }
          }).catch(() => {})
        );
        return cached;
      }

      return fetch(request).then((response) => {
        if (!response.ok) {
          if (request.mode === 'navigate') {
            return caches.match(OFFLINE_URL).then((offline) => {
              return offline || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/html' } });
            });
          }
          return response;
        }

        const responseToCache = response.clone();
        caches.open(STATIC_CACHE).then((cache) => {
          cache.put(request, responseToCache);
        });

        return response;
      }).catch(() => {
        if (request.mode === 'navigate') {
          return caches.match(OFFLINE_URL).then((offline) => {
            return offline || new Response('Offline', { status: 503, headers: { 'Content-Type': 'text/html' } });
          });
        }
        return new Response('Offline', { status: 503 });
      });
    })
  );
});

self.addEventListener('sync', (event) => {
  if (event.tag === 'ghostly-sync') {
    event.waitUntil(syncPendingData());
  }
});

async function syncPendingData() {
  try {
    const cache = await caches.open('ghostly-pending-sync');
    const keys = await cache.keys();
    for (const request of keys) {
      const response = await cache.match(request);
      if (response) {
        const body = await response.text();
        await fetch(request, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: body
        });
        await cache.delete(request);
      }
    }
  } catch (e) {
    console.error('[SW] Sync failed:', e);
  }
}

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
