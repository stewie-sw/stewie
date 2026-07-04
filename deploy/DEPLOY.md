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
cd <repo root>
docker tag stewie-backend:latest  stewie-backend:rollback        # undo target
docker tag stewie-frontend:latest stewie-frontend:rollback
docker compose -f deploy/compose.yml build backend frontend
docker compose -f deploy/compose.yml up -d backend frontend
# rollback: re-tag rollback->latest + up -d
```

## ⚠ Required env: `STEWIE_TLS_TERMINATED=1` (BP-02)

The backend now enters the **guarded** entrypoint (`stewie-serve` -> `server.main`), so the public-bind
TLS guard actually runs in the container (before BP-02 the raw `uvicorn ...server:app` CMD bypassed it).
The guard **fails closed** (SystemExit -> crash loop) on a `0.0.0.0` bind unless TLS termination is
declared. In this deploy TLS is terminated at Cloudflare and the backend is **internal-only** (no host
port; only the frontend reaches it over the docker network), so `deploy/.env` MUST set
`STEWIE_TLS_TERMINATED=1`. (A stale `.env` with `=0` crash-loops the backend under the guarded
entrypoint — this is the intended safety, not a regression.) The compose default is `:-1`, so leaving the
var unset also yields `1`; do not set it to `0` in production.

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

## Supported server image vs optional capability profiles (PO-14)

The **supported server image** is the two-service stack built from `deploy/Dockerfile.backend`
(the planner + API) and `deploy/Dockerfile.frontend` (the nginx UI + proxy) — the `backend` and
`frontend` compose services above. That is what `docker compose up -d backend frontend` deploys and
what fronts `app.stewie.space`.

Everything heavier is an **opt-in compose profile** (nothing in the default `up` pulls it in):

| Profile | Service | What it adds | Gate |
|---|---|---|---|
| `ros2` | `ros2` | ROS2 Jazzy teleop/nav executive (CCSDS demo, Twist teleop) | heavy `osrf/ros:jazzy-desktop` image; DDS wants host networking |
| `godot` | `godot` | Godot 4.6.3 render/sensor sidecar (8-camera rig, state-field + AprilTag egress) | **GPU-gated** (headless Vulkan) + the gitignored Godot binary, both host-provided |

```bash
docker compose -f deploy/compose.yml --profile ros2  up -d ros2         # ROS2 executive
docker compose -f deploy/compose.yml --profile godot run --rm godot \
    res://sidecar.tscn -- --cameras --layers terrain,clasts,rover ...    # a render job (runs to completion)
```

The `godot` profile builds the render RUNTIME (`deploy/Dockerfile.godot`: Xvfb + Vulkan loader + Mesa)
but deliberately does **not** bundle the Godot binary or a GPU: it mounts the repo read-only and expects
the binary at `stewie/.tools/godot/Godot_v4.6.3-stable_linux.x86_64` (gitignored) plus a real NVIDIA GPU
via the service's device reservation. On a CPU-only host, drop the `deploy.resources` block — the
container still builds, but `render.sh` has no GPU to attach and the render will not produce frames. That
is the intended gate: the profile is DECLARED and documented; a live render needs the GPU host.

## Session secret + key rotation (BP-03)

Production (`STEWIE_TLS_TERMINATED=1`) **requires** a standalone `STEWIE_SESSION_SECRET` — the backend refuses
to boot without it (fail-loud, like the API key). Without it the session-signing key is derived from
`STEWIE_API_KEY`, so rotating the automation key would silently invalidate every live session.

- **Rotate `STEWIE_API_KEY`** (automation credential): live operator sessions are UNAFFECTED (they are signed
  with the separate session secret). Safe to rotate anytime.
- **Rotate `STEWIE_SESSION_SECRET`**: intentionally invalidates all live sessions (operators must sign in
  again). Use to force a global session reset.

## Secrets management (SOPS + age)

Deploy secrets are **age-encrypted with SOPS** so the encrypted file is safe to commit; the plaintext
`deploy/.env` stays gitignored.

- `deploy/.env.enc` — the SOPS/age-encrypted secrets (committed). dotenv mode: variable NAMES are visible,
  VALUES are encrypted (`ENC[AES256_GCM,...]`).
- `deploy/.env` — the decrypted runtime file docker compose reads (gitignored, `chmod 600`).
- `.sops.yaml` — the encryption config (the age recipient / public key).
- `~/.config/sops/age/keys.txt` — the age **PRIVATE key**. NEVER committed. **BACK IT UP** (e.g. a password
  manager): if it is lost, `deploy/.env.enc` is unrecoverable.

**Edit a secret:** `sops deploy/.env.enc` (opens decrypted in `$EDITOR`, re-encrypts on save).
**Deploy:** `deploy/decrypt-env.sh` (writes `deploy/.env`) then `docker compose -f deploy/compose.yml up -d`.
**Add another machine/person as a recipient:** add their age public key under `.sops.yaml` `age:`, then
`sops updatekeys deploy/.env.enc`.
**Tooling:** `go install filippo.io/age/cmd/age@latest github.com/getsops/sops/v3/cmd/sops@latest` (→ `~/go/bin`).
