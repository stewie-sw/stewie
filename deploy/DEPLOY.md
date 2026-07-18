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

## Scoped anonymous GIS principal (AR-005)

The public GIS routes (`/api/plan`, `/api/export/geojson`, `/api/structure`, `/dem/site_lonlat`,
`/dem/site_meta`, `/dem/sources`) are reached by anonymous `/ide` users. nginx used to inject the
**director-equivalent** `STEWIE_API_KEY` on them, so an anonymous browser was a full director. It now injects a
**scoped guest key** via the distinct `X-Stewie-Anon-Key` header (`include /etc/nginx/gis-anon-key.conf`), which
the backend resolves to identity `gis-anon` → role **guest** (plan/read only, its own audit actor + quota,
never director or command authority).

**Provisioning (required before deploying the nginx change — else these routes 401 / nginx fails to start):**

1. Generate a scoped key distinct from `STEWIE_API_KEY`: `openssl rand -hex 32`.
2. Set it in `deploy/.env`: `STEWIE_GIS_ANON_KEY=<that value>` (the backend reads it; empty ⇒ no anonymous
   principal ⇒ the public routes stay auth-required, fail-closed).
3. Create the mounted include `gis-anon-key.conf` (same pattern as the existing `api-key.conf`, but the scoped
   value): `proxy_set_header X-Stewie-Anon-Key <that value>;` — LOCAL-ONLY, never committed.
4. `docker compose -f deploy/compose.yml up -d` and verify through Cloudflare.

**Rollback:** revert `deploy/artemis-nginx.conf` (restores the `api-key.conf` includes) and redeploy. The
backend change is backward-compatible — it still accepts `STEWIE_API_KEY`, so a mismatched rollout degrades to
the old behaviour rather than an outage.

**UX note — `/api/construction` (operator) + `/api/resync/compare` (director):** these two are gated ABOVE
guest at the route, so the scoped principal gets **403** on them (correct least-privilege: an anonymous user
should not reach operator/director functions). If the `/ide` needs either for anonymous planning, that is a
deliberate follow-up: lower the route gate to `guest` after confirming the handler is non-destructive — do NOT
re-inject the director key.

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

---

# viz2 drive-validate + the QWC2 `/ide` embed (RT-06) — artemis runbook

The `/ide` panel **Validate ▸ Drive 3D** embeds the viz2 Godot pixel-stream so an operator drives the
authored mission on the real Haworth surface. It is **two separate origins**, both fronted by the SAME
host cloudflared (`/etc/cloudflared/config.yml`), which is why there is no CORS and no nginx work:

```
artemis.stewie.space  -> cloudflared -> 127.0.0.1:8083  (docker `artemis-web` nginx; serves /ide/ from gis/qwc2/prod)
viz2.stewie.space     -> cloudflared -> 127.0.0.1:8900  (HOST systemd --user unit; Godot on the host GPU)
```

The `/ide` page embeds `https://viz2.stewie.space/stream?token=…` **cross-origin**. That works because
viz2's parent-origin allowlist admits `*.stewie.space` and viz2 sets no `X-Frame-Options`/CSP
`frame-ancestors`. **cloudflared runs on the host, not in a container** — this is the whole trick: the
`artemis-web` container *cannot* reach a host port (this host drops container→host traffic, the same wall
that forced the rosbridge collector), but cloudflared can, so viz2 needs no nginx proxy at all.

## viz2 is a HOST service, not a container (GPU)

Godot needs the real GPU (`xvfb-run` + `--rendering-driver vulkan`); GPU **graphics** in Docker is blocked on
this host (compute-only). So viz2 runs as a **systemd `--user` unit** — `~/.config/systemd/user/viz2-stream.service`
(not in git; recreate from the block below). `Linger=yes` is already set for the user, so it survives logout
**and reboot**. It spawns one xvfb+Godot per browser session, so an idle unit costs nothing.

```ini
[Service]
WorkingDirectory=/mnt/projects/stewie/code
Environment=STEWIE_GODOT_PROJECT=/mnt/projects/stewie/code/stewie/godot
Environment=STEWIE_GODOT=/mnt/projects/tools/Godot_v4.6.3-stable_linux.x86_64
Environment=VIZ2_STREAM_MAX_SESSIONS=2
Environment=VIZ2_STREAM_MAX_CONN_PER_MIN=20
Environment=VIZ2_STREAM_TOKEN=<token; must match the one injected into prod/index.html>
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=XDG_RUNTIME_DIR=/run/user/1000
Environment=PYTHONPATH=/mnt/projects/stewie/code:/mnt/projects/stewie/code/packages/stewie-bodies:/mnt/projects/stewie/code/packages/stewie-forge
# loopback ONLY: cloudflared reaches it; there is no raw LAN/tailnet :8900 surface.
ExecStart=/mnt/projects/stewie/code/.venv/bin/python -m uvicorn stewie.stream.app:app --host 127.0.0.1 --port 8900 --ws websockets
Restart=on-failure
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now viz2-stream     # enable => survives reboot (linger)
systemctl --user status  viz2-stream
journalctl --user -u viz2-stream -n 50        # Godot/xvfb spawn errors land here
curl -s https://viz2.stewie.space/healthz     # {"ok":true,"service":"viz2-stream"}
```

## Rebuilding + shipping the `/ide` bundle (the trap that will bite you)

`gis/qwc2/prod` is **gitignored** — building locally IS the deploy (the `artemis-web` container bind-mounts
it read-only, so new files are served immediately; no container restart). **The trap:** webpack's
`output.path` is `<qwc2>/prod`, i.e. `npm run prod` in the main tree writes **straight into the LIVE mount**
and would serve a half-built tree. So **build in a throwaway worktree/copy, then rsync in**:

```bash
# 1) build in an ISOLATED checkout (its own gis/qwc2/prod), never the live tree
cd <isolated-worktree>/gis/qwc2 && npm run prod          # -> <isolated>/gis/qwc2/prod

# 2) tell the page where viz2 lives (the plugin reads these globals; nothing else injects them)
#    insert BEFORE the QWC2App.js bundle tag in the built prod/index.html:
#    <script>window.STEWIE_VIZ2_ORIGIN="https://viz2.stewie.space";window.STEWIE_VIZ2_TOKEN="<token>";</script>

# 3) back up the live bundle = the rollback anchor
cd /mnt/projects/stewie/code/gis/qwc2
rsync -a --exclude='cesium/' prod/ prod.bak-$(date +%Y%m%d-%H%M)/

# 4) swap in (keep cesium/: it is a separate ~20 MB mount the build does not produce)
rsync -a --delete --exclude='cesium/' <isolated>/gis/qwc2/prod/ prod/
```

**Cache:** `/ide/index.html` is Cloudflare `DYNAMIC` (never edge-cached) and the JS chunks are
content-hashed, so a rebuild ships immediately — the `?v=` stamping trap that applies to
`app.stewie.space/assets/cockpit.js` does **not** apply here. Verify through the domain anyway:

```bash
curl -s https://artemis.stewie.space/ide/ | grep -o 'QWC2App.js?[a-f0-9]*'   # expect the NEW hash
curl -s https://artemis.stewie.space/ide/config.json | grep -c MissionDrive3D # expect 2
```

**Rollback:** `rsync -a --delete --exclude='cesium/' prod.bak-<ts>/ prod/` (and
`systemctl --user disable --now viz2-stream` to pull viz2).

## ⚠ Exposure posture (read before you widen anything)

The viz2 token is embedded in the **public** `/ide` bundle, so `Validate ▸ Drive 3D` is a **public,
unauthenticated, interactive GPU drive service** on the shared RTX 3090. It is bounded by design:

- **SIM-only.** The console's `{cmd_vel}`/`{safe}`/`{rearm}` + excavation verbs actuate the in-process
  conserved plant + Godot. The stream server holds **zero real-rover egress** (no rclpy/live node, no
  executive/release path) — RT-02 sole-egress and the AG-08 real-instruction gate are intact. This is not a
  convention: `[REQ:RT-06] stewie/stream/test_viz2_ide_embed.py` **fails the build** if a real-rover egress is
  ever imported into the stream server, and if a `{safe}` latch stops letting through dig/dump/drum/arm.
- **Capped.** `VIZ2_STREAM_MAX_SESSIONS=2` + `VIZ2_STREAM_MAX_CONN_PER_MIN=20` (enforced in
  `stewie/stream/security.py`, gated by `test_security.py`).

To lock it down: rotate `VIZ2_STREAM_TOKEN` (unit env **and** `prod/index.html`, then `systemctl --user
restart viz2-stream`), lower `MAX_SESSIONS`, put the existing basic-auth (`artemis-htpasswd`) in front of it,
or add Cloudflare Access on the `viz2.stewie.space` ingress.
