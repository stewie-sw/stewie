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
