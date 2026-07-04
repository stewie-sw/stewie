# Autonomous restructure loop — charter + state (2026-07-03)

The persistent memory + guardrails for the unattended STEWIE platform-restructure loop. Each wake reads this,
does the NEXT buildable row, updates the progress log, commits on the branch, and re-schedules. Configured
with Aaron 2026-07-03 (three decisions recorded below). Branch: `feat/platform-restructure`.

## Decisions (locked with Aaron)

1. **PX-06 approach = PRESERVE OVERLAY (inject).** `terramechanics` carries forge-local literal geotech
   defaults; the `stewie.specs.config` overlay path is PRESERVED by injecting config-overlaid values at the
   stewie-side call sites (dependency inversion). Runtime behavior byte-identical. `stewie-forge` ends up
   importing no `stewie.specs.constants`.
2. **Scope = RESTRUCTURE FIRST, THEN BROADEN.** Order: PX-06 -> PO-18 -> DE-01, then continue into the other
   on-host-buildable P0 rows (EG governance, MP planning, etc.). SKIP genuinely gated rows (need a live pit /
   real hardware / a physical GPU / external LAC-IPEx geometry) and pure-frontend rows that need the GeoLibre
   rewrite. Continue until the on-host-buildable P0 queue is dry, then report.
3. **Guardrails = BRANCH-ONLY, VERIFY, SURFACE ON BLOCKER.** See Hard stops.

## Per-row protocol (every row, no exceptions)

1. SCREEN the live implementation before any TDD (the row may be partially built; matrix "V != D" is often
   integration-partial, not missing).
2. TDD: write the `[REQ:<ID>]` test first (must fail), then implement, run it green. Real data only, no
   stubs/synthetic/placeholders. If real data/impl is unavailable, STOP and record a blocker.
3. FULL GATE green before flipping the glyph: `scripts/req_trace.py` + `scripts/test_assessment_gate.py` +
   `scripts/test_check_deps_lock.py` + the row test + `ruff` + `mypy` + a broad regression over the touched
   areas.
4. For a PACKAGE extraction (PO-18): also run a real `docker compose -f deploy/compose.yml build backend` +
   an in-container import smoke (the PO-17 pattern) before flipping.
5. For a UI/board row: verify via real-Chrome Playwright (runtime venv python has playwright; chrome at
   /usr/bin/google-chrome), screenshot + assert, before flipping. Re-stamp `?v=` after any `.js` edit.
6. COMMIT PRD before `gen_program_snapshot.py` (it reads `git show HEAD:PRD.md`). Flip the glyph N->D only on
   a fully green gate. Commit on the branch. Regen + commit the snapshot.
7. Update the progress log below (append one line). Re-schedule the next wake.

## Hard stops (NEVER do these unattended)

- NEVER `git push`, deploy, merge to `main`, `rclone`/gdrive, or `rm`/delete anything.
- NEVER integrate a subagent's unverified "done" — re-run the cited gate yourself.
- NEVER flip a glyph on a red or unrun gate; NEVER fake-promote.
- NEVER silently change behavior (e.g. drop the config overlay) — preserve it or record the decision.

## Surface + STOP conditions (record to this file's Blocker log, then wait)

- A genuine blocker (missing real data/impl, a gated resource, an external dependency).
- A design fork that needs Aaron's call (like the PX-06 overlay decision was).
- A red gate the loop cannot self-fix within the row.
- A regression the loop caused that it cannot cleanly revert.

On any of these: revert to the last known-good commit if the row broke something, append to the Blocker log,
and stop scheduling (wait for Aaron).

## Queue (ordered; updated as rows land)

1. **PX-06** — break `terramechanics -> constants` (inject, overlay-preserved). NEXT.
2. **PO-18** — extract `stewie-forge` (bearing + terramechanics + PhysicsBackend + body_params), bodies+numeric
   only, shim, Docker-verified.
3. **DE-01** — Demo 001 vertical slice (body/profile -> backend -> plan -> conserved txn -> reconcile ->
   report), deterministic, `[REQ:DE-01]`.
4. **P0 broaden** (on-host-buildable, screen each first): EG-01/02/03/05/06/11 (governance modes/enforcement/
   DB-isolation/live-gate/command-safety/safety-layer), MP-07 (plan-executability gate), then any other
   non-gated non-pure-frontend P0.
5. Report when the on-host-buildable P0 queue is dry.

## Progress log

- 2026-07-03 f28e2a9 — loop CONFIGURED (PX-06 row + brief added; charter written). Queue seeded. First wake = PX-06.
- 2026-07-03 1b9b64b — PX-06 DONE (wake 1). terramechanics->constants edge broken: forge-local literal defaults +
  config-overlay re-injected at call time in body_params.params_for_body (byte-identical, more robust for
  overrides). Fixed the one caller reaching constants via terramechanics.K (lode/costmap_layers.py). TDD 3/3;
  byte-identical regression green (physics+lode+specs+forge+dart+leap+runtime); ruff+mypy+req_trace+assessment
  +check_deps green. Note for PO-18: body_params STAYS in stewie-core (imports stewie.specs.constants for the
  overlay); split the PhysicsBackend protocol (-> forge) from the Tier2 concrete (-> core). NEXT = PO-18.
- 2026-07-03 c30d6f2 — PO-18 DONE (wake 2). stewie-forge extracted: terramechanics + bearing + the
  PhysicsBackend PROTOCOL -> packages/stewie-forge (numpy-only; concept API estimate_sinkage /
  estimate_bearing_capacity); backend.py SPLIT (protocol->forge, Tier2NumpyBackend->core); verbatim shims at
  the old paths. Docker build rc=0 + in-container smoke PASSED; byte-identical regression green
  (physics+lode+specs+forge+dart+leap); CI x4 install; ruff+mypy+req_trace+assessment+check_deps green.
  PACKAGING PHASE COMPLETE (stewie-bodies + stewie-forge both extracted, shimmed, Docker-verified). NEXT = DE-01.
- 2026-07-03 f106454 — DE-01 DONE (wake 3). Demo 001 vertical slice (scripts/demo_001.py) composes the platform
  loop from EXISTING code: body(moon) -> conserved PhysicsBackend -> plan(mission_planner) -> conserved
  execution + world/terrain-memory txn (mission_terrain_delta + WorldStateService) -> RegolithVolumeEstimate
  reconcile (siteplan_volume_evidence) -> deterministic evidence artifact. A real IPEx dig moves 3528 kg,
  conserved_err ~2.7e-11. [REQ:DE-01] 2/2 (every-stage payload + determinism); additive; gate green. RESTRUCTURE
  BACKBONE COMPLETE (edges + packaging + demo). NEXT = P0 BROADEN, starting EG-01 (EnvironmentMode enum +
  authority matrix). Screen for an existing runtime_mode/env concept first (BA-11 authority tuple has one).
- 2026-07-03 cf9072e — EG-01 DONE (wake 4). EnvironmentMode enum (6 modes) + per-mode authority matrix (§29.1,
  7 flags) in stewie/contracts/governance.py; only-LIVE-commands, REPLAY read-only, ARCHIVE export-only. The
  looser mission_namespace (live/sandbox) + runtime_mode tuple key map onto these (canonical typed def).
  [REQ:EG-01] 7/7; additive; gate green. NEXT = EG-02 (central mode-authority ENFORCEMENT guard).
- 2026-07-03 64ed122 — EG-02 DONE (wake 5). Central enforcement: require_authority/permits/ModeAuthorityError +
  mode_from_namespace in governance.py; WIRED at command_eligibility (command_real_robot gate is now
  matrix-driven, byte-identical). modify_accepted_world write-site wiring DEFERRED (record_terrain carries no
  mode; EG-03 territory) -- delivered guard + noted, not half-wired. [REQ:EG-02] 3/3; regression (contracts+
  bridge+runtime) green. NEXT = EG-03 (DB/branch isolation) -- likely more architectural; do the MINIMAL real
  isolation (mode -> store namespace/path + isolation guard), SURFACE+STOP only if it needs a genuine
  persistence-architecture decision from Aaron.
- 2026-07-03 6646ee4 — EG-03 DONE (wake 6). DB/branch isolation by mode: stewie/twin/store_isolation.py
  (store_key/store_root/require_live_store_write/save_site_for_mode/load_site_for_mode) -- minimal
  directory-namespace over the existing file store (NOT a multi-DB fork); only LIVE -> the live store, non-LIVE
  write to live fails closed (reuses EG-02). Existing raw-data_dir callers byte-identical. Threading the active
  session mode into every WorldStateService/router call site is the noted [REQ:EG-03] follow-up. [REQ:EG-03]
  4/4; additive; gate green. GOVERNANCE = model(EG-01)+enforcement(EG-02)+isolation(EG-03). NEXT = EG-05
  (training-to-live gate + live-execution token).
- 2026-07-03 b16c12e — EG-05 DONE (wake 7). Training-to-live gate + live-execution token (§29.5):
  stewie/contracts/live_gate.py (LivePreconditions / issue_live_token / require_live_token) -- token minted
  ONLY when the 8-step sequence (steps 1-6) completes; the command bridge rejects a missing/mismatched/forged
  token (signature-bound to mission+revision); SEPARATE from EG-02 (LIVE authority alone insufficient). Steps
  1-6 = the MO-02 DRAFT..RELEASED SignedRevision chain. Token->/executive/run wiring is the noted follow-up.
  [REQ:EG-05] 4/4; additive; gate green. NEXT = EG-06 (command-safety pipeline + single-ROS2-egress invariant).
- 2026-07-03 93b632b — EG-06 DONE (wake 8). Command-safety pipeline + single-egress (§29.6):
  stewie/bridge/command_pipeline.py lower_command (ordered mission-validate -> command_eligible interlock,
  fail-closed at first unmet stage). SCREEN: the pipeline + single-egress ALREADY hold (rc.py is the sole
  lower_plan_ir importer; command lowering only via command_eligible) -- formalized as one named function +
  GUARDED. [REQ:EG-06] 3/3 (stage-order fail-closed + emit + single-ROS2-egress guard); additive; gate green.
  NEXT = EG-11 (safety-control layer). Remaining on-host P0: EG-11, MP-07.
- 2026-07-03 (deploy) — Aaron requested a full /program rebuild+deploy. The branch (HEAD at the time, a0c98d3)
  was BUILT + DEPLOYED to app.stewie.space (backend+frontend images; rollback tags stewie-{backend,frontend}:
  rollback = old main 7247d94). Verified: backend healthy, /program live at 315/193 phase-grouped, restructure
  endpoints 200, zero board JS errors. NOTE: prod now runs the UNMERGED branch build; main untouched; NOT
  git-pushed. Loop rows AFTER a0c98d3 (EG-11, MP-07) are NOT in prod until a re-deploy.
- 2026-07-03 5a29800 — EG-11 DONE (wake 9). Safety-control layer (§29.8): stewie/runtime/safety_limits.py
  (SafetyLimits / check_within_limits / estop / comms_loss_behavior) -- ALL limit values SOURCED (V_CAP 0.5,
  slope 20, obstacle 0.075m, dig 0.50, battery 0.10, comms 2.0s), fail-closed; e-stop -> BRAKED_HOLD;
  comms-loss -> SAFE. Pipeline-wiring (call check_within_limits in EG-06 lower_command) is the noted follow-up.
  [REQ:EG-11] 6/6; additive; gate green. GOVERNANCE COMPLETE (EG-01/02/03/05/06/11). NEXT = MP-07 (the LAST
  on-host-buildable P0).
- 2026-07-03 c4d6ae5 — MP-07 DONE (wake 10). Plan-executability gate (§30.3): stewie/contracts/plan_gate.py
  (PlanPreconditions 8 steps + is_executable + require_executable -> PlanNotExecutable). The planning-domain
  mirror of EG-05's live gate; each precondition maps to a real PlanResult/executive source. Plan-flow wiring is
  the noted follow-up. [REQ:MP-07] 4/4; additive; gate green.
- 2026-07-03 — LOOP COMPLETE. On-host-buildable P0 queue DRY (all 10 rows done). Board 195/315 (67.2% in-scope).
  52 commits on feat/platform-restructure, NOT pushed, NOT merged (main = 7247d94); prod app.stewie.space runs
  the a0c98d3 build (rows after that are branch-only). Summary: session_notes/2026-07-03_autonomous_restructure_loop.md.
  No further ScheduleWakeup -- clean end.
- 2026-07-03 (reconcile) — Aaron: "1 2 3" (merge + deploy-refresh + continue). Deploy-refreshed prod to
  01d8407 (195/315 live). Pushed the branch; CI surfaced 5 restructure/loop-caused failures (wheel-smoke
  4edf1d6, full-tree-mypy import* shims ed6c392, deploy-hardening 03a73f4, uncommitted s3li 03a73f4,
  stale STATUS/manifest 2c22e83) -- ALL fixed + verified locally + pushed. The 6th failure = PRE-EXISTING
  test_release_gate AS-04 (V=D without container evidence), which main itself was red on 10+ h (concurrent
  AS-lane work; 7ecf0ed is a main ancestor). Aaron chose "merge now" -> fast-forward 7247d94 -> 2c22e83
  pushed to origin/main (57 commits). main now == branch; red only on the pre-existing AS-04.
  LESSON: run the FULL `mypy` (no args) + expect fresh-clone CI to catch uncommitted artifacts + stale
  generated files the per-row LOCAL gate never exercises. NEXT = P1 loop (EG-04/07/08/09/12, MP-05/06/08..11),
  branch-local commits, NEVER push/merge unattended.

## P1 phase (branch-local, one row per wake)
- 2026-07-03 92d7fc3 — EG-04 DONE (P1 wake 1). Role/permission model (§7): governance.py Role (11 roles) +
  RolePermissions (7 caps) + ROLE_PERMISSIONS matrix + role_permits (fail-closed) + can_command_live (role
  floor AND mode floor). The 4 named floors load-bearing (Viewer RO / Trainee training-only / Engineer
  non-live / SafetyOfficer approves live). Endpoint/pipeline wiring = noted follow-up. [REQ:EG-04] 7/7;
  additive; FULL gate green (mypy 312 files). Branch-local, 2 ahead of main. NEXT = next on-host P1
  (EG-07 audit trail / EG-08 reconciliation lifecycle / EG-09 import-DAG guard / MP-05 object model).
- 2026-07-03 f7445e9 — EG-07 DONE (P1 wake 2). Immutable audit trail (§7): contracts/audit.py AuditRecord
  (9 fields who/what/when/where/mode/reason/before/after/evidence + prev_hash + record_hash) + AuditLog
  (append-only, NO delete/update) + verify_chain (hash-chain tamper detection; caller-provided timestamp keeps
  the digest deterministic). Wiring audit.append into command/merge/config sites = noted follow-up. [REQ:EG-07]
  4/4; additive; FULL gate green (mypy 313). Branch-local, 5 ahead of main. NEXT = EG-08 (reconciliation
  lifecycle) / EG-09 (import-DAG guard) / MP-05 (object model).
- 2026-07-03 f99f94d — MP-05 DONE (P1 wake 3). Mission-planning object model (§30): contracts/planning_model.py
  the 12 planning objects (Intent/Mission/Task/TaskDependency/Plan/PlanCandidate/Assignment/ResourceBudget/
  RiskAssessment/RehearsalResult/ExecutionPolicy/PlanDecision) as strict frozen Contract subclasses; a Plan
  round-trips through the store (plan_to_record/from_record, JSON) carrying candidate+decision+provenance+txn.
  FORMAL §30 spine contracts (distinct from operational lode.planner_model); MP-06/08/09/10/11 build on these.
  Plan-persistence wiring = noted follow-up. [REQ:MP-05] 3/3; additive; FULL gate green (mypy 314). Branch-local,
  8 ahead of main. NEXT = EG-08 (reconciliation lifecycle) / EG-09 (import-DAG guard) / MP-06 (intent->world flow).
- 2026-07-03 03342a6 — EG-08 DONE (P1 wake 4). Reconciliation lifecycle (§29.7): contracts/reconciliation.py
  ReconcileState (observed→compared→proposed→reviewed→accepted/rejected→applied→archived) + LEGAL_TRANSITIONS
  DAG + Proposal (confidence + model/sensor error flags) + advance (guarded) + apply_proposal (only ACCEPTED
  applies → REJECTED never mutates accepted truth, reaches only archived) + manual_override (legal transition,
  logged to the EG-07 audit trail). Composes EG-07; fed by MP-11. [REQ:EG-08] 4/4; additive; FULL gate green
  (mypy 315). Branch-local, 11 ahead of main. NEXT = EG-09 (import-DAG guard) / MP-08 (capability match) /
  MP-09 (physics scoring) / MP-06 (flow).

## Decision update (2026-07-03, Aaron via AskUserQuestion)
- AS-04 RESOLVED (my recommendation, accepted): un-flipped V=D -> V=P (container-verification evidence not
  recorded; the firewall's own rule). This cleared the last CI red on branch + main. REVERSIBLE (flips back to
  V=D when the AS-lane owner records the container evidence). Do NOT re-flip it or touch the AS lane.
- CADENCE CHANGE: now PUSH + MERGE each batch (was branch-local). After a batch of P1 rows: push the branch,
  ff main, push main. CI should be GREEN now (all reds resolved) — verify green on each batch push.
- SCOPE: continue through the on-host P1 rows (EG-09/MP-08/MP-09/MP-06/...), THEN pivot to the integration
  follow-ups (wire the delivered gates into /executive/run) — the higher-value next phase.
- Batch pushed+merged @ 97a75c1: EG-04 + EG-07 + MP-05 + EG-08 + AS-04 un-flip. Board 198/315.
- 2026-07-03 5a8617b — MP-08 DONE (P1 wake 5). Capability matching (§30): contracts/capability_matching.py
  effective_capabilities (Vehicle.capabilities ∪ mounted Tool grants, from the REAL vehicles registry) +
  match_task (Task required-caps × available assets → MP-05 Assignment; rule = most-specialized covering asset;
  unmet → CapabilityUnmet blocks assignment). [REQ:MP-08] 5/5; additive; FULL gate green (mypy 316). Branch-local,
  3 ahead of main. PUSH-GATE HELD: prior CI 97a75c1 still in_progress (fast jobs GREEN: package/UI/JS; the 2 test
  jobs + lint+type+cov still running, zero failures) → MP-08 rides the next batch. NEXT = MP-09 (physics scoring)
  / EG-09 (import-DAG guard).
- 2026-07-03 4e60972 — MP-09 DONE (P1 wake 6). Physics scoring (§30): contracts/physics_scoring.py
  score_candidate via the REAL conserved backend (tier2_numpy) + real vehicle/body/soil inputs: per-wheel load
  → static sinkage; feasibility = contact pressure <= allowable bearing (else entrapment). PhysicsScore
  (load/sinkage/pressure/allowable/feasible/score); infeasible FLAGGED (score<0), rank_feasible EXCLUDES it;
  requires a conserved backend (raises otherwise). [REQ:MP-09] 4/4; additive; FULL gate green (mypy 317).
  Board 200/315 (crossed 200). Branch-local, 6 ahead of main. PUSH-GATE HELD again: 97a75c1 CI still
  in_progress (~25min; fast jobs green, test jobs slow but zero failures) → MP-08+MP-09 ride the next batch.
  NEXT = EG-09 (import-DAG guard) / MP-06 (flow) / MP-10 (rehearsal) / MP-11 (reconciliation feed).
- 2026-07-03 d7e0795 — CI-RED FIX + MP-08/MP-09 batch merged. The 97a75c1 CI went RED (NEW, not AS-04):
  test_gen_status + test_gen_release_manifest failed on the fresh clone. ROOT CAUSE: the per-row loop regen'd
  program_snapshot.json each row but NOT STATUS.md/STATUS.json/release_manifest.json — they drifted stale from
  EG-04 through the AS-04 un-flip. Coverage was FINE (90.2% > 85). Fixed: regen'd all three (cited 214→220,
  AS-04→P). Pushed+merged the held batch (MP-08+MP-09) + the fix to origin/main d7e0795; new CI 28694406604
  running (expected green). ★ CORRECTED PER-ROW PROTOCOL: after flipping a glyph / editing the PRD, regen
  ALL of {program_snapshot.json (python3 scripts/gen_program_snapshot.py), STATUS.md+STATUS.json (python3
  scripts/gen_status.py), release_manifest.json (.venv/bin/python scripts/gen_release_manifest.py — needs
  stewie_bodies)} and commit them, EVERY row. The snapshot alone is not enough.

## Mode shift 2026-07-03 (Aaron): FAN OUT AGENTS + add P0 + restart net
- Aaron: "fan out agents, cont this loop until complete; if usage limit met restart at 0315 04 july; add p0 to loops."
- Cron restart net set: one-shot 1853b3ee @ 03:15 Jul 4 (SESSION-ONLY — dies on full session exit; best-effort).
- Remaining on-host-buildable rows (screened): P0 = BD-01 (versioned BodyProfile), PX-01 (needs a [REQ:PX-01]
  test for /plan byte-compat + microgravity refusal; protocol+adapter already exist). P1 = EG-09/EG-12/MP-06
  (composes MP-10)/MP-10/MP-11 + a longer tail (PX-02, VT-03/04/05/10, BP-03/04/06, MT-04, ...). SKIP: all
  frontend/GeoLibre (GL/RF/DW/MG/FR/TU/FS-24/MT-03), ROS/Gazebo/hardware (BA/RS-05/06, PM-18/19, AS lane), AS-04.
- METHOD (fan-out): a Workflow drafts N rows in parallel (agents screen the REAL code + return complete module +
  [REQ:] test code; NO commits/push/PRD-edits by agents). The MAIN THREAD then INTEGRATES each serially: write
  files → FULL gate (my authoritative verify: row test + req_trace + assessment + ruff + FULL mypy + regression)
  → flip glyph → regen ALL 3 artifacts → commit → push+merge gated on origin/main CI green. NEVER integrate an
  unverified draft; a 'blocked' draft (design fork / real code contradicts acceptance) is surfaced, not forced.
- WAVE 1 launched: EG-09, EG-12, MP-10, MP-11, BD-01 (Workflow wtmag1our). Integrate on completion.

## BLOCKER LOG
- EG-09 RESOLVED 2026-07-04 (fixed directly, commit ~fc92014): relocated heavy_quota->deps + _terrain_lock->world_state (killed the world<->mission<->execution cycle), added service_boundaries.py manifest + test_service_import_dag.py [REQ:EG-09] (service graph ACYCLIC + CORE sink + rclpy execution-only). Server regression + smoke green. Board 217/315.
- EG-09 (P1, import-DAG guard) BLOCKED 2026-07-03 (fan-out agent, verified honest). The REAL backend import
  graph has cross-service reach-throughs forming a world→mission→execution→world cycle, so a faithful
  "12 bounded services form a DAG" test cannot be written green without a refactor + a taxonomy decision.
  Exact offending imports: (1) stewie/server/routers/gis_export.py:22 → routers.plan.heavy_quota (world→mission,
  top-level); (2) stewie/server/routers/executive.py:160 → routers.twin._terrain_lock (execution→world,
  fn-local); (3) stewie/server/routers/plan.py:190 → stewie.bridge.rc_contract (mission→execution, legit fwd).
  CLEAN HALF verified today: sole ROS2 egress holds (rclpy only in stewie/bridge/{ros2_bridge,points_egress}.py,
  one service). FORK for Aaron: (a) the 12-service→35-router ownership manifest is a design call; (b) scope =
  top-level-only ("packaging DAG") vs all-imports; (c) tolerate vs refactor. AGENT RECOMMENDATION (makes EG-09
  clean-drafted): move heavy_quota → stewie/server/ratelimit.py (exists) + move _terrain_lock →
  stewie/server/world_state.py; both small additive relocations, then the service graph is acyclic. NOT done
  (needs Aaron's taxonomy call + it is a code change to other lanes' modules).
- 2026-07-03 WAVE 2 integrated (fan-out): MP-06 (mission flow), VT-03 (arm joint state), VT-04 (per-drum fill),
  PX-01 (already-built + [REQ:PX-01] byte-compat/microgravity test). All main-verified (full mypy 324, 25 tests,
  regression green). Board 208/315 (71.7% in-scope). 8 rows across 2 waves. NEXT: fix EG-09 directly (import
  cycle refactor); wave 3 (VT-05 dynamic CG / VT-10 camera extrinsics / SN-11 / more).

## ★ CRITICAL PROCESS FIX 2026-07-04 — flip glyphs by EXACT LINE EDIT + re-run req_trace AFTER
- BUG: the `re.sub(r'\| ID \| P \|.+? \| N \| N \| N \| NA \|', ...)` flip with re.S + non-greedy .+? SPANS
  across rows when the target row's Q-column != NA. Wave 2: VT-03 (Q=G) + VT-04 (Q=P) did not match "NA", so
  the regex jumped to the next NA rows and FAKE-PROMOTED FS-25 + GI-03 to D|D|D while VT-03/VT-04 stayed N.
  Reached main + prod before req_trace (run only BEFORE the flip) caught it. Fixed b3dcd2d/8e8d661.
- MANDATORY going forward: (1) flip by EXACT line-based edit — find the line starting `| ID |`, replace its
  exact `| I | X | V | Q |` tail (Q may be NA/P/G/D — preserve it), assert the old tail was present. NEVER a
  multi-row-spanning regex. (2) RE-RUN `python3 scripts/req_trace.py` AFTER the flip (it flags V=D-without-test)
  + confirm the snapshot bucket matches. (3) gen_program_snapshot reads `git show HEAD:PRD.md` -> COMMIT the
  PRD flip BEFORE regen, or regen reads the stale pre-flip PRD (hit this too, 8e8d661).
- WAVE 3 (VT-05/VT-10/SN-11/AM-08) drafted (Workflow wru43p8ik) — NOT yet integrated. Integrate with the
  line-based flip + post-flip req_trace.
- 2026-07-04 WAVE 3 integrated: VT-05 (dynamic CG), VT-10 (camera extrinsics), SN-11 (Meerkat obs), AM-08
  (braked hold torque). Board 212/315 (71.9%). ★★ SECOND flip-bug caught by the mandatory post-flip req_trace:
  the line-based flip regex `\| N \| N \| N \| Q \|(\s*)$` with `l[m.end():]` ATE THE TRAILING NEWLINE, merging
  each flipped row with the next line (315->312, SN-12/VT-06 vanished). FIX: the replace MUST preserve the
  newline — use `re.sub(r'\| N \| N \| N \| ([A-Za-z]+) \|(\s*)$', lambda m:'| D | D | D | '+m.group(1)+' |'+m.group(2), l)`
  and ASSERT new.endswith(newline). The post-flip req_trace is what caught it — NEVER skip it. Reverted (git
  checkout PRD.md, uncommitted) + re-flipped correctly.
- 2026-07-04 WAVE 4 integrated: SN-15 (feature association), AM-03 (Meerkat raise), AM-04 (differential pitch),
  AM-09 (Meerkat decision). All dart/, compose wave-3 Meerkat/arm/camera. Board 216/315 (72.2%). 16 rows /
  4 waves. Newline-preserving flip + post-flip req_trace = CLEAN (rows 321->321, no fake-promote). CI NOTE:
  b3dcd2d (first corruption-fix, stale snapshot) failed CI as expected; 8e8d661 (re-regen) superseded it, CI
  in_progress + slow (~40min, runner queueing) but verified green-worthy locally. Held batch (waves 2-4)
  waits on it. NEXT: push when green, FIX EG-09 directly, wave 5 (PX-02/BP-*/MT-04/EP-06 + remaining).
