# Phase 5 — cockpit cutover plan (PREPARED, NOT executed)

**Date:** 2026-06-18 · **Status:** ready for Aaron's explicit go. **Nothing in this doc has been run.**
This is the high-blast step: it replaces the live vanilla cockpit served at `app.stewie.space`. Per the
operating rules it waits for an explicit yes; the rollback is named in every step.

## Preconditions (must hold before cutover)

1. **GPU-verified on a real browser** (only Aaron can do this — headless swiftshader can't):
   - the **Cesium planetary globe** renders the Moon/Mars tiles (the one piece not yet built — see §"Open
     build" below), and
   - the **Perception** render→depth pipeline (render-gated) is either built + verified or explicitly
     deferred for the first cutover.
2. **The React cockpit drives end-to-end against a running backend** (`stewie-serve`): sign-in, all work
   areas, real `/dem/heightfield` terrain, Plan authoring + `/plan` solve, Admin/System/Settings. (Phases
   0-4c are integration-verified headlessly; this is the live-backend confirmation.)
3. **CI green** on the `cockpit/` build (add a CI job: `npm ci && npm run build && npm test` in `cockpit/`).

## What changes (the diff)

The build pipeline + which static files nginx serves. **No CSP change is needed** — the Vite build is
already CSP-clean (no inline scripts), and the deployed policy (`deploy/nginx.conf:46`,
`script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval' blob:`, `worker-src 'self' blob:`,
`trek.nasa.gov` in img/connect-src) already covers React + Cesium. This is the low-risk part.

1. **`deploy/Dockerfile.frontend`** — add a build stage:
   ```dockerfile
   FROM node:20 AS cockpit
   WORKDIR /cockpit
   COPY cockpit/package*.json ./ && RUN npm ci
   COPY cockpit/ ./ && RUN npm run build           # -> /cockpit/dist (hashed assets, CSP-clean)
   # then in the nginx stage:
   COPY --from=cockpit /cockpit/dist /usr/share/nginx/html
   ```
   (The design system is a `file:` dep; either vendor it into the image build context or publish it.)
2. **`deploy/nginx.conf`** — serve the Vite output:
   - `index.html` stays `expires -1` (no-cache) — already the case.
   - **Remove** the per-file `location = /assets/cockpit.js { … }` (lines ~67-69) and the other vanilla
     asset blocks; Vite emits **content-hashed** filenames under `/assets/`, so the generic
     `location /assets/ { expires 30d; }` rule is correct AND the **manual `?v=N` cache-buster trap goes
     away** (the hashes self-bust — this fixes the Cloudflare edge-cache footgun in
     `infra_stewie_deploy_cloudflare`).
   - SPA fallback: `location / { try_files $uri /index.html; }` for the cockpit routes, with the API
     catch-all still proxying to `backend:8770` (keep the `/auth`, `/plan`, `/dem`, … proxies — the React
     app calls the same routes).
3. **Delete** `stewie/server/web/assets/cockpit.js` + the vanilla helpers (`adapters.js`, `cockpit_state.js`,
   `panel_layout.js`, `idle_logout.js`, `three3d.js`) and `stewie/server/index.html` **only after** the
   staging cutover (§sequence step 3) verifies the React app on the real host.

## Sequence (staging first, then prod)

1. Land the Dockerfile/nginx changes on a branch; build the frontend image locally; **serve it at a
   staging route** (`app.stewie.space/app2` or a separate cloudflared hostname) — the live cockpit at `/`
   is untouched. **Rollback: nothing to roll back; the live site is unchanged.**
2. Aaron drives the staging React cockpit on a real browser (Cesium globe, Perception, the full flow).
   **Rollback: discard the branch.**
3. Once accepted: flip `/` to serve the React `index.html`, redeploy via the cloudflared path
   (`code/deploy/DEPLOY.md`), and **verify through `https://app.stewie.space`** (check `cf-cache-status`,
   not just `:8000`). **Rollback: `git revert` the nginx/Dockerfile commit + redeploy — the vanilla
   cockpit.js is still in git history (and on disk until step 4), so this restores the old cockpit in one
   deploy.**
4. After a soak period with the React cockpit live + healthy: delete the vanilla cockpit files (step §3
   above) in a follow-up commit. **Rollback: `git revert` that deletion.**

## Open build (the one piece still to write)

The **Cesium planetary globe** (`CesiumGlobe.tsx`, the §11 planetary spine) is not yet built — it was held
because its pixels need a real GPU browser + the NASA tile service to verify, which this environment lacks.
Two honest paths: (a) I build the integration boundary (Cesium Viewer in a thin React wrapper, CSP already
compatible) and Aaron verifies the globe pixels on his browser; or (b) now that the design system is on
claude.ai/design, design the globe view there and emit it as React. Either way it precedes step 1.

## Why the cutover is low-risk once the preconditions hold

The React app is an isolated, CSP-clean static bundle that calls the **same** backend routes the vanilla
cockpit does (verified route-by-route in the FS-23 ledger). nginx changes are additive + reversible; the
deploy topology (Cloudflare → cloudflared → docker frontend → backend:8770) is unchanged; and the rollback
is a one-commit `git revert` + redeploy at every step. The only irreversible-ish moment is deleting the
vanilla files (step 4), which happens last, after soak, with the files still in git history.
