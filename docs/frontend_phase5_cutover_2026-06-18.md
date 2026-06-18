# Phase 5 — cockpit cutover plan (image BUILT + serve-tested; live flip awaits Aaron's go)

**Date:** 2026-06-18 · **Status:** the React image is built, serve-tested, and browser-verified on this
deploy host. The only remaining step is the **live flip**, which swaps what `app.stewie.space` serves —
a public, outward action. Per the operating rules it waits for an explicit yes; the rollback is one
command and is named below. Everything up to (and including) building + serve-testing the image has been
done; nothing public has changed.

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

## The flip + rollback (the only remaining, public step)

This host **is** the deploy host (`stewie-frontend-1` on `127.0.0.1:8000`, cloudflared at
`/etc/cloudflared/config.yml`, `app.stewie.space` reachable → HTTP 200). The flip is reversible in ~1 min
and verifiable immediately.

**Flip (swaps the public cockpit):**
```
cd /mnt/projects/stewie/code
( cd design-system && npm ci && npm run build ) && ( cd cockpit && npm ci && npm run build )   # ensure fresh dist
docker compose -f deploy/compose.yml -f deploy/compose.react.yml up -d --build frontend
```
**Verify (must do, through Cloudflare — not just :8000):**
```
curl -sS -D - https://app.stewie.space/ | grep -iE "STEWIE Cockpit|cf-cache-status|content-security-policy"
```
plus a real-browser sign-in on `https://app.stewie.space`.

**Rollback (restores the vanilla cockpit in one deploy):**
```
docker compose -f deploy/compose.yml up -d --build frontend     # rebuilds from the untouched Dockerfile.frontend
```
The vanilla `Dockerfile.frontend` + `cockpit.js` are unchanged on disk and in git, so this is a clean revert.

## After a healthy soak (follow-up, not now)

Delete the vanilla cockpit files (`stewie/server/web/assets/cockpit.js` + helpers, `stewie/server/index.html`)
and fold the React Dockerfile into the canonical one. **Rollback: `git revert` that deletion** (files remain
in history). Optional hardening: a CI job that builds `cockpit/dist` so the deploy host no longer needs a
manual pre-build; revisit the from-source multi-stage image if/when the npm bug is resolved upstream.
