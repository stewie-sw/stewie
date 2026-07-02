# STEWIE production deployment

```bash
docker compose -f deploy/compose.yml up -d     # frontend on http://127.0.0.1:8000 (+ tailnet)
```

| Service | Image | Role |
|---|---|---|
| `frontend` | nginx:1.27-alpine | serves the planner UI + `bodies.json`, reverse-proxies every other route to the backend (300 s read timeout for `/plan` PDF renders, 4 MB body cap mirroring the API limit); sets the edge security headers (CSP / X-Content-Type-Options / Referrer-Policy / Permissions-Policy) |
| `backend` | python:3.12-slim + `pip install .[server]` | FastAPI app `stewie.server.server:app` on uvicorn :8770 (internal only), non-root user, `/healthz` container healthcheck; reports/profiles persist in the `stewie-data` volume (`STEWIE_DATA_DIR=/data`) |

## TLS / HTTPS (required for any public exposure) — audit S-04

STEWIE serves **plaintext HTTP only**; it does not terminate TLS itself. The compose file binds the
frontend to **loopback + the tailnet** (`127.0.0.1:8000` and the Tailscale IP), never `0.0.0.0`, so the
cleartext port is not reachable from the open LAN. For any internet exposure a TLS terminator MUST sit
in front:

- **cloudflared tunnel** (the intended origin): the tunnel terminates HTTPS at Cloudflare and reaches
  the loopback origin; HTTP→HTTPS redirect + HSTS are handled by Cloudflare.
- **or an outer nginx/Caddy** holding the cert: add a `listen 443 ssl;` block, a
  `listen 80; return 301 https://$host$request_uri;` redirect, and
  `Strict-Transport-Security: max-age=31536000; includeSubDomains` on the HTTPS responses. The header
  stubs are commented in `deploy/nginx.conf`.

The backend enforces this in code: `stewie-serve` / `python -m stewie.server.server` **refuses a
non-loopback bind** (e.g. `--host 0.0.0.0`) unless `STEWIE_TLS_TERMINATED=1` (or `STEWIE_DEV_OPEN=1`)
declares that HTTPS is terminated in front (`server._require_tls_for_public_bind`). The compose backend
sets `STEWIE_TLS_TERMINATED=1` because the edge terminates TLS; do not flip it off while exposing the
service. **Never** publish the cleartext port directly to the internet without the terminator.

Production knobs (compose env):
- `STEWIE_API_KEY` — **set this in production**: gates the mutating POST routes (fails closed when unset; dev-loopback uses `STEWIE_DEV_OPEN=1`)
- `STEWIE_CORS_ORIGINS` — **same-origin by default** (empty); a comma list pins exact origins; `*` re-opens the authenticated API to any website (avoid in production) — audit S-11
- `STEWIE_TLS_TERMINATED` — `1` asserts an HTTPS terminator fronts a public bind (compose default `1`) — audit S-04
- `STEWIE_REPORTS_TTL_S` — report retention (default here: 7 days)

Verified 2026-06-09: UI + bodies.json from nginx; `/healthz`, a real Tutorial-1 `/plan` -> 63 KB PDF
fetched back through the proxy; malformed orders -> contracted 400; backend restart -> healthy +
frontend reconnects; reports survive restart in the volume. Builds use `network: host` (host without
a working docker bridge for buildkit). An opt-in ROS2 teleop/nav service ships behind the `ros2`
compose profile (heavy `osrf/ros:jazzy-desktop` base): `docker compose -f deploy/compose.yml --profile ros2 up -d`.
