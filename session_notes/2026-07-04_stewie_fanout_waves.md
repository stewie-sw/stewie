# STEWIE fan-out waves — 2026-07-03 → 07-04

An autonomous multi-agent `/loop` (Aaron: "fan out agents, cont until complete") drove the on-host P0/P1
backlog to V=D across 5 fan-out waves + a direct EG-09 refactor, on branch `feat/platform-restructure`.
Method per wave: a `Workflow` fans out N agents (each screens the REAL code + returns complete module + `[REQ:]`
test code, NO commits/PRD-edits by agents); the **main thread independently re-gates every draft** (full mypy +
req_trace + assessment + regression + server-import smoke where relevant) before flipping the glyph. Never
integrate an unverified draft.

## Rows landed (20)

| Wave | Rows | Home |
|---|---|---|
| 1 | BD-01, EG-12, MP-10, MP-11 | contracts (body profile, physics-model control, rehearsal, reconciliation step) |
| 2 | MP-06, VT-03, VT-04, PX-01 | contracts/specs/physics (mission flow, arm joint, drum set, backend byte-compat test) |
| 3 | VT-05, VT-10, SN-11, AM-08 | physics/specs/dart (dynamic CG, camera extrinsics, Meerkat obs, braked hold) |
| 4 | SN-15, AM-03, AM-04, AM-09 | dart (feature association, Meerkat raise, differential pitch, Meerkat decision) |
| 5 | EP-06, VT-06 | dart/physics (posture policy time/energy; VT-06 already-built → citing test) |
| — | EG-09 | server (import-DAG guard — see below) |

EG-09 correctly SELF-BLOCKED in wave 1 (a real backend import cycle) and was fixed directly later.

## EG-09 — the one real blocker, fixed directly

Wave-1 agent found a genuine cross-service import cycle (world→mission→execution→world) via
`routers.plan.heavy_quota` (reached by gis_export) and `routers.twin._terrain_lock` (reached by executive),
and refused to fabricate a green test. Fixed per the open-fix-all rule: relocated `heavy_quota` →
`stewie/server/deps.py` and `_terrain_lock` → `stewie/server/world_state.py` (both shared-core), so the
world/mission/execution services import them from CORE, not across each other. Added
`stewie/server/service_boundaries.py` (documented 12-service manifest + `service_of` + AST `build_service_graph`
+ `find_cycle` + `rclpy_importers`) and `test_service_import_dag.py` `[REQ:EG-09]`: the service graph is
ACYCLIC, CORE is a sink, rclpy egress is execution-only. The test itself caught a real `core→execution`
layering issue (`ros_evidence`/`session` consume the ROS bridge) which was fixed HONESTLY by reclassifying them
as execution-domain — not gerrymandered. `heavy_quota` now re-reads its env limit per check (runtime-tunable);
the heavy-routes test fixture resets the now-shared quota per test. Server-import smoke + full server regression
green.

## Bugs caught + fixed by the honesty guards (the important part)

1. **Fake-promote** (wave-2 flip): a `re.sub` glyph-flip with `re.S` + non-greedy `.+?` matching `| N | N | N |
   NA |` SPANNED past rows whose Q≠NA (VT-03=G, VT-04=P) and falsely flipped FS-25 + GI-03 to done while
   VT-03/VT-04 stayed N. Reached main + prod briefly; **req_trace caught it** (`V=D without a citing test`).
   Fixed: exact line-based flip + revert FS-25/GI-03.
2. **Newline-eater** (wave-3 flip): the "corrected" line-flip's `\s*$` ate the trailing newline, merging rows
   and deleting SN-12/VT-06 (315→312). **The mandatory post-flip req_trace caught it.** Fixed: newline-preserving
   `re.sub(r'\| N \| N \| N \| ([A-Za-z]+) \|(\s*)$', ...)` + assert the newline survives + assert row count
   unchanged.
3. **Stale generated artifacts**: the loop regenerated `program_snapshot.json` each row but not
   `STATUS.md/json` + `release_manifest.json` (they read `git show HEAD:PRD.md`, so must be regenerated AFTER
   committing the PRD flip). Reded main's CI twice; fixed by regenerating ALL THREE on every PRD change.

MANDATORY protocol now (charter ★): flip by exact newline-preserving line-edit → RE-RUN req_trace + row-count
check → commit PRD → regen all 3 artifacts. This guard chain caught every bug before it stuck.

## State

- **origin/main = `b5c8a3d`**, board **219/315 (72.8% in-scope)**. All 20 rows + EG-09 pushed; each main push
  was CI-verified green (main went from 10+h-red to green early in the session).
- **AS-04**: un-flipped V=D→P (the honest firewall correction — it was V=D without recorded container evidence,
  from concurrent AS-lane work; do NOT re-flip or touch the AS lane).
- **Deploy**: `app.stewie.space` was redeployed twice mid-session (last to the ~208-board corrected build). It
  is now BEHIND main (219) by the wave-3/4/5 + EG-09 rows — a redeploy would bring prod current.

## Remaining tail (NOT done — the honest gaps)

- **Edit-heavy backend P1** (need file edits, not additive): PX-02 (mission-schema `physics_backend_id` +
  `/physics/backends` endpoint) + MT-04 (lean pyproject extras split) — both hit the weekly usage limit in
  wave 5; BP-03/04/06 (prod session-signing secret / strict identity / training-view access).
- **Integration follow-ups** (the delivered gates are built + tested but NOT yet wired into the live flow):
  EG-02/03/05/06/11 enforcement + EG-07 audit + EG-08 lifecycle + MP-05/07 gates + the MP-06 execution seam
  all stop at "typed + tested"; wiring them into `/executive/run` is where they start ENFORCING.
- **Gated frontier** (correctly deferred): all frontend/GeoLibre (RF/GL/DW/MG/FR/FS-24/MT-03), ROS/Gazebo/
  hardware (BA-*, RS-05/06, PM-18/19, the AS lane), dense-stereo GPU, PyChrono oracle, LAC/IPEx geometry.

## Recommended next phase

1. **Wire the delivered governance/planning gates into `/executive/run`** (highest value): the ~15 typed
   contracts built this session (modes/roles/authority/audit/reconciliation/live-gate/plan-executability/
   physics-scoring/mission-flow) are inert until the live command path calls them. This turns "built" into
   "enforcing" and is mostly additive wiring at known chokepoints.
2. Then the **edit-heavy backend-security P1s** (PX-02, BP-03/04/06, MT-04) — small, well-scoped edits.
3. The **frontend GeoLibre rewrite** is the separate large track (its own React/MapLibre effort).
