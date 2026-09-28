const CACHE_NAME = "quality-sims-v24";
const APP_SHELL = [
  "/static/offline.html",
  "/static/css/styles.css?v=21",
  "/static/js/login.js?v=2",
  "/static/js/password-toggle.js?v=2",
  "/static/js/pwa.js?v=2",
  "/static/js/scanner.js",
  "/static/manifest.webmanifest?v=2",
  "/static/icons/qaqc-app-192-v2.png",
  "/static/icons/qaqc-app-512-v2.png",
  "/static/icons/qaqc-app-maskable-512-v2.png"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames
          .filter((cacheName) => cacheName !== CACHE_NAME)
          .map((cacheName) => caches.delete(cacheName))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname.startsWith("/api/")) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match("/static/offline.html"))
    );
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (!response.ok) return response;
        const copy = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        return response;
      })
      .catch(() => caches.match(request))
  );
});
