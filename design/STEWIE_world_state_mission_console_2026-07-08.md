# STEWIE — World-State Mission Console (external UI/UX review, 2026-07-08)

**Source:** Aaron's external reviewer assessment of the artemis IDE mission planner (rated ≈8.5/10 — "already a
mission operations console, not a game UI"). Captured verbatim-in-spirit + audited against the live code so the
autonomous loop builds the GAPS, not what already exists. **Sequencing:** folded into the product roadmap AFTER
the quality campaign (#55) is clean; this is the north star, not a stop-everything redirect.

## Central thesis (the north star)

**Shift from a COMMAND-driven interface to a WORLD-STATE-driven one.** Every plan should be based on the
*current* state of the lunar world model; every executed mission should *modify* that state; every modification
should automatically become part of the historical record used for future planning, validation, and learning.
Make the persistent lunar world model the centerpiece. This is what distinguishes STEWIE from a conventional
robotics mission planner and aligns it with the digital-twin / world-model dissertation direction.

**Good news from the audit:** STEWIE already has the world-state BACKBONE — the observed twin (DT-04/05,
per-(site,source), versioned + chain-verified), the as-built TerrainMemory, and the SIM **execute→remember**
loop (a completed run folds its terrain into TerrainMemory + records belief/authority into the DT-01 log). The
review is mostly about CENTERING that in the UI, not building new world-state machinery.

## The 7-phase reorg (replaces the one long scrolling panel)

`🌍 World State` → `🗺 Planning` → `🤖 Resources` → `🧠 AI & Optimization` → `🎮 Simulation` → `🚀 Deployment`
→ `📈 Mission Review`. Collapsible phases mirroring the mission-engineering workflow. (Today the Plan sidebar is
7→4 sections + the ConOps spine; this is a fuller reorg around the world model.)

**RECONCILIATION (2026-07-08, post-b833069):** the artemis /ide Map & Tools menu is NOW the ConOps spine itself
— Plan → Rehearse → Validate → Release → Execute → Report → Support (shipped b833069). So this 7-phase reorg is
NOT a menu re-structure to build — the ConOps spine is the delivered surface. The world-state thesis lands as
(1) the World-State header strip + the panels below as ADDITIONS foregrounded within the existing ConOps stages
(World State / Layers / Timeline → Plan+Validate; Simulation → Rehearse; Twin Health / Playback → Execute;
Learning / Report / Future-comparison → Report), and (2) the RESEARCH / OPERATE / TRAIN mode-lens (PRD FS-32)
RE-FOREGROUNDS which of these ConOps panels are prominent per mode WITHOUT changing the selected mission / world
/ authority or re-structuring the menu. Do not rebuild the spine; layer the world-state panels + the mode-lens
over it.

## Section-by-section: proposed vs EXISTING vs action

| Section | Proposed | Live-code status (audited) | Action |
|---|---|---|---|
| **World State header** | Mission · Digital Twin sync · Terrain Version · Changed-since-last-mission · Confidence · Learning Dataset · Pending Validation | NEW panel. Data mostly composable: `/twin/version` (version+chain), the observed-fraction confidence (DT-05), MissionHUD mission-time. Learning-dataset size + pending-validation = NEW surfaces. | **BUILD** a permanent top World-State strip from existing endpoints; add the 2 new counters. |
| **Layers** | DEM/Hillshade/Traversability/Risk/Ice/Slip/LocalizationConfidence/WheelTracks/ExcavationHistory/Planned+ActualRoute/SensorCoverage/Comms/BatteryCost/DigitalTwinDiff | PARTIAL — the 65-layer catalog + MissionLayers tree EXIST (base/terrain/hazard/traffic/regolith/physics/…). Missing kinds: ice-probability, localization-confidence, sensor-coverage, comms, digital-twin-difference. | **PROMOTE + EXPAND** — the reviewer's "largest omission" is really "make the existing catalog prominent + add the missing kinds." |
| **Mission Timeline** | Behavior-tree-like sequence (not one flat queue) | PARTIAL — the executable **Plan IR** (typed actions GoTo/Excavate/CutHaulFill/Import/Sinter + a precedence DAG + plan_id) EXISTS. | **VISUALIZE** the existing Plan IR as a timeline/behavior-tree. |
| **Simulation pipeline** | Generate Plan → Simulate → Review → Approve → Deploy | PARTIAL — the ConOps spine Plan·Rehearse·Validate·Release·Execute EXISTS; Release is director-gated. | **REFRAME** the ConOps as an explicit pipeline with the Simulate step surfaced. |
| **Digital Twin Health** | Localization/Map-agreement/Terrain/Wheel/Battery/Excavation model % | PARTIAL — twin version + chain-valid EXIST; the per-model trust %s are research metrics not yet surfaced live. | **BUILD** a twin-health panel; wire the model-agreement metrics (some new). |
| **Mission Playback** | Replay with speed + sensor/slip/terrain/energy toggles | EXISTS — the Execute pane replays a SIM run via SSE (just hardened: id:/resume). | **ENHANCE** with speed + layer toggles. |
| **Learning** | Collect Experience · Generate Dataset · Retrain Traversability/Slip/Energy · Evaluate Policy | NEW IDE surface. The roversim RL stack (envs, PPO/CEM, world-model) EXISTS but is not exposed in the IDE. | **BUILD** a learning-lifecycle panel (the biggest genuinely-new capability). |
| **Approval Gate** | Generate → Run Physics → Validate → Human Approval → Export → Deploy ROS2 | PARTIAL — Release sign-off + the executive release-plan gate EXIST; the full NASA-style gate chain is not one surface. | **REFRAME/EXTEND** into an explicit gate with the ROS2 export step. |
| **Mission Report** | Auto per-mission card (time/distance/excavated/fill/slip/energy/loc-error/battery/terrain-modified/confidence) | PARTIAL — EV-01 evidence bundle + the plan PDF/MD report EXIST. | **ENHANCE** into an auto-generated per-mission report card = mission log + training metadata. |
| **Future comparison** | Show tradeoffs (Future A/B/C: kWh/hours/slip/recharge/completion) | EXISTS — forward-compare across planners (Greedy/OR-Tools/Held-Karp/…). | **EXPAND** the readout into a side-by-side tradeoff card. |

## Phased build plan (prioritized by the world-state thesis; AFTER campaign #55)

1. **World-State header + Layers promotion** (the two that most directly realize "world model is the
   centerpiece"; both largely surface existing data). Highest leverage, lowest new-machinery.
2. **Mission Report card + Future-comparison tradeoff readout** (surface existing EV-01 + forward-compare as
   decision tables — mission planners think in tradeoffs).
3. **Mission Timeline (Plan IR viz) + ConOps→pipeline reframe + Approval Gate** (make the plan→sim→approve→
   deploy spine explicit).
4. **Digital Twin Health panel** (some new metrics — wire the model-agreement %s).
5. **Mission Playback enhancement** (speed + layer toggles on the existing SSE replay).
6. **Learning panel** (the largest new capability — expose the RL/retraining lifecycle; couples to the
   execute→remember loop that already exists).
7. **7-phase collapsible reorg** (do last, once the panels exist, so the reorg has real content to organize).

## Honesty notes

- Claims marked "EXISTS" are confirmed against code seen this session (layer catalog, MissionLayers, ConOps
  spine, SSE run playback, twin version/chain, TerrainMemory, EV-01, forward-compare, Plan IR).
- "the roversim RL stack EXISTS but not in the IDE" + the twin-health model-% metrics are **inferred** — verify
  the live surfaces/endpoints before building the Learning + Twin-Health panels.
- Several proposed layers (ice-probability, localization-confidence, sensor-coverage, comms, twin-difference)
  may need a real backend producer — per the no-synthetic rule, wire real data or mark the layer unavailable;
  do not fabricate a drape.

---

## Extension pt.2 (2026-07-08): STEWIE as an operational OS + the RESEARCH / OPERATE / TRAIN mode switch

**Bigger philosophy shift (Aaron):** for production (NASA / commercial ISRU / terrestrial autonomous
construction) STEWIE should resemble mission-control / mine-planning / fleet-management / SCADA software, not a
collection of planning widgets. **Intent-driven, NOT algorithm-driven:** the operator states an OBJECTIVE
("build a 100 m haul road between the dig site and the plant before sunset, keeping all rovers >30% battery");
STEWIE translates intent → optimization problems. The operator never picks "nearest-neighbour, 25° slope".

**Workspaces (STEWIE = the OS for lunar construction):** Operations (supervisor: current mission / fleet /
hazards / comms / alerts / timeline / approvals) · Planning (engineer: excavate/construct/transport/survey/
inspect/maintenance/emergency/templates as WORK ORDERS) · World Model (the heart: Moon version / terrain
changes / twin health / confidence / surface age / traffic history / resource map / localization quality /
predicted changes) · Fleet (SCADA: per-rover status/battery/bucket/health/ETA) · Simulation (preview / run
physics / stress test / FAILURE INJECTION: night ops, comm loss, wheel/sensor failure, dust) · Execution
(mission control: deploy/pause/abort/resume/replan/manual) · Replay (full recording).

**Intent → work orders:** Mission Goal (Construct Landing Pad) → Survey → Remove 32 m³ → Transport → Compact →
Validate → Inspect → Approve. **NASA approval chain:** Draft → Automated → Physics → Safety → Energy →
Operator Review → Approval → Deployment. **Learning is BACKGROUND for operators:** Mission Complete → Archive →
Generate Dataset → Nightly Retrain → Benchmark → Deploy Improved Policy — operators just benefit over time.

**THE architectural distinction — the MOON IS THE DATABASE:** the Moon is the persistent, version-controlled
object; every mission updates it; the world accumulates operational history (Moon → M1 → Moon' → M2 → … → M500).
Every wheel track / excavation / berm / foundation / haul road becomes part of the environment. STEWIE ALREADY
has the substrate: the versioned observed twin + as-built TerrainMemory + the SIM execute→remember loop. This
is the novelty that distinguishes STEWIE from conventional robotics mission planners.

**The mode switch — RECOMMENDED = 3 lenses on ONE world model** (Aaron's "research vs live? or training?"):
- **RESEARCH** — algorithm-forward: planner selection + comparison + benchmarking, raw GIS layers, controlled
  experiments. The dissertation surface (the current interface, refined).
- **OPERATE** (Live) — intent-forward: objective → optimization; mission control; fleet SCADA; NASA approval
  gates; alerts/hazards. Algorithms + ML HIDDEN.
- **TRAIN** — lifecycle-forward (ML engineer): collect experience → dataset → retrain → benchmark → deploy
  policy. (In OPERATE this runs invisibly in the background.)
The three share the SAME persistent world model + physics authority; the mode changes which persona's controls
are foregrounded, never the underlying truth. Personas: researcher / operator / ML-engineer.

**Stack mapping (long-term OS vision):** QGIS = engineering/planning workspace · Godot = the operator's
immersive digital twin + mission viz (the drive-in-Godot #63) · Gazebo = vehicle-dynamics / excavation / sensor
validation · ROS2/Nav2 = execute approved missions (sim or physical) · **STEWIE = orchestrates the whole
lifecycle** (plan → validate → deploy → execute → monitor → world-update → improve) on the evolving lunar world
model as the SINGLE SOURCE OF TRUTH. Scales from one research rover to many autonomous construction assets over
months/years on a continually changing surface.

**Status:** north-star vision captured. Mode-set + sequencing pending Aaron's confirmation.

---

## Extension pt.3 (2026-07-08): Mission Tasks palette — capability + work-package, not geometry

**Reframe "Tool Palette" → "Mission Tasks" (Aaron):** operators think in WHAT-TO-BUILD, not geometry — not "I
want to cut" but "I need to build a landing pad"; STEWIE decomposes it into cut/fill/traverse automatically.
**This backend capability ALREADY EXISTS** — structure templates (LandingPad/HaulRoad/Berm/…) decompose into
mass-balanced cut/fill with per-structure constructability evidence (bearing/sinkage/slip). The reframe leads
the PALETTE with the work-packages instead of the primitives + adds the wizard/dynamic/context UX.

**Functional groups (each two-level: Primitive Ops + Templates):**
- **Earthworks** — primitives: Excavate/Dig/Dump/Push/Grade/Level/Scarify/Rip/Compact/Trench/Drill/Backfill/
  Stockpile/Spread. Engineered-feature templates: Landing Pad/Haul Road/Berm/Crater Fill/Habitat Foundation/
  Solar Pad/Cable Trench/Radiation Shield/Drainage Channel/Ramp/Anchor.
- **Transportation** — Haul/Transfer/Return/Recharge/Standby/Escort/Follow.
- **Construction** — Landing Pad/Road/Berm/Habitat Pad/Solar Field/Cable Trench/Anchor/Foundation.
- **Survey** — Stereo Survey/Panorama/Inspection/Resource Scan/Localization Pass/Calibration/Change Detection.
- **Science** — Collect Sample/Core Sample/Deploy Instrument/Beacon/Reflector/Marker/Target.
- **Fleet** — Assign Rover/Hauler/Charger/Maintenance/Recover/Tow.

**Intelligent Templates (intent→decomposition, concretized):** selecting "Landing Pad" launches a wizard
(Length/Width/Bearing Capacity/Surface Finish/Flatness Tolerance/Finished Elevation/Material Source/Priority) →
STEWIE computes cut + fill polygons + equipment + routes + time + energy + risk, expanding to the work order
Survey → Excavate → Move Material → Grade → Compact → Inspect → Approve.

**Dynamic palette (rover-dependent):** tools depend on the SELECTED vehicle's capabilities — Excavator: Dig/
Dump/Compact/Grade; Survey rover: Stereo Survey/Localization/Inspection/Mapping; Hauler: Haul/Dump/Recharge/
Transfer. The UI reflects the real vehicle registry.

**Object palette (separate from operations; persists in the world model):** Beacon/Instrument/Sample/Antenna/
Habitat/Power Station/Relay/Charging Station/Storage Bin/Processing Plant/Navigation Marker. (STEWIE already has
place-object markers beacon/cache/instrument/sample/antenna — expand the vocabulary + persist to the twin.)

**Smart context (context-sensitive):** selecting an EXISTING world-model feature (e.g. a berm) changes the
palette to Inspect/Extend/Repair/Remove/Compact/Survey Berm. Tools follow the selected object's type + state.

**Existing-vs-new:** structure templates + cut/fill decomposition + constructability evidence EXIST (backend);
place-object markers EXIST. NEW: the capability/work-package palette framing, the template WIZARDS, the
rover-dynamic palette, the object-palette expansion, and smart-context. Largely a UX reframe over existing
backend capability + a richer template/wizard layer.

## Consolidated build order (the whole 2026-07-08 arc, AFTER campaign #55)

1. **Mission Tasks palette reframe** (work-package-first over the EXISTING structure-template decomposition) +
   **World-State header/centerpiece** — the two highest-leverage, both mostly surfacing existing backend.
2. **Mode scaffold** (Research / Operate / Train toggle over one world model) — thin at first (re-skins which
   controls are foregrounded), deepens over time.
3. Layers promotion + expansion · Mission Report card · Future-comparison tradeoff table.
4. Intent→optimization translation (objective sentence → constraints → planner) · template wizards.
5. Fleet SCADA · Execution/Mission-Control controls · NASA approval chain.
6. Digital-twin health · prediction-vs-reality · Mission Playback enhancement.
7. Learning (background in Operate; foreground in Train) · 7-phase collapsible reorg last.
The MOON-AS-DATABASE substrate (versioned twin + TerrainMemory + execute→remember) already exists — the arc is
about CENTERING it in the operator experience.
