# STEWIE deploy — public host (app.stewie.space) runbook

## Serving path (what actually serves the public cockpit)

```
app.stewie.space / stewie.space / www.stewie.space
  -> Cloudflare (edge CDN + TLS)
  -> cloudflared tunnel        (/etc/cloudflared/config.yml, service: http://127.0.0.1:8000)
  -> docker frontend container (deploy/compose.yml, published 127.0.0.1:8000:80; nginx)
       /        -> landing.html   (public)
       /app     -> index.html     (the cockpit; backend-login-gated)
       /assets, /cesium, /dem, /... -> static or proxied to backend:8770
```

`127.0.0.1:8000` **is** the public origin (via the tunnel). A `docker compose build/up` of the
frontend updates the origin. There is **no separate host nginx** for stewie — the host `nginx` processes
are the frontend container's. (`webmail.stewie.space -> 127.0.0.1:8001` is unrelated.)

## Deploy steps

```bash
cd stewie/code
docker tag stewie-backend:latest  stewie-backend:rollback        # undo target
docker tag stewie-frontend:latest stewie-frontend:rollback
docker compose -f deploy/compose.yml build backend frontend
docker compose -f deploy/compose.yml up -d backend frontend
# rollback: re-tag rollback->latest + up -d
```

## ⚠ The cache rule (the "redeploy did nothing" trap)

Cloudflare **edge-caches `/assets/*.js`**. `index.html` busts `cockpit.js` with a **manual** query:
`/assets/cockpit.js?v=N`. The app shell (`/app` / index.html) is `no-cache` (Cloudflare `DYNAMIC`, always
fresh), but the JS asset is cached — so **changing `cockpit.js` content without bumping `?v=N` ships
nothing to users** (Cloudflare keeps serving the stale `?v=N` for up to its TTL; a 30-day entry was once
pinned). A direct `curl 127.0.0.1:8000/assets/cockpit.js` looks correct while `app.stewie.space` is stale.

**Rule (now automated + CI-enforced):** run **`python scripts/stamp_cockpit_version.py`** before a
frontend deploy — it stamps the cockpit.js **content hash** into index.html's `?v=` (fresh URL iff the
bytes changed). `stewie/server/test_asset_version_stamp.py` **fails CI** if the stamp is stale, so a
changed `cockpit.js` can't ship behind a stale Cloudflare cache. (Manual `?v=N` bumping is the old, error-
prone way this trap bit us.)

## Verify a deploy THROUGH Cloudflare (not just the origin)

```bash
curl -I https://app.stewie.space/assets/cockpit.js     # want a fresh last-modified; cf-cache-status not a stale HIT
curl -s https://app.stewie.space/assets/cockpit.js | grep -c '<a marker from your change>'
# 127.0.0.1:8000 bypasses Cloudflare -> it will look fine even when the public host is stale. Always re-check the domain.
```

A `?v=` bump sidesteps a stale entry without the Cloudflare API. A true edge purge needs the Cloudflare
dashboard/API token (the cloudflared tunnel credentials are NOT cache-purge credentials).
