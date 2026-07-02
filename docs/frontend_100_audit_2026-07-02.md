---
title: STEWIE Frontend 100 Percent Audit Boundary
nav_order: 57
---

# STEWIE frontend and product audit - 2026-07-02

This audit compares the current STEWIE cockpit, public pages, settings/admin surfaces, frontend
wiring, world-model/digital-twin UX, ArcGIS-style GIS capability, and deployed app behavior against
the updated PRD and the frontend design contract.

## Audit boundary

Audited completely from the available workspace:

- Updated PRD requirements, especially product modes, autonomy sequence, depth-source neutrality,
  runnable profiles, run-everything gate, and backend-to-frontend WMDT mapping.
- Local cockpit shell and assets under `stewie/server/index.html` and `stewie/server/web/assets/`.
- Existing frontend design/audit docs and ArcGIS parity docs.
- Local automated tests that can run in the current host environment.
- Deployed unauthenticated surfaces at `https://app.stewie.space/`, `/app`, `/program`, and `/landing`
  across desktop and mobile viewports.

Not honestly audit-complete without more access or environment setup:

- Authenticated deployed role-by-role behavior for trainee, operator, director, admin.
- Live ROS2, Gazebo, RViz, rosbag replay, Jetson/HIL, sensor bench, or rover bench evidence.
- Production data retention, scheduled backup, runtime profiles, and real operator audit trails.
- Hardware telemetry, real stereo/LiDAR/RGB-D calibration, and live command authority.

So the result is a 100 percent audit of the accessible code, PRD contract, tests, and public deployed
surface. It is not a 100 percent acceptance certification of the whole mission system.

## Evidence collected

- JS frontend module tests: `node --test stewie/server/web/assets/*.test.js` passed 277/277.
- Focused UI/server tests: `pytest -q -o addopts=''` over the cockpit/auth/admin/UI subset passed
  109/109.
- Full `stewie/server` package test: `pytest -q -o addopts='' stewie/server` produced 818 passed,
  16 failed, 13 skipped. Failures cluster around unauthenticated DEM egress expectations and missing
  optional host deps: `pyproj` and `gymnasium`.
- Default pytest command is not runnable in this host because `pyproject.toml:96` injects
  `--timeout=600` and the current environment lacks `pytest-timeout`; the dependency is declared in
  the dev extra at `pyproject.toml:37-40`.
- Deployed Playwright snapshots saved under `/mnt/projects/`:
  - `stewie-app-desktop-wide-snapshot.md`
  - `stewie-app-mobile-snapshot.md`
  - `stewie-program-desktop-snapshot.md`
  - `stewie-program-mobile-snapshot.md`
  - `stewie-root-desktop-snapshot.md`
  - `stewie-landing-desktop-snapshot.md`
  - `stewie-landing-mobile-snapshot.md`
- Deployed console evidence: `/mnt/projects/.playwright-mcp/console-2026-07-02T17-20-45-302Z.log`.

## Severity-ranked findings

### P0 - Runtime identity and mode model do not match the PRD

The PRD requires every screen to expose product mode, runnable profile, selected sensor profile,
command-authority state, and truth-denial label (`PRD.md:1155-1159`). Product modes are explicitly
`GIS-PLAN`, `TRAIN`, `SIM-OPERATE`, `EVALUATE`, and future `OPERATE` (`PRD.md:404-418`).

The routeable state model only has `SOURCES = ["live", "sim", "eval"]` and
`MODES = ["sandbox", "live"]`, with default `mode: "live"` and `source: "sim"`
(`stewie/server/web/assets/cockpit_state.js:8-12`, `:27-30`). That conflates namespace/workspace
with product mode and cannot represent `desktop_sil`, `digital_twin`, `ros2_replay`,
`hil_jetson`, `sensor_bench`, `rover_bench`, `field_traverse`, or `monte_carlo`
(`PRD.md:1254-1271`).

Impact: operators cannot reliably distinguish simulation, forecast, replay, HIL, evaluation, and
future live operation from route state alone. This is the central blocker for "run everything."

### P0 - Sensor/LiDAR swappability is specified in the PRD but not yet operator-selectable

The PRD is correct now: depth is source-neutral and LiDAR, stereo, RGB-D, and replay are profiles
behind `DepthObservation` or `PointCloud2` (`PRD.md:1219-1252`). The UI design contract repeats the
same requirement (`docs/full_stewie_frontend_design_2026-07-01.md:49-62`).

The current cockpit perception state hardcodes `source_profile: "stereo_sgbm"` and a single
`/stewie/perception/points` topic (`stewie/server/web/assets/cockpit.js:945-959`). The point-cloud
loader reads static `assets/perception/pointcloud.json` and `pointcloud.png`, falling back to
`stereo_sgbm` (`cockpit.js:1013-1035`). There is no visible runtime selector for `lidar`, `rgbd`,
`replay`, or `stereo_neural`, no calibration identity selector, no profile freshness gate, and no
Release/Execute block tied to selected depth-source thresholds.

Impact: the architecture is LiDAR-swappable on paper, but the current operator path is still
stereo-sample-oriented.

### P0 - ROS/Gazebo/RViz are required by the PRD but not first-class cockpit evidence surfaces

The PRD requires ROS diagnostics with lifecycle state, Gazebo bridge status, RViz config/run status,
bag replay, topic freshness, QoS warnings, latency, dropped frames, bridge status, and container
profile (`PRD.md:1147-1149`, `:1181-1190`). The run-everything gate requires RViz or cockpit evidence
screenshot plus report artifacts linking requirement IDs and run IDs (`PRD.md:1287-1322`).

Current System support is mostly server/admin oriented: Twin snapshot, Retention, Replicate backup,
Validate gates, event history, and server health/metrics (`stewie/server/index.html:1338-1352`).
Validate subtabs are Navigation, Perception, and Solar only (`index.html:879-884`), while the PRD
requires Perception, Navigation, Mapping, ROS/Gazebo, and Evidence panes (`PRD.md:1166-1169`).

Impact: a ROS2/Gazebo/RViz MVP can be built, but the cockpit does not yet make it auditable or
profile-complete.

### P0 - Release/Execute do not yet enforce the full command-evidence contract

The PRD requires Release to show immutable revision, runtime profile, namespace, sensor/depth-source
profile, AG-08 eligibility, sign-off, and artifact links (`PRD.md:1170-1172`). Execute must show only
bounded next segment/action goal, acknowledgements, watchdog/link state, SAFE/pause/replan controls,
covariance, map freshness, and refusal reasons (`PRD.md:1173-1175`).

The Release pane signs via `/executive/release-plan` and displays the signed revision and plan ID
(`stewie/server/web/assets/cockpit.js:2347-2389`). However the release request body carries body,
orders, mission ID, and optional solver algorithm, not runtime profile, sensor profile, ROS namespace,
or AG-08/SF-01 evidence (`cockpit.js:2366-2370`). Execute starts a director-only SIM run through
`/executive/run` and streams events (`cockpit.js:2433-2468`), but the cockpit does not yet expose a
single command-eligibility card with AG-08/NV-12/SF-01 refusal reasons.

Impact: the mission lifecycle exists, but the safety/operator evidence contract is incomplete.

### P1 - Mobile cockpit chrome still overflows and exposes offscreen controls

On deployed mobile `/app`, the sidebar is visually offscreen but remains in the accessibility tree at
negative x positions (`/mnt/projects/stewie-app-mobile-snapshot.md:3-74`). The health chip at x=356
with width 44 clips the text `OK up 48m FRESH`, and the alert button is offscreen at x=410
(`stewie-app-mobile-snapshot.md:76-83`). The stepper extends to x=913 on a 390px viewport
(`stewie-app-mobile-snapshot.md:84-95`).

On desktop `/app`, the stepper also exceeds the stage width: the Report button starts at x=1444 on a
1440px viewport (`/mnt/projects/stewie-app-desktop-wide-snapshot.md:84-95`).

Impact: command/status affordances are partially hidden at the exact viewport where touch operation
matters.

### P1 - `/program` mobile layout overflows

At 390px wide, deployed `/program` has document scroll width 595px. The main content and panels render
as 575px wide children (`/mnt/projects/stewie-program-mobile-snapshot.md:5-23`). The requirement board
and filter chips remain wider than the viewport (`stewie-program-mobile-snapshot.md:29-43`).

Impact: the program board is not a reliable mobile status/requirements surface.

### P1 - Public cockpit boot fires protected requests before auth is resolved

The deployed root/app page opens behind the Operator Access modal, but still fetches protected
resources and logs 401s for DEM workarea, events, DEM sources, profiles, missions, sites, georef, and
custom structures (`/mnt/projects/.playwright-mcp/console-2026-07-02T17-20-45-302Z.log:1-7`,
`:15`). The password input is also outside a form (`console log:8-14`).

Impact: first-load telemetry is noisy, unauthenticated state is harder to reason about, and automated
browser smoke tests will flag console errors even when the app is merely gated.

### P1 - World-model/digital-twin UI exists but is not yet the full WMDT operator surface

The PRD requires backend WMDT objects to have explicit cockpit surfaces and command consequences
(`PRD.md:1659-1688`). The current cockpit has useful pieces: Report loads `/world/transaction`,
`/world/transactions`, and `/world/terrain_view` (`cockpit.js:2394-2428`); Construction has Terrain
Memory and a Record Plan action (`stewie/server/index.html:1268-1274`).

Missing relative to PRD:

- System twin/provenance pane with world hash, chain hash, checkpoint age, replay divergence, and
  unresolved sync mismatch (`PRD.md:1679`).
- Execute/System comms pane with link state, one-way/ack latency, command eligibility, and comm-loss
  fallback reason (`PRD.md:1681`).
- Fault/health pane with active fault class, severity, derating/safe action, and remaining-life
  estimate (`PRD.md:1683`).
- Report evidence bundle with requirement IDs, run IDs, screenshots, logs, bag links, validation JSON,
  pass/fail/refuted labels, and Graphify diagnostics (`PRD.md:1176-1177`, `:1189-1190`, `:1688`).

Impact: the world model is present as data and some report cards, but not yet as a complete command
and evidence operating picture.

### P1 - Settings and admin are real, but not yet full operational governance

Settings are browser-local display preferences: theme, account, font size, named layout, idle timeout,
and local workspace reset (`stewie/server/index.html:1354-1397`). Named layouts persist via
`localStorage` and are explicitly view-only (`cockpit.js:2251-2261`). Admin supports operator create,
invite, approve, role, revoke, reset password, delete, per-user login history, and audit events
(`index.html:1423-1448`, `cockpit.js:2134-2240`).

Missing:

- Durable settings for runnable profile, sensor profile, depth source, calibration ID, container/runtime
  profile, evidence retention policy, ROS/Gazebo/RViz profile, and operator defaults.
- Admin controls for profile governance, evidence retention schedules, backup status, ROS/runtime
  process status, key rotation, role-scoped mode availability, and hardware/simulation command locks.
- A deployed authenticated audit pass to verify these actions under real roles.

Impact: account administration is meaningful, but mission-system administration is not yet complete.

### P1 - ArcGIS parity is strong in domain GIS, weak in general GIS platform UX

The existing ArcGIS parity assessment is directionally correct: STEWIE exceeds general GIS tools on
conserved terrain memory, mission-intent authoring, mass-conserving excavation replay, lunar solar
geometry, and operational twin execution (`docs/stewie_arcgis_parity_2026-06-29.md:15-32`). It is
ArcGIS-grade for raster layer math, least-cost path routing, GeoJSON interchange, contents/layer tree,
3D scene drape, basemap management, opacity, CRS transform, and coordinate readout
(`docs/stewie_arcgis_parity_2026-06-29.md:34-39`).

Current gaps remain important for product completeness:

- No served OGC service (`docs/stewie_arcgis_parity_2026-06-29.md:43-46`).
- Display RGBA layers rather than persisted value rasters/map algebra surfaces (`:46`).
- No bring-your-own DEM upload (`:47`).
- Create-only map editing, no move/reshape/vertex edit (`:48`).
- Fixed symbology/classification and no print composer (`:49-50`).

Impact: STEWIE is a strong lunar mission GIS, not yet an ArcGIS-like platform.

### P2 - Frontend architecture still concentrates too much risk in the shell

The repo has many tested pure JS modules, but the cockpit shell remains large:
`stewie/server/web/assets/cockpit.js` is 6201 lines and `stewie/server/index.html` is 1547 lines.
A raw search for `fetch(`, `innerHTML`, `localStorage`, `EventSource`, and browser confirm/prompt sites
returns 300 matches in `cockpit.js`.

The PRD requires typed adapters and view models instead of raw backend JSON or ad-hoc global state
(`PRD.md:1192-1195`). The current architecture has started that migration, but shell behavior still
contains many direct fetches and direct DOM sinks.

Impact: feature work is possible, but shell regressions are likely unless CI gains a Playwright smoke
test over the full routed cockpit.

## Page-by-page coverage

| Surface | Current state | Missing against PRD |
|---|---|---|
| Landing | Public `/landing` is responsive on mobile and desktop; no horizontal overflow found. | Needs to stay non-authoritative and link into authenticated app/program without implying live readiness. |
| Root/App | Cockpit loads, auth modal gates use, Plan map appears behind modal. | Protected fetches fire before auth; mobile and desktop chrome overflow; no explicit product mode/profile/sensor rail. |
| Program | Requirement matrix and fanout summary are public and useful. | Mobile width overflow; not yet a full release dashboard for run-everything artifacts. |
| Plan | Strong domain authoring: site, layers, rovers, orders, solver, missions, link profiles. | Must add selected depth-source profile, runtime profile, evidence requirements, calibration status, and WMDT provenance as first-class inputs. |
| Rehearse | Director-gated candidate comparison exists. | Needs operator read-only state, candidate adoption into immutable release body, costmap explanations, failure branches, and scenario/runtime profile labels. |
| Validate | Navigation, Perception, Solar panes exist. | Missing Mapping, ROS/Gazebo, Evidence panes; no complete `DepthObservation`/PointCloud2 health card or no-truth-input assertion card. |
| Release | Director sign-off and signed revision flow exist. | Missing runtime profile, namespace, sensor profile, AG-08/SF-01 eligibility, artifact links, and profile mismatch blockers. |
| Execute | SIM run stream exists and labels forecast/sim behavior. | Missing bounded next-command card, watchdog/link ack, SAFE/pause/replan control set, command refusal ledger, covariance/map freshness gate. |
| Report | PDF report, world-state overlay, terrain provenance, dashboards exist. | Missing complete evidence bundle: requirements, bag/log links, RViz screenshot, metrics JSON, claim labels, pass/fail/refuted status. |
| Fleet | Vehicle roster and last-plan allocation are wired. | Missing live fleet pose/SoC/last-seen/reservation conflict state for Execute/System. |
| Construction | Catalog, acceptance, terrain memory, record action exist. | Needs clearer conserved-world transaction consequence, terrain diff review, and evidence links before mutation. |
| Models | System/vehicle/body registries and ML governance are wired. | Needs operator-facing runtime/sensor/depth profile governance and calibration provenance. |
| Trainer | Program history, director truth board, and debrief scrubber are wired. | Needs clearer `TRAIN` mode identity and role-isolated truth-denial rail on every screen. |
| System | Health/metrics, events, backup/snapshot/gates/config exist. | Missing ROS node health, topic freshness, QoS, bridge status, Gazebo/RViz/bag status, container profile, twin sync status. |
| Settings | Local display/layout/account preferences exist. | Missing durable operational settings for runtime profile, sensor profile, evidence retention, ROS/Gazebo/RViz defaults. |
| Admin | Accounts, invites, roles, revoke/reset/delete, login history, audit events exist. | Missing mission-system admin for profiles, retention schedules, runtime process governance, hardware/live locks, and authenticated deployed verification. |
| Evidence | Navigation evidence route exists. | Needs global evidence drawer for any selected decision with requirement IDs, fixtures, bags, metrics, screenshots, logs, and report links. |

## Recommended build sequence

1. Replace `sandbox/live` plus `live/sim/eval` with explicit product mode, runnable profile, source
   class, selected sensor profile, and command-authority state in `cockpit_state.js`.
2. Add the always-visible mode/profile/sensor/authority/truth rail and make mobile/desktop share the
   same state model.
3. Add Sensor Profile and Depth/Cloud Health cards, with `stereo_sgbm`, `stereo_neural`, `lidar`,
   `rgbd`, and `replay` as selectable profiles behind one `DepthObservation` view model.
4. Add ROS/Gazebo/RViz status cards under Validate/System and require their artifacts in Report for
   `ros2_replay`, `digital_twin`, and `hil_jetson` profile claims.
5. Wire Release/Execute to runtime profile, sensor profile, namespace, command eligibility, watchdog,
   link ack, covariance, map freshness, and refusal reasons.
6. Complete the Evidence drawer and Report bundle as the universal objective gate for PRD rows and
   run-everything claims.
7. Fix deployed mobile overflow in `/app` and `/program`; hide/inert offscreen sidebar controls from
   accessibility until opened.
8. Add one deployed-style Playwright smoke tier that opens root/app/program/landing, checks desktop and
   mobile widths, clicks the mission spine, and fails on unexpected console errors.
9. Move cockpit shell fetch/DOM behavior incrementally behind typed API/view-state adapters.
10. Add ArcGIS leverage items in this order: OGC tile service, value raster/COG outputs, DEM upload,
   edit/reshape tools, classification/symbology controls, and map capture/print composer.

## Bottom line

The updated PRD does not need a major conceptual expansion for stereo-as-virtual-LiDAR, LiDAR
swappability, ROS2/Gazebo/RViz, simulation-first development, ARGUS/ShadowNav, or the full WMDT loop.
Those concepts are now represented in the PRD.

The build is not yet fully taking advantage of that PRD. The missing work is primarily productization
and wiring: explicit mode/profile state, sensor profile selection, ROS/Gazebo/RViz evidence, command
eligibility cards, complete evidence bundles, mobile reliability, durable operational settings, and
authenticated deployed role verification.
