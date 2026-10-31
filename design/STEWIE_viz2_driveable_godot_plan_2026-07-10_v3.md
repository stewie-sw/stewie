# STEWIE viz2 — Driveable Godot Simulation ("Artemis STEWIE viz2") — Implementation Plan v3

**Date:** 2026-07-10 (v3, incorporating LLM-council round 2 — see §8)
**Status:** PLAN ONLY. No pipeline code touched; this document is the single write of the v3 pass.
**Supersedes:** `STEWIE_viz2_driveable_godot_plan_2026-07-10_v2.md` (v2, left untouched as the round-2
review target). v1 also intact.
**Council reviews:** round 1 `STEWIE_viz2_council_review_2026-07-10.md`; round 2
`STEWIE_viz2_council_review_round2_2026-07-10.md` (3-lens; verdict NOT CONVERGED — 3 new blockers
NB-1/2/3, majors NM-4..9, refinements R-M3/R-BL1/R-M7, 2 Opus minors).

---

## §0 Status / method note

Read-and-plan pass over `/mnt/projects/stewie/code` @ `main` HEAD **`f632f5ef`** (confirmed `git log`
this session; moved from v2's `ad414bb2`, same branch line). Path-root convention unchanged:
`code/…` paths are under `/mnt/projects/stewie/code/`; `data/gis/raw/`, `design/DEM_CROSSREF_…`, and
`/mnt/projects/datasets/…` are siblings of `code/` (repo-root or host level).

All v2-era verification stands (v2 §0 items 1-5, carried; claims not re-opened are marked
*(v2-verified)* or *(v1-verified)*). Every load-bearing **round-2** premise was **independently
re-verified this session** before this rewrite — each by opening the cited code or running the cited
command, not by trusting the council text:

1. **NB-2 render geometry is real:** the frozen loader's active-zone mesh **CPU-bakes heights into
   ArrayMesh vertices** — `terrain.gd:136` (`_build_active_zone`) samples `sf.height_uv(...)` per
   vertex at `:160`; `terrain.gdshader`'s `vertex()` stage (`:139-142`) only forwards UV, and the
   shader header states it plainly: "Vertex geometry for the ACTIVE zone comes pre-displaced from
   the CPU mesh" (`terrain.gdshader:4-8`). `state_fields.gd` builds ONE raster set from bundle
   metadata at load (`load_scene`, grid dims from metadata `:142-146`, rasters `:167-180`).
   So `ImageTexture.update` on a height texture moves **nothing** on that mesh — v2's B3 as written
   would silently render a static surface. **Counter-precedent found in the same tree:**
   `terrain_farfield.gdshader:1-20` IS a vertex-displace-from-height-texture shader (uniform
   `height_lowres`, displaced in `vertex()`), fed by `terrain.gd:63-68` — the exact mechanism viz2's
   moving-window mesh needs, at fine scale instead of decimated. Fix in §2b.5 + B3.
2. **NB-3 deadman cannot self-run:** `StreamSession.tick(now=…)` trips ONLY when a caller invokes it
   with a supplied clock (`stewie/bridge/stream.py:60-69`; the module is deliberately pure/clockless,
   header `:7-9`). `RuntimeProcess`'s handler blocks on `self.rfile.readline(MAX_LINE_BYTES + 1)`
   (`stewie/runtime/process.py:510`) inside a single-threaded `UnixStreamServer` — while a request
   (or a stalled client) holds the handler, nothing else runs, so "reuse RuntimeProcess" gives the
   deadman no driver. (`serve_forever(poll_interval=0.05)` at `:538` does wake between requests, but
   its `service_actions` hook does not run while a handler blocks — so a poll-loop hook alone is NOT
   a fix; confirmed by reading the handler structure.) Fix in §2b.3 + B2.
3. **NM-4 memory is real and the arithmetic reproduces:** `worked_store` is an unbounded in-memory
   dict (`stewie/physics/worksite.py:146-147` declaration; `_commit_active` `:363-375` copies every
   departed tile's full float64 fields into it; nothing ever evicts or pages it, and `total_mass()`
   `:449-453` sums over all of it). Per fine cell: 4 float64 fields + 1 uint8 = **33 B**. Full 2 km
   worked at 5 cm = 40000² cells → **49.2 GiB**; at 2 cm = 100000² → **307.5 GiB** — the council's
   numbers reproduce exactly. The bounded alternative exists in-tree: `TileMosaic` is explicitly
   "BOUNDED / EVICTABLE RESIDENT SET … LRU-pages-out … optionally paging them to disk"
   (`stewie/terrain/tiles_mosaic.py:16-27`), and `WorkSite` already threads a `page_dir` to it
   (`worksite.py:127-128`). Fix in B1b.
4. **NM-6 security is real:** `RuntimeProcess.handle()` trusts a **caller-provided** `role` —
   `role = str(req.get("role", ""))` and the mutation gate is just `cmd in _MUTATING and role !=
   "drive"` (`process.py:466-470`). Today that is defensible ONLY because the transport is an
   owner-0600 Unix socket (born under `umask(0o177)` + chmod, `:521-528`). A plain loopback-TCP port
   is reachable by any local process and carries no owner semantics — the boundary evaporates. Fix
   in §2b.3 + B2.
5. **NM-8 is real:** `WorkSite.inventory_kg` is the **residual** drum ledger — `dump()` decrements
   it by what landed (`worksite.py:257-268`), so after a dig-then-dump cycle it is ~0, not the moved
   mass. The evidence contract wants a terrain delta: `leap/volume_evidence.py` builds
   `RegolithVolumeEstimate.from_delta(base, as_built, …, conserved_mass_kg=moved)` from before/after
   surfaces + a cumulative moved-mass cross-check (`volume_evidence.py:1-6,15,26-35`). v2's E3
   ("estimate's conserved mass == WorkSite ledger") compared the wrong quantity. Fix in E1/E3.
6. **NM-9 is confirmed live, by me, this session:** `~/micromamba/envs/chrono/bin/python3 -c
   "import pychrono, pychrono.vehicle as veh; …"` → `pychrono True SCMTerrain True` (run this
   session). `scripts/chrono_scm_export.py` + `scripts/chrono_clast_producer.py` are committed
   (`ls` this session). AND the same script's header states the honest limit: SCM sources
   height/disturbance/state, but "mass_areal.rf32 ← THE conserved invariant. SCM does NOT
   conserve/expose areal mass" (`chrono_scm_export.py:20-27`) — so the ADVISORY lane is buildable
   NOW and the CONSERVING lane is blocked on physics validation, not environment. Matches the
   standing project rule that STEWIE has no host-gated work. Fix in B5 + §4.
7. **R-M3 is real:** `select_backend(mode, …)` applies the strict gate ONLY in LIVE mode; any
   non-LIVE mode admits any registered non-deprecated model
   (`stewie/contracts/physics_model_control.py:154-165`). Mutation authority must therefore name
   `resolve_live_backend` (`:119-151`) directly. Fix in §2b.2 + B4.
8. **NM-5 is real:** the ledger `calibration` field is a **status string** ("the
   calibration/validation status string", `physics_model_control.py:44-47`), and the resolved
   backend's soil resolver is **body-based, not model-version-based**:
   `Tier2NumpyBackend.resolve_soil_params(body_name)` → `params_for_body(body_name)`
   (`stewie/physics/backend.py:39-40`). Nothing model-version-shaped reaches
   `drive_step(params=…)` (`drive.py:181-205`). v2's "calibration params feed drive_step" claim was
   wrong. Fix (claim dropped + real seam named) in §2b.2.
9. **R-M7 is real:** `DemSource` has NO `citation` field — its fields are id/name/instrument/…/
   `notes` only (`dart/dem_sources.py:24-38`), and the `lroc_nac_sfs_1m` row (`:167-174`) carries no
   Alexandrov & Beyer citation. v2-A2's "citation derives from the DemSource row" was
   unimplementable as specced. Fix in A2/A3.
10. **NM-7 verified with two mechanism corrections** (see §8 "partially rejected"): an out-of-bounds
    `recenter()` does not merely "build an empty tile set" — with the rover fully outside the site,
    `new_tiles` filters empty and `min(r[0] for r in regions.values())` raises an unhandled
    `ValueError` (`worksite.py:397-409`) — a crash, worse than the council stated. And
    `_wheel_mask` never indexes off-grid (it is built from grid-shaped aranges,
    `rover.py:44-49`); an off-grid pose instead yields an EMPTY mask → the wheel silently stops
    carving/loading (`rover.py:211-217` skips empty) — silent physics degradation, not an
    out-of-bounds access. The amendment (clamp + typed refusal + displacement bound) stands either
    way. Fix in B1.
11. **NB-1 is real at the stamping layer:** `four_wheel_pass` stamps each wheel's rut as its own
    disjoint disc sweep (`rover.py:211-227`), so one drive step's dirty area is up to four disjoint
    regions; two steps' regions can be fully disjoint. v2-B3's "skip to the newest complete
    generation, drop stale" therefore loses the earlier step's edits from the display forever.
    Fix in §2b.4 + B3.

Constraint posture unchanged from v2: Godot 4.6.3 pinned; no synthetic terrain, no fabricated
boulder statistics; FORGE stays point-eval-only (round-1 BLOCKER-2, council-converged — not
reopened); the frozen seams (`state_fields.gd`, `terrain.gd`, `terrain.gdshader`, io_fields) are
not edited. Converged round-1/round-2 items NOT reopened per the round-2 instruction: BLOCKER-2,
M-4 (WorkSite single authority + datum), GW-12 coordinates, all data grounding + citations,
M-8a-e (incl. the live-confirmed SfS/5 m overlap).

---

## §1 Current-state table

Carried from v2 unchanged (rows 1-8; all evidence stands — none of the round-2 findings touched
these rows' EXISTS/PARTIAL claims). One annotation: row 2's "hot-swappable terramechanics" meaning
is further narrowed by NM-5 — see §2b.2; the row's code citations are unaffected.

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Driveable EZ-RASSOR rover, keyboard/gamepad | **PARTIAL** | *(v2, unchanged)* live WASD kinematic drive view (`drive_controller.gd:1-6,143-157`); gamepad NEW; EZ-RASSOR glbs real + MIT-attributed; stale postures path bug (A6) |
| 2 | Hot-swappable terramechanics via FORGE in the drive loop | **PARTIAL** | *(v2, unchanged)* six pure protocol members (`backend.py:30-50`); only `tier2_numpy` registered (`:54`); real conserved drive loop `drive.py:181-298`; no Godot view calls `drive_step`. **v3 note (NM-5):** soil params are body-resolved (`backend.py:39-40`), not model-version-resolved — see §2b.2 |
| 3 | Haworth at highest resolution (1 m SfS base + 2 cm runtime fine) | **PARTIAL** | *(v2, unchanged)* real SfS tif on host twice (11660×12060 @ 1.0 m); `lroc_nac_sfs_1m` registered (`dem_sources.py:167-174`); committed 5 m bundle does NOT overlap the SfS footprint |
| 4 | Interactive sun azimuth + elevation sliders | **PARTIAL** (scripted only) | *(v2, unchanged)* |
| 5 | Realistic rock dispersion + size patterns from real statistics | **PARTIAL** | *(v2, unchanged)* |
| 6 | Dig + before/after dig-depth difference field | **PARTIAL** | *(v2, unchanged)* |
| 7 | Map + path analysis vs rock height/size and slope | **PARTIAL** | *(v2, unchanged)* |
| 8 | Cross-analyze / compare all DEM sites + papers | **PARTIAL** | *(v2, unchanged)* |

---

## §2 Key architecture forks

### (a) Separate Godot project vs a new driveable mode inside `code/stewie/godot/` — UNCHANGED

Carried from v2/v1: a new, separately-launched SCENE + script family inside the existing
`code/stewie/godot/` project (`viz2.tscn` + `viz2_*.gd` + `viz2.sh`), zero edits to the frozen
sidecar/render seams. See v1 §2a for the full argument.

### (b) How the Godot loop talks to the physics — AMENDED (round-2 blockers NB-1/2/3 + NM-4/5/6/7)

**Recommendation (v2 core kept, four sub-contracts hardened): ONE core-owned, serialized, windowed
conserved-terrain session actor — an adopted `WorkSite` — owned by a viz2 runtime built as a
FIXED-RATE ACTOR LOOP that reuses `RuntimeProcess`'s seam discipline (it does not subclass its
request-driven mutation model). FORGE stays point-eval-only. Terrain reaches Godot as
generation-namespaced patch manifests whose coverage is the dirty-region UNION since the last
acknowledged generation, with periodic keyframes; a viz2-owned moving-window MESH displaces its
vertices from a live height texture in its own vertex shader. The frozen `state_fields.gd` /
`terrain.gd` / `terrain.gdshader` seams are untouched.**

#### (b.1) The session object: `WorkSite` — ADOPTED (converged; carried from v2 with two additions)

All of v2 §2b.1 stands (datum-verified load `worksite.py:65-83`; fine window IS a `ColumnState`
`:137`; `drive()`/`payload_kg=ledger` `:229-240`; `recenter` + worked-store paging `:377-434`;
one ledger + `conservation_residual()` `:140,446-468`; streaming-path-only; additive per-tick
`step()`; G1 seam risk). Window sizing unchanged: 240² @ 5 cm fine (k=20) / 600² @ 2 cm (k=50)
on the 1 m base with `tile_base_cells=4, radius_tiles=1` (`worksite.py:132`).

Two v3 additions, both from round-2 verification:

- **The worked store must be bounded (NM-4).** `worked_store` retains every departed tile's full
  float64 fields in RAM forever (`worksite.py:146,363-375`) — 33 B/fine-cell → ~49.2 GiB if the
  full 2 km is worked at 5 cm, ~307.5 GiB at 2 cm (arithmetic reproduced §0.3). The fix mirrors
  the in-tree `TileMosaic` discipline (`tiles_mosaic.py:16-27`): an LRU resident set of worked
  tiles with page-to-disk eviction (reusing the `page_dir` convention `WorkSite` already carries,
  `worksite.py:127-128`), plus a small in-memory per-tile index `{(tr,tc): grid_mass_kg, path}` so
  `total_mass()`/`conservation_residual()` stay O(resident) without reloading pages. **Resident-set
  budget (stated, the NM-4 requirement):** active window (240²·33 B ≈ 1.9 MB / 600²·33 B ≈ 11.9 MB)
  + `worked_resident_tiles = 64` tiles (5 cm tile = 80²·33 B ≈ 211 KB → ~13.5 MB; 2 cm tile =
  200²·33 B ≈ 1.32 MB → ~84 MB) + the scalar index — **worst case ~100 MB RAM at 2 cm fine**. Disk
  growth is bounded by terrain actually WORKED (a mission corridor, not the map): ≈33 B per touched
  fine cell. This is task B1b; it also de-risks the streaming checkpoint (B2b).
- **Boundary/displacement safety is missing (NM-7).** Verified failure modes: fully-OOB
  `recenter()` crashes (`ValueError` from `min()` over empty regions, `worksite.py:404-409` — worse
  than the council's "empty tile set"); an off-grid pose silently stops carving/loading (empty
  `_wheel_mask`, `rover.py:44-49,211-217`) — physics degrades without an error. B1 adds: pose
  clamped to the site's `world_bounds_m` minus a wheelbase margin; `recenter` target validated
  non-empty with a typed refusal (never the bare `ValueError`); a max per-tick displacement bound
  (`v_max·dt` + rejection of non-finite/teleport commands, the `process.py:471-476` M-04 pattern);
  and the recenter margin guarantees the 4-wheel footprint lies inside the active window.

#### (b.2) FORGE stays point-eval-only (converged) — what "hot-swappable" honestly means (NM-5, R-M3)

v1-B1 stays withdrawn; the protocol stays pure. Two round-2 corrections to the v2 text:

- **Mutation authority resolves ONLY through `resolve_live_backend` (R-M3).** v2 said
  "`resolve_live_backend` (or `select_backend(mode, model_id)` composing the same gate)" — wrong:
  `select_backend` is strict only when `mode is LIVE`; every other mode admits any registered
  non-deprecated model (`physics_model_control.py:154-165`). The viz2 session mutates live-analog
  state, so its authority resolution names `resolve_live_backend(model_id)` directly
  (`:119-151`: validated AND frozen AND non-deprecated AND conserved backend AND per-body profile —
  fail-closed at every layer). `select_backend` never appears on the mutation path.
- **The calibration claim is DROPPED (NM-5).** v2 claimed "the resolved model's calibration params
  feed `drive_step(params=…)`". Verified false: the ledger's `calibration` is a validation-status
  STRING (`physics_model_control.py:44-47`), and the backend's soil resolver is body-based —
  `resolve_soil_params(body_name)` → `params_for_body` (`backend.py:39-40`) — with per-cell
  material overrides inside `drive_step` itself (`drive.py:206-215`, `material=True`). What the
  session actually does: (i) resolve mutation authority by `model_id` through the strict gate;
  (ii) obtain soil params from the RESOLVED backend's `resolve_soil_params(body)` — a real,
  honest, backend-owned seam; (iii) display the ledger `calibration` string on the HUD as
  **advisory governance metadata only**. A future model version that carries a real per-version
  parameter set would enter through the existing `drive_step(params=…)` seam — but no such
  parameter set exists today, so the plan claims no calibration swapping in the drive loop.
- Advisory point-evals for non-conserving backends + swaps-only-between-acked-generations: carried
  from v2 unchanged. B5 now makes the advisory lane concrete (buildable NOW — §2b.6).

#### (b.3) Transport + liveness: a fixed-rate actor loop with an authenticated loopback-TCP seam (NB-3, NM-6)

v2's "extend `RuntimeProcess`" was architecturally underspecified in two verified ways: the deadman
has no driver (a blocked `readline()` starves everything, `process.py:510` — §0.2), and swapping the
owner-0600 Unix socket (`process.py:521-528`) for bare loopback TCP deletes the security boundary
while `handle()` trusts a caller-supplied `role` (`process.py:466-470` — §0.4). The v3 contract:

- **The authority is a fixed-rate actor loop, not a request handler.** `Viz2Runtime` runs ONE
  physics thread — the sole mutator — looping at the command rate (15 Hz): drain the command
  mailbox (bounded queue) → apply the latest twist (commands coalesce to latest-twist) → `ws.step()`
  → write the patch generation → **drive `StreamSession.tick(now=monotonic())` every iteration**
  (`stream.py:60`) → on trip, zero the twist (safe-stop) in the same thread. Socket I/O lives on
  the server side and only ENQUEUES messages / reads snapshots — it never mutates. This keeps the
  `RuntimeProcess` single-serialization-point invariant (the loop thread is the point) while giving
  the deadman a clock that no stalled client can starve. Godot polls nonblocking
  (`StreamPeerTCP.poll()` + `get_available_bytes()`; *inferred from the Godot 4 API surface — B2
  confirms before build, unchanged from v2*).
- **Honest provenance (Opus minor): `Viz2Runtime` REUSES `RuntimeProcess`'s seam discipline — it
  does not extend the class.** Reused verbatim as patterns: bounded request lines
  (`MAX_LINE_BYTES`, `process.py:51,505-512`), input-bounds on mutating commands (M-04,
  `:471-484`), the readiness handshake (`:530-535`), and the validate-on-a-fresh-object-then-swap
  checkpoint/restore transaction (`:440-464`). NET-NEW (named as such, each a real sub-task):
  the actor loop + mailbox (this section), the `StreamSession` wiring + deadman driver, the
  TCP + handshake transport (below), and the streaming-WorkSite checkpoint rewrite (B2b — the A-01
  restore snapshots a plain `ColumnState` world; a streaming WorkSite needs the paged
  `worked_store` + index, both baselines, mosaic `world_seed`/RNG anchoring, pose, ledger, and the
  generation counter snapshotted bit-exact).
- **Loopback TCP hardened per NM-6 option (b)** (chosen over (a) "Unix socket behind a local
  broker" — a broker must itself speak TCP to Godot, which only relocates the exposed port while
  adding a process): bind `127.0.0.1` on an ephemeral port; at startup the runtime mints a random
  per-session token and writes `{port, token}` to a **0600 token file** (the S-09 umask discipline,
  `process.py:521-528`, applied to a file instead of a socket node — so the OS owner boundary is
  preserved: only the same user can read the token); the first client frame must present the token;
  the **SERVER assigns the session role** (the authenticated Godot session gets `drive`); any
  client-supplied `role` field is ignored and a wrong/missing token closes the connection.
  Unauthenticated processes that can reach 127.0.0.1 hold no token and get nothing. The existing
  `RuntimeProcess` Unix seam is untouched for Python clients.
- **Flow control carried from v2 unchanged:** `(protocol_version, seq, timestamp)` on every frame;
  bounded un-acked window with refuse+count backpressure; cumulative ACK as heartbeat; deadman →
  zero-twist safe-stop (`stream.py:1-13` discipline, now actually driven — above).

#### (b.4) Terrain to Godot: generation manifests with union-coverage + keyframes (NB-1, M-5)

v2's "skip to the newest complete generation, drop stale" was verified UNSAFE: each manifest
carried only its own dirty bbox, and one drive step's edits are up to four disjoint wheel-disc
regions (`rover.py:211-227`); dropping an intermediate generation dropped its regions from the
display forever. The v3 protocol (merging both council options — union-coalescing AND keyframes):

- **Patches carry absolute field values** (rf32/r8 crops), never additive deltas — so applying a
  region twice is idempotent and superset coverage is always safe.
- **Union coverage invariant:** the runtime tracks the consumer's last ACKED generation; every
  manifest for generation N covers the **union of all dirty regions in (last_acked, N]** (as one
  bbox or a small list of crop rects — implementation-time detail per the convergence bar). Godot
  may then safely apply ONLY the newest complete generation: its coverage includes everything the
  client has not acknowledged. Stale manifests are dropped without loss **by construction**.
- **Keyframes:** a periodic full-window keyframe manifest (every K generations, K a build-time
  knob), and ALWAYS a keyframe on `recenter` (the window origin moved — carried from v2) and on
  session (re)connect. A client that missed everything resyncs from the newest keyframe + newer
  patch manifests.
- Manifest atomicity, digests, write-order (manifest LAST, tmp+rename), ALL changed fields
  (height, density, state_label, disturbance every drive step; + mass_areal on dig; + diff field
  from E2), and generation-ACK on the command channel: all carried from v2 unchanged.

#### (b.5) NEW — the live render-geometry contract (NB-2)

Verified (§0.1): the frozen loader's fine mesh bakes heights on the CPU (`terrain.gd:136,160`) and
its shader displaces nothing (`terrain.gdshader:4-8,139-142`) — a live height texture under that
mesh renders as a static surface. viz2 therefore owns its own moving-window geometry, modeled on
the in-tree far-field precedent (`terrain_farfield.gdshader:1-20`: PlaneMesh + vertex-shader
displacement from a height texture — the mechanism already ships, just at decimated scale):

- **`viz2_terrain_window.gd` + `viz2_window.gdshader` (both NEW, viz2-owned):** one PlaneMesh
  sized to the active window's world footprint, whose **vertex shader displaces from the live
  window height texture** (FORMAT_RF `Image` → `ImageTexture`, updated in place per applied
  generation via `Image.blit_rect` + `ImageTexture.update`; *in-place-update inference stays
  B3-gated, unchanged from v2*). Fragment stage samples the live density/state/disturbance window
  textures with the same appearance conventions as `terrain.gdshader` (new shader file; the frozen
  one is not edited). Normals recomputed in-shader from height-texture central differences (the
  farfield pattern).
- **Explicit coordinate mapping (base ↔ fine ↔ window ↔ mesh), the NB-2 contract:**
  1. **Base grid:** bundle raster (2000² @ `base_cell_m` = 1.0 m); base cell `(br,bc)` → global
     metres `(x0 + bc·1.0, y0 + br·1.0)`, origin = `world_bounds_m` min corner (GW-12, frozen).
  2. **Fine window:** `WorkSite` streaming window — `(2·radius_tiles+1)·tile_base_cells` base
     cells per side × `k = base_cell_m/fine_cell_m` fine cells (240² @ 5 cm, 600² @ 2 cm);
     window fine cell `(fr,fc)` → global metres via `window_world_origin + (fc,fr)·fine_cell_m`
     (`worksite.py:433-435`, inverse `active_rc_for_xy` `:441-447`).
  3. **Window texture:** texel `(fr,fc)` ↔ fine cell `(fr,fc)` 1:1; every manifest carries
     `window_world_origin` + `bbox_rc` so the client places crops absolutely (carried from v2).
  4. **Mesh:** the window PlaneMesh spans `[window_world_origin, +side_m]²` in the Godot local
     frame (= global metres minus the scene's declared local origin, GW-12); mesh UV `(0..1)` maps
     linearly to window texel coords; vertex budget = one vertex per fine cell up to 600²
     (361k verts — well inside the RTX 3090 envelope; a fixed-budget decimation knob is named for
     the build). On a `recenter` keyframe the node repositions to the new
     `window_world_origin` and the textures reload whole.
  5. **Context terrain:** the surrounding unworked bundle renders via the viz2 root's own
     far-context plane using the existing farfield shader pattern, seeded once from the bundle by
     READING through the frozen loader (`state_fields.gd` used as a read-only library — not
     edited). The window mesh overdraws the context plane inside its footprint; the edge seam is
     accepted and honestly visible (the physics window boundary is a real thing; hiding it would
     misrepresent where live physics ends). Frozen `terrain.gd`/`terrain.gdshader` are NOT
     instantiated by viz2.

#### (b.6) The Chrono advisory lane is buildable NOW (NM-9 re-scope)

Round 1 filed B5 as blocked on a PyChrono env. **Wrong, and now twice-confirmed:** the
`~/micromamba/envs/chrono` env imports `pychrono` + `pychrono.vehicle.SCMTerrain` (run by me this
session, §0.6), and `scripts/chrono_scm_export.py` / `scripts/chrono_clast_producer.py` are
committed. The main `.venv` has no pychrono (and PyPI `pychrono` is a typosquat — never
pip-install), so the lane is a **subprocess/IPC bridge**:

- A small advisory service script runs under `~/micromamba/envs/chrono/bin/python3` speaking
  JSON-lines over stdin/stdout (the `RuntimeProcess` bounded-line discipline); the viz2 runtime
  spawns it at startup when the env probe succeeds.
- A `Tier2ChronoAdvisoryBackend` implements the six pure protocol members —
  `info()` returns `authority_class="advisory"`, `conserves_mass() → False`; the point-eval members
  (`wheel_static_sinkage` etc.) proxy over the bridge to SCM (`chrono_scm_export.py`'s
  SCMTerrain machinery, §4.1/§4.2 field mapping). Registered into `_BACKENDS` as `tier2_chrono`
  (the id the ledger row `tier3_chrono@0.0` already names, `physics_model_control.py:88-89`)
  **only when the env probe succeeds** — no stub registration.
- Governance is unchanged and now exercised for real: the ledger row stays `validated=False`, so
  `resolve_live_backend` refuses it at gate step 1, and even a hypothetical validated row would be
  refused at the conservation gate (`:138-144`) — B4's monkeypatched fake-backend test proves the
  gate logic; B5's REAL advisory backend then exercises the same refusal against live code.
- **What stays BLOCKED — and on WHAT:** Chrono as a CONSERVING release-authority backend (PX-03)
  is blocked on **conservation validation**, not environment: SCM structurally does not conserve or
  expose areal mass (`chrono_scm_export.py:20-27` — mass_areal/density stay surrogate-side by
  design). Until a hybrid producer closes that loop AND validates conservation, `tier3_chrono@0.0`
  stays `validated=False` and mutation-refused.

### (c) Coordinate frames — UNCHANGED (converged; carried from v2 verbatim)

GW-12 contract adopted wholesale; Godot local origin = bundle `world_bounds_m` min corner; float32
ULP budget verified; sun convention `Vector3(−elev, azim, 0)`. See v2 §2c.

### (d) Where the GPU rendering runs — UNCHANGED (carried from v2)

Host GPU on the archimedes RTX 3090 (windowed, or xvfb+Vulkan headless-verify); NOT Docker; euclid
= second headless render host or local session only. Python runtime CPU-only, same host.

---

## §3 Phased, atomic task list

Verification discipline unchanged: each task ends with a REAL observation; the full suite gate is
`pytest` over `lode/ leap/ dart/ forge/ stewie/` parsed by **exit code** (standing rule), plus the
Godot headless-verify captures. Tasks marked **BLOCKED** are honestly blocked (§4) with the blocking
condition named. Phase order carried from v2 (A → B keystone → C∥ → D → E → F → G).

### Phase A — 1 m Haworth site + viz2 scene renders it + drive input

| Task | Change | File(s) | Verification |
|---|---|---|---|
| A1 | PIL `Image.MAX_IMAGE_PIXELS` guard (explicit, bounded, comment naming the 140.6 Mpx SfS file) in the ingest lane | `dart/dem_import.py` | Unit test: `load_lola_geotiff` on the real SfS tif returns (11660,12060) float32 with the verified affine, no DecompressionBombWarning |
| **A2 (AMENDED, R-M7)** | SfS-correct ingest as in v2 (`--source-id` / `--citation-mode from-source` / `--center`), **now implementable**: A3a first adds the `citation` field the derivation reads. Provenance strings derive from the named `DemSource` row + its new `citation`; `--center` bypasses `find_max_relief_window`; defaults unchanged → every existing LOLA bundle regenerates byte-identically | `scripts/build_from_dem.py` (additive args) | (1) Regression: rebuild `haworth_10km_5m` with defaults → metadata.json deep-equal to committed. (2) New-path test: emitted `dem_provenance.source/citation` string-match the registry row's fields (incl. Alexandrov & Beyer 2018) and `world_bounds_m` ⊂ the verified SfS bounds |
| **A3a (NEW, R-M7)** | **Add `citation: str = ""` to the `DemSource` dataclass** (additive, default-empty → all existing rows and their tests unaffected) and populate the `lroc_nac_sfs_1m` row: USGS Astrogeology LRO NAC photoclinometry (SfS) DEM 1 m product citation + Alexandrov & Beyer 2018 (method). Optionally backfill the bundled-5 m rows with Barker/Mazarico (additive, no behavior change) | `dart/dem_sources.py:24-38,167-174` | Existing registry gates green by exit code (`dart/test_dem_sources.py`, `stewie/server/test_dem_sources_registry.py`); new assert: the SfS row's `citation` contains "Alexandrov" and the USGS product name |
| A2b | Build the 1 m bundle (2000² @ 1.0 m) with `--source-id lroc_nac_sfs_1m --center …` | new bundle dir | Script self-verify + `world_bounds_m` ⊂ SfS bounds (carried from v2) |
| A3 | Register the site (`sites.py` + `DemSource(bundled=True)` note) | two registries | Existing site/registry/GW-12 gates green by exit code (carried from v2) |
| A4 | viz2 scene skeleton: `viz2.tscn` + `viz2_root.gd` — seeds context terrain by READING the bundle via the frozen loader, instantiates the §2b.5 window-mesh node + the EZ-RASSOR rig; `viz2.sh` launcher | new files under `stewie/godot/` only | Headless verify capture; human eyeball: real 1 m relief + rover visible |
| A5 | Input: InputMap actions (WASD + gamepad) | `project.godot`, `viz2_root.gd` | On-host interactive gamepad run (named operator check); headless action-injection *(inferred; A5 confirms first)* |
| A6 | Fix the stale postures path in the EXISTING drive_controller (adjacent one-line bug, round-1 non-finding) | `stewie/godot/drive_controller.gd:51` | `--drive-auto` run prints posture load success |

### Phase B — the conserved-terrain session actor (AMENDED: NB-1/2/3, NM-4/5/6/7, R-M3/BL1, Opus minors)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| **B1 (AMENDED, NM-7)** | Additive `WorkSite.step(v_cmd, omega_cmd, dt)` as in v2 (per-tick conserved drive; recenter near window edge; `payload_kg=self.inventory_kg`; telemetry + dirty regions) **plus boundary/displacement safety**: (i) pose clamped to `world_bounds_m` minus a wheelbase margin, with a `bounds_clamped` telemetry flag; (ii) `recenter` validates the target tile set non-empty and raises a TYPED refusal on OOB (replacing the verified bare-`ValueError` crash path, `worksite.py:404-409` — additive guard before the region assembly); (iii) max per-tick displacement bound: non-finite/`|v|>v_max`/`|ω|>ω_max` commands refused (the `process.py:471-476` M-04 pattern), so one tick can never teleport the footprint out of the window; (iv) the recenter margin guarantees the 4-wheel footprint stays interior (empty `_wheel_mask` = silent physics loss, `rover.py:44-49,211-217` — must be unreachable) | `stewie/physics/worksite.py` (additive) | `[REQ:]` test on the real 1 m bundle: v2's three clauses (step==drive_step byte-identical; datum verified pre-first-step; residual <1e-6·baseline across a recenter) **plus**: drive INTO the site boundary → pose clamps + flag set + no crash + wheels still carve (non-empty masks asserted); `recenter((x,y))` fully outside the site → typed refusal, session state unchanged; a `v` exceeding `v_max` → refused, pose unmoved |
| **B1b (NEW, NM-4)** | **Bounded worked store**: LRU resident set of worked tiles (`worked_resident_tiles = 64` default) with page-to-disk eviction (`.npz` per tile under the existing `page_dir` convention, `worksite.py:127-128`, mirroring `TileMosaic`'s discipline `tiles_mosaic.py:16-27`); an in-memory per-tile index `{(tr,tc): (grid_mass_kg, path)}` keeps `total_mass()`/`conservation_residual()` exact and O(resident) without reloading pages; `recenter` loads worked tiles from RAM or page transparently. **Resident-set budget stated in-code**: ≤ ~100 MB RAM at 2 cm fine (window ~12 MB + 64 tiles ~84 MB + index); disk grows only with terrain actually worked (~33 B/touched fine cell) | `stewie/physics/worksite.py` (additive; no frozen seam) | `[REQ:]` test: work >64 tiles' area on the real bundle → `len(resident worked tiles) ≤ 64` while `conservation_residual()` stays <1e-6·baseline (paged mass still counted); re-enter a paged tile → its worked state returns byte-identical (npz round-trip); RSS sanity: process RSS delta over the run < the stated budget (measured via `resource.getrusage`, printed + asserted with headroom) |
| **B2 (AMENDED, NB-3 + NM-6 + Opus minor)** | **`Viz2Runtime` as a fixed-rate ACTOR LOOP** (§2b.3): one physics thread = the sole mutator (drain mailbox → latest-twist → `ws.step()` → write generation → `StreamSession.tick(monotonic())` → safe-stop on trip); socket side only enqueues/snapshots. Transport = loopback TCP `127.0.0.1` + **0600 token file + server-assigned role** (client `role` ignored; bad token = disconnect). Reuses `RuntimeProcess` DISCIPLINES (bounded lines, M-04 input bounds, readiness handshake, validate-then-swap restore) as patterns, not as a subclass — the actor loop, StreamSession wiring, and TCP handshake are named NET-NEW. Mandatory bounded physics window (240² default / 600² gated) carried from v2. Confirm `StreamPeerTCP` client viability first (the standing Godot-API gate) | `stewie/runtime/viz2_runtime.py` (new) | Pytest over a real socket: (1) v2's physics clauses (slip on slope, entrapment, mass conserved); (2) **deadman without traffic**: connect, send one twist, then SILENCE → within `ack_deadline_s` the runtime zeroes the twist and telemetry shows the safe-stop (proves the tick driver runs independent of inbound reads — the NB-3 gate); (3) **auth**: a tokenless local connection is refused before any command; a client-supplied `role:"drive"` without the token is refused; the token file mode is 0600 (stat asserted); (4) flood → backpressure refuses + counts; (5) command→**telemetry** p95 at the window size (intermediate smoke gate; the BINDING end-to-end gate is B3/B6 per R-BL1) |
| **B2b (NEW, Opus minor)** | **Checkpoint/restore of the STREAMING WorkSite**: extend the A-01 validate-on-fresh-then-swap transaction (`process.py:440-464`) to snapshot fine window + worked-store pages **and index** + `inventory_kg` + both baselines (`_baseline_virgin_kg`, `_baseline_mass`) + mosaic `world_seed` + pose/yaw + generation counter + cumulative moved-mass counters (E1) — bit-exact | `stewie/runtime/viz2_runtime.py` | `[REQ:]` test: drive+dig across ≥2 recenters (worked store partly paged) → checkpoint → kill → restore → `total_mass()`, `conservation_residual()`, pose, generation, and a full field digest of the active window all byte-equal; a corrupted checkpoint → refused, live session untouched (the A-01 property) |
| **B3 (AMENDED, NB-1 + NB-2 + R-BL1)** | **Patch protocol with union coverage + keyframes** (§2b.4): absolute-value crops; every manifest covers the dirty UNION since the consumer's last ACK; periodic keyframes + keyframe on recenter/connect; manifest-last atomic write + digests carried from v2. **Render side** (§2b.5): NEW `viz2_terrain_window.gd` + `viz2_window.gdshader` — moving-window PlaneMesh, VERTEX-shader displacement from the live height texture (the `terrain_farfield.gdshader:1-20` mechanism at fine scale), fragment appearance mirroring `terrain.gdshader` conventions in a new file; explicit base↔fine↔window↔mesh mapping implemented as specced; frozen loader used read-only for seeding; `viz2_drive_client.gd` — StreamPeerTCP + token handshake, 15 Hz commands, pose interpolation (~66 ms budget on HUD, carried) | new Godot files + runtime patch writer | (1) Pytest: torn write → generation refused whole; **disjoint-edit safety (the NB-1 gate)**: two steps editing DISJOINT regions, client deliberately skips the intermediate manifest → applying only the newest yields field textures byte-equal to the authority (union coverage proved); missed-everything client resyncs from keyframe alone. (2) Headless `--auto` drive: a rut is **visibly carved in the falsecolor capture** (proves vertices actually displaced from the live texture — the NB-2 gate: v2's design would have shown a static surface here), density+disturbance patches changed, final pose matches runtime (<1 cell). (3) **End-to-end command→APPLIED-RENDER p95 gate (R-BL1)**: client timestamps command-send → generation-applied; p95 < the 15 Hz budget with render margin stated — this, not B2's telemetry gate, is the gate the 600²/2 cm scope decision (§3 scope block) hangs on |
| **B4 (AMENDED, R-M3)** | Fail-closed backend governance: HUD picker lists `MODELS` ledger rows; the session's mutation authority resolves **ONLY through `resolve_live_backend`** (`physics_model_control.py:119-151`) — `select_backend` removed from the mutation path (strict only in LIVE, `:154-165`); swaps between acked generations after `conservation_residual()` + digest checks; `tier3_chrono@0.0` greyed/read-only; HUD shows the ledger `calibration` STRING as governance metadata (labeled advisory — NM-5), soil params attributed to `resolve_soil_params(body)` | runtime + HUD | v2's 4 clauses (unknown id → `ValueError`; `tier3_chrono@0.0` → `PhysicsModelRefused`; monkeypatched registered-fake-non-conserving backend refused at the conservation gate `:138-144`; same-model re-resolve is a generation-boundary no-op) **plus**: a call-graph/static assert that the runtime module never references `select_backend` |
| **B5 (RE-SCOPED, NM-9 — BUILDABLE NOW)** | **Chrono ADVISORY lane via subprocess/IPC bridge** (§2b.6): advisory service under `~/micromamba/envs/chrono/bin/python3` (env verified live this session — pychrono + `SCMTerrain` import OK) speaking bounded JSON-lines; `Tier2ChronoAdvisoryBackend` proxying the six pure protocol members, `authority_class="advisory"`, `conserves_mass()=False`, registered as `tier2_chrono` only when the env probe succeeds (no stub registration); HUD renders advisory point-evals beside the authority's, tagged. Mutation stays governance-refused (ledger `validated=False`) | new bridge script + `stewie/physics/backend.py` (additive registration) + runtime/HUD | `[REQ:]` tests RUN on this host (env present — not skipped): bridge round-trip sinkage matches a direct in-chrono-env computation of the same case; `resolve_live_backend("tier3_chrono@0.0")` still raises `PhysicsModelRefused` with the advisory backend REGISTERED (the real-code twin of B4's fake-backend proof); env-absent CI runners skip LOUDLY with the reason printed. Capture: advisory numbers visible beside authority numbers, tagged "advisory" |
| **B6 (AMENDED)** | End-to-end soak: real socket + real headless Godot client, N minutes drive+dig — now also covering: deliberate manifest drops (client recovers via union/keyframe, final texture == authority), a deadman trip + recovery mid-soak, B2b checkpoint/restore leg, **applied-render p95** (R-BL1) + bounded backlog asserted | test only | Pytest exit code; recorded applied-render p95 + max backlog + post-restore digest equality printed and asserted |

### Phase C — Live sun sliders (carried from v2 unchanged)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| C1 | HUD azimuth/elevation sliders driving the DirectionalLight; grazing-band annotation. Depends only on A | `viz2_hud.gd` | Interactive sweep; two headless captures at (215°,5°) vs (35°,5°) — shadow direction flips |
| C2 | Godot shadow mask vs `dart.illumination` horizon-march mask IoU gate on the real 1 m crop | runtime + `[REQ:]` test | Pytest: IoU above stated threshold at grazing sun |
| C3 | Preserve the scripted sweep (reuse `SunSweep.run_sun_sweep`) | none | Existing sun_sweep manifest run green on the new scene |

### Phase D — Rock dispersion from real statistics (carried from v2 unchanged)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| D1 | Spatial-k Golombek field over the real DEM (`[CALIB]` honesty tag in manifest) | `stewie/terrain/rockfield.py` (new) | v2's 4 clauses (F_k(D) recovery, determinism, envelope, tag) |
| D2 | Pre-dig rock-field DISPLAY (clasts + k-drape + real-count histogram) | `viz2_root.gd`, HUD, window node | v2's capture + numeric-equality clauses |
| D3 | h/d realism + [UNKNOWN] buried_frac provenance | manifest fields | Citation + tag asserted verbatim |
| D4 | Thread clasts into `WorkSite.step` → `drive_step(clasts=…)` | runtime | Capture + telemetry: >wheel-radius rock blocks/rides per `conform_pose` |
| D5 | Haworth-local measured calibration — **BLOCKED** (§4 item 2: needs a real Haworth-area NAC ortho on disk); fallback = D1's `[CALIB]` envelope, stated in-task | `benchmarks/nac_shadow/` reuse | Only activates with the real ortho on disk; skip-clean with reason printed |

### Phase E — Dig + before/after difference drape (E1/E3 AMENDED, NM-8)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| **E1 (AMENDED)** | Dig interaction as in v2 (dig/dump → `WorkSite.flatten/.dump`, same actor + generation stream; energy debits on HUD) **plus additive cumulative moved-mass counters** `cut_total_kg` / `placed_total_kg` incremented inside `flatten`/`dump` (the residual `inventory_kg` ledger is NOT a moved-mass record — verified §0.5) | runtime + HUD + `worksite.py` (two additive counters) | Pytest: dig N kg → `conservation_residual()` holds; `cut_total_kg` grows by exactly the moved mass while `inventory_kg` returns to ~0 after the dump (the two quantities proven distinct); HUD energy decreases by the grounded J/kg |
| E2 | Signed diff h_now − h_virgin (deterministic per-tile virgin regen `worksite.py:344-358`), streamed as a patch field; `falsecolor_diff.gdshader` on the viz2 window node | new shader + window-node wiring | Capture after scripted dig+dump: cut negative, berm positive; max cut depth in texture == authority value at the same cell |
| **E3 (REWRITTEN, NM-8)** | Evidence tie-in via the REAL contract: on session end, build before = deterministic virgin surface over the worked region (E2's regen), after = as-built surface, and emit **`RegolithVolumeEstimate.from_delta(before, after, cell_m, …, conserved_mass_kg=cut_total_kg + placed-adjusted moved mass)`** (`leap/volume_evidence.py:15,26-35` shape) — the drum-residual `inventory_kg` equality claim is dropped; server-up: register the run so LY-07 `changed_terrain` + `/world/point` show the same dig | runtime | Pytest: the estimate's terrain-delta mass agrees with the CUMULATIVE moved-mass counters within the contract tolerance (self-check, the `from_delta` cross-check field); cross-surface: `/world/point` depth == Godot diff texture at the same cell |

### Phase F — Path/traversability analysis (carried from v2 unchanged)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| F1 | `rock_hazard` costmap layer (h = 2r(1−buried_frac) vs `OBSTACLE_HEIGHT_M`) | `lode/costmap_layers.py` (additive) | 0.3 m rock blocks with reason; 0.05 m costs-but-passes; existing gate unchanged-green |
| F2 | Plan over it; 4-clause routes-around proof (corridor blocked / path clean / real detour / removal control) | runtime glue + `viz2_path.gd` | The v2 4-clause `[REQ:]` test + detour capture |
| F3 | Live what-if: replan over the as-built surface | runtime | Dig a trench across the old path → replan detours (same 4-clause pattern) |

### Phase G — Cross-site DEM compare (carried from v2 unchanged; G4 consumes A3a's citation field)

| Task | Change | File(s) | Verification |
|---|---|---|---|
| G1 | Site switcher over every bundled site | `viz2_root.gd` | 3 spot-checked sites match `metadata.json height_range_m` |
| G2a | Re-crop the on-host raw 5 m Haworth source over the SfS window (LOLA provenance, correct by default) → `haworth_5m_over_sfs` (overlap live-confirmed in round 2 — no longer inferred) | one `build_from_dem.py` run + registry rows | Bundle self-verify + explicit bounds-overlap assert |
| G2b | Cross-site comparison producer + 1 m-vs-5 m residual exhibit vs published error budgets | `dart/dem_site_compare.py` (new) + router + panel | v2's clauses (table == on-disk bundles; residual only where footprints overlap; stats vs error budgets) |
| G3 | Companion uncertainty layers — **BLOCKED** (§4 item 1: PGDA companion rasters not on disk; explicit download go required) | ingest + metadata | No partial build |
| G4 | "About this DEM" pane reads bundle `dem_provenance.citation` verbatim (now sourced from A3a's registry field via A2) | small generator script | Rendered pane text == metadata citation strings |

### Resolution scope (carried from v2, one gate re-pointed)

First cut = 2 km @ 1 m base (2000²); 10 km @ 1 m deferred to the TileMosaic base-reader lane; 2 cm
fine wired via WorkSite `fine_cell_m=0.02` (600² window), gated by contract §7 `coarsen(fine)==base`
acceptance at a 1 m base **plus the B3/B6 end-to-end command→applied-render p95 gate (R-BL1 — no
longer the B2 telemetry gate)**. Until both pass, viz2 ships at 5 cm fine (240², measured-safe) —
an honest intermediate, not a stub.

---

## §4 Real-data + provenance inventory

**On disk, verified:** carried from v2 §4 verbatim (SfS tif twins, 11 curated bundles, PGDA tiles,
raw 5 m sources, LOLA global, NAC shadow fixtures, EZ-RASSOR meshes, tagged constants). One
**addition, verified this session:** the PyChrono host env `~/micromamba/envs/chrono`
(pychrono + `pychrono.vehicle.SCMTerrain` import OK — run by me, §0.6) + committed
`scripts/chrono_scm_export.py` / `chrono_clast_producer.py`.

**MISSING — BLOCKED items (each with the blocking condition named):**

1. **Haworth companion uncertainty rasters** (`_toterr/_ldec/_slperr.tif`) — not on disk. **G3
   BLOCKED** on the PGDA Product-78 companion downloads (no download without an explicit go).
2. **A NAC ortho covering the Haworth work area** for measured local boulder density. **D5
   BLOCKED** on that real data; the rockfield ships honestly `[CALIB]` (D1) until then.
3. **Chrono as a CONSERVING release-authority backend (PX-03)** — **re-scoped (NM-9): this is the
   ONLY Chrono item still blocked, and it is blocked on CONSERVATION VALIDATION, not environment.**
   SCM structurally does not conserve/expose areal mass (`chrono_scm_export.py:20-27`); until a
   hybrid producer closes the mass loop and validates conservation against the Tier-2 invariants,
   `tier3_chrono@0.0` stays `validated=False` and mutation-refused. The **advisory** Chrono lane is
   NOT blocked — B5 builds it now on the verified env (item above).
4. ~~Overlap pair for the 1 m-vs-5 m residual~~ — UNBLOCKED into G2a (round 2 live-confirmed the
   footprint overlap; the confirm-or-stop guard stays in the task as a regression tripwire).

---

## §5 Research-paper summary — UNCHANGED (converged; carried from v2 verbatim)

The DEM product table and rock-SFD literature list stand as in v2 §5 (Barker 2021/2023/2016,
Alexandrov & Beyer 2018, Bertone-Barker-Mazarico, Smith 2010; Golombek, Bandfield, Demidov &
Basilevsky, etc.; Cintala-absent honesty note). v3 addition: Alexandrov & Beyer 2018 now also
lands in the machine-readable registry as the `lroc_nac_sfs_1m` `citation` field (A3a), which A2
derives and G4 renders.

---

## §6 Risks / explicitly deferred

**Risks**

1. **Per-step whole-grid cost** (carried from v2): mitigation structural (bounded WorkSite window,
   240²/600²), now gated by the **end-to-end applied-render p95** (B3/B6, R-BL1), not
   command→telemetry alone.
2. **2 cm fine at a 1 m base** (carried): contract §7 `coarsen(fine)==base` acceptance at 1 m +
   the R-BL1 gate before trusting the visuals.
3. **SfS DEM veracity at rock scale** (carried): D-phase rocks are STATISTICAL, never read off the
   DEM.
4. **Two copies of the 562 MB SfS tif** (carried): `code/datasets/…` canonical; twin name-and-left.
5. **GDScript kinematic drive remains** beside viz2 (carried): authority labeled on both HUDs.
6. **WorkSite G1 cross-seam gap** (carried): size `radius_tiles` so each dig+dump stays inside one
   window; B1 drives across a boundary deliberately.
7. **Godot editor-vs-headless input** (carried): A5 named operator check.
8. **Display latency of pose interpolation** (carried): ~66 ms budget on HUD; interp over
   extrapolation (entrapment v→0 discontinuity); asserted in B6.
9. **NEW — worked-store paging + checkpoint volume:** disk (not RAM) now carries the worked set
   (B1b), so a long mission grows `page_dir` by ~33 B/touched fine cell, and B2b checkpoints
   reference the paged store. Budget printed per soak run; if a mission profile ever approaches the
   full-area worst case (49 GiB @ 5 cm), the stated fallback is capping the workable area per
   session — a refusal, not silent degradation.
10. **NEW — window-edge seam:** the viz2 window mesh meets the coarse context plane at the physics
    window boundary; the seam is real and rendered honestly (§2b.5). If it proves visually
    disruptive, a skirt strip is the named knob (build-time detail).
11. **NEW — token-file locality:** the 0600 token file gates same-user processes only (the same
    boundary the Unix socket had); multi-user hosts would need a real broker — out of scope,
    named here so it isn't re-litigated.

**Explicitly deferred (not in scope)**

- **Chrono as CONSERVING release authority (PX-03)** — blocked on conservation validation (§4
  item 3). The advisory lane ships in B5.
- ROS2/Gazebo lowering of the viz2 loop — the flow-control discipline mirrors `stream.py` so the
  lowering stays mechanical (carried).
- Whole-tile 10 km @ 1 m base — TileMosaic base-reader streaming lane (carried).
- Multi-rover / fleet — single-vehicle first (carried).
- QWC2 /ide embedding of viz2 — /ide keeps GW-11; viz2 stays native (carried).
- DM1/LM7 downloads — tracked in `STEWIE_more_DEMs_plan_2026-07-09.md` §5.2 (carried).

---

## §7 Changes from v1 (council round 1) — CARRIED

The full v2 §7 amendment table stands unchanged (consensus unifying fix; BLOCKER-1/2; M-3..M-8e;
minors). It is not reproduced here — see v2 §7. Round-2 scoring of those amendments: Opus
CONVERGED on BLOCKER-2/M-4/M-5/M-6; Sonnet on M-7/M-8a-e; Codex downgraded M-5 to PARTIAL via
NB-1 and BLOCKER-1's gate via R-BL1 — both re-resolved below.

---

## §8 Changes from v2 (council round 2)

| Amendment | What changed in v3 | Evidence (opened/run this session unless noted) |
|---|---|---|
| **NB-1** (patch coalescing not atomic state delivery) | §2b.4 + B3 rewritten: patches are ABSOLUTE-value crops (idempotent, superset-safe); every manifest covers the dirty UNION since the consumer's last ACK, so newest-complete-only application is lossless by construction; periodic keyframes + keyframe on recenter/connect for cold resync. Latest-only-drop of self-bbox-only manifests is gone. B3 gains the disjoint-edit skip test (skipped intermediate manifest → final textures byte-equal to authority) | `rover.py:211-227` (per-wheel disjoint disc stamping — one step's dirty area is up to 4 disjoint regions) |
| **NB-2** (live render geometry contract missing) | NEW §2b.5: viz2-owned `viz2_terrain_window.gd` + `viz2_window.gdshader` — moving-window PlaneMesh whose VERTEX shader displaces from the live height texture (the shipped far-field mechanism at fine scale); explicit 5-step base↔fine↔window↔mesh mapping; frozen loader used read-only; frozen `terrain.gd`/`terrain.gdshader` never instantiated by viz2. B3's headless gate now PROVES displacement (a carved rut visible in the capture — v2's design would have rendered a static surface there) | `terrain.gd:136,160` (CPU-baked vertex heights), `terrain.gdshader:4-8,139-142` (vertex stage forwards UV only), `state_fields.gd:142-146,167-180` (load-once rasters); precedent `terrain_farfield.gdshader:1-20` + `terrain.gd:63-68` (vertex displace from height texture EXISTS in-tree) |
| **NB-3** (deadman has no driver) | §2b.3 + B2 rewritten: `Viz2Runtime` is a fixed-rate ACTOR LOOP — the physics thread is the sole mutator and drives `StreamSession.tick(monotonic())` every iteration; socket I/O only enqueues; safe-stop zeroes the twist in the loop thread. B2's gate: silence after one twist → deadman trips with NO inbound traffic. (Nuance verified: `serve_forever(poll_interval)`'s `service_actions` hook can't substitute — it never runs while a handler blocks in `readline`) | `stream.py:60-69` (tick caller-driven, pure/clockless header `:7-9`), `process.py:510` (blocking `readline`), `:538` (`serve_forever(poll_interval=0.05)`) |
| **NM-4** (`worked_store` unbounded) | §2b.1 addition + NEW task B1b: LRU resident set (default 64 tiles) + page-to-disk mirroring `TileMosaic`, per-tile mass index keeps conservation O(resident); resident budget STATED (~100 MB worst case @ 2 cm) + RSS-asserted in the test; §6 Risk-9 names the disk-growth fallback (cap workable area, a refusal). Arithmetic reproduced: 33 B/cell → 49.2 GiB @5 cm / 307.5 GiB @2 cm full-area | `worksite.py:146-147,363-375,449-453`; `tiles_mosaic.py:16-27` (the bounded pattern); `worksite.py:127-128` (page_dir already threaded) |
| **NM-5** (calibration doesn't reach `drive_step`) | Claim DROPPED, seam named (§2b.2): soil params come from the resolved backend's `resolve_soil_params(body)` + drive_step's per-cell material overrides; the ledger `calibration` string is HUD-labeled advisory governance metadata; a future per-version param set would enter via the existing `drive_step(params=…)` seam — none exists today, so no calibration-swap claim. B4 verification updated to match | `physics_model_control.py:44-47` (calibration = status string), `backend.py:39-40` (body-based resolver), `drive.py:181-215` (params seam + material path) |
| **NM-6** (loopback TCP removes the security boundary) | §2b.3 + B2: option (b) chosen — 127.0.0.1 + per-session random token in a 0600 file (the S-09 umask discipline applied to a file) + SERVER-assigned role; client `role` ignored; bad/missing token disconnects. Option (a) broker rejected with reason (the broker must itself expose TCP to Godot — relocates, doesn't remove, the port). The existing Unix seam untouched for Python clients. §6 Risk-11 names the same-user-only boundary honestly | `process.py:466-470` (caller-trusted role), `:521-528` (owner-0600 Unix socket = the boundary being lost) |
| **NM-7** (no boundary/displacement safety) | B1 gains 4 safety clauses: pose clamp to bounds + telemetry flag; typed OOB-recenter refusal (replacing a verified CRASH path); M-04-pattern per-tick displacement bounds; footprint-interior guarantee. Two mechanism corrections logged (below) | `worksite.py:397-409` (OOB recenter → `ValueError` from `min()` over empty regions — a crash), `rover.py:44-49,211-217` (off-grid pose → EMPTY mask → silent physics loss, not an index error), `process.py:471-476` (the M-04 bound pattern reused) |
| **NM-8** (E3's mass check wrong) | E1 adds additive cumulative counters (`cut_total_kg`/`placed_total_kg`) proven distinct from the residual `inventory_kg` in-test; E3 rewritten onto `RegolithVolumeEstimate.from_delta(before, after, …, conserved_mass_kg=cumulative)` with before = deterministic virgin regen, after = as-built. The ledger-equality claim is gone | `worksite.py:257-268` (`dump` decrements the residual ledger), `volume_evidence.py:1-6,15,26-35` (the from_delta + conserved-mass-cross-check contract) |
| **NM-9** (B5 mislabeled blocked) | B5 RE-SCOPED buildable-NOW (§2b.6): subprocess/IPC bridge from the pychrono-less `.venv` to the verified chrono env; real `Tier2ChronoAdvisoryBackend` (advisory, non-conserving) registered `tier2_chrono` only on a successful env probe; tests RUN on this host, skip loudly elsewhere. ONLY PX-03 (conserving release authority) stays blocked — on conservation VALIDATION (SCM structurally lacks areal-mass conservation), not env. §4 item 3 rewritten accordingly | Run this session: `~/micromamba/envs/chrono/bin/python3 -c "import pychrono, pychrono.vehicle as veh; …"` → `pychrono True SCMTerrain True`; `ls scripts/chrono_scm_export.py scripts/chrono_clast_producer.py` (present); `chrono_scm_export.py:20-27` (SCM does NOT conserve/expose areal mass) |
| **R-M3** | Mutation authority names `resolve_live_backend` exclusively; `select_backend` removed from the mutation path (verified strict only in LIVE); B4 adds a static assert that the runtime never references `select_backend` | `physics_model_control.py:119-151,154-165` |
| **R-BL1** | The BINDING latency gate is end-to-end command→APPLIED-RENDER p95, measured in the Godot client (B3) and re-asserted in the soak (B6); B2's command→telemetry p95 demoted to an intermediate smoke gate; the 600²/2 cm scope decision re-pointed at the end-to-end gate (§3 scope block) | v2:135,261-262 (the old telemetry-only gate) |
| **R-M7** | NEW task A3a: additive `citation: str = ""` on `DemSource` + populate the SfS row (USGS product + Alexandrov & Beyer 2018); A2's registry-derived-citation assertion now implementable; G4 consumes it | `dem_sources.py:24-38` (no citation field today), `:167-174` (SfS row citation-less) |
| **Opus minor: "extends" honesty** | §2b.3 restates `Viz2Runtime` as REUSING `RuntimeProcess` disciplines (bounded lines, M-04, readiness, validate-then-swap restore) with the NET-NEW parts named: actor loop + mailbox, StreamSession wiring + tick driver, TCP + token handshake, streaming checkpoint | `process.py:51,440-464,471-484,505-535` (the reused disciplines at their real lines) |
| **Opus minor: streaming checkpoint sub-task** | NEW task B2b: explicit checkpoint/restore of the streaming WorkSite (paged store + index, dual baselines, mosaic seed, pose, generation counter, moved-mass counters) — bit-exact restore test + corrupt-checkpoint refusal | `process.py:440-464` (the A-01 transaction extended), `worksite.py:146,154-158` (the state that A-01 never covered) |
| **Godot-API inferences stay gated** (Opus minor) | `StreamPeerTCP` viability + in-place `ImageTexture.update` remain explicitly *inferred*, confirmed as the FIRST act of B2/B3 respectively (carried from v2, restated) | — |
| **Converged items NOT reopened** | BLOCKER-2 (FORGE pure), M-4 (WorkSite + datum), GW-12, data grounding + citations, M-8a-e (incl. the live-confirmed G2a overlap) — carried intact per the round-2 instruction | round-2 doc "DO NOT reopen" list |

**Council findings partially rejected after code check: none rejected; two NM-7 mechanisms
corrected in the council's own direction.** (i) "Out-of-bounds `recenter()` can build an empty tile
set" understates it — the empty set then CRASHES on `min()` over empty regions
(`worksite.py:404-409`), so the typed-refusal fix is even more necessary than stated. (ii) "wheel
masks fall off-grid" (`rover.py:44,621`) is mechanically inexact — `_wheel_mask` is built from
grid-shaped aranges and cannot index off-grid; an off-grid pose instead yields an EMPTY mask and
the wheel silently stops carving/loading (`rover.py:211-217`) — silent physics degradation rather
than an access violation. Both corrections leave the NM-7 amendment (clamp + typed refusal +
displacement bound) fully in force. One design choice made where the council offered alternatives:
NM-6 option (b) (token + server-assigned role) over option (a) (broker), with the reason recorded
in §8; NB-1 resolved by MERGING the two offered options (union coverage AND keyframes), since
absolute-value crops make superset coverage free and keyframes are needed for cold resync anyway.
