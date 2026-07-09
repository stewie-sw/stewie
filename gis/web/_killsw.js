// STEWIE kill-switch service worker.
//
// The subdomain artemis.stewie.space previously served an interim Vite PWA (the reverted 2D map rewrite) that
// registered a service worker (default path /sw.js, scope /). That SW serves the whole
// cached that PWA offline-first, so browsers that visited the old site keep seeing
// the stale app even though the origin now serves the QWC2/OpenLayers viewer.
//
// nginx serves THIS file at /sw.js (and /service-worker.js) with no-cache. On the next
// navigation the browser update-checks the SW script, sees new bytes, installs this one,
// which immediately unregisters itself, deletes all Cache Storage, and reloads every open
// tab to the live origin content. Net effect: the stale PWA evicts itself.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      try {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      } catch (_) {}
      try {
        await self.registration.unregister();
      } catch (_) {}
      const clients = await self.clients.matchAll({ type: "window" });
      for (const client of clients) {
        try {
          client.navigate(client.url);
        } catch (_) {}
      }
    })(),
  );
});
// No fetch handler: every request goes straight to the network (the new viewer).
