// Service worker - umožní instalaci aplikace a zobrazí offline stránku bez připojení.
// Stránky se vždy načítají ze sítě (data musí být aktuální), z cache jen statické soubory.
const CACHE = "sfm-static-v12";
const PRECACHE = [
    "/offline",
    "/static/style.css?v=11",
    "/static/app.js?v=10",
    "/static/charts.js?v=5",
    "/static/icons/icon.svg",
    "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(() => caches.match("/offline")));
        return;
    }

    if (url.pathname.startsWith("/static/")) {
        event.respondWith(
            caches.match(request).then((cached) => cached || fetch(request).then((response) => {
                const copy = response.clone();
                caches.open(CACHE).then((cache) => cache.put(request, copy));
                return response;
            }))
        );
    }
});
