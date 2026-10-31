# STEWIE viz2 plan — LLM Council Review (Round 1) + Amendment Spec

**Date:** 2026-07-10
**Target reviewed:** `STEWIE_viz2_driveable_godot_plan_2026-07-10.md` (v1, Fable-authored)
**Method:** 4 independent LLM council members, one adversarial lens each, each verifying against
live code at `main` (HEAD moved `7b250003`→`ad414bb2` during review; same branch line). Author (Fable)
excluded from its own review. Reviewers were READ-ONLY (findings only); amendments applied by the main
thread. Repo-root path note: `data/gis/raw/` and `/mnt/projects/datasets/...` are **siblings of** `code/`,
not under it.

## Verdicts

| Member | Model | Lens | Verdict |
|---|---|---|---|
| A | Opus | §2 architecture forks + §3 phase order | **REVISE** (3 major) |
| B | Sonnet | real-data / provenance / no-synthetic-no-stub | **SHIP-AS-IS** (1 minor) |
| C | Haiku | coverage vs the user's 8 requirements | **GAPS-EXIST** (5 gaps) |
| D | Codex (GPT) | feasibility + FORGE authority-safety + concurrency | **NOT-FEASIBLE as written** (2 blocker, 5 major, 1 minor) |

**Convergence signal:** A and D independently converged on the SAME root fix — one serialized, windowed,
conserved-terrain **session actor**. B confirms the data lens is the plan's strongest part. The dynamic
(live terrain-update + authority) path is the consensus weak spot.

---

## CONSENSUS UNIFYING FIX (Opus + Codex, independent)

Replace v1 §2b ("physics daemon owning a plain `ColumnState` + a new FORGE-protocol `drive_step` method +
updates through the existing `state_fields.gd` texture path") with **ONE core-owned, serialized, windowed
`ConservedTerrainSession` actor**:

1. **Single authority.** The actor owns exactly ONE terrain-session object — recommend a **`WorkSite`**
   (it already carries a fine `ColumnState` + global inventory + dig verbs + a recenter/store window path +
   datum reconstruction, `worksite.py:65,136,242`). Drive runs `drive_step` on the WorkSite's active-window
   `ColumnState`; dig runs WorkSite verbs. No copying between two states. *(Fable to confirm WorkSite exposes
   a drive-compatible active-window path; else a core-owned `ConservedTerrainSession` wrapping a windowed
   `ColumnState` + inventory.)*
2. **Bounded moving PHYSICS window (mandatory, not a fallback).** Measured cost forces it (see BLOCKER-1).
3. **FORGE stays point-eval-only.** Mutation lives in the session/transaction layer; a non-conserving
   backend may return advisory results, never a mutation-capable interface. (Matches the repo's own
   "single physics authority, never split" rule, `CLAUDE.md` Architecture §.)
4. **Generation-namespaced complete patch manifest, published last:** `{generation, bbox, field, shape,
   digest}` for ALL changed fields; Godot validates one complete generation, coalesces/drops stale display
   generations, patches via a **viz2-owned live node** with `ImageTexture.update` (in-place), leaving
   `state_fields.gd`/`terrain.gd` frozen.
5. **Backend swap** resolved by immutable `model_id` through a `resolve_live_backend`-equivalent gate,
   applied only **between acknowledged generations** after invariant/hash checks.
6. **Transport:** reuse/extend `RuntimeProcess` single-threaded authority serialization; bounded command +
   display queues with seq/ACK/deadman (mirror `stream.py:3`); nonblocking Godot poll.
7. **Datum reconstructed + verified before the first drive step.**

---

## BLOCKERS (fix before any viz2 code)

**BLOCKER-1 — whole-tile 2000² drive infeasible at 15–20 Hz (Codex measured; Opus corroborates).**
Codex ran the real `drive_step` on this host: **256² 0.75 ms · 512² 2.6 ms · 1024² 11.3 ms · 2000² 47.1 ms**
(max 48.6). Root cost = `cs.derive_height()` over the whole grid every step (`column_state.py:161`, called
`drive.py:219`) + `four_wheel_pass` full-grid boolean masks per wheel (`rover.py:44,220`) — NOT
`four_wheel_pass` alone as v1 §6 Risk-1 stated. 47 ms = ~71% of a 15 Hz period / ~94% of 20 Hz, before TCP,
rename, texture upload, render. The "rover window" (`terrain.gd:23`) crops the **render mesh only**, not the
physics `ColumnState`. B3's acceptance has no timing gate despite §6 claiming one.
→ Bounded moving PHYSICS window mandatory in B2; add a measured p95 command-to-render latency gate on the
target GPU at the chosen window size; re-point §6 Risk-1 at `column_state.py:161`/`drive.py:219`.

**BLOCKER-2 — B1 turns a deliberately pure FORGE interface into an unguarded terrain mutator (Codex).**
`PhysicsBackend` is 3 pure point functions (`backend_protocol.py:29`); its header says clients don't mutate
terrain and non-conserving backends can't hold release authority (`backend_protocol.py:1`). Putting mutable
`ColumnState` drive/worksite ops into that protocol leaks mutation semantics + hands every future backend a
mutating method; `PhysicsBackendInfo` is descriptive, enforces nothing.
→ Keep FORGE point-eval-only; move mutation to the core-owned session/transaction layer (see Unifying Fix).

## MAJORS

**M-3 — B4 fail-closed gate not future-proof + wrong Chrono ID (Codex; Opus "hot-swap oversells" upgraded).**
Today's refusal exists only because `_BACKENDS` has one entry (`backend.py:53`); `list_backends()` returns
every registered backend (`backend.py:66`) and `/physics/backends` uses it directly as `selectable_backends`
(`models.py:168`). So "is in selectable_backends" grants mutation the instant a non-conserving backend
registers. Shipped strict gate is `resolve_live_backend` (`physics_model_control.py:119`; rejects unvalidated
/unfrozen/deprecated/non-conserved) — B4 doesn't use it. Chrono ID is wrong: ledger model `tier3_chrono@0.0`
has backend id **`tier2_chrono`**; `tier3_chrono` is NOT a backend id (regression note
`test_r4_chrono_backend_ui_parity.py`).
→ Select by immutable `model_id`; resolve through a `resolve_live_backend`-equivalent mutation-authority
gate; test with a REGISTERED fake non-conserving backend (not just unknown-id + tier2→tier2 no-op); Chrono
ledger row read-only, never sent to `get_backend()`.

**M-4 — two terrain authorities + omitted datum reconstruction (Codex).**
B2 = plain `ColumnState`; E1 = `WorkSite` (own fine `ColumnState` + global inventory, `worksite.py:136,242`).
Copying splits mass/terrain authority. Bundles don't persist `datum`; naive `ColumnState` load defaults
datum=0 (`column_state.py:108`) → **flattens the real DEM**; WorkSite reconstructs from height/mass/density
(`worksite.py:65`).
→ One session object (recommend WorkSite); reconstruct + verify datum before the first drive step.

**M-5 — patch protocol absent, shows mixed generations, omits changed fields (Codex; Opus corroborates).**
`state_fields.gd` is load-once full-raster (`387/460`) — no patch reader/bounds/manifest/checksum/latest-only
queue. Atomic rename protects single files, not a multi-field generation → Godot can combine fields from N and
N+1. Rutting changes `density`, `state_label`, `disturbance` (`rover.py:239`), which v1 does NOT stream (only
height/state/mass; mass doesn't change on a wheel pass).
→ generation-namespaced manifest published last `{generation,bbox,field,shape,digest}`; validate one complete
generation, coalesce/drop stale; patch ALL changed fields (height, density, disturbance, state; +mass on
excavation) via a viz2-owned live node (`ImageTexture.update`), frozen seams untouched.

**M-6 — same-state hot swap + TCP flow control unspecified; cited precedent doesn't exist (Codex; Opus corr.).**
No locking on `ColumnState`/`drive_step`; B4 swaps "mid-session on the SAME ColumnState" without a serial
barrier. `stream.py:3` (the claimed mirror) actually has bounded outstanding frames + cumulative ACK +
safe-stop-on-deadline — v1 borrows the name, not the discipline. The cited `planet_browser/server.py`
socket-test precedent **does not exist**; real precedent is `RuntimeProcess` (`process.py`, single-threaded
authority serialization).
→ Serialize all drive/dig/swap through one actor; swaps only between acked generations after invariant/hash
checks; bounded queues + seq/ACK/deadman; nonblocking Godot poll; reuse/extend `RuntimeProcess`.

**M-7 — A2 would falsely label an SfS DEM as a PGDA LOLA product (Codex — DATA INTEGRITY).**
`build_from_dem.py` hard-codes "real LOLA DEM ingest" + PGDA Product-78 provenance + Barker/Mazarico citation
(`106,149`) and always picks its own max-relief window (`61`); the planned explicit center can't be passed
(`203`). Running it on the NAC SfS tif emits a bundle that **falsely claims LOLA provenance** = a no-false-data
violation.
→ SfS-specific builder (or `--source/--provenance/--center` args) with correct SfS citation (USGS NAC
photoclinometry, `dem_sources.py:168-174`; Alexandrov & Beyer 2018 method); A2 verification compares emitted
provenance + bounds vs the chosen SfS window, not only round-trip height.

**M-8 — coverage gaps vs the user's 8 asks (Haiku).**
- Req 8a "dig + SEE dispersion": add an EXPLICIT task to DISPLAY the pre-dig rock field on the terrain
  (height/size/burial visible) so "see dispersion patterns" lands before Phase-E digging (v1 leaves it implicit
  in D3).
- Req 6 "realistic rock dispersion": keep honest `[CALIB]` (global Bandfield/Golombek), not "Haworth-measured";
  D4 (measured) stays BLOCKED on a Haworth NAC ortho — state the fallback.
- Req 5 "highest resolution": state the scope decision (2 km@1 m first cut; full 10 km@1 m deferred to
  TileMosaic) AND explicitly wire/verify the 2 cm fine at a 1 m base (or mark deferred).
- Req 7 "cross-analyze ALL DEM + papers": G2 is data-BLOCKED; G4 as written is metadata display — add a real
  cross-site comparison deliverable (residuals / uncertainty / site-selection) or mark it blocked.
- Req 8b "path vs rock height/size": F2 must verify the planner actually ROUTES AROUND rock clusters (path
  detours), not just "no cell violates the mask."

## MINORS
- Pose interpolation adds ~66 ms fixed latency; name the budget + tradeoff (interp over extrapolation because
  entrapment is a v→0 discontinuity, `drive.py:248-257`) [Opus].
- §1 row 2d "only 3 point functions" undercounts (also `info`/`conserves_mass`/`resolve_soil_params`) [Opus].
- §2d drop euclid "SSH + display forwarding" (X11-forwarded Vulkan isn't HW-accelerated); euclid = 2nd headless
  host or local session [Opus].
- §3 keystone rationale loose: "B unlocks the dig/replan/authority chain," not "everything reads telemetry";
  C1 depends only on A → parallelizes earlier [Opus].
- §0 path-root convention + HEAD now `ad414bb2` [Sonnet].
- Add an end-to-end soak test (real socket, real Godot client, out-of-order generations, swap-during-drive,
  daemon restart/restore, p95 latency + backlog assertion); treat B5/D4/G3 as BLOCKED, not verified [Codex].

## NON-FINDINGS — confirmed SOUND, do NOT churn
GW-12 coordinate adoption §2c (float32 ULP 0.122 mm at 2 km, verified); the disjoint-footprint finding
(re-derived on both axes, md5-confirmed byte-twin); host-GPU-not-Docker; all citations (Golombek `q(k)`,
Demidov h/d=0.60, Cintala genuinely absent, `OBSTACLE_HEIGHT_M=0.075`); the 4 BLOCKED items are genuinely
blocked (no hidden buildable work, no stub); verification-by-real-observation discipline; the stale
`drive_controller.gd:51` posture-path bug + fix.
