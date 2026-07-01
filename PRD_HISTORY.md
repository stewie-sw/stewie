# STEWIE PRD — Historical Session Logs (§16-§25, extracted 2026-07-01)

These are the dated 2026-06-08 to 2026-06-15 session-log sections that used to live inline in PRD.md
§16-§25. They are provenance, not current truth: read PRD.md §0 (the completion snapshot) and §7 (the
requirements matrix) for the current state. Extracted to keep the PRD focused; nothing here is parsed by
req_trace / gen_status (the block contains zero §7 requirement rows). Full history is also in git.

---

## 16. STEWIE alignment (2026-06-09)

**STEWIE** (Surface Terrain Engineering & World-model Integration Environment, McCardle & Storey,
June 2026) is the adopted platform name + responsibility architecture over this codebase. IPEx is the
hardware program ("IPEx builds the Moon; STEWIE plans the build"; *in silico → in situ*). Subsystems
own OUTCOMES, not algorithms. Authoritative architecture/roadmap docs are maintained privately;
this section is the public mapping of record.

### 16.1 Subsystem ↔ codebase mapping
| STEWIE subsystem | Question it answers | Existing code (this repo) | Primary gap |
|---|---|---|---|
| **STEWIE platform** | What is happening on the Moon right now? | stewie physics authority, the server/UI, io_fields twin seams, world-model/forward-sim engines (`autonomy`, beam search) | live ROS2 bridge; telemetry injection; director/operator split |
| **DART** (perception) | What does the world look like? | Godot sensor render, YOLOv8/U-Net++ detectors, `dem_import` (LOLA + GeoTIFF), `map_channel`, `localization` | typed interface contract; COLMAP→resync pipeline |
| **LODE** (operations) | What should happen next? | `mission_planner` (7-alg optimizer, multi-vehicle, precedence, plan IR, PDF report), scheduler | acquisition inventory; bandwidth-aware downlink queue |
| **LEAP** (earthmoving) | How should we move the regolith? | conserved cut/fill/dump physics, `structures`, skill/worksite envs, build-order queue | per-structure policy; multi-vehicle routing |
| **FORGE** (infrastructure) | What are we building? | sinter authority (gated, `SINTER_ENABLED=False`), `validate_plan`/I11 as-built acceptance | typed interface; certified-record provenance store |

### 16.2 Phase-1 gate — the new top of the forward queue
The ROS2 bridge is the first gate on operational usefulness (the sim must speak the real robot's
language). These stages PRECEDE the previously queued P-stages:

| Stage | Deliverable | Acceptance |
|---|---|---|
| **P20 ROS2 bridge** | bidirectional bridge: sim state → standard sensor/geometry topics; `/cmd_vel` → the physics drive loop; REP-103 ↔ sim frame mapping implemented ONCE at the bridge | container starts, `/healthz` 200, ROS2 node joins the graph, external teleop moves the simulated rover |
| **P21 Telemetry injection** | configurable bandwidth/latency/drop/frame-rate layer from a mission-profile JSON ("ideal" profile = constraints off) | operator node receives downsampled/delayed data; drops counted + reported; director sees full-rate |
| **P22 Director/operator split** | session-mode toggle: operator view = telemetry-constrained only; director view = full state + auth + replay/debrief (fast-forward without breaking link time accounting) | two browser sessions, one simulation; side-by-side replay of seen-vs-actual trajectory |
| **P23 Intern beta (Day 28)** | Docker container packaging physics + server + bridge; end-to-end training run with real remote-control software | operator completes a simulated Haworth traverse in <30 min with no technical assistance |

Note: the container exposes host port 8000 per the STEWIE docs; the app's internal default (8770)
is unchanged — the container maps the port.

### 16.3 Year-1 phase ↔ P-stage crosswalk
- **Ph.1 (Mo 1–3) Training sim** = P20–P23 + full motion-planner topic set + scenario library +
  pluggable external-planner interface + DEM site expansion (wires the existing `dem_import`).
- **Ph.2 (Mo 4–6) World model + charging gap** = COLMAP→GeoTIFF→**resync POST API** (versioned twin)
  + forward-sim ensemble service/panel (existing headless engines) + **DART typed contract locked**
  (extends P6/P15).
- **Ph.3 (Mo 7–9) Data management** = acquisition inventory (per-cell imagery/sun-angle/downlink) +
  world-model uncertainty map + bandwidth-aware downlink queue + science-targeting overlay (extends
  `map_channel`).
- **Ph.4 (Mo 10–12) Construction integration + Year-1 release** = LODE+LEAP end-to-end scenario +
  FORGE certified records + the packaged benchmark (extends the M1 challenge platform: authored
  scenarios + rubric + baseline; reviewer runs on a clean machine in <1 hr).
- **Year 2** = mission assistant (suggestion queue), multi-sol planning, DART live feedback loop —
  the operator approves; they no longer initiate.

### 16.3b Navigation — Articulated Rover Geometry for Unified State Estimation (added 2026-06-10)
The articulated vehicle-twin subsystem: documented rover geometry (chassis/wheels, bucket drums,
arm swing, the 8-camera rig, the LED work-light units) carried as ONE state consumed by every
estimator and the renderer alike. Implementation spine: stewie/specs/vehicle_twin.py +
ipex_specs.py camera/lighting truth + camera_rig.gd LIGHT_UNITS + the ArmState joint model (plan
T2.1). Plan of record: design/IPEX_TRUTH_INTEGRATION_PLAN_2026-06-10.md. Named in tribute to
Jadon Schuler, IPEx Project Manager and Principal Investigator, whose TRL-5 documentation
[SCHULER24] is the ground truth the subsystem traces to.

### 16.4 World-model strategy vs reconstruction-based world models (added 2026-06-10)
Assessment of the Martian World Model line of work (M3arsSynth + MarsGen, arXiv:2507.07978):
**we already own their OUTPUT side, with something stronger underneath.** Their world model is
reconstructed APPEARANCE (3DGS scenes, static); ours is a conserved PHYSICAL STATE -- terrain that
actually changes under excavation, with producer-exact poses and per-pixel geometric depth truth
(stewie/eval/depth_truth). What we lack is their INPUT side: real-mission stereo -> metric 3D
scenes. Their recipe for that is genuinely good (VGGT intrinsics + Metric3D depth + PnP; COLMAP
fails ~30% on planetary stereo, theirs hits 100% at 0.77 px reprojection).

Adoption, three phases in value order:
1. **LunarSynth data engine (first; modest cost):** curate real lunar stereo -- CE-3/CE-4 PCAM
   (CE-3 already in our detector training), Apollo surface pairs, LRO NAC -- through metric-aware
   reconstruction into REAL-imagery scenes imported via the existing dem_import path. Yields
   real-lunar DART evaluation scenes + planner demos on real terrain + a dataset paper. All real
   data.
2. **3DGS NVS layer** for the training sim (photoreal operator views) -- rides Year-1 Ph.2.
3. **Generative video ("MoonGen") -- DEFERRED** until 1-2 prove out + GPU access (their fine-tune
   used 8xA100).

**Non-negotiable rail: diffusion-generated frames are NEVER evidence.** Rehearsal, visualization,
and detector-training augmentation only -- the same fencing as the perception track.
Their 2D-warp-error consistency metric is adopted for render/NVS QA regardless. Full note:
`design/LUNAR_WORLD_MODEL_NOTE_2026-06-10.md` (private workspace).

### 16.5 Control-room human-factors analysis (Carstens & Schuler, IEMS 2025) — UI/UX requirements
Source: Carstens, D.S. & Schuler, J.M. (2025), "Next Generation ISRU Pilot Excavator control room
and facility design," Proc. 31st IEMS, 73-88, doi:10.62704/10057/31312 — interviews with the 8
operators of the fall-2024 5-day mock IPEx mission (13-h shifts, 2-h rotations; roles: Primary/
Secondary Operator, Telemetry Desk, Sim-C). 50 recommendations across 11 Spradley domains. The
software-relevant findings map DIRECTLY onto STEWIE's operator UI:

| Operator finding (domain) | STEWIE UI requirement |
|---|---|
| Fonts illegible / "small font defeats at-a-glance reading" (D1) | **UI-1 Settings tab: font-size control** (global scale, persisted) |
| "Dark room kept people calm" + dim-lighting recommendation (D4/D8) | **UI-2 Settings tab: light/dark mode** (dark default for ops) |
| "Push a lot of buttons to get information," drill-down slow, cognitive overload (D1) | UI-3 One-action depth for critical info; macros/scripts for repeatable tasks |
| 6 camera grid "not pertinent" -> show 1-3 relevant; tedious full-screen/zoom/exposure (D1) | UI-4 Pertinent-camera selection + one-click fullscreen/zoom/exposure per feed |
| Image freshness uncertainty -> "green border, ~20 s yellow, >1 min red" (D1, P4 verbatim) | **UI-5 Staleness borders on every camera/telemetry tile (green/yellow/red)** |
| Warnings/errors/info messages wanted (D1) | UI-6 Alert rail (severity-typed, timestamped) |
| "One big display to know what the robot is doing" (D1) | UI-7 Big-board mode (single situational view; operator desk composes it) |
| Lap/cycle counter "easy to forget"; "status visual on where we are in the cycle" (D2) | UI-8 ConOps position widget (cycle/lap/phase, always visible) |
| Handover: "show instead of tell," pull up past noteworthy events, checklists (D6) | UI-9 The session debrief/summary IS this -- add noteworthy-event bookmarks + handover checklist export |
| "Structure on how to replay what just happened" when overloaded (D9) | UI-10 Replay scrubber over recorded legs (P22 visual replay; same data, operator-facing) |
| Sim-C tracked believed-vs-actual state (methodology) | UI-11 The operator/director divergence view = exactly our truth-denylisted session design — keep it load-bearing |

These are OPERATOR-DERIVED requirements from the real IPEx mock mission — the highest-authority
UI/UX source we hold. UI-1/UI-2 ship first (the Settings tab); UI-5 and UI-8 are small and
high-value; UI-4/UI-7/UI-10 fold into the operator-screen redesign (the role x workflow split).

### 16.5b UI/UX status pass + the 2026-06-10 audit folded in (the planner-voice audit,
### pane boundaries, OSS survey, and wireframe sprint — design/MISSION_PLANNER_UIUX_AUDIT,
### OSS_GIS_SURVEY, WIREFRAME_SPRINT)

Status of UI-1..11 (evidence = shipped commits + captures, per the V&V discipline):

| Req | Status 2026-06-10 |
|---|---|
| UI-1 font control | ✅ SHIPPED (Settings, persisted) |
| UI-2 light/dark | ✅ SHIPPED (dark ops default) |
| UI-3 one-action depth | 🟡 partial (popovers + workbench cards; macros ⬜) |
| UI-4 pertinent cameras | ⬜ (rides the operator-screen split, #68) |
| UI-5 staleness borders | ✅ SHIPPED (green/20s-yellow/60s-red sweeper) |
| UI-6 alert rail | ✅ SHIPPED (severity-typed/timestamped `#alertrail` + 🔔 badge; `alertMsg` chokepoint fed by plan hazard flags, layer failures, error-shaped status; Playwright-verified + `test_ui6_alert_rail.py`) |
| UI-7 big-board mode | 🟡 (the control-room patterns adopted: status rail + sparklines; the single composed view ⬜) |
| UI-8 ConOps widget | ✅ SHIPPED (header chip) |
| UI-9 debrief + bookmarks | 🟡 (debrief ships; bookmarks/checklist export ⬜) |
| UI-10 replay scrubber | 🟡 (exec playback at 60×; an operator-facing scrubber ⬜) |
| UI-11 divergence view | ✅ load-bearing (truth-denylisted sessions) |

New requirements from the 2026-06-10 audit/wireframe (the audit's priority order):

| Req | Source | Requirement | Status |
|---|---|---|---|
| UI-12 | audit P1 | physics-fed layer legends + an on-map true-scale bar | ✅ SHIPPED (TDD: legend == code defaults) |
| UI-13 | audit P2 | drag-to-move features + the branded glyph set, one drawing language | ✅ SHIPPED |
| UI-14 | audit P3 | the queue as an attribute table + authoring undo | ✅ SHIPPED (`#qtable` sortable attribute table — kind/action/x·E/y·N/m²/depth, click-to-sort, per-row locate/reorder/delete; `undoAuthoring` history + ↶/Ctrl+Z; Playwright-verified + `test_ui14_queue_table.py`) |
| UI-15 | audit P4 | the pip as a true overview-locator (draggable view rectangle) — or removed | ✅ SHIPPED (`pipDraw` strokes the main camera's `computeViewRectangle` on the `#piploc` pip over the `#workareaimg` hillshade; single-drag pans, double-click renders that sub-area. Playwright-verified: the pip renders 240×240 and the neon view-rectangle is drawn — canvas getImageData found ~2198 stroke px, redrawing after a pip drag. `test_ui15_overview_locator.py`) |
| UI-16 | survey | TerriaJS workbench cards (per-layer legend/opacity/zoom/remove) + basemap stacking | ✅ SHIPPED |
| UI-17 | wireframe | REPORT = the mission dashboard (totals strip + route hero + activity Gantt) | ✅ SHIPPED (`#dashboards`: the totals chip strip, the `#routehero` canvas drawing the authored plan view enlarged, and the `#gantt` activity timeline — `drawGantt` lanes per phase with [t0,t1] bars + the battery curve. Playwright-verified: planning a real cut→fill mission draws the route hero + takes `#gantt` 0→~27.8k bright px over a 0–320 h axis. `test_ui17_report_dashboard.py`) |
| UI-18 | wireframe | the pane manager (user-created, resizable, persisted layouts) | 🟡 (FS-21 `wirePanelLayout`: drag-to-reorder the sidebar panes via the `⠿` grips, the order persists per operator in localStorage + a reset-to-default, view-only so ids/handlers/role-gates are unchanged; + the resizable inset. `test_ui18_pane_manager.py`. Open: multiple NAMED saved layouts) |
| UI-19 | pane spec | SYSTEM tab consolidation + pane boundaries (the one-line tests) | ✅ SHIPPED |
| UI-20 | Aaron | mobile: drawer cockpit, touch targets, phone-viewport verified | ✅ SHIPPED |
| UI-21 | edit mode | QGIS-style edit sessions: camera lock, draw tools, select/move/delete features | ✅ SHIPPED |

Open UI surface, in priority order: UI-4/UI-7 (the operator-screen split, rides #68), UI-18 (pane
manager), UI-9/10 remainders. (UI-6 alert rail + UI-14 queue attribute table + UI-15 overview-locator
+ UI-17 report dashboard/Gantt all shipped 2026-06-19.)

### 16.6 Boundary note
The DART navigation track planning set (G1–G9 gates, separate honesty firewall) is NOT renamed or
re-scoped by STEWIE. Convergence: STEWIE P20 (ROS2 bridge + live drive loop) is the same engineering
object as the navigation track's persistent-runtime gap (G1.A4/A6) — one build advances both tracks;
the navigation track's evidence-mode rules still apply on its side.

### 16.7 On-rover autonomy stack — Autoware-derived architecture (added 2026-06-15)

**Intent, not a committed full build.** The rover needs a modular on-board autonomy stack with the same
*shape* Autoware established for terrestrial AVs (Sensing → Perception → Localization → Planning →
Control → Vehicle interface, as ROS2 nodes with frozen message contracts). STEWIE's subsystems already
mirror those layers, so the strategy is **adopt the architecture + the road-agnostic plumbing; reuse the
off-road-applicable components; build the lunar-specific autonomy ourselves** — never fork the whole
stack (Autoware's planning is road/lanelet2-centric; there are no lanes on the Moon, so that layer is
dead weight). The lunar planning/perception layer is both the product differentiator and the
Navigation articulation-localization novelty.

| Layer | Autoware fit | STEWIE plan | Maps to |
|---|---|---|---|
| ROS2 framework, node lifecycle, QoS, TF, message discipline | Excellent | **Adopt** | the P20 ROS2 bridge |
| Sensing drivers, time-sync | Good | **Adopt/adapt** | DART sensing |
| Localization (NDT scan-match, EKF/ESKF fusion) | Reusable reference | **Adapt** (we already do map-relative `register_to_dem` + ESKF, P15) | LEAP |
| Control (pure-pursuit / MPC tracking) | Mostly reusable | **Adapt** (skid-steer kinematics) | LEAP→vehicle |
| **Planning / behavior** | **Poor fit (lanelet2/road)** | **Build our own** — terrain-costmap, slip/sinkage/tip-aware, illumination/PSR-aware, excavation-aware | DART + LODE |

**The seam to STEWIE = AG-08.** The cockpit plans → rehearses → and at the Command stage lowers a verified
Plan IR / commands across the ROS2 bridge (NV-11 lowering / NV-12 live channel) under the SF-01 dead-man
interlock to this on-rover stack. STEWIE is the ground/planning/twin side; the autonomy stack is the
on-rover consumer of AG-08's output. Most of the on-rover stack is the **gated hardware future** — the
planning cockpit and sim drive-loop exist today; real on-rover perception/localization/control do not.

**License.** Modern Autoware (autowarefoundation) is **Apache-2.0** (permissive, patent grant). Adopting
the *architecture* (reimplementing layers) carries **no license obligation** (architecture/APIs are not
copyrightable). Vendoring Apache-2.0 *code* into the all-rights-reserved STEWIE is permitted (Apache-2.0
is not copyleft) provided we preserve license/copyright/`NOTICE`, state changes to modified files, and
avoid the Autoware trademark. **Caveat:** Autoware's transitive dependencies are mixed-license (BSD/GPL/…)
and must be swept before any code is vendored — tracked as task #124 (THIRD_PARTY.md). Reimplementation
(no vendored code) sidesteps this entirely and is the recommended default.

**ROS 2 distribution strategy (added 2026-06-15).** The ROS 2 framework layer targets two distinct
distributions for two purposes:
- **Ground / sim development → ROS 2 Jazzy** (the current P20 bridge target; the live `cmd_vel`→SF-01
  seam lands here, `ros2_bridge.py`). **ROS 2 Iron (Iron Irwini)** is the intermediate release and is an
  acceptable dev target where a tool requires it, but Jazzy is the default (newer, longer support than Iron,
  which is EOL'd; Humble/Jazzy are the LTS-class anchors).
- **Flight / on-rover → Space ROS.** [Space ROS](https://space.ros.org) is the NASA + Blue Origin + Open
  Robotics **spaceflight-hardened ROS 2** distribution — deterministic execution, safety-process/V&V
  rigor (toward NPR-7150-class software assurance), and a vetted subset — currently tracking ROS 2
  **Humble (LTS)**. The on-rover autonomy stack's flight build targets Space ROS; STEWIE's contracts and
  the bridge stay distribution-agnostic at the message/topic seam so the same Plan-IR lowering (NV-11/12,
  under AG-08 + SF-01) drives a Jazzy ground/sim node OR a Space ROS flight node. Honest: this is the
  **gated hardware future** — STEWIE develops against Jazzy today; Space ROS is the flight-grade migration
  target, not a current dependency.

## 17. Cockpit state + pending work (2026-06-10 session close)

A full live-debug day with Aaron driving. SHIPPED and verified (each capture-proofed,
commits adff7b6..e59cbde):

**Map truth chain**: SPICE is the default sun (NAIF kernels at $STEWIE_SPICE_KERNELS;
mean-motion fallback's 5.6° elevation error MEASURED into a dated artifact — it can mis-state
polar day/night); the Haworth tile drapes the globe via server-side reprojection to geographic
(IAU_2015:30135; the matplotlib-figure-as-drape and footprint-polygon-paint bugs found and
killed); coordinate truth verified (WGS84-shaped globe documented; scale bar now true body
meters); slope hierarchy verified (15° ConOps / 20° TESTED no-go / ~30° Gen-1 failure — 40°
indefensible); docs/map_reference.md carries the pipeline + in-stack source links.

**Cockpit**: workflow sidebar (7 independently collapsible groups, separators, drum-mark header,
Orbitron headers); Contents pane with TerriaJS-style WORKBENCH CARDS (in-card physics-fed
legends, opacity, zoom-to, remove); layer toggles ACTUALLY work (root cause: `let viewer` is not
`window.viewer` — every globe-path guard silently early-returned since written); toggles fly to
the work area; footprint click loads the granular set; cursor lat/lon + site-frame meters +
scale bar; per-body WORKSETS (no cross-body leakage); S-3 path-first authoring (goto orders,
auto-precedence, draw-path mode, drag-to-move, branded glyphs); S-4 object store (missions +
custom structures CRUD, mission notes); live plan→render reactivity (#33); API key via Settings
with actionable 401s; nginx no-cache (the stale-UI culprit).

**Physics**: berm re-hazard rule (later legs crossing executed cut/fill flag at the body's
repose angle); CG with loaded drums (mass-symmetric ballast is the maneuver target — the naive
counter-pose REFUTED by the model and test-pinned).

**Pending (the task queue, in priority order)**: #31 telemetry rail (channel chips +
sparklines); #40/#41 QGIS-style edit mode (camera lock + globe drawing tools through
/dem/site_xy); #32 no-terminal (Server-tab buttons for snapshot/backup/replicate/gate-run);
#26 info popovers; #25 remainder (live CG widget, perception-gated DockWithLander, Mars
enhanced datasets); #38 resizable panes; #39 event history (who/what/when audit trail); #30 the
FULL docs rewrite + astrophysics primer (agent fan-out, constants verified against code).
Hard-won lessons in force: guard on bare let bindings; verify USER click paths; setView not
flyTo; tile-verify every imagery product; a keyless browser's 401 confirms auth wiring.

### 17.1 Hot-loop addendum (2026-06-10 evening, f669336..e58686e + queue)

Shipped in the production-readiness rendering loop (each USER-path capture-proven):
- **#45 full-tile analysis layers** (slope/hazard/shadow/permanently-shadowed over the whole
  10 km tile; rock-hazard disclosure: surveyed crop only)
- **#46+#47 linear Plan methodology** (A where-are-we → B traverse → C work → D constraints →
  E solve → F review; solver wiring TDD-pinned nearest-vs-brute; Feasibility = sandbox)
- **#40/#41 edit mode** (camera-locked QGIS-style session; waypoint/keep-out/note via
  /dem/site_xy; footprint click = far-out gesture only) + **#48 plan-canvas hillshade underlay**
- **sub-collapsible A..F steps**; **#51 basemap stacking** (multi-imagery + per-layer opacity
  cards) + Site-before-Contents reorder (groups 1..7)
- **PSR root-cause** (44 s sweep → 384 px + disk cache + startup warm = 2.6 s; opacity persists)
  + acronym rule (Permanently Shadowed Region spelled out)
- **#26 popover pattern debut** on Feasibility (one key line + live ⓘ breakdown; open popovers
  refresh on change) + render-401 actionable + keyless auto-render skip
- **#31 telemetry rail** (channel chips + sparklines, exec-fed)

Open queue (tracked tasks): **#52 auth + operator whitelist** (mccardle.john@gmail.com,
aaron.w.storey80@gmail.com, storeyaw@clarkson.edu; Tailscale-header and email+key paths) — IN
PROGRESS; #32 no-terminal Server tab; #25 CG widget + docking + Mars sets; #38 panes; #39 event
history (rides the #52 identity); #49 Artemis-site DEM bundles (all candidates south-polar);
#50 wireframe sprint + 3D quantized-mesh terrain spike; #30 docs+primer fan-out; #26 remaining
surfaces (capabilities/validation verdicts).

## 18. Intent alignment — the scope ladder (John's framing via Aaron, 2026-06-10)

**Who is this for?** Four rungs, from horizon to ground truth. The PRD's product modes (§5) and
everything in §17 must serve these in priority order BOTTOM-UP — the concrete rung funds the
ambitious ones, never the reverse.

### Rung 4 (MOST CONCRETE — the product): the training environment / mission simulator
The rover is ordered to waypoints. A Docker container runs the ACTUAL rover motion planning and
simulated sensors. The TEAM observes only the data they would really receive — over the limited
telemetry and the latency of the real mission. The SIMULATION OPERATOR gets the 3rd-person view
and immediate state access. **Hard requirement: pluggable with the existing remote-control
system that operates the actual robot in the dirt pit** — the sim differs only in its training
affordances: fast-forward while driving, ignore battery, disable latency.

What exists today → this rung:
- the operator/sim-operator SPLIT is already real: training sessions (B3) run the closed loop
  server-side with the operator link showing only telemetry-delivered legs; link models
  (ideal / mission / comm_dropout) exist; the debrief view exists
- the Docker container IS the deployment (compose, healthz, beta_accept)
- RuntimeProcess is the frozen seam the motion planner + sensors speak through (Unix-socket
  JSON-lines; checkpoint/restore bit-exact); the ROS 2 bridge (rover_executive /cmd_vel teleop)
  is the dirt-pit-shaped interface
- waypoint ordering is the S-3 path-first authoring; EXEC fast-forward exists (60×); the
  third-person view is the Godot render path
GAPS (the real backlog for this rung):
1. **The pluggable RC contract** — a written interface spec matching the dirt-pit remote-control
   system's actual protocol (need that protocol from John); the sim must present the SAME
   surface, with the training toggles (fast-forward / battery-ignore / latency-off) as sim-side
   flags the operator cannot see.
2. Telemetry SHAPING to mission reality — bandwidth caps + latency injection per link model on
   EVERY operator-visible channel (today the link models gate legs; cameras/telemetry need the
   same budget).
3. Operator/sim-op AUTH separation (the #52 identity work makes this assignable: operator role
   vs director role).

### Rung 3: COLMAP world-map updates + the bandwidth-triage science loop
COLMAP (offline map generator) refines the rover's world map between sorties → better waypoint
navigation. Charging = ZERO connectivity; the mission ends with data stranded on the rover.
Opportunity: low-res first-pass data downlinked → suggest what to image at high-res next, or
where exploratory excavation should go.
Today's assets: the frame store + camera channels (8-cam rig with intrinsics) are COLMAP's
input shape; the map-channel reward (P6) is the "what's been observed" machinery; the conserved
twin holds as-built state. GAPS: the COLMAP ingest path (images → poses/points → DEM/feature
update), a downlink BUDGET model (bytes per sol), and the triage recommender (rank unimaged /
under-observed cells by science value — needs the team's actual objectives).

### Rung 2: faster-than-realtime forward simulation, compared outcomes, frequent resync
"COLMAP output + simulate movements faster than realtime with multiple possible inputs, compare
outcomes, resync often" — the world-model-flavored rung, honestly implementable as input
iteration over the existing terramechanics (the closed loop already runs candidate plans;
optimize_sequence already compares algorithms). GAP: a resync protocol (real telemetry ingested
→ state correction → re-simulate futures) — the navigation track-relevant piece.

### Rung 1 (HORIZON): "Claude Rove" — click-accept mission autonomy
A glimpse, not a deliverable: the rover will not run this code, and no one is running
--dangerously-skip-permissions on flight hardware. Keep as the north-star demo only.

### What today's 40+ tasks served (honest audit)
The GIS cockpit + truth chain (reprojection, half-pixel fix, SPICE sun, site DEMs, grid,
legends, edit mode, waypoint lifecycle) = the MISSION-AUTHORING FACE of rung 4 and the data
truth every rung needs. The auth/whitelist + event history = rung 4's role separation. The
telemetry rail + link sessions = rung 4's operator reality. Horizon-flavored excursions (Mars
enhanced basemaps, multi-body worksets) were cheap and stay, but the priority from here is the
rung-4 gap list above.

## 19. NASA-standards build-out (2026-06-10, Aaron: "build this out to NASA standards")

### 19.0 SF-01 safing/watchdog — DONE (2026-06-11)
The P0 safety requirement declared in §19.2 is BUILT: `stewie/bridge/rc_contract.py`
`SafingWatchdog` — a command-timeout dead-man switch that auto-issues SAFE to whatever backend is
plugged in (sim or real pit) when valid commands stop arriving, latching on the trip and resetting
on each heartbeat. [REQ:SF-01] test-cited; wired at /rc/telemetry (ticks on every poll). This
closes the architecture's "flagged-REQUIRED-and-missing, Phase-0/Week-4" node.

### 19.1 Where the §7 matrix actually stands (census, 2026-06-10)

> **SUPERSEDED 2026-06-20 (see §27.1):** this 112-requirement / "0 release-ready, 19 partial, 93 not
> started" census is **stale**. The live §7 matrix is ~186 rows; the parsed 2026-06-20 tally is
> **33 DONE / 39 IXV-done (Q-pending) / 73 partial / 41 open-or-gated**. The headline "0 release-ready"
> is a column-completeness artifact (no family has every column at D), not a statement that the product
> doesn't work — the rung-4 trainer surface is software-complete. The census below is kept for the
> per-family track tagging, which remains valid; the counts are historical.

112 identified requirements; **0 release-ready (all-required-columns D), 19 partial, 93 not
started.** By family (worst-column):

**Track tagging (architecture review rec 3, 2026-06-11):** the "0 release-ready" headline is read
correctly only WITH the track each family is on. **PRODUCT** families are on the rung-4 trainer
critical path (their gap is real product work); **DEFERRED** families are deferred frontier or
externally-gated by design (their "N" rows are the roadmap, not debt) — do not read their N count
as product debt. **GATED** = blocked on an external input (IPEx geometry, John's pit protocol).

| Family | Scope | P | N | Track | Note |
|---|---|---|---|---|---|
| CT 7.1 | contracts/conserved authority | 3 | 4 | PRODUCT | the strongest family — the core IS the product |
| TW 7.2 | terrain/material/illumination | 4 | 6 | PRODUCT | TW-06 ephemeris sun = DONE in code (SPICE) — matrix stale, flip on evidence |
| VT 7.3 | vehicle/arms/drums/stability | 1 | 9 | GATED | the two-vehicle stance gap (VT-01/02/05); exact geometry awaits authoritative IPEx data |
| AM 7.4 | posture maneuvers (MEERKAT…) | 0 | 9 | GATED | all gated on authoritative IPEx geometry |
| CP 7.5 | perception/mapping/localization | 5 | 5 | PRODUCT | the G1/G2 evidence feeds this |
| SN 7.6 | solar-terrain navigation | 0 | 13 | DEFERRED | **the Navigation frontier** — open by design (the navigation contribution) |
| NV 7.7 | navigation/planning/recovery | 1 | 11 | PRODUCT | berm re-hazard + routing + docking/berm FSMs exist; recovery behaviors don't |
| PM 7.8 | construction mission planning | 1 | 11 | PRODUCT | the planner is rich but matrix-unverified (mostly flip-on-evidence) |
| EP 7.9 | energy/thermal/power/ops | 2 | 6 | PRODUCT | battery-honest timeline shipped; thermal ops partial |
| FL 7.10 | fleet | 0 | 7 | DEFERRED | MV1-7 exists; the RL multi-vehicle frontier + fleet reqs are frontier-scale |
| PO 7.11 | product/packaging/ops | 2 | 12 | PRODUCT | docs trilogy + fetcher land here; flip on evidence |

**Reading the census honestly:** the rung-4 trainer product (the §0 / §18 intent) is software-COMPLETE;
the matrix's "N" rows are dominated by the DEFERRED frontier (SN 15, FL 7) + the GATED families
(VT/AM 18, awaiting IPEx geometry / John's protocol) + PRODUCT rows that are flip-on-evidence (the
capability exists, the matrix column hasn't been moved on a citing test yet). "0 release-ready" means
no family has every column at D, NOT that the product doesn't work.

### 19.2 The standards frame (honest scoping)
- **Classification (NPR 7150.2 software classes):** STEWIE-as-simulator/training-tool is
  Class-E-like; the moment the pluggable RC contract (#66) lets it COMMAND the dirt-pit robot, the
  command path crosses into safety-relevant territory → that path (and only that path) needs
  Class-D-style rigor: independent review, hazard analysis, the SAFING/WATCHDOG requirement the
  architecture notes already flag as REQUIRED-and-missing (command-timeout halt). The watchdog is
  hereby **SF-01**, P0, owner = the #66 contract work.
- **Requirements traceability:** the §7 ID matrix becomes ENFORCED, not aspirational —
  `scripts/req_trace.py` (added with this section) parses every §7 requirement ID and scans the
  test suite for `[REQ:<ID>]` markers; a requirement may only hold `V=D` if at least one test
  cites it. CI runs the tracer; the report is the traceability matrix.
- **V&V evidence discipline:** the I/X/V/Q columns only move on artifacts (tests, dated
  validation JSONs, captures) — the same rule the G1/G2 gates already enforce. No column flips by
  prose.
- **Coding standard:** the conserved core already lives Power-of-10-adjacent (no recursion-heavy
  paths, bounded loops, asserts banned in production contracts per CT-06); adopt explicitly for
  stewie/physics + stewie/twin: add ruff rules + a documented exception list rather than a
  rewrite.
- **Configuration management:** already strong (frozen byte-identical baseline, dated artifacts,
  CI gates, the event audit trail, journaled twin) — document it as the CM plan rather than
  rebuild it.

### 19.3 The build-out order (what "to NASA standards" means next)
1. **SF-01 safing/watchdog** + the #66 RC contract (the class boundary).
2. `req_trace.py` in CI + seed `[REQ:]` markers on the requirements that ALREADY have tests
   (CT/TW/CP families first) — turn the 19 P's into evidence-backed D's or honest N's.
3. Flip stale matrix rows on existing evidence (TW-06 SPICE; PO docs/fetcher; EP battery).
4. Then the families in mission order: VT/AM (needs IPEx geometry from John), NV recovery,
   SN as the navigation track track.

### 18.1 Rung status (2026-06-11)
Rung 4: ALL THREE software gaps CLOSED. Gap 2 (telemetry shaping — downlink latency first-class,
per-sol ledger + stranded accounting) and gap 3 (director/operator roles; truth views + admin
director-gated) shipped earlier. **Gap 1 (the pluggable RC contract + SF-01 watchdog) is now DONE
too** — it was never actually blocked: John's frozen `ccsds_ros_nav/CONTRACT.md` §2/§3 already
specifies the dirt-pit interface (GoTo/Safe/SetSim + Pose/Leg/Img over CCSDS). `stewie/bridge/
rc_contract.py` is the STEWIE adapter: the RCBackend ABC (pluggable sim/pit), `commands_from_plan`
(a plan → a reusable GoTo command tape, "plan once command many" — /plan/commands + a cockpit
download), and **SF-01 the SafingWatchdog** (command-timeout dead-man auto-SAFE). What remains for
a REAL pit is the wire-level UDP/ROS binding to John's package + a PitBackend when the pit's link
details land — an integration, not a design unknown. Rung 3: designed (COLMAP_TRIAGE_DESIGN); the budget ledger shipped; ingest
awaits the director-side COLMAP container; triage weights await science objectives. Rung 2: in
progress (#70). UI: 16.5b updated through UI-17 (report dashboard/Gantt shipped); UI-18 + UI-4/7 open.

## 20. Full-stack audit + production-readiness (2026-06-11)

An 8-dimension line-by-line audit (security, concurrency, twin integrity, vehicle twin, physics,
registries, frontend↔backend wiring, comments), every high-severity finding adversarially
verified (0 refuted of 5). 44 confirmed findings. Disposition:

### 20.1 Fixed (this session)
| ID | Sev | Finding | Family | Fix (commit) |
|---|---|---|---|---|
| SEC-1 | CRIT | GET /config leaked the plaintext API key (reproduced live) | CT/PO | source-redacted describe()+endpoint, TDD (414df2e) |
| RC-01 | CRIT | TwinStore journal append unlocked race -> chain corruption | CT-03 | per-store RLock + torn-line recovery, 24-thread TDD (414df2e) |
| RC-02 | HIGH | _TWIN lazy singleton double-init race | CT | double-checked lock (414df2e) |
| RC-03 | HIGH | globe cache non-atomic .npy+.json write | PO | .part -> os.replace, JSON commit-marker last (414df2e) |
| TWIN-01 | MED | torn FINAL journal line aborted the whole restore | CT-03 | recover-past-tail (414df2e) |
| SEC-2 | MED | GET /events disclosed the operator audit trail | PO | director-gated (c819b40) |

### 20.2 Verified FALSE POSITIVE
| ID | Finding | Why it's not real |
|---|---|---|
| PHYS-01 | "shipped slip uses Earth-fit Bekker on the Moon" | each body's Bekker is its SOURCED value; the Moon's k_phi 820000 IS the NASA LTV lunar measurement (already low-g). A runtime lyasko reduction would DOUBLE-count (the known FIX-6). Caught by test_bodies; reverted. Low-g physics is correct in the shipped path. |

### 20.3 Confirmed open (tasked / tracked) — maps to the §7 matrix gaps
| ID | Sev | Finding | Family | Disposition |
|---|---|---|---|---|
| VT4-01 | MED | /twin/cg discards the fore/aft CG shift (dx) | VT-05/06 | the posture model is 3D-in-Z, 2D-fixed-rect in XY; posture_a3.py has the fore/aft + shrinking polygon but isn't wired. Real physics-incompleteness in an ADVISORY widget. -> a vehicle-twin task |
| PHYS-02 | MED | cg_offset_m drum-load term absolute, not relative-to-stow | VT-05 | refine with VT4-01 |
| REG-01 | MED | imported sites (Shackleton, Nobile) unreachable from the PLANNER | PM/TW | the globe shows them; the planner still hard-targets Haworth. Real functional gap -> task |
| REG-02 | MED | vehicle choice only changes drum capacity in the plan | VT-02 | drive/dig/battery/mass not threaded through the planner per-vehicle |
| TWIN-02 | MED | io_fields float32 save not mass-exact + omits drum_inventory | CT-03 | the RUNTIME checkpoint IS exact; only the scene-export path drifts ~6e-10 -> document/fix |
| SEC-3 | MED | body-size cap trusts client Content-Length | CT | hardening |
| RC-04/05 | MED | _METRICS + object-store writes non-atomic | PO | observability/store hardening |
| D8-01 | LOW | stale `terrain_authority.*` run-instructions in ~7 docstrings | PO | comment sweep |

### 20.4 Production-readiness assessment (honest)
STEWIE has TWO production targets with very different bars (PRD §18 ladder):

- **As the TRAINING ENVIRONMENT / MISSION SIMULATOR (rung 4, the product):** **~75%.** The
  authoring cockpit, conserved twin, link/latency shaping, operator/director roles, audit trail,
  and no-terminal ops are real and tested; the two security criticals are now closed. The
  remaining 25% is almost entirely the **#66 pluggable RC contract + SF-01 watchdog** (blocked on
  John's protocol) plus the medium hardening list above. NOT a demo — a usable trainer
  once the RC seam lands.
- **As FLIGHT-RELEVANT autonomy / the Navigation estimator (the navigation track):** **~30%, by design.**
  The SN solar-terrain-navigation family is 13/13 open; the pose-graph that fuses sun/shadow/DEM
  factors over mutating terrain is scaffolded (shadow_predict, register_to_dem, the re-hazard,
  the conserved mutable twin) but NOT integrated. This is the protected contribution, correctly
  currently unbuilt.

**Quantitatively against the §7 matrix:** 112 requirements, 0 were release-ready (all-D) at the
§19.1 census; after the audit fixes + the traceability seeding, the CT (contracts) family is the
closest to release and the security posture moved from "one remote-compromise critical" to
"no known criticals." The honest headline: **the simulator product is ~75% and gated on one
external dependency (the RC protocol); the flight-autonomy story is early and protected.**

## 21. Architecture review + structural remediation (2026-06-11)

A full architecture review (pattern, layering, coupling/complexity hotspots, PRD-vs-intent) ran
against the live tree (~62k LOC, 153 core modules, 169 test files, 61 endpoints). Verdict: the
system is in unusually good shape for a pre-production codebase — a PURE conserved kernel
(`stewie/physics` + `stewie/twin` have zero upward imports; mass-exactness + the hash-chained
journal are production guards, not asserts), four enforced CI gates (pyflakes, mypy,
requirements-traceability, Power-of-10), and documented contract seams. Against INTENT (the rung-4
trainer product) the system is software-complete; against the full §7 matrix it is ~18%
partial/done, but that delta is the DEFERRED/GATED frontier (§19.1 track tags), not architectural
debt. Findings + remediation (ranked):

### 21.1 Structural defects to remediate (tracked)
| ID | Sev | Finding (file:line) | Remediation |
|---|---|---|---|
| ARCH-1 | MED | **`lode`↔`dart` circular dependency**: `dart/hazard_map.py:22` `from lode import rock_costs`, while `lode/actions.py` + `lode/resync.py` import `dart`. Perception (lower layer) reaches up into planning. | Move `rock_costs` to `stewie/specs` (the shared kernel both already depend on) — it is cost DATA, not planning logic. One move removes the only layering violation. |
| ARCH-2 | DONE | **`lode/mission_planner.py` god-module — RESOLVED (ARCH-2, 2026-06-22; commits 140a7cb..66f20b4, task #123).** Was 2110+ lines / 78 functions: solver + report + Plan-IR + math worksheet + command-tape + site loading in one file. | DONE: decomposed into a **448-line facade** re-exporting **10 dependency-ordered leaf modules** — `planner_constants`, `planner_model`, `planner_routing`, `planner_balance`, `planner_multivehicle`, `planner_endurance`, `planner_trips`, `planner_sim`, `planner_optimize`, `planner_assembly` (plan/compare/run), alongside the earlier `planner_views` (report/PDF/plan_math/commands) and `planner_acceptance` (validate_plan). Every public symbol stays byte-identical via facade re-export (`MP.<name>` / `from lode.mission_planner import …` unchanged); the former lode↔planner_views import cycle is broken via `planner_constants`. Formalizes the RB-03 "every output is a VIEW over the one artifact" principle. |
| ARCH-3 | LOW | **`server.py` handler sprawl**: 61 endpoints in 1261 lines — the safety-relevant auth + RC command path sits beside everything else. | Split into routers by concern (auth/session/plan/twin/rc/admin); isolate the RC command path (the Class-boundary surface, §19.2) for focused review. |
| ARCH-4 | LOW | **Cockpit is a single 2855-line inline `index.html`** — no module boundary; the largest single-file complexity in the repo. | Extract the cockpit JS into modules behind a small build/bundling step; keep the `node --check` gate. Lower priority — it is verified per-change and outward behavior is covered by the live UI evals. |

### 21.2 Non-issues confirmed (do NOT "fix")
- The high fan-in of `stewie/specs` (×96) and `stewie/physics` (×74) is a shared KERNEL, not a god
  object — expected and healthy for a conserved-core design.
- "0 release-ready" in §7 is NOT product debt — see the §19.1 track tags. The rung-4 product is
  complete; the open rows are the deferred frontier + externally-gated families.

### 21.3 Sequencing
ARCH-1 first (smallest, removes the cycle), then ARCH-2 (the RB-03-aligned split — DONE 2026-06-22, the 448-line facade + 10 `planner_*` leaves), then ARCH-3
(routers — do this WITH the SF-01/#66 hardening since it touches the same command path), ARCH-4 last
(or never, if the build step is judged not worth it). None block the product; all improve
reviewability ahead of a NASA-standards external review.

## 22. Completion audit + the navigation-track bridge (2026-06-12 — read with §0)

A four-agent fan-out (server API, estimator reachability, frontend cockpit, unfinished-marker
sweep) mapped the whole monorepo against intent; findings verified and folded in below. The shape:
STEWIE is two tracks.
The excavation planner and trainer (LODE planning, the conserved physics, the operator/trainer
sessions) is wired end to end, backend to a 71-endpoint API to a full cockpit. The navigation
subsystem, the Navigation estimator that is the navigation core, is built and validated as a library
of eighteen modules but has no HTTP endpoint and no cockpit presence. Completing the system is
mostly bridging the second track into the live one.

### 22.1 The three findings

**(1) Not in the frontend (backend exists, no UI).** The cockpit (`stewie/server/index.html`) is
entirely the planning product. Absent: the whole localization stack (no pose-graph estimate, no
trajectory-versus-truth, no drift bounding, no shadow-yaw or articulation-parallax fix, no
relocalization action, no covariance ellipse); the integrated SLAM result, the leave-one-out
attribution, the shared-testbed head-to-head; the measured-edge sigma and cross-dataset
generalization; the depth pass and photometric render-pair (the Perception tab shows only the
planner before/after, not the parallax measurement); the eval-gate results (a validate button with
no readout) and the evidence-notebook set.

**(2) Not wired on the backend.** Eighteen estimator modules have no HTTP endpoint (integrated_slam,
articulated_parallax, articulated_shadow, pose_graph_se2, shadow_vectors, shadow_edge_sigma,
localization, mapping, camera_select, comparison, depth_truth, annotate, posture_select,
posture_coverage): reachable only from tests and notebooks. `articulation_bridge` is not on the
`/render` path (it produces the planner before/after, not the two-posture parallax capture).
Genuinely unimplemented: the worksite controller seam (the one stub, the RL/autonomy that drives
the build is deferred); multi-vehicle cross-precedence (v1, not yet coordinated); berm-holds-slope
firming (the G5 gap); the Lyasko one-g to one-sixth-g sinkage correction (deferred to the euclid
oracle); DEM imports for several Artemis sites (`bundle_dir` is None); the map-uncertainty cost
coefficient (placeholder until the coverage field feeds it). FORGE is an empty package (its physics
code lives in `stewie/physics`). Gated by design, not a gap: sinter (IPEx carries no sinter tool).

**(3) What is left.** P1 wire the navigation half into the system; P2 finish the backend build
items; P3 surface the evidence. External, not buildable here: a lunar-surface rover traverse with
shadows and pose truth; the SN-07 LED-illumination hardware.

### 22.2 UI/UX status — live cockpit visibility pass (screenshots, 2026-06-12)

Captured headless on the live server (`validation/ui_2026-06-12/`, playwright + chromium, no page
errors). Each view read against intent:

| View (tab) | Screenshot | What it shows today | Gap vs the Navigation nav track |
|---|---|---|---|
| Plan (LODE) | `00_initial.png`, `01_plan.png` | Cesium Haworth globe; sidebar 1 Site / 2 Contents / 3 Fleet / 4 Feasibility / 5 Plan A-F / 6 Catalog / 7 Telemetry. The full authoring product. | None — the complete planning surface. |
| Perception (DART) | `02_perception.png` | "Godot PLAN → RENDER", before/after sensor frame. Empty-state copy: a live SLAM map is "the open map-channel work, not a faked feed." | No parallax measurement, no depth pass, no photometric render-pair, no shadow-vector overlay. P1 (parallax capture) + P3 (evidence). |
| Metrics (LEAP) | `03_metrics.png` | Live CG and tip-margin stability widget; an execution top-down replay ("a deterministic forecast of the plan, not live rover telemetry"). | By its name (Localization, Estimation and Analysis) it should host the estimator; it shows none — no pose-graph, no trajectory-versus-truth, no covariance. P1. |
| Report (FORGE) | `04_report.png` | Mission-control PDF surface (empty until a plan runs). The planner product. | None for the planner; the comparison/evidence packet (P3) can surface here. |
| System | `05_system.png` | VALIDATION / API / SERVER / CONFIG sub-panes; Twin snapshot, Retention, Replicate-backup, and a "Validate gates" button with no readout; health + metrics JSON. The `by_route` census confirms the cockpit never calls `/localize`, `/slam`, `/sense`, or `/compare`. | Gate results have no readout (P3); the estimator endpoints do not exist (P1). |
| Settings | `06_⚙.png` | Configuration pane. | None. |

The finding the screenshots make concrete: every empty-state placeholder narrates a planner
function, and none of the six tabs references the navigation/estimation track. The cockpit is the
planning-and-trainer product, complete; the Navigation estimator is invisible to it. The work
tied into UI/UX is therefore P1 (a Navigation/Estimation view plus the endpoints behind it) and P3
(the evidence figures into Perception, System, and Report).

### 22.3 TDD-sequenced forward plan

Each slice is bounded, gate-byte-identical, and lands with a citing `[REQ:]` test plus (where it is
navigation evidence) a baseline-comparing notebook. The matrix rows each slice promotes are named.

**P1 — wire the navigation half (#106, #96, #97) — ✅ DONE 2026-06-14.** The Navigation estimator is now
reachable from the live system and visible in the cockpit: P1.1 `/localize` (heading-free fix +
covariance; truth-field denylist; 5 citing tests), P1.2 `/slam` + `/slam/compare` (trajectory + ATE +
LOO over a named real segment; 503 when the dataset is absent; 5 tests), P1.3 `/render/parallax` +
`stewie/godot/articulation_bridge.py` (two-posture parallax capture → shadow-tip pixels + exact dh),
P1.4 the cockpit Navigation/Estimation view (pose-graph estimate vs dead reckoning, covariance,
perception-gated relocalize #96/#97) — live-verified headless-Chrome (`scripts/ui_eval.py`,
`validation/ui_2026-06-14_nav/`: navview renders, gate `ARMED` when σ>tolerance, no page errors). The
table below is the original slice plan.


| # | Slice | Citing test (`[REQ:]`) | Promotes |
|---|---|---|---|
| P1.1 | `/localize` endpoint: `articulation_localize` returns a heading-free fix + covariance from a posture-pair shadow-tip parallax. | `test_server_localize` (socket POST → fix + covariance; truth-field denylist holds) | PM-06 I, PO-10 |
| P1.2 | `/slam` endpoint: `run_integrated_slam` returns trajectory, absolute trajectory error, and the leave-one-out attribution over a named real segment. | `test_server_slam` (POST → trajectory + ATE + LOO; matches the frozen keystone artifact) | PM-06 V, NV-10 |
| P1.3 | `articulation_bridge` on `/render`: a two-posture parallax capture (not the planner before/after), returning the per-frame shadow-tip pixels + the exact `dh`. | `test_render_parallax_capture` | SN-10 wiring (I→V) |
| P1.4 | Cockpit Navigation/Estimation view: pose-graph estimate versus dead reckoning, the shrinking covariance ellipse, a perception-gated relocalize action (#97), and planner relocalization stops (#96). Live-verify headless Chrome + a `ui_eval` screenshot. | `test_ui_eval_nav_view` (the view renders the estimate + ellipse; relocalize is perception-gated) | PO-12, PO-10, SN-10 tie-ins B/C |

**P2 — finish the genuinely-unimplemented backend items (#107).** Buildable now: REG-01 DEM site
imports (make the Shackleton/Nobile bundles plannable), FORGE (point its `__init__` at
`stewie/physics` or remove the empty package), berm-holds-slope firming (CP-06 acceptance), the
map-uncertainty cost coefficient (feed it from the coverage field), multi-vehicle cross-precedence
(FL-02/FL-04). Externally gated, kept honest: the worksite controller seam (needs John's pit wire /
the RC transport), the Lyasko one-sixth-g correction (the euclid PyChrono oracle, FIX-2). Each
buildable item is one bounded slice with a citing test; the gated items stay N until their external
dependency arrives.

**P3 — surface the evidence (#108).** Put the comparison head-to-head (notebook stages 17-19, 28),
the cross-dataset generalization (stage 26), and the photometric render-pair + depth pass (stages
23-24) into the System and Perception tabs; give the "Validate gates" button a G1/G2 readout; link
the evidence-notebook set. A `/compare` endpoint serves the shared-testbed result the System tab
renders. These are product-story and review-surface items, not new measurement.

**External, not buildable here.** A lunar-surface rover traverse carrying both shadows and pose
truth (no such public dataset exists); the SN-07 LED-illumination hardware (the one row that stays N
honestly).

### 22.4 Sequence rationale

P1 first and most: it is the only item that changes what the system IS rather than what it shows,
and it is the two tie-ins already on the board (#96, #97) plus the two endpoints that make the
eighteen library modules reachable from the live system. P3 is cheap and high-value for the review
surface but adds no capability, so it can interleave with P1.4. P2 is a mix of small now-buildable
closes and honestly-gated externals; it blocks neither P1 nor P3. The frozen 2026-06-07 gate JSON is
untouched by all of this: every slice reproduces it byte-identically, and a gate flips only via a
new dated artifact.

## 23. Architectural/security/numerical audit (2026-06-13) — production-readiness remediation

A read-only architectural + security + numerical + terramechanics audit (4 critical, 20 high, 24
medium, 10 low; against commit `9a592cc`) found the core theme: several product paths bypass or
disagree with the authoritative models they claim to represent ("recomputing alternate versions of
reality"). It re-prioritizes the production-readiness work AHEAD of new capability. Tracked as tasks
**#110-#116**; one finding (M-34, a SPICE call left outside the serialization lock) is already fixed.

**Phase 0 — stop unsafe operation (production blockers, do first):**
- **C-01 (#110)** the published Compose deployment is auth-fail-open by default (`require_auth`
  returns director-equivalent `dev-open` when no key is set; `deploy/compose.yml` defaults it empty
  on port 8000). Production must fail closed.
- **C-02 (#111)** conserved-state mutations (`cut_to_inventory`/`dump_from_inventory`/
  `set_height_via_mass`/`drum_pass`) accept negative/non-finite values and reverse mass flow. Validate
  every authority-mutation boundary.
- **C-03 (#112)** the two shadow engines use incompatible azimuth→grid mappings (90° rotation between
  `shadow_predict.horizon_clip` and `illumination.cast_shadow_mask`). **Gates the SN/nav track** —
  shadow-derived localization may be rotated. One frame contract + cross-module tests first.
- **C-04 (#113)** mission transit can drive battery SoC negative and still return an executable plan.
  Reserve-aware edges; suppress Plan IR on infeasibility.

**Phase 1 — one source of truth (#114) — ✅ DONE 2026-06-13 (11/11 HIGH, all gated, gate byte-identical):**
one `PlanningContext` from the selected vehicle threaded through energy/mass/range/slip/report/acceptance
(H-01, `plan_context`; rassor2 mass/drum now drive the plan); route inter-site legs once and share the
routed geometry across optimizer/timeline/report so sequencing scores what the Plan IR executes (H-02,
`_make_routes`); acceptance honestly scoped, not over-claimed full validation (H-07, the self-balanced
trip decomposition makes IR re-execution materially identical); compaction is timestep/pass-invariant
(H-09, convergent target density); skid-steer propagated to the runtime drive loop (H-10); out-of-regime
microgravity body gate (H-12); fail-closed routing — off-DEM footprint reject (H-08), unreachable-leg
fail-closed at /plan (H-03), no diagonal corner-cut (H-04), adaptive window vs the 20 m bbox margin
(H-05), cumulative-ascent haul lift (H-06).

**Phase 2 — harden estimation + persistence (#115) — ✅ DONE 2026-06-13 (every slice TDD, gate
byte-identical). Touched the §22 nav track:** estimation — reject impossible parallax (H-13, the
`/localize` + render-fix primitives), require ≥3 landmarks or flag the 2-landmark mirror ambiguity
(H-14, `/localize` allows 2), pose-graph observability/anchor check (H-15, no ridge covariance), real
shadow map-match not centroid (H-16), per-frame camera pose in mapping (H-17), keep anisotropic
parallax covariance (H-30), one solar authority (H-18). Persistence/socket — durable-before-commit +
atomic verify-before-mutate twin journal (H-20/M-12, `bb6aa94`), atomic + content-checksummed twin
snapshots (M-11, `1bac883`), Unix-socket hardening = bounded readline + finite/bounded twist +
0o600 socket + finite set_thermal (M-03/04/05, `f471648`), session TTL + bounded store (M-09,
`60f0406`). Adjacent finding tracked for its own slice: arbitrary-path checkpoint/restore traversal
(#120).

**Phase 3 — scale + maintain (#116) — IN PROGRESS:** sparse graph factorization, swept/compiled
illumination, materialized twin state, split the server/planner god modules, pin deps + CI action
SHAs, green the lint gate (L-01 broken `viz/*` imports), reduce mypy exclusions, quarantine
archive/public copies + the committed Godot binary.

*Low-blast cleanup DONE 2026-06-14 (each verified, frozen G1/G2 gate byte-identical, no Claude
trailer): L-01 ruff-F lint gate greened — fixed 3 botched `viz/*` imports (`from the conserved
authority import constants as K` -> `from stewie.specs import constants as K`) + a dead dart import
(`8dce51d`); mypy ratchet tightened — un-excluded `lode.self_optimizing`, the remaining
18-module/90-error typing debt tracked as #121 (`f8f0c8c`); CI action SHAs pinned across ci/pages/
publish workflows + a publish-lint typo fixed (`2966da5`); Power-of-10 complexity gate greened —
`sandpile.deposit` had been complexity 11 since the Phase-0 C-02 fix, extracted `_deposit_target_cells`
(`f5baa06`). The full CI gate now passes locally end to end (req_trace + Power-of-10 + ruff-F + mypy +
pytest/coverage). STILL OPEN (high-blast, each its own reviewed slice): the server/planner god-module
split, materialized twin state, sparse graph factorization, swept/compiled illumination, and the
archive/public-copy + committed-Godot-binary quarantine.*

Sequencing (Aaron, 2026-06-13): **the next session STARTS with audit Phase 0** — the four criticals
**#110 C-01 → #111 C-02 → #112 C-03 → #113 C-04**, in order, before option 1/2b or any new
capability. C-03 (the 90° shadow-azimuth disagreement) is a hard prerequisite for further nav work.
Then the Phase 2 nav-primitive hardening rides alongside the option-1 rendered-DEM traverse (it makes
the measured nav fixes honest under bad geometry), then Phase 1, then Phase 3. The honesty rules are
unchanged: every fix lands TDD, gate byte-identical, no synthetic data.

## 24. LanderPi / IPEx capability diff + convergence plan (2026-06-15)

A terrestrial nav testbed (LanderPi-class: ROS2 + Nav2 + SLAM-Toolbox/RTAB-Map + AMCL + TEB/DWA on
real hardware) covers ~70% of the autonomy *software* stack but only ~30% of the IPEx *mission* stack
because it has zero excavation/terramechanics. **STEWIE is the inverse:** it owns the mission-physics
"hard 30%" a terrestrial robot structurally cannot, and is weaker exactly where the testbed is strong
(real-hardware ROS2/perception/SLAM). They are **complementary**, not competing — prototype the
autonomy-software layer on the testbed, validate the excavation/terramechanics/illumination layer in
STEWIE, converge on IPEx.

### 24.1 Capability map — STEWIE actual (grounded)

| Domain | testbed | STEWIE actual | Evidence / PRD |
|---|---|---|---|
| ROS2 infra | 100% | ~50% — RC contract + SF-01 watchdog + CCSDS PitBackend + telemetry; live rclpy node bridge gated | `bridge/rc_contract.py`, `pit_backend.py`; P20 |
| Navigation | 90% | ~50% — routing, plan-view authoring, keep-outs, negative-obstacle, multi-goal; local trajectory planner N | NV-01 P, NV-03/04 N |
| SLAM/localization | 90% | ~60% — map-relative register-to-DEM, SE(2) pose graph, loop closure, Shadow-SLAM shadow-σ calib, PSR supervisor; Katwijk ATE 3.35 m; full SLAM-from-scratch N | `dart/pose_graph_se2.py`, `loop_closure.py`, `shadow_sigma_calibration.py` |
| Perception | 80% | ~40% — rock taxonomy, obstacle map, camera rig/select, dock pose; dense stereo→depth→cloud gated | PM-13..16 N |
| Mission planning | 70% | ~85% — planner, Plan IR, scheduler, `plan_multi`, challenge platform | CP-01..10 |
| **Excavation** | **5%** | **~70%** — mass-conserving cut/fill, deposit_field, drum-fill mass sensing (ICE-RASSOR FDC), IPEx dig energy; Tier-3 force-accurate drum gated | `physics/column_state.py`, `rassor_mass_model.py` |
| **Terramechanics** | **0%** | **~85%** — Bekker pressure-sinkage, slip ladder (Janosi/drawbar/entrapment/runaway), Lyasko ⅙g, tip-over stability; quantitative oracle calib deferred | `physics/terramechanics.py`, `slip.py`, `stability.py` |
| Lunar ops | 10% | ~40% — solar/shadow/PSR illumination; thermal partial; dust render-only; multi-day clock N | TW-06 D, EP-04/07 N |

**STEWIE already holds 5 of the 6 "missing" areas** the analysis flags as the differentiator (excavation
physics, regolith flow, terramechanics, wheel-slip, illumination/shadow); AutoDig is partial (dig physics
+ energy yes, adaptive control loop no), and Shadow-SLAM is real scaffolding, not just a concept.

### 24.2 Diff — three buckets
- **STEWIE owns (testbed can't):** Bekker terramechanics, slip/entrapment, mass-conserving excavation,
  drum-fill sensing, IPEx dig energy, solar/shadow/PSR, the conserved digital twin, the planner +
  multi-vehicle scheduler, Shadow-SLAM + Navigation articulation localization (the platform novelty).
- **Testbed complements (STEWIE's real gaps):** a physical robot running ROS2/Nav2/RTAB-Map/AMCL on real
  sensors — the proving ground for the autonomy software STEWIE only simulates.
- **Gaps in both (the build list):** live ROS2-Jazzy node bridge, dense stereo→depth producer, adaptive
  AutoDig, Tier-3 force-accurate drum (Chrono GPU-DEM), full fleet coordination, dust/thermal/multi-day.

### 24.3 Convergence plan (Phases A–E)
- **A. Autonomy seam** — live ROS2-Jazzy bridge (RC contract + PitBackend speak rclpy/cmd_vel); adopt the
  Autoware architecture (§16.7). Where testbed ROS2/Nav2/SLAM prototyping transfers in. (P20, AG-08 seam.)
- **B. Perception producer** — render→depth→point-cloud, unblocking PM-13..16 + dense Shadow-SLAM.
- **C. Multi-vehicle coordination** — extend `plan_multi` (allocation + space-time conflict, built) into
  fleet coordination: shared chargers/pits/corridors as reservable resources, cross-vehicle precedence,
  per-rover belief/health, exact-oracle validation; Autoware multi-robot conventions inform interfaces.
  (FL-03..07.) Progress: the shared charger AND declared resources (pit/dump/vantage/corridor) are now
  scheduled JOINTLY (`_resolve_joint_resources`, FL-03 done) — one per-vehicle delay clock over a single
  multi-server `ReservationLedger`, so the makespan/waits are the real coupled FCFS schedule, not a sum of
  independent per-server estimates; the exact 2-rover oracle (FL-06, `plan_multi_oracle`) lower-bounds +
  validates the heuristic. Per-rover belief/health + active replan on the trigger (FL-04) remain.
- **D. Excavation depth** — Tier-3 force-accurate drum (Chrono GPU-DEM) + adaptive AutoDig control. (CP-03, P7.)
- **E. Navigation contribution** — close the Shadow-SLAM + articulation-parallax loop (scaffolds exist) →
  GPS-independent PSR localization + excavation-progress tracking; the publishable contribution. (SN-*.)

Honest restatement: the "~70% software / ~35% mission" figure is the *testbed's*. STEWIE is the mirror —
~55% autonomy-software (ROS2/perception/real-SLAM is the gap), ~70% mission-physics (excavation/
terramechanics/illumination is the strength). Fastest path to an IPEx-relevant twin = **Phase A** (connect
the mission-physics twin to a testbed/Autoware-style ROS2 autonomy layer). All phases land TDD, gate
byte-identical, no synthetic data.

## 25. Full-stack onboard autonomy execution plan (2026-06-15)

This is the optimized sequence for the next autonomy build. It is deliberately ordered from
contracts -> backend -> frontend -> autonomy loops -> model integration -> hardening. Each phase is
atomic: it may touch several files, but it must ship one coherent contract or capability, with tests,
traceability, security review, and performance budget before the next phase depends on it.

### 25.1 Current codebase assessment baseline

Current front-end surface:
- `stewie/server/index.html` and `stewie/server/web/assets/cockpit.js` provide the cockpit shell,
  static tabs, plan authoring, GIS/map layers, Navigation/Estimation, Perception, Metrics, Report,
  System, Admin, and Settings.
- Navigation/Estimation already calls the `/slam`, `/slam/compare`, and `/localize/render` endpoints
  and renders trajectory/covariance evidence, but Fleet, Models, Construction Skills, and Security
  are not yet first-class work areas.
- The front end is still effectively one large cockpit script; the restructure must split by product
  work area without breaking the existing no-inline-script CSP and mobile hardening.

Current backend surface:
- `stewie/server/routers/plan.py` owns planning, math, command, and raster-layer paths.
- `stewie/server/routers/perception.py` owns compare, localize, SLAM, render, structure, and sensing
  paths, including the current Navigation/render-pair entry points.
- `stewie/server/routers/twin.py`, `admin_ops.py`, `missions.py`, `structures.py`, `config.py`,
  `layers.py`, `auth.py`, `invites.py`, `operators_admin.py`, `health.py`, and related routers cover
  world/twin state, mission persistence, access, layers, admin, health, and operator state.
- Domain support already exists for conserved terrain, Bekker/slip/stability, PlanResult-like planning,
  route planning, fleet allocation/reservation primitives, solar geometry, articulated shadow/parallax,
  pose graphs, training scripts, and model experimentation. The gap is not absence of code; it is that
  the surfaces are not yet unified by one typed onboard-autonomy contract and one cockpit workflow.

### 25.2 Build sequence

**Phase 0 — inventory and freeze the contract boundary.**
Exit: FS-01 and FS-02 are current. Produce a module map for touched frontend/backend/domain code,
define the typed contract spine, and decide which current routes remain public, which become internal,
and which need role-gated writes. Define the correlation-ID and event-ledger fields at this phase.
Do not start new UI work before the contracts and logging envelope exist.

**Phase 1 — backend contract APIs.**
Exit: typed API fixtures exist for world, fleet, navigation, ephemerides, Navigation, model artifacts, and
construction skills. Add schema validation at route boundaries and expose examples that browser tests
can load. Existing route handlers may delegate to current modules, but their payloads must match the
contract spine. Every route emits structured decision/error/latency logs with redaction and truth-firewall
checks.

**Phase 2 — front-end contract layer and cockpit restructuring.**
Exit: the cockpit has first-class work areas for Plan, Fleet, Navigation/Navigation, Perception/Imagery,
Construction, Models, Security/System, and Reports on desktop and mobile. Build this in sublayers:
first the route/state shell, then typed API adapters, then normalized view models, then shared
visualization components, then command/approval affordances. The existing plan/GIS/nav features keep
working while new panes are introduced behind typed API adapters. Every pane labels forecast,
simulated truth, estimator belief, and live telemetry explicitly. No component may fetch raw backend
JSON directly after its work area has a contract adapter.

**Phase 3 — ephemerides, azimuth, imagery, and Navigation authority.**
Exit: one sun/ephemeris/azimuth service feeds shadows, imagery layers, navigation risk, camera policy,
and Navigation. The UI displays sun elevation, azimuth convention, site frame, source/provenance, and
accepted/rejected evidence. Navigation becomes an operational loop: planned relocalization stop -> render or
camera observation -> articulation/shadow/parallax factor -> pose graph update -> cockpit evidence.

**Phase 4 — path planning, navigation, and Autoware-style execution seam.**
Exit: global planner, local planner, tracker, recovery, keep-outs, obstacle classification, height/volume
classification, slip/energy budget, and command lowering are connected by one navigation contract.
Autoware concepts may be reused at the interface level, but STEWIE's lunar terrain, illumination,
excavation, and low-g terramechanics remain the authority. ROS2 action lowering stays gated by AG-08
and SF-01.

**Phase 5 — multi-vehicle coordination.**
Exit: fleet planning moves beyond allocation into coordinated execution: per-vehicle belief/health,
shared-resource reservations, corridor/time deconfliction, charger/dock/pit conflicts, cross-vehicle
precedence, conflict explanation, and deterministic fallback. The Fleet pane must show why a rover is
waiting, blocked, replanning, or cleared.

**Phase 6 — construction skills, recorded movements, volume/height acceptance, and self-docking.**
Exit: excavation, dump, berm-shape, traverse-repeat, and dock behaviors can be recorded, versioned,
replayed, compared, approved, and corrected by estimator feedback. Obstacle size, terrain height,
cut/fill volume, berm geometry, fill fraction, slip, and docking alignment all produce uncertainty
bands and acceptance events.

**Phase 7 — model integration and fine-tuning hardening.**
Exit: terrain assessment, rock classification, Shadow-SLAM/Navigation, excavation state, regolith volume,
mission-planner LLM, and operator-assistant models are registered artifacts with lineage, model cards,
evaluation fixtures, calibration, OOD detection, quantized deployment budgets, rollback, and safe
fallback. No model gets a command path; the mission executive consumes typed outputs only.

**Phase 8 — test, optimize, secure, and release-gate.**
Exit: the slice has unit, contract, route, browser, mobile, integration, security, performance, and
traceability coverage. Optimization budgets cover map rendering, tile/cache behavior, planning latency,
fleet solve time, Navigation factor latency, model inference, memory, and bandwidth. Security review covers
auth/roles, CSP, secrets, SBOM/CVEs, backup/restore, exposed routes, command interlocks, log retention,
redaction, and replayability from event hashes.

### 25.3 Non-negotiable implementation rules

- No capability is complete unless it is visible in the cockpit, backed by a typed route, tested, and
  traceable to a PRD row.
- No learned model directly controls the rover. Models produce bounded, typed estimates; deterministic
  planners, safety checks, role gates, and the mission executive decide whether commands can be emitted.
- No solar, shadow, Navigation, or illumination result may use a private azimuth convention. The convention
  must be displayed, tested, and shared across all consumers.
- No fleet claim is complete until resource conflicts and path/time conflicts are represented in both
  the backend result and the UI.
- No self-docking or recorded construction movement may replay open loop; estimator feedback and safing
  checks are part of the primitive.
- No slice is complete without structured logs for success, rejection, failure, timeout, fallback,
  permission denial, and safing paths. Logs must be correlated across browser, backend, model runner,
  ROS bridge, simulator, and report artifacts.
- No release claim is allowed while front-end, backend, security, optimization, and test evidence are
  split across separate unverifiable narratives.

### 25.4 Front-end contracts, wiring, and windowing

The cockpit should be organized as one production application with routeable work areas, not as a set
of independent pages that each invent their own fetch/state/error logic. The contract boundary is:

```text
Backend route
  -> schema / fixture
  -> typed frontend client adapter
  -> normalized view model
  -> work-area component
  -> browser/mobile regression test
```

Required frontend contract adapters:
- `world`: body/site/time, terrain layers, illumination, ephemerides, map provenance.
- `mission`: PlanResult, command tape, feasibility, report, namespace/ownership.
- `fleet`: vehicles, assignments, reservations, conflicts, health, waiting reasons.
- `navigation`: route, local trajectory, tracker state, recovery state, keep-outs, cost layers.
- `nav`: articulation pose, camera rig, shadow/parallax factors, covariance, residual gates.
- `perception`: imagery, depth/point cloud summaries, rock/obstacle classes, height/volume estimates.
- `construction`: cut/fill state, bucket/drum fill, volume moved, berm/pad acceptance, recorded skills.
- `models`: model artifacts, datasets, eval reports, deployment profile, fallback/rollback status.
- `security`: role, permissions, command eligibility, audit events, session/auth state.
- `system`: health, metrics, storage, backups, validation gates, dependency/SBOM state.

Required log/event channels:
- `audit`: login, logout, invite, role change, permission decision, namespace publish/delete/restore.
- `mission`: mission create/save/load, plan request, feasibility result, replan, report export.
- `command`: command eligibility, approval, lowering, dispatch, acknowledgement, timeout, SAFE.
- `world`: TwinStore/timeline event, terrain mutation, observed patch, backup, restore, provenance.
- `navigation`: route request, local-plan update, tracker state, recovery action, blocked reason.
- `nav`: sun/azimuth source, observation, residual, covariance, accepted/rejected factor.
- `fleet`: reservation, conflict, wait reason, handoff, deconfliction, reassignment.
- `model`: artifact selected, version, input/output hashes, confidence, OOD/fallback, latency.
- `frontend`: pane route, contract adapter error, empty/loading/error state, command affordance shown.
- `system`: startup, config, dependency, storage, health, metrics, security scan, backup drill.

Wiring order for each work area:
1. Add or freeze the backend response schema and example fixture.
2. Add the frontend adapter and normalized view model.
3. Render a fixture-only empty/loading/error/success pane.
4. Connect the live route behind the adapter.
5. Add route, permission, mobile, and failure-mode tests.
6. Only then expose the pane in the primary cockpit navigation.

Windowing decision:
- **Production operations use one browser cockpit.** A commandable mission must not require two
  browser windows, because duplicated command state, stale approvals, and split role context are safety
  risks.
- **A second browser window is allowed only as read-only support context**, for example a detached
  telemetry/evidence display for a director or reviewer. It mirrors state from the primary cockpit and
  has no unique command buttons, approvals, or hidden state.
- **Engineering tools are separate by design.** RViz, Gazebo, ROS2 CLI, bag replay, and Godot render
  diagnostics may run in separate windows during development, but they are not the operator interface
  and must not bypass AG-08, SF-01, role gates, or the cockpit audit trail.
- **Large screens use panes, not independent authority.** The preferred production layout is a single
  routeable cockpit with optional split panes: map/world left, selected work area right, evidence drawer
  bottom, command/approval rail explicit and role-gated.

### 25.5 Code-grounded architectural review and reconciliation

The current PRD is not allowed to be treated as automatically current. The completion path is a
code-grounded reconciliation sweep, then implementation of the truly-open subset. Each row reviewed
gets one of four labels:

| Label | Meaning | Action |
|---|---|---|
| DONE-stale | Code and tests satisfy the requirement, but the PRD row is stale. | Correct the PRD status and add/verify `[REQ:<ID>]` trace markers. |
| PARTIAL | Some implementation exists, but product integration, tests, qualification, or frontend wiring is incomplete. | Record the missing link and smallest atomic follow-up. |
| OPEN | No meaningful implementation exists. | Keep the row open and sequence it into §25.2. |
| BLOCKED | Implementation requires external data, hardware, licensing, deployment, or qualification. | Name the blocker and avoid claiming completion. |

Reconciliation evidence format:

```text
REQ-ID:
  status: DONE-stale | PARTIAL | OPEN | BLOCKED
  evidence:
    - file:line implementation
    - file:line test
    - file:line frontend/backend wiring, if applicable
  missing:
    - smallest next action, or "none"
```

First verified stale-done correction:
- `CT-04` is no longer `N/N/N`. `stewie/twin/io_fields.py` publishes scene rasters atomically,
  validates raster dimensions before writing, writes `metadata.json` last as the commit marker, and
  removes stale optional contract rasters on republish. Existing tests cover commit-marker behavior,
  no leftover `.tmp` files, and incomplete-scene rejection; the PRD row is corrected to `D/P/D/NA`.

Architectural review scope for the next sweep:
- Contracts and authority: CT, TW, VT, AG, FS rows plus manifest drift.
- Terrain, energy, vehicle, terramechanics: real authority versus calibrated/oracle gaps.
- Perception, Navigation, SLAM, imagery, small models: backend reachability, truth firewall, UI evidence.
- Navigation, construction, fleet: PlanResult, local planner, resource conflicts, execution feedback.
- Frontend organization: every top-level work area must have a contract adapter, route/state binding,
  role gate, fixture render, mobile layout, error/empty states, and log visibility.

The review output should feed §7 status corrections first, then implementation. A row that is stale
done should not consume implementation time; a row that is partial should be split into the exact
missing backend route, frontend adapter, test, log, or qualification slice.

