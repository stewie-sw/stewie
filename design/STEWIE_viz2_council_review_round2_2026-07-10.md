# STEWIE viz2 plan — LLM Council Convergence Review (Round 2) + v3 Amendment Spec

**Date:** 2026-07-10
**Target reviewed:** `STEWIE_viz2_driveable_godot_plan_2026-07-10_v2.md`
**Method:** 3-lens convergence council (Opus arch / Sonnet data+coverage / Codex feasibility), each scoring
every round-1 finding RESOLVED/PARTIAL/NOT against live code at HEAD `ad414bb2`, then hunting for NEW
material findings. Author (Fable) excluded. Reviewers READ-ONLY; amendments applied by the main thread.

## Convergence status: **NOT CONVERGED**

| Lens | Verdict |
|---|---|
| Opus (architecture) | CONVERGED — BLOCKER-2/M-4/M-5/M-6 resolved; 2 minors |
| Sonnet (data+coverage) | NOT-CONVERGED — M-7 + M-8a-e resolved; **new MAJOR B5** (host-confirmed); 1 minor |
| Codex (feasibility) | STILL-NOT-FEASIBLE — round-1 blockers PARTIAL; **3 new blockers + 5 new majors** |

**Converged & confirmed by ≥2 lenses — DO NOT reopen:** BLOCKER-2 (FORGE stays pure point-eval, v1-B1
withdrawn); M-4 (single WorkSite authority + datum reconstruction, `worksite.py:65-83`); the GW-12 coordinate
contract; all data grounding + citations; coverage gaps M-8a-e (pre-dig rock display D2, honest [CALIB],
resolution scope, cross-site compare G2a/G2b — the SfS/5 m overlap was live-confirmed TRUE, not inferred).

---

## v3 MUST-FIX (the dynamic render/transport + safety layer)

### New BLOCKERS (Codex, code-cited)

**NB-1 — patch coalescing is not atomic state delivery.** v2 drops stale manifests, but each manifest
carries only its own dirty bbox, so two DISJOINT wheel edits leave the first absent once only the newest is
applied (`v2:197`, `rover.py:203`). This also downgrades round-1 M-5 to PARTIAL.
→ Coalesce by UNION of dirty regions, OR periodic full-window keyframe + accumulated deltas since the last
keyframe. Never latest-only-drop for disjoint edits. Godot applies a keyframe then every delta after it.

**NB-2 — the live-render geometry contract is missing.** The frozen loader builds ONE 1 m mesh from bundle
metadata with CPU-baked heights (`terrain.gd:136`, `terrain.gdshader:5`), but the physics state is a moving
~12 m 5/2 cm window. `ImageTexture.update` on a texture the static mesh never samples shows nothing.
→ Define a viz2-owned moving-window mesh whose VERTEX shader samples a LIVE height texture (updated in place),
with an explicit base↔fine↔window↔mesh coordinate mapping. Do NOT reuse the CPU-baked static mesh; leave
`terrain.gd`/`terrain.gdshader` frozen.

**NB-3 — the deadman cannot run by "reusing RuntimeProcess."** `StreamSession` trips only when a caller
invokes `tick()`, but `RuntimeProcess`'s sole authority thread blocks on one socket `readline()`
(`stream.py:60`, `process.py:510`).
→ The actor runs a timer/event loop (`select`/`poll` with timeout, or a dedicated tick thread) that drives
`StreamSession.tick()` on a deadline independent of inbound reads; Godot polls nonblocking.

### New MAJORS

**NM-4 — `worked_store` is unbounded.** In-memory dict copying every departed fine tile (`worksite.py:144,
363`), unlike `TileMosaic`'s bounded/pageable resident set (`tiles_mosaic.py:16`); full 2 km exploration
retains ≈49 GiB @5 cm / 307 GiB @2 cm before checkpoint overhead.
→ Bound/evict the resident worked set (LRU + page-to-disk, mirroring `TileMosaic`) OR cap the explorable
area; state the resident-set memory budget. (Also de-risks Opus's checkpoint-of-streaming-WorkSite concern.)

**NM-5 — calibration does not reach `drive_step`.** The ledger stores a calibration string; `resolve_live_
backend()` returns a backend whose soil resolver is body-based, not model-version-based (`physics_model_
control.py:38,119`, `backend.py:39`).
→ Either plumb model-version calibration into the soil params `drive_step` consumes, or drop the claim that
calibration reaches the drive loop (state it as advisory ledger metadata only).

**NM-6 — loopback TCP removes the security boundary.** Swapping the owner-only Unix socket for TCP makes the
authority reachable by any local process; authorization trusts a caller-provided `role` (`process.py:466,
528`). Godot 4 `StreamPeerTCP` is TCP-only, so a Unix socket can't be spoken directly.
→ Either (a) keep the Unix socket behind a tiny local broker, or (b) bind loopback TCP to 127.0.0.1 + a
per-session shared-secret handshake, and have the SERVER assign role (never trust the client's `role`).

**NM-7 — no boundary/displacement safety.** Out-of-bounds `recenter()` can build an empty tile set; pose
integration is unclamped; wheel masks fall off-grid (`worksite.py:397,436`, `rover.py:44,621`).
→ B1 clamps pose to site bounds, rejects/clips out-of-bounds `recenter`, defines a max per-tick displacement
+ footprint.

**NM-8 — E3's mass check is wrong.** `inventory_kg` is residual drum mass, not a before/after terrain delta;
`volume_evidence` expects a terrain delta + cumulative moved-mass cross-check (`v2:292`, `worksite.py:256`,
`volume_evidence.py:15`).
→ E3 verifies via `RegolithVolumeEstimate.from_delta` (before/after terrain) + cumulative moved-mass, not
`inventory_kg` equality.

**NM-9 — B5 mislabeled "blocked" (Sonnet; MAIN-THREAD CONFIRMED live).** `~/micromamba/envs/chrono/bin/
python3 -c "import pychrono.vehicle as veh; veh.SCMTerrain"` → import OK, `SCMTerrain=True`; committed
`scripts/chrono_scm_export.py` + `chrono_clast_producer.py` present; matches Aaron's dated record that
STEWIE has no host-gated work. The round-1 review WRONGLY filed this as a genuine block.
→ Re-scope B5 as buildable-NOW: the advisory (non-conserving, display-only) Chrono lane via the existing
chrono env + a subprocess/IPC bridge from the pychrono-less main `.venv`. Keep ONLY PX-03 (Chrono as a
CONSERVING release-authority backend) blocked — and blocked on conservation-VALIDATION, not env availability.

### Refinements (PARTIAL → resolve)

- **R-M3 [Codex]:** route mutation authority ALWAYS through the strict LIVE-mode gate (`resolve_live_backend`),
  not `select_backend`, which outside `LIVE` admits any registered non-deprecated backend (`physics_model_
  control.py:154`).
- **R-BL1 [Codex]:** the latency gate measures end-to-end command→APPLIED-RENDER p95, not command→telemetry
  (`v2:135,261`).
- **R-M7 [Codex+Sonnet]:** `DemSource` has no `citation` field (`dem_sources.py:24`) and the SfS row carries no
  Alexandrov & Beyer citation — add a citation field (or source it) so A2's registry-derived-citation
  assertion is implementable.

### Minors [Opus]

- Make Viz2Runtime's "extends `RuntimeProcess`" honest: `StreamSession` wiring, the WorkSite checkpoint/restore
  rewrite (A-01 snapshots a plain `ColumnState`; a streaming WorkSite needs paged `worked_store` + mosaic RNG +
  dual baselines snapshotted bit-exact), and the Unix→TCP swap are NET-NEW sub-tasks, not a light extend. Add
  an explicit "checkpoint/restore of streaming WorkSite" sub-task.
- The Godot-API inferences (`StreamPeerTCP`, in-place `ImageTexture.update`) stay B2/B3-gated.

---

## Convergence bar for the v3 re-check (to avoid infinite regress)

Codex is a maximally adversarial skeptic; a plan will always admit "not specified to the last detail." v3 is
CONVERGED when: (1) all current BLOCKERS (NB-1/2/3) resolved with a concrete contract; (2) the host-confirmed
B5 (NM-9) re-scoped; (3) NM-4/6/7/8 + R-M3/BL1/M7 resolved or explicitly, honestly deferred with reason.
Residual items that are genuinely implementation-time TDD decisions (exact queue depths, shader uniform names)
do NOT block a PLAN's convergence — they belong in the build, not the plan.
