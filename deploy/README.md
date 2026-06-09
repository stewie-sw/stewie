# STEWIE production deployment

```bash
docker compose -f deploy/compose.yml up -d     # frontend on http://localhost:8000
```

| Service | Image | Role |
|---|---|---|
| `frontend` | nginx:1.27-alpine | serves the planner UI + `bodies.json`, reverse-proxies every other route to the backend (300 s read timeout for `/plan` PDF renders, 4 MB body cap mirroring the API limit) |
| `backend` | python:3.12-slim + `pip install .[server]` | FastAPI app `stewie.server.server:app` on uvicorn :8770 (internal only), non-root user, `/healthz` container healthcheck; reports/profiles persist in the `stewie-data` volume (`DUSTGYM_DATA_DIR=/data`) |

Production knobs (compose env, all optional):
- `DUSTGYM_API_KEY` — **set this in production**: gates the mutating POST routes (unset = open, dev only)
- `DUSTGYM_CORS_ORIGINS` — comma list or `*`
- `DUSTGYM_REPORTS_TTL_S` — report retention (default here: 7 days)

Verified 2026-06-09: UI + bodies.json from nginx; `/healthz`, a real Tutorial-1 `/plan` -> 63 KB PDF
fetched back through the proxy; malformed orders -> contracted 400; backend restart -> healthy +
frontend reconnects; reports survive restart in the volume. Builds use `network: host` (host without
a working docker bridge for buildkit). The ROS2 bridge service joins this compose file at B1.3-B1.6.
