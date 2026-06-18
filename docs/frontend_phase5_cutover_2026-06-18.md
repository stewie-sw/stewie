# Phase 5 — cockpit cutover (DEPLOYED + verified live 2026-06-18)

**Date:** 2026-06-18 · **Status:** ✅ **LIVE.** The React cockpit was flipped on `app.stewie.space`
(explicit go) and verified end-to-end through Cloudflare with a real browser. The vanilla cockpit + its
Dockerfile/nginx config remain on disk and in git, so the rollback below restores it in one deploy. Only
`stewie-frontend-1` was recreated; backend + ros2 were never touched.

## Approach: serve a prebuilt bundle (mirrors the live Dockerfile.frontend)

The live `deploy/Dockerfile.frontend` runs **no npm in-image** — it COPYs hand-written static assets and
vendors Cesium with `curl`. The React cockpit takes the same shape: a **separate** `deploy/
Dockerfile.frontend.react` COPYs the prebuilt `cockpit/dist` into nginx. The live Dockerfile is untouched,
so rollback is simply "stop using the override."

**Why not a multi-stage in-image `npm ci` build:** it was tried and hit npm's reproducible
**"Exit handler never called!"** bug in clean `node:20` — npm crashes mid-install, half-installs esbuild
(dir present, no `package.json`), yet exits 0, so `&&` proceeds to a build that can't resolve esbuild
(`ERR_MODULE_NOT_FOUND … esbuild/index.js`). Confirmed reproducible in an isolated `node:20` container,
unrelated to our code (the Vite toolchain builds cleanly on the host). Serving a host-built bundle sidesteps
this entirely and matches the project's existing deploy pattern.

**Prerequisite — build `cockpit/dist` on the host before `docker build`** (the Dockerfile header repeats this):
```
( cd design-system && npm ci && npm run build )   # cockpit imports @stewie/design-system (file: dep)
( cd cockpit && npm ci && npm run build )          # -> cockpit/dist: index.html + /assets/* + /cesium/*
```
`cockpit/dist` is gitignored (15 MB, includes the Cesium 1.140 bundle) — it is a regenerated build artifact,
not committed, exactly as the vanilla image's curl-vendored Cesium is not committed.

## What changes (the diff) — all NEW files, the live config untouched

- **`deploy/Dockerfile.frontend.react`** (NEW) — `FROM nginx:1.27-alpine@<digest>`; COPY `nginx.conf`,
  `landing.html`, `cockpit/dist/ → html/`, `bodies.json`; `chmod -R a+rX`. No node stage.
- **`deploy/compose.react.yml`** (NEW) — a one-service override pointing `frontend.build.dockerfile` at the
  React Dockerfile. Nothing else (ports, depends_on, networks all inherit from `compose.yml`).
- **`.dockerignore`** (edited) — un-ignore `cockpit/dist` so it is in the build context (it is the shipped
  artifact); `node_modules` + `design-system/dist` stay ignored (not needed in the image).
- **`deploy/nginx.conf`** — **no change needed.** The deployed policy already serves the React bundle: the
  CSP (`script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:`, `worker-src 'self' blob:`, `trek.nasa.gov`
  in img/connect-src) covers React + Cesium; on `app.stewie.space` `location = /` already serves `/index.html`
  (now the React app); content-hashed `/assets/index-<hash>.js` falls under the generic 30 d `location /assets/`
  (correct for immutable hashed assets — and the manual `?v=N` Cloudflare cache trap is gone: the hashes
  self-bust). The vanilla `location = /assets/cockpit.js` no-cache blocks become harmless no-ops.

## Verified on this host (2026-06-18, before any flip)

- `docker build -f deploy/Dockerfile.frontend.react` → clean image (75.7 MB), seconds (no npm).
- Serve-tested in a throwaway container on `127.0.0.1:8099` (`--add-host backend:127.0.0.1`, isolated from
  the live network): `GET /app` → 200 with "STEWIE Cockpit" + hashed asset refs; host routing (`app.stewie.space/`
  → cockpit, apex → landing); `/assets/index-*.js` → 200 (684 KB, `application/javascript`); `/cesium/Cesium.js`
  → 200 (5.8 MB); production CSP header present; hashed asset `Cache-Control: max-age=2592000`.
- Real-browser (Playwright, swiftshader): the app mounts (`#root` populated) and renders the sign-in screen
  ("Invitation-only. Your role …"), zero page errors — the production image serves a working React shell.
- Prior in-session verification of the same `dist`: vitest 16/16; six Playwright harnesses (phase1/2/3/4b/4c,
  globe with real Moon imagery, perception with the real `/evidence` fixture) all PASS.

## The flip + rollback — use `--no-deps` (build ONLY the frontend)

This host **is** the deploy host (`stewie-frontend-1` on `127.0.0.1:8000`, cloudflared at
`/etc/cloudflared/config.yml`, `app.stewie.space` → HTTP 200). The flip is reversible in ~1 min.

**IMPORTANT — never use `up -d --build frontend`.** In this compose version `--build` rebuilds the
service's dependencies too, so it triggers a **backend** image build, which is slow and out of scope for a
frontend flip. Build the one service explicitly, then recreate it with `--no-deps` so the backend + ros2
containers are never touched:

**Flip (swaps the public cockpit) — what was run:**
```
cd /mnt/projects/stewie/code
( cd design-system && npm run build ) && ( cd cockpit && npm run build )                     # fresh dist
docker compose -f deploy/compose.yml -f deploy/compose.react.yml build frontend              # build ONLY frontend
docker compose -f deploy/compose.yml -f deploy/compose.react.yml up -d --no-deps --force-recreate frontend
```
**Verify (through Cloudflare — not just :8000):**
```
curl -sS -D - https://app.stewie.space/ | grep -iE "STEWIE Cockpit|cf-cache-status|content-security-policy"
```
plus a real-browser sign-in on `https://app.stewie.space`.

**Rollback (restores the vanilla cockpit in one deploy) — frontend-only, no backend build:**
```
docker compose -f deploy/compose.yml build frontend                                          # vanilla Dockerfile.frontend
docker compose -f deploy/compose.yml up -d --no-deps --force-recreate frontend
```
The vanilla `Dockerfile.frontend` + `cockpit.js` are unchanged on disk and in git, so this is a clean revert.

## Verified LIVE (2026-06-18, post-flip)

- Local origin `:8000` (what cloudflared serves): `/` → 200, **604 B** React index (was 89 324 B vanilla),
  "STEWIE Cockpit" + hashed `/assets/index-CXL9ESjB.js`; `/healthz` → 200. Frontend healthy in 16 s.
- Public through Cloudflare: `https://app.stewie.space/` → 200, React index, `cf-cache-status: DYNAMIC`
  (no stale vanilla HIT), CSP header present; hashed `/assets/index-*.js` → 200 (685 KB, `MISS` → now
  edge-cached fresh, content-hashed so no `?v=` trap); `/cesium/Cesium.js` → 200 (5 MB); apex
  `stewie.space` still serves the landing page (host routing intact).
- Real browser (Playwright) on `https://app.stewie.space`: app mounts, JS + Cesium load 200, `/auth/me`
  401, sign-in screen renders, **zero page errors**.
- `.dockerignore` regression fixed in the same pass: a `**/validation` glob added during this rewrite was
  excluding the repo-root `validation/` that `Dockerfile.backend` ships → scoped to `cockpit/validation`;
  `docker compose build backend` re-verified green.

**Residual (only a signed-in run confirms):** a full authed mission flow (sign in → author → `/plan`)
against the live backend — the cockpit is invitation-only and this run had no operator credentials.

## After a healthy soak (follow-up, not now)

Delete the vanilla cockpit files (`stewie/server/web/assets/cockpit.js` + helpers, `stewie/server/index.html`)
and fold the React Dockerfile into the canonical one. **Rollback: `git revert` that deletion** (files remain
in history). Optional hardening: a CI job that builds `cockpit/dist` so the deploy host no longer needs a
manual pre-build; revisit the from-source multi-stage image if/when the npm bug is resolved upstream.
