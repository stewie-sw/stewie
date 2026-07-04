# STEWIE remainder execution plan (items 1–5) — 2026-07-04

Baseline: `origin/main` @ board 227/315 (P0 93/102, P1 130/178) after the v8 campaign. This sequences the
decision-/hardware-bound remainder into a loop-executable order.

## Ordering principle
**Enablers first** (they accelerate or unblock everything downstream) → **on-host build tracks by dependency**
→ **the big independent frontend track** → **decisions/hardware**. Externally-blocked items (CI token,
hardware) are *prepared + surfaced*, not skipped. High-blast items (MT-01 git-history rewrite) get an explicit
confirm-gate before any irreversible step.

## Phase A — Enablers (fast, high-leverage, mostly on-host)
- **A1. GPU-EGL container fix** — makes Gazebo/gpu_lidar RENDER in-container (the mesa/EGL segfault blocks
  item 3). On-host: nvidia-container-toolkit + the NVIDIA runtime (`--gpus all` + `NVIDIA_DRIVER_CAPABILITIES`
  incl. `graphics`/`display`, or `--runtime=nvidia`). Verify with the H-6 gpu_lidar world (real topics + a
  rendered frame). **Unblocks RS-05 / BA-07 / BA-08 / PM-13–16** — highest leverage, do first.
- **A2. CI self-hosted runner (item 5)** — install the GitHub Actions runner on this 32-core box; registration
  needs a token only Aaron can mint (repo → Settings → Actions → Runners → New self-hosted runner). Loop
  PREPARES the install + surfaces the token step; once registered, add `runs-on: [self-hosted, linux, x64]`.
  Drops CI ~25 min → ~2 min (the real fix for the runner-queue diagnosis).

## Phase B — ROS2 node track (item 2, on-host in stewie-ros2, incremental like BA-06)
- **B1. BA-09** — promote DART/LODE autonomy into REAL ROS2 nodes, phase-by-phase (interop first, then a
  node per subsystem), each container-verified.
- **B2. PM-18** — perception + mapping ROS2 nodes run the tested classifiers/mapper.
- **B3. PM-19** — the connected live hazard-perception loop (needs A1 render + B2).

## Phase C — GPU render + dense perception (item 3, after A1)
- **C1. RS-05** — Gazebo live-sensor loop + RViz.
- **C2. BA-07** (running-sim smoke gate) + **BA-08** (ROS→Godot viz bridge, never command authority).
- **C3. PM-13/14/15/16** — depth-source abstraction, dense point cloud + recognition, regional target
  height + volume (GPU dense stereo).

## Phase D — Backend maintainability (item 4 backend parts)
- **D1. MT-05** — continuity ADRs (real DART/LODE/LEAP/FORGE/stewie boundary decisions) + a regenerable-
  artifact manifest.
- **D2. MT-01** — DEM externalization (~225 MB `samples/lunar_dem/*.rf32` → checksum manifests + fetch +
  gitignore, keep one tiny smoke fixture). **HIGH-BLAST**: implies a git history rewrite + force-push. Loop
  PREPARES the manifests + fetch + working-tree removal, then **STOPS for Aaron's explicit confirm** before any
  history rewrite / force-push (irreversible).

## Phase E — Frontend React/GeoLibre (item 1, the biggest board lever; keep vanilla cockpit live, no big-bang)
- **E1. AC-01/AC-02** — TS API client + route registry generated from the FastAPI OpenAPI (141 routes).
- **E2. RF-01/RF-02/RF-03** — React shell + workspace state (web-first, wrapper-agnostic per D1).
- **E3. GL-01/GL-02** (MapLibre 2D workbench, GeoLibre-first) + **DW-01** (DuckDB-WASM mission package).
- **E4. MG-01/02/04** — migration governance + parity gates + responsive `/program`.
- **E5. §7.17 remediation** FR-01..06/09 + **BD-03** + **TU-01** + the FS-25 / PM-17 / PO-15 UI surfaces.
- Playwright-verify each pane; redeploy + Cloudflare-verify per milestone.

## Phase F — Decisions + hardware (item 4 tail)
- **F1. D2/D3** — Wave-6 scope (PKG track, vision tier): surface a recommendation to Aaron; PKG-01..06 is
  on-host-doable if approved.
- **F2. RS-06** — hardware loop (Jetson): genuinely BLOCKED (no device); ledger.

## Per-row execution contract
screen live code → TDD `[REQ:ID]` on REAL data (no synthetic) → **gate to GREEN as a separate confirmed step**
(ruff + FULL mypy + req_trace + assessment + regression; server-import smoke for routers; wheel-smoke for
pyproject; container-verify container-gated; Playwright for frontend) → clean split-edit glyph flip → regen
ALL 3 artifacts → post-flip req_trace + row-count-unchanged → commit → gated branch→main ff push. Never
integrate unverified; never fake-promote; never fabricate/synthetic; gate-green-BEFORE-commit; stop-for-confirm
before any irreversible/outward action (MT-01 force-push, CI runner registration, deploys stay main-thread).

## Execution update (2026-07-04) — A1 blocked, reordered
- **A1 (GPU-EGL) DEEPER THAN A FLAG FIX.** `nvidia-ctk` present + RTX 3090 visible in-container with
  `NVIDIA_DRIVER_CAPABILITIES=all` + `10_nvidia.json` EGL vendor, BUT Gazebo/OGRE2 SEGFAULTS at render-system
  init on BOTH the headless-EGL and the xvfb-GLX path (Ogre2RenderEngine::CreateRenderSystem / RenderSystem_
  GL3Plus). Needs the container's NVIDIA GL userspace aligned to host driver 535.261.03 (rebuild stewie-gazebo
  on an `nvidia/opengl`/`nvidia/cudagl` base, or mount matching libnvidia-gl), OR real display hardware. NOT a
  quick win → item 3 (GPU render/dense perception) stays blocked on this.
- **A2 (CI runner)** needs Aaron's GitHub registration token → surface, don't block the loop.
- **REORDERED loop start** (GPU-independent tracks first): **item 2 (BA-09 ROS2 nodes, on-host, incremental)**
  → **item 4 backend (MT-05 ADRs)** → **item 1 frontend** (scaffold AC-01/02 then CHECK IN with Aaron on the
  React approach before the full UI — it is huge + opinionated + must not big-bang the live cockpit).
  Deferred pending decisions/hardware/deeper-infra: A1/item3 (GPU), A2 (token), RS-06 (Jetson), MT-01 (confirm),
  D2/D3.

## Aaron's decisions (2026-07-04)
- **Frontend (item 1): SCAFFOLD + REVIEW** (my recommendation, Aaron: "recommendations?"). Loop builds
  AC-01/AC-02 (TS API client + route registry from OpenAPI -- concrete/testable), THEN asks Aaron on the React
  shell approach before the UI rewrite. Do NOT big-bang the live cockpit.
- **CI runner (A2): SET UP -- done but BLOCKED.** stewie-archimedes registered at org stewie-sw + Listening,
  BUT org self-hosted runners are blocked from the PUBLIC repo by default -> jobs queued -> reverted CI to
  ubuntu-latest. **AARON ACTION NEEDED:** org Settings -> Actions -> Runner groups -> Default -> "Allow public
  repositories" (then I re-apply runs-on: self-hosted for push events), OR give a REPO-level runner token to
  re-register at repo scope. Runner install persists; for reboot-persistence: `cd ~/actions-runner && sudo
  ./svc.sh install && sudo ./svc.sh start`.
- **GPU (item 3): INVEST in the gazebo-nvidia rebuild** (Aaron). Loop rebuilds stewie-gazebo on an
  nvidia/opengl base (host driver 535.261.03) to unblock OGRE2 render, then does RS-05/BA-07/08/PM-13-16.
- **PKG (D2): DEFER** until the PyPI names are parked + everything tested (Aaron). Parked.

## Loop work order (post-decisions)
1. GPU gazebo-nvidia rebuild (A1 deeper fix) -> if it renders, item 3 (RS-05/BA-07/08/PM-13-16).
2. Item 2: BA-09 ROS2 nodes (on-host, no render needed).
3. Item 4 backend: MT-05 ADRs.
4. Frontend scaffold: AC-01/AC-02 -> then ASK Aaron.
5. MT-01: prepare -> confirm-gate before force-push.
Blocked-on-Aaron: CI runner (org setting), RS-06 hardware, D3 vision tier, PKG (names+tests).

## GPU render diagnosis (2026-07-04) — root cause found, host-config fix for Aaron
The Gazebo/OGRE2 container segfault is NOT a rebuild problem: it is docker not injecting the NVIDIA graphics
libs. Confirmed: (1) host has libGLX_nvidia/libEGL_nvidia/libnvidia-glcore (driver 535.261.03); (2) the
nvidia-container-toolkit supports graphics + the CDI spec /var/run/cdi/nvidia.yaml HAS 7 graphics-lib mount
lines; BUT (3) `--gpus all`, `--runtime=nvidia`, AND `--device nvidia.com/gpu=all` all fail to mount them ->
the container falls back to mesa -> OGRE2 CreateRenderSystem segfaults. **Cause: docker CDI is not enabled in
the daemon.** **AARON FIX (sudo):** add `{"features": {"cdi": true}}` to /etc/docker/daemon.json ->
`sudo systemctl restart docker` -> then `docker run --device nvidia.com/gpu=all -e NVIDIA_DRIVER_CAPABILITIES=all
stewie-gazebo:jazzy bash -lc 'ls /usr/lib/x86_64-linux-gnu/libGLX_nvidia.so*'` should list the lib. Then item 3
(RS-05/BA-07/08/PM-13-16) unblocks. NOTE: Godot render already works HOST-NATIVE (xvfb+vulkan on the 3090);
only Gazebo (container-only, not on Debian apt) needs this docker-CDI fix.

## Aaron frontend decisions (2026-07-04, post-AC-01)
- **Mode: LOOP BUILDS AUTONOMOUSLY, pane-by-pane** (strangler-fig behind parity gates; vanilla cockpit stays live).
- **Stack: Vite + React + TypeScript + React Router** (MULTI-ROUTE, answering Aaron's "more than one page?" --
  each ConOps view + /program + admin is its own route/page; binds to the AC-01 api_client.ts). Next.js = the
  heavier SSR/file-routing alternative, not chosen. A separate Vite bundle only for a genuinely separate app.
- **Map: MapLibre GL / GeoLibre, 2D-first** (D1; avoids the Cesium-init black-screen that reverted the last rewrite).
- **AC-02 now unblocked**: pane taxonomy = the ConOps spine routes -> AC-02 route registry can annotate pane
  ownership against them.
- **Build order (Phase E):** RF-01 (Vite+React+TS+Router shell, served at /app, vanilla stays at /) -> RF-02/03
  (workspace state) -> GL-01/GL-02 (MapLibre workbench) + DW-01 -> MG-01/02/04 (migration governance + parity
  gates + responsive /program) -> AC-02 + FR-01..09 + BD-03 + TU-01 + FS-25/PM-17/PO-15 UI. Playwright-verify
  each pane; keep the vanilla cockpit authoritative until a pane's MG parity gate passes (no big-bang).

## GPU item-3 status (2026-07-04, after Aaron's CDI fix)
- **CDI ENABLED (Aaron applied the sudo fix).** docker features.cdi=true; `--device nvidia.com/gpu=all` now
  DISPATCHES (nvidia-smi shows the RTX 3090) AND the NVIDIA GL libs MOUNT into the container (at
  /usr/lib/x86_64-linux-gnu/nvidia/current/, loadable after ldconfig). This is a real step forward from the
  prior "libs never mount" state.
- **STILL BLOCKED: OGRE2/Gazebo render.** Even with the nvidia GL libs mounted + loadable + on LD_LIBRARY_PATH,
  gz sim SEGFAULTS in Ogre2RenderEngine::CreateRenderSystem -> "Unable to load Ogre Plugin RenderSystem_GL3Plus"
  across EGL (--headless-rendering), forced-nvidia-EGL (__EGL_VENDOR_LIBRARY_FILENAMES=10_nvidia.json), and
  xvfb+GLX. The container's OGRE2 GL3Plus plugin does not init against the mounted nvidia GL (likely a GL/mesa
  ABI mismatch in the osrf/ros:jazzy-derived gazebo image).
- **Real fix = rebuild stewie-gazebo on an nvidia/opengl (or nvidia/cudagl) base** with matching OGRE2/GL, a
  dedicated infra effort (uncertain, multi-step) -- NOT a quick env tweak. Do NOT re-chase the env-var
  combinations (CDI/EGL-vendor/xvfb all tried + fail at the same OGRE2 CreateRenderSystem segfault). Item 3
  (RS-05/BA-07/08/PM-13-16) stays deferred pending that rebuild; the frontend pane-migration is the main track.

## GPU item-3 UNBLOCKED (2026-07-04) — CORRECTION: no rebuild needed, it was LIBGL_ALWAYS_SOFTWARE=1
The "needs a gazebo-nvidia rebuild" conclusion above is SUPERSEDED. Root cause of the OGRE2 segfault: the
stewie-gazebo image bakes `ENV LIBGL_ALWAYS_SOFTWARE=1` (deploy/ros2/Dockerfile.gazebo:27) which FORCES
software mesa GL; with the CDI-mounted nvidia GL libs also present, that conflict segfaults OGRE2 at render-
system init. FIX (runtime env, no rebuild): --device nvidia.com/gpu=all + LIBGL_ALWAYS_SOFTWARE=0 +
LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/nvidia/current + __GLX_VENDOR_LIBRARY_NAME=nvidia + xvfb (see
deploy/ros2/render_gpu.env). VERIFIED: the H-6 gpu_lidar world renders + publishes /model/ipex/perception +
/model/ipex/perception/points (a real GPU sensor render). Item 3 (RS-05 Gazebo live-sensor loop, BA-07/08,
PM-13-16) is now BUILDABLE on the box; the container CPU-only default (LIBGL_ALWAYS_SOFTWARE=1) is unchanged
for CI. Requires Aaron's docker features.cdi=true (applied 2026-07-04).
