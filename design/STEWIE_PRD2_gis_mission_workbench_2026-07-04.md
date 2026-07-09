# STEWIE PRD2 - GIS-First Lunar Mission Workbench

Date: 2026-07-04  
Status: product/workflow companion to `design/STEWIE_PRD_v8_2026-07-04.md`  
Purpose: capture the new GIS-user mentality before implementation continues.

## Verdict

The current PRD v8 is a cleanup and execution campaign. It is useful for sequencing rows, CI recovery, and hardening, but it is not yet the product PRD that explains how a GIS operator, mission planner, robotics engineer, and director should experience STEWIE. PRD2 defines STEWIE as a GIS-first lunar mission workbench: the map, layers, assets, selection, editing, analysis, simulation evidence, and command authority all synchronize through one workspace context. ROS 2, Gazebo, RViz, and Godot are integrated as runtime/evidence engines behind that context, not as independent command surfaces.

## Core Product Principle

STEWIE should feel like a lunar ArcGIS/QGIS mission workbench where map edits become executable mission intent, and every visible layer, robot state, simulation result, and command carries machine-readable provenance: prior, observed, belief, forecast, sim-truth, replay, HIL, or live.

The old design starts with mission tabs. The target design starts with the operator's GIS question:

- What area am I looking at?
- What layers are active?
- What object is selected?
- What can I edit?
- What analysis can I run?
- What did the analysis produce?
- Can this become a mission plan?
- Can it be rehearsed?
- Can it be released?
- What runtime produced the evidence?
- Is this simulation, replay, HIL, or live?

## Relationship To PRD v8

PRD v8 remains the campaign plan:

- Restore green.
- Clean up drift.
- Complete existing P0/P1 rows.
- Finish React/GeoLibre migration lanes.
- Harden ROS/Gazebo/RViz/Godot runtime rows.

PRD2 is the product target that PRD v8 should converge toward:

- View model.
- User workflows.
- Runtime integration architecture.
- GIS asset model.
- Multi-engine evidence surfaces.
- Acceptance criteria for a coherent end-to-end local lunar rover autonomy system.

## Current-State Reading

Confirmed from current repo/docs:

- Live cockpit is mostly vanilla JS in `stewie/server/index.html` and `stewie/server/web/assets/cockpit.js`.
- Current primary tabs are Plan, Rehearse, Validate, Release, Execute, Report, plus Fleet, Construction, Models, Trainer, Settings, System, Admin.
- React/Vite strangler shell exists under `frontend/`.
- React workspace state already introduces product mode, runnable profile, body, physics backend, source class, command namespace, and depth source.
- Vanilla cockpit state already carries mission/site/body/vehicle/time/mode/source/workArea/selectedEntity.
- GIS layer tree exists, but layers, durable assets, runtime evidence, and command authority are still too blended in the operator flow.
- ROS 2 workspace exists with `stewie_msgs`, description, bringup, perception, mapping, planning, control, executive, RViz, and vehicle-interface packages.
- Gazebo has a lunar world and IPEx bridge scaffold, but the current default world still includes a flat regolith plane path and must treat real DEM ingest as a release gate.
- RViz config exists as an engineering mission dashboard.
- Godot assets/render paths exist, but Godot is currently a renderer/sidecar, not the authoritative operator shell.
- Some ROS nodes remain skeletons; mapping/executive have more host-testable core than perception/planning/control.

## Product Roles

### GIS Mission Planner

Primary job: create, inspect, edit, analyze, and package lunar mission geography.

Needs:

- Layers, legend, identify, measure, coordinate readout.
- Site/body/CRS clarity.
- Editable mission features: waypoints, keep-outs, work zones, excavation/fill regions, candidate routes, surface assets.
- Analysis outputs: slope, hazard, shadow, traversability, cost, energy, regolith volume, trafficability, confidence.
- Export/import: GeoJSON, COG/GeoTIFF, GeoParquet, mission package, ROS bag/evidence links.

### Robotics/Autonomy Engineer

Primary job: understand whether the rover stack is coherent and whether perception/navigation/control are healthy.

Needs:

- ROS graph status.
- TF tree and frame sanity.
- Sensor stream freshness.
- RViz diagnostics.
- Costmap/localization/perception evidence.
- Gazebo/rosbag/replay profile match.
- Clear separation of truth from estimator inputs.

### Director/Safety Officer

Primary job: approve or refuse release/execution.

Needs:

- Mode/profile/namespace authority.
- Release packet.
- Command eligibility and refusal reasons.
- Watchdog/safe-state/link status.
- Human signoff.
- Immutable audit trail.

### Field/Test Operator

Primary job: run a bounded rehearsal, replay, HIL, or live test without losing situational awareness.

Needs:

- One cockpit that shows plan-vs-actual.
- No hidden command authority in secondary tools.
- SAFE/abort/replan controls.
- Telemetry and acknowledgement state.
- Runtime evidence and logs.

### Administrator

Primary job: govern users, roles, profiles, runtime capabilities, assets, evidence retention, and integrations.

Needs:

- Separate admin surface.
- Searchable account/role/profile registries.
- Auditable changes.
- No admin controls hidden in map editing UI.

## Unified Workspace Context

All views must subscribe to one routeable workspace context. This is the bridge between GIS, mission planning, ROS, Gazebo, RViz, Godot, and reports.

Minimum context fields:

```text
mission_id
site_id
body_id
site_crs
local_frame_id
vehicle_id
fleet_id
selected_entity
selected_layers
product_mode        GIS_PLAN | TRAIN | SIM_OPERATE | EVALUATE | OPERATE
runnable_profile    desktop_sil | digital_twin | ros2_replay | gazebo_sim | hil | field_test | live_rover
source_class        prior | observed | belief | forecast | sim_truth | replay | hil | live
command_namespace   sandbox | live
physics_backend     tier2_numpy | gazebo | chrono | hardware
depth_source        stereo | lidar | rgbd | learned_depth | replay | sim_depth
time_cursor
branch_id
release_id
run_id
role
```

Rule: changing context once updates the web GIS map, asset inspector, Godot view, RViz/Foxglove bridge, Gazebo/replay evidence, report pane, and authority card.

## Core Data/Physics Spines

PRD2 has three first-class spines that must not be hidden inside panes: the layer spine, the physics spine, and the terramechanics spine.

### Layer Spine

Layers are not just visual toggles. In STEWIE, a layer can be a map display, a planning constraint, a simulation input, an autonomy observation, a release gate, an execution input, or an evidence artifact. The UI must show that distinction.

Layer categories:

- Basemap/imagery: visual context only unless explicitly promoted.
- DEM/elevation: terrain authority input, slope/hillshade source, Gazebo heightfield source.
- Terrain derivatives: slope, roughness, incidence, shadow, PSR, traversability.
- Hazards: rocks, negative obstacles, no-go zones, steep slopes, low confidence regions.
- Mission features: waypoints, routes, keep-outs, target zones, work zones, landing/charging zones.
- Surface-design layers: cuts, fills, berms, pads, roads, trenches, stockpiles, sintered surfaces.
- Perception/mapping layers: observed DEM, occupancy, rock map, changed terrain, uncertainty, object graph.
- Runtime layers: planned path, local trajectory, executed path, telemetry track, costmap, covariance.
- Evidence layers: before/after terrain delta, as-built mask, rehearsal divergence, report snapshots.

Every layer must declare:

```text
layer_id
layer_type              raster | vector | mesh | point_cloud | costmap | evidence
body_id
site_id
crs
local_frame
source_class            prior | observed | belief | forecast | sim_truth | replay | hil | live
freshness
resolution
uncertainty
provenance
owner
version
display_eligible
planning_eligible
release_eligible
execute_eligible
export_formats
```

Explicit layer catalog:

| Layer ID | Type | Purpose | Source Class | Planning | Release/Execute |
|----------|------|---------|--------------|----------|-----------------|
| `base.imagery` | raster/tile | visual basemap or orthomosaic | prior | no by default | no |
| `base.dem` | raster/DEM | authoritative elevation source for site | prior/observed | yes | yes if fresh/provenanced |
| `base.hillshade` | raster | visual terrain relief | prior/derived | no | no |
| `base.contours` | vector | elevation interpretation | derived | no by default | no |
| `base.grid` | vector | local frame/grid reference | derived | no | no |
| `base.crs_control` | vector | CRS/frame control points | prior | yes for validation | yes if verified |
| `terrain.slope` | raster | slope angle | derived | yes | yes if DEM valid |
| `terrain.roughness` | raster | terrain roughness/mobility proxy | derived/observed | yes | yes if calibrated |
| `terrain.aspect` | raster | slope aspect (gradient azimuth) | derived | no by default | no |
| `terrain.curvature` | raster | surface curvature (Laplacian) | derived | no by default | no |
| `terrain.incidence` | raster | solar incidence | derived | yes | yes if ephemeris valid |
| `terrain.illumination` | raster/time | lit/shadow state by mission time | forecast/observed | yes | yes if time-bound |
| `terrain.shadow` | raster/time | shadow hazard | forecast/observed | yes | yes if time-bound |
| `terrain.psr` | raster | permanently shadowed region | prior/derived | yes | yes if sourced |
| `terrain.thermal` | raster/time | thermal exposure risk | forecast/observed | yes | profile-dependent |
| `terrain.los` | raster/vector | line-of-sight/visibility | derived | yes | profile-dependent |
| `terrain.comms` | raster/vector | communications access | forecast/observed | yes | profile-dependent |
| `hazard.slope_nogo` | raster/vector | no-go steep slope mask | derived | yes | yes |
| `hazard.rocks` | raster/vector | rock/obstacle detections | observed/belief | yes | yes if sensor fresh |
| `hazard.negative_obstacles` | raster/vector | holes/dropoffs | observed/belief | yes | yes if sensor fresh |
| `hazard.keepouts` | vector | user/imported no-go regions | prior/observed | yes | yes if approved |
| `hazard.low_confidence` | raster | low-confidence/no-data mask | derived/observed | yes | yes as refusal input |
| `traffic.traversability` | raster | combined mobility score | derived/belief | yes | yes if terms valid |
| `traffic.cost_global` | costmap | global route cost | derived/forecast | yes | yes if reproducible |
| `traffic.cost_local` | costmap | local planner cost | observed/belief | yes | execute-profile dependent |
| `traffic.backlink` | raster | accumulated-cost backlink/allocation | derived | yes | evidence only |
| `traffic.compaction` | raster | traversal-hardening (Dr) from repeated traffic | observed/derived | yes | yes if measured or approved |
| `regolith.class` | raster/vector | soil/regolith class | prior/observed | yes | yes if sourced |
| `physics.bearing` | raster | bearing capacity | derived/estimated | yes | yes if calibrated |
| `physics.sinkage` | raster | predicted wheel/tool sinkage | derived/estimated | yes | yes if calibrated |
| `physics.slip_risk` | raster | slip probability/risk | derived/estimated/learned | yes | yes if calibrated |
| `physics.traction_margin` | raster | traction/drawbar margin | derived | yes | yes if calibrated |
| `physics.energy_cost` | raster | drive/work energy cost | derived/forecast | yes | yes if calibrated |
| `physics.excavation_resistance` | raster | wheel compaction (motion) resistance R_c -- legacy id, not a dig/draft force (task #78) | derived/estimated | yes | yes if calibrated |
| `physics.compaction` | raster | compaction/sinter/support state | observed/derived | yes | yes if measured or approved |
| `mission.waypoints` | vector | planned traverse points | user/prior | yes | yes if released |
| `mission.route_candidates` | vector | candidate routes | forecast | yes | evidence only |
| `mission.selected_route` | vector | selected plan route | forecast/released | yes | yes if released |
| `mission.local_trajectory` | vector | local planner trajectory | forecast/live | yes | execute-profile dependent |
| `mission.command_queue` | vector/evidence | pending command geometry | released/live | no | yes |
| `design.work_zones` | vector | work/exclusion zones | user/prior | yes | yes if approved |
| `design.cut` | vector/raster | cut/excavation region | user/forecast | yes | yes if validated |
| `design.fill` | vector/raster | fill/deposition region | user/forecast | yes | yes if validated |
| `design.berm` | vector/mesh | berm geometry | user/forecast | yes | yes if validated |
| `design.pad` | vector/mesh | landing/work pad | user/forecast | yes | yes if validated |
| `design.road` | vector/raster | route/road surface design | user/forecast | yes | yes if validated |
| `design.trench` | vector/mesh | trench geometry | user/forecast | yes | yes if validated |
| `design.stockpile` | vector/mesh | stockpile area/volume | user/forecast | yes | yes if validated |
| `design.sinter` | vector/raster | sintered surface | user/forecast | yes | yes if validated |
| `map.observed_dem` | raster | perception-updated DEM | observed/belief | yes | yes if fresh |
| `map.occupancy` | raster | occupancy/obstacle grid | observed/belief | yes | yes if fresh |
| `map.rocks` | vector/raster | rock detections/object graph | observed/belief | yes | yes if fresh |
| `map.object_graph` | vector/graph | mapped objects/features | observed/belief | yes | evidence dependent |
| `map.uncertainty` | raster | map/pose/terrain uncertainty | derived/belief | yes | yes as refusal input |
| `map.changed_terrain` | raster | changed/as-built terrain mask | observed | yes | yes if reconciled |
| `map.excavation_state` | raster | excavation/as-built state | observed/belief | yes | yes if reconciled |
| `robot.pose` | vector | current/estimated rover pose | belief/live | yes | execute-profile dependent |
| `robot.covariance` | raster/vector | localization covariance | belief/live | yes | yes as refusal input |
| `robot.footprint` | vector | vehicle footprint/collision envelope | prior/live | yes | yes |
| `robot.sensor_frustums` | vector/mesh | camera/depth/LiDAR coverage | live/sim/replay | yes | evidence only |
| `robot.telemetry_track` | vector/time | actual telemetry path | live/replay | no | evidence |
| `robot.executed_path` | vector/time | executed trajectory | live/replay/sim | no | evidence |
| `runtime.gazebo_truth` | vector/time | simulator truth channel | sim_truth | no for autonomy | evidence/scoring only |
| `runtime.rviz_status` | evidence | RViz display/topic status | replay/live/sim | no | evidence only |
| `runtime.godot_capture` | evidence/media | Godot rendered view/capture | forecast/replay/live | no | evidence only |
| `evidence.before_after_dem` | raster/evidence | before/after terrain delta | observed/reconciled | yes | report/release evidence |
| `evidence.rehearsal_divergence` | raster/vector | plan-vs-sim/actual divergence | forecast/replay/live | yes for replan | evidence |
| `evidence.report_snapshot` | media/evidence | frozen map/report snapshot | evidence | no | evidence |

Rules:

- A displayed layer is not automatically planner-eligible.
- A planner-eligible layer is not automatically release-eligible.
- A release-eligible layer must have provenance, freshness, frame/CRS, and uncertainty.
- Execute-eligible layers must be compatible with the selected runnable profile and command namespace.
- Imported ArcGIS/OGC/GeoJSON/COG data must pass CRS/frame validation before it can influence planning.

### Physics Spine

Physics is not one engine. STEWIE needs an explicit physics authority model so the user knows what is simulated, what is conserved, what is visual, and what is command-eligible.

Physics authorities:

- `tier2_numpy`: STEWIE conserved terrain/terramechanics authority for local planning and mass-conserving excavation evidence.
- `gazebo`: robot, sensor, contact, odometry, and clock simulation; truth-isolated; not automatically terrain-mutation authority.
- `chrono`: optional high-fidelity terramechanics/contact reference; not release-eligible unless conservation and calibration gates pass.
- `hardware`: real rover/testbed telemetry and actuator feedback.
- `godot`: visualization/rendering/replay; never physics authority unless a future explicit row promotes a limited capability with tests.

Physics authority payload:

```text
physics_backend
authority_scope          terrain | robot | sensor | contact | rendering | hardware
conserves_mass
calibration_id
body_id
soil_profile_id
vehicle_profile_id
runtime_profile
valid_for_planning
valid_for_rehearsal
valid_for_release
valid_for_execute
refusal_reason
evidence_artifacts
```

Rules:

- The planner must state which physics backend produced each cost/risk/volume value.
- Gazebo can validate robot/sensor/control behavior but must not silently replace conserved terrain authority.
- Chrono can be a benchmark/oracle only when its limits are labeled.
- Godot can communicate predicted/actual state but does not own physics.
- Release/Execute must show physics backend compatibility and refusal reasons.

### Terramechanics Spine

Terramechanics is the lunar surface mobility and excavation model. It must be visible as its own domain, not buried under "planning."

Variables:

- Slope.
- Roughness.
- Regolith class.
- Bulk density.
- Cohesion.
- Friction angle.
- Bearing capacity.
- Wheel load.
- Contact pressure.
- Sinkage.
- Slip.
- Drawbar pull / traction margin.
- Excavation resistance.
- Compaction.
- Repose/stability.
- Energy cost.
- Uncertainty/calibration confidence.

Each terramechanics value must be classified:

- Simulated: produced by selected physics backend.
- Sensed: measured from rover/testbed sensors.
- Estimated: inferred from DEM/perception/telemetry.
- Learned: model-derived and requiring model provenance.
- Assumed: explicit assumption, never release-eligible without signoff.

Terramechanics outputs:

- Traversability layer.
- Trafficability/refusal layer.
- Energy-cost layer.
- Slip-risk layer.
- Bearing/sinkage map.
- Excavation feasibility layer.
- Cut/fill/sinter constructability report.
- Costmap inputs for global/local planners.

Rules:

- A route cost must expose its terramechanics terms, not only a single scalar.
- Surface-design volume/mass estimates must include DEM resolution and material assumptions.
- A live/rehearsal run must compare predicted slip/energy/sinkage to observed telemetry when available.
- As-built excavation must update terrain memory and future terramechanics cost layers.

## Target Information Architecture

### Global Shell

Top status bar:

- STEWIE / site / body / mission.
- Product mode.
- Runnable profile.
- Source class.
- Command namespace.
- Health.
- Alerts.
- Account.

Left primary rail:

- Workbench.
- Assets.
- Design.
- Rehearse.
- Validate.
- Operate.
- Evidence.
- Admin/System.

Center:

- GIS map/workbench as the default surface.

Right inspector:

- Selected object.
- Attributes.
- Provenance.
- Confidence/freshness.
- Actions available for this object.
- Runtime evidence affecting this object.

Bottom evidence/timeline drawer:

- Time cursor.
- Plan/rehearsal/execution events.
- ROS/Gazebo/RViz/Godot evidence links.
- Logs.
- Exports.

Command strip:

- Release/Execute/Safe controls only when eligible.
- Disabled controls must show refusal reason.

## Required Views

### View 1 - GIS Workbench

Purpose: default operator surface.

Contains:

- 2D local lunar map.
- Layer tree.
- Legend.
- Identify/measure/coordinate readout.
- Edit session controls.
- Current selection inspector.
- Analysis overlays.

Layers:

- DEM/hillshade.
- Slope.
- Hazard.
- Illumination/shadow/PSR.
- Traversability.
- Costmap.
- Keep-outs.
- Work zones.
- Routes.
- Surface assets.
- Observed hazards.
- As-built terrain delta.
- Uncertainty.

Acceptance:

- A user can select a site, turn layers on/off, identify a cell/feature, measure distance, draw a keep-out, and see whether that keep-out affects planning eligibility.
- Each layer declares whether it is display-only, planning-eligible, release-eligible, or execute-eligible.

### View 2 - Asset Library

Purpose: durable object browser, separate from visible layers.

Assets:

- Missions.
- Sites.
- Bodies.
- DEMs.
- Layer packages.
- Vehicles.
- Tools.
- Structures.
- Mission plans.
- Rehearsals.
- Runs.
- Reports.
- Evidence bundles.
- ROS bags/MCAP.
- Godot captures.
- RViz screenshots/config snapshots.

Acceptance:

- Every durable object can be browsed, searched, inspected, exported, and traced to provenance.
- Visible layers are not the only way to recover an asset.

### View 3 - Surface Design

Purpose: lunar construction/excavation design.

Contains:

- Pads, berms, trenches, roads, stockpiles, cuts, fills, sintered surfaces, science zones.
- Geometry editor.
- Cut/fill/volume estimates.
- Bearing/sinkage/trafficability.
- Constructability checks.
- Acceptance criteria.

Acceptance:

- A drawn surface asset can become typed mission orders.
- Volume/mass estimates show DEM resolution, material assumption, and uncertainty.
- A before/after terrain transaction influences the next plan.

### View 4 - Mission Planner

Purpose: convert GIS/design intent into executable plan candidates.

Contains:

- Mission objective.
- Task graph.
- Constraints.
- Fleet/tool selection.
- Candidate routes.
- Resource/energy/time budget.
- Refusal reasons.
- Plan IR.

Acceptance:

- A plan output includes immutable plan id, route geometry, action sequence, resource budgets, confidence, hazards, and refusal reasons.
- No plan is release-eligible unless map freshness, sensor/profile assumptions, and authority gates pass.

### View 5 - Rehearse / Simulation

Purpose: run candidate plan against a simulation/replay runtime.

Runtime engines:

- Gazebo for robot/sensor physics.
- STEWIE conserved terrain authority for excavation/cut/fill truth.
- Chrono only when explicitly selected and mass-conservation limitations are labeled.
- Godot for high-fidelity visualization/capture.

Contains:

- Candidate plan.
- Runtime profile.
- Sim inputs.
- Predicted outcome.
- Divergence vs plan.
- Energy/slip/terrain risk.
- Run artifacts.

Acceptance:

- Rehearsal writes predicted outcomes to a simulation branch only.
- Gazebo truth never feeds estimator inputs.
- Runtime profile mismatch is visible and blocks release.

### View 6 - Validate

Purpose: prove plan readiness.

Sub-views:

- Navigation.
- Perception.
- Mapping.
- Localization.
- Solar/illumination.
- Terramechanics.
- Communications/link.
- Authority.

Contains:

- Route vs local trajectory.
- Costmap.
- Sensor health.
- Depth-source profile.
- Perception detections.
- Mapping coverage.
- Covariance.
- Shadow/hazard risk.
- Refusal reasons.

Acceptance:

- A new hazard observation changes map/costmap, planner result, command eligibility, and cockpit evidence.
- Truth/eval channels are visibly separate from belief/observed channels.

### View 7 - Operate / Execute

Purpose: run bounded command flow in the selected runtime profile.

Contains:

- Plan-vs-actual.
- Telemetry.
- Command queue.
- Acknowledgements.
- Watchdog.
- SAFE state.
- Link health.
- Replan/pause/relocalize/reverse/safe decisions.
- Live token and release id.

Acceptance:

- No UI panel commands ROS 2 directly.
- Execution service is the sole egress.
- Live commands require valid release, live token, role, namespace, sensor/map freshness, watchdog, link ack, covariance, and safe-inactive state.

### View 8 - Physics / Terramechanics

Purpose: make physical assumptions, model authority, and terrain interaction visible and auditable.

Contains:

- Active physics backend and authority scope.
- Body and soil profile.
- Vehicle profile and wheel/tool parameters.
- Slope, roughness, bearing, sinkage, slip, energy, traction, excavation resistance, and uncertainty.
- Backend compatibility matrix: planning, rehearsal, release, execute.
- Calibration source and confidence.
- Predicted vs observed telemetry comparison.
- Costmap contribution breakdown.

Acceptance:

- A selected route or surface-design asset shows the physics backend and terramechanics terms that produced its cost/risk.
- Release is blocked when a required terramechanics value is assumed, stale, uncalibrated, or incompatible with the runnable profile.
- Rehearsal/report surfaces compare predicted slip/energy/sinkage against observed or replayed data when available.

### View 9 - Robot Debug / RViz Evidence

Purpose: engineering introspection, not command authority.

Embedded or linked via containerized web bridge/Foxglove/RViz screenshot stream.

Contains:

- Robot model.
- TF tree.
- `/clock`.
- `/joint_states`.
- `/stewie/odom`.
- Planned path.
- Local trajectory.
- Costmap.
- Occupancy/DEM map.
- PointCloud2.
- Camera feeds.
- Covariance.
- Diagnostics.
- Safe state.

Acceptance:

- RViz may inspect and debug.
- RViz cannot approve, release, or command.
- RViz evidence is attached to selected run/profile.

### View 10 - Godot Mission View

Purpose: high-fidelity spatial rendering and communication surface.

Godot shows:

- Rover body/articulation.
- Terrain and lighting/shadows.
- Planned path.
- Executed path.
- Sensor cones.
- Excavation zones.
- Hazards.
- As-built changes.
- Rehearsal playback.

Godot does not replace:

- GIS editing authority.
- Gazebo robot/sensor simulation.
- ROS 2 middleware.
- Release/execute authority.

Acceptance:

- Godot subscribes to workspace context and selected branch/run.
- Godot outputs capture artifacts with timestamps, camera pose, site/body, branch/run id, and source class.
- Godot can be embedded later, but first integration may be sidecar capture/stream.

### View 11 - Evidence / Report

Purpose: explain what happened and preserve proof.

Contains:

- World transactions.
- Terrain memory changes.
- Rehearsal results.
- Runtime logs.
- ROS bag/MCAP links.
- Gazebo artifacts.
- RViz evidence.
- Godot captures.
- Release packet.
- Command acknowledgements.
- As-built reconciliation.

Acceptance:

- A report can reproduce plan inputs, selected layers, assumptions, runtime profile, and evidence artifacts.

### View 12 - Admin / System

Purpose: governance and operations.

Contains:

- Users/roles.
- Runtime profiles.
- Body/site registries.
- Physics backends.
- Sensor profiles.
- ROS/Gazebo/RViz/Godot capability profiles.
- API keys/secrets.
- Audit log.
- Storage/evidence retention.
- Health/degraded dependencies.

Acceptance:

- Admin changes are role-gated, auditable, searchable, and recoverable where applicable.
- Personal settings are separate from operational configuration.

## Primary Workflows

### Workflow A - Create A GIS-Constrained Rover Traverse

1. Open GIS Workbench.
2. Select body/site/mission.
3. Inspect DEM, slope, hazard, illumination, traversability, and uncertainty layers.
4. Draw waypoints, keep-outs, and target zones.
5. Identify terrain values along route.
6. Run planner.
7. Inspect candidate path, cost, energy, slope, shadow, and refusal reasons.
8. Save as Plan candidate.

Proof:

- The route is tied to site CRS and local frame.
- The plan consumes the same layer manifest the map shows.
- Keep-outs and hazards influence the planner.

### Workflow B - Surface Design To Mission Orders

1. Create surface asset: pad, berm, trench, cut/fill zone, road, or stockpile.
2. Define geometry and acceptance tolerance.
3. Compute volume/mass/bearing/sinkage.
4. Decompose into orders.
5. Validate constructability.
6. Add to mission plan.

Proof:

- Surface design asset has owner/version/provenance.
- Orders preserve geometry, material assumptions, and uncertainty.
- As-built updates feed future planning.

### Workflow C - Rehearse A Plan In Gazebo

1. Select plan candidate.
2. Choose `gazebo_sim` runnable profile.
3. Export or spawn robot model, terrain, initial pose, and plan.
4. Run Gazebo with ROS 2 bridge.
5. Collect `/clock`, `/tf`, `/joint_states`, camera, IMU, wheel odom, point cloud, command, diagnostics.
6. Attach bag/MCAP and runtime metadata to rehearsal.
7. Compare predicted vs planned.

Proof:

- Gazebo truth is only on truth topics.
- Estimator sees only sensor topics.
- Rehearsal does not mutate accepted live world.

### Workflow D - Validate Navigation/Perception/Mapping

1. Load rehearsal, replay, or live run.
2. Inspect RViz evidence for TF, odom, path, costmap, cameras, covariance.
3. Inspect cockpit evidence for map freshness, sensor profile, detections, costmap effects.
4. Confirm planner reaction to observed hazard.
5. Record pass/fail evidence.

Proof:

- One observation can be traced from sensor frame to perception output, map update, planner cost/refusal, and UI evidence.

### Workflow E - Release And Execute

1. Director reviews plan candidate.
2. Validate authority evidence.
3. Release signed plan revision.
4. Mint live token only if training-to-live sequence passes.
5. Execute through execution service.
6. Monitor plan-vs-actual, acknowledgements, SAFE, link, covariance, replan state.
7. Commit world/as-built reconciliation.

Proof:

- Execution service is sole command egress.
- ROS 2 bridge cannot be commanded directly from UI.
- Release and execution produce immutable audit records.

## Runtime Integration Model

```text
React GIS Workbench / Operator Cockpit
  |
  | WorkspaceContext + typed API client
  v
FastAPI Authority Sidecar
  |-- world model / terrain memory / mission assets / evidence
  |-- planner / validator / release / execution service
  |-- runtime profile registry
  |
  +--> ROS 2 bridge/execution egress
          |
          +--> ROS 2 nodes
          |     perception / localization / mapping / planning / control / executive
          |
          +--> Gazebo
          |     robot + sensors + contact + clock + truth-isolated sim
          |
          +--> RViz/Foxglove
          |     engineering visualization + diagnostics evidence
          |
          +--> Godot
                high-fidelity render/capture/playback sidecar
```

### Responsibility Boundaries

FastAPI/STEWIE backend:

- Authority.
- Persistence.
- Mission assets.
- World model.
- Terrain memory.
- Layer manifest and layer eligibility.
- Physics backend registry.
- Terramechanics contracts and evidence.
- Release/execute gates.
- Evidence registry.
- Runtime profile registry.

React/GIS frontend:

- Operator workflow.
- GIS editing.
- Layer and asset browsing.
- Selection/inspection.
- Evidence display.
- Command intent submission to backend only.

ROS 2:

- Robotics middleware.
- Node lifecycle.
- Topic/action/service contracts.
- Sensor, localization, mapping, planning, control, vehicle interface, executive.

Gazebo:

- Robot/sensor/contact simulation.
- `/clock`, sensors, odometry, contact.
- Truth topics only for scoring/evaluation.
- Not the conserved excavation truth authority unless explicitly bridged through validated terrain transactions.

RViz:

- Engineering visualization/debug.
- No command approval.
- Evidence source for selected run/profile.

Godot:

- Rendered mission scene, replay, communication, high-fidelity visual context.
- No command approval.
- No replacement for Gazebo physics or GIS editing.

## ROS 2 Contract Target

Required packages:

- `stewie_msgs`
- `stewie_description`
- `stewie_bringup`
- `stewie_vehicle_interface`
- `stewie_perception`
- `stewie_localization`
- `stewie_mapping`
- `stewie_planning`
- `stewie_control`
- `stewie_executive`
- `stewie_rviz`

Required topic families:

- `/clock`
- `/tf`, `/tf_static`
- `/robot_description`
- `/joint_states`
- `/cmd_vel`
- `/stewie/imu`
- `/stewie/wheel_odom`
- `/stewie/odom`
- `/stewie/camera/*/image`
- `/stewie/camera/*/camera_info`
- `/stewie/perception/points`
- `/stewie/perception/rocks`
- `/stewie/map/dem`
- `/stewie/map/occupancy`
- `/stewie/map/excavation_state`
- `/stewie/costmap`
- `/stewie/plan/path`
- `/stewie/plan/local_traj`
- `/stewie/localization/cov`
- `/stewie/nav/factors`
- `/stewie/exec/decision`
- `/stewie/safe_state`
- `/stewie/truth/*` for truth/evaluation only

Required actions/services:

- Submit plan.
- Arm run.
- Pause/resume.
- Replan.
- Relocalize.
- SAFE/estop.
- Snapshot evidence.
- Export bag/MCAP.

Required tests:

- Topic graph matches contract.
- No estimator node subscribes truth topics.
- Gazebo bridge topic names match URDF/SDF sensor names.
- RViz config references existing contract topics.
- A recorded bag produces the same host-side perception/mapping result as the ROS node path.

## Gazebo Integration Target

Gazebo must provide:

- IPEx/rover model from URDF/Xacro.
- Gazebo/SDF extensions for sensors, plugins, contact, friction, camera/depth/LiDAR as configured.
- Lunar gravity.
- Real DEM heightfield per selected site, not only a flat plane.
- Camera, IMU, wheel odom, contact, point cloud/depth outputs.
- `/cmd_vel` and actuator/joint command inputs.
- `/clock` with sim time.
- Truth pose only on isolated truth topics.

Acceptance:

- Starting `gazebo_sim` profile launches the selected site/robot and publishes the required topics.
- The cockpit shows Gazebo profile, `/clock`, bridge freshness, bag path, and truth-denial assertion.
- A route rehearsal returns predicted path, sensor evidence, and divergence.

## RViz Integration Target

RViz remains the engineering view.

Integration options by phase:

1. Export RViz config and screenshot evidence.
2. Serve Foxglove/rosbridge panel in System/Robot Debug.
3. Optional desktop shell panel for RViz process status.

Acceptance:

- RViz evidence is linked to the selected run.
- Operator cockpit can show whether RViz displays loaded and topics were fresh.
- RViz cannot hold unique command authority.

## Godot Integration Target

Godot should be synchronized to workspace context.

Phase 1:

- Headless/batch render from mission package.
- Store PNG/GIF/video/capture metadata.

Phase 2:

- Live sidecar stream or embedded panel.
- Subscribe to pose/path/layer context.

Phase 3:

- Mission playback synchronized with timeline.
- Sensor frustums, shadows, excavation/as-built, hazards, uncertainty.

Acceptance:

- Godot renders a selected plan/run using the same site/body/frame and branch id as the GIS map.
- Captures include run id, branch id, camera pose, timestamp, source class, and asset hashes.

## Proposed PRD2 Rows For Future Matrix Intake

These are product rows to fold into `PRD.md` only after review. Codes are two-letter/two-digit to fit current matrix tooling.

| ID | Priority | Requirement |
|----|----------|-------------|
| GW-01 | P0 | GIS Workbench shell: map/layers/selection/inspector are the default operator surface; mission lifecycle is an overlay, not the only navigation model. |
| GW-02 | P0 | Unified workspace context drives GIS, assets, Godot, RViz/Foxglove, Gazebo evidence, reports, and authority cards. |
| GW-03 | P0 | Layer manifest differentiates display/planning/release/execute eligibility and exposes freshness/provenance/uncertainty. |
| GW-04 | P1 | Asset Library separates durable mission assets from visible map layers with browse/search/inspect/export/recover paths. |
| ED-01 | P0 | Edit sessions support select/create/modify/delete/measure/snap/undo for mission features, with versioned audit. |
| SD-01 | P1 | Surface Design view converts pads/berms/trenches/cuts/fills/roads into typed mission orders with volume/constructability evidence. |
| LY-01 | P0 | Layer spine: every layer declares type, body/site/frame, source class, freshness, uncertainty, provenance, eligibility, and export formats. |
| LY-02 | P1 | Layer inspector shows where a layer is consumed: display, planner, costmap, rehearsal, release, execute, report, or export. |
| PH-01 | P0 | Physics backend registry exposes authority scope, mass conservation, calibration, compatibility, refusal reasons, and evidence artifacts. |
| PH-02 | P1 | Planner and reports attribute every route/volume/risk value to a physics backend and calibration source. |
| TM-01 | P0 | Terramechanics spine exposes slope, roughness, regolith, bearing, sinkage, slip, traction, excavation resistance, energy, and uncertainty as inspectable terms. |
| TM-02 | P1 | Terramechanics outputs generate traversability, energy, slip-risk, bearing/sinkage, excavation-feasibility, and constructability layers. |
| TM-03 | P1 | Rehearsal/report compares predicted slip, sinkage, and energy against observed/replayed telemetry when available. |
| RT-01 | P0 | Runtime profile registry defines desktop_sil, digital_twin, ros2_replay, gazebo_sim, hil, field_test, live_rover and their allowed command/evidence capabilities. |
| RT-02 | P0 | ROS/Gazebo/RViz/Godot evidence surfaces are bound to selected run/profile and cannot hold independent command authority. |
| RT-03 | P0 | Gazebo rehearsal uses real site DEM and truth-isolated sensor topics; cockpit shows `/clock`, bridge freshness, and artifact links. |
| RT-04 | P1 | RViz/Foxglove engineering panel shows topic freshness, TF, robot model, path, costmap, perception, covariance, diagnostics, and SAFE state. |
| RT-05 | P1 | Godot mission view renders selected branch/run with terrain, rover, path, hazards, sensor cones, shadow, excavation/as-built, and capture metadata. |
| AU-01 | P0 | Release/Execute authority card is globally visible when command capability exists and shows every refusal reason. |
| EV-01 | P1 | Evidence/Report view reproduces plan inputs, selected layers, runtime profile, ROS/Gazebo/RViz/Godot artifacts, world transactions, and audit trail. |

## Implementation Slices

### Slice 0 - Stabilize Current PRD Campaign

- Keep v8 Wave 0/1 cleanup.
- Do not replace v8 with PRD2.
- Add PRD2 as product target.

Acceptance:

- PRD2 exists and is referenced by future PRD/gap docs.

### Slice 1 - Context Contract

- Merge vanilla cockpit state and React workspace state into one documented contract.
- Route/share state through URL.
- Add runtime profile registry endpoint.

Acceptance:

- One URL restores site/body/mission/profile/source/layers/view/selection.

### Slice 2 - GIS Workbench Shell

- In React/GeoLibre shell, build map, layers, selection, inspector, and edit session as the first screen.
- Keep vanilla cockpit live until parity.

Acceptance:

- User can complete Workflow A without entering old Plan tab first.

### Slice 3 - Layer/Physics/Terramechanics Contracts

- Promote layer manifest, physics backend registry, and terramechanics terms into typed contracts.
- Add layer inspector fields for eligibility, provenance, uncertainty, and consumers.
- Add physics/terramechanics inspector for selected route/design/run.

Acceptance:

- Selecting a layer shows whether it can drive planning/release/execute.
- Selecting a route/design shows physics backend and terramechanics terms.
- A release gate refuses stale, assumed, or incompatible physical inputs with a visible reason.

### Slice 4 - Asset Library

- Add asset registry view over missions/sites/DEMs/layers/plans/runs/reports/evidence.

Acceptance:

- A saved plan/run/report can be found without relying on current map state.

### Slice 5 - Runtime Evidence Spine

- Normalize runtime evidence for ROS/Gazebo/RViz/Godot into backend artifacts.
- Show profile match/mismatch in Validate/System/Report.

Acceptance:

- Selecting a run shows all runtime evidence and missing-artifact refusal reasons.

### Slice 6 - Gazebo Rehearsal

- Real DEM heightfield.
- Bridge topic names consistent with URDF/SDF.
- Bag/MCAP capture.
- Cockpit evidence.

Acceptance:

- Workflow C completes in local containers.

### Slice 7 - RViz/Foxglove Panel

- RViz config + screenshot/status artifact first.
- Optional web panel later.

Acceptance:

- Engineering evidence is visible but cannot command.

### Slice 8 - Godot Mission View

- Batch render/capture from mission package.
- Later stream/embed.

Acceptance:

- Godot capture is reproducible from the selected branch/run.

### Slice 9 - Authority/Execute Consolidation

- Global command authority card.
- Sole execution egress.
- Live token integration.

Acceptance:

- Release/Execute refusal reasons are visible from every command-capable view.

## Non-Negotiables

- No UI control may command ROS 2 directly.
- No external visualization tool may hold unique command authority.
- Gazebo truth must never feed estimator inputs.
- Godot is visualization/replay unless explicitly promoted with tests; it is not the physics authority.
- RViz is debug/evidence only.
- GIS display layers are not automatically planning-eligible.
- A layer or asset without provenance/freshness/confidence cannot be release-eligible.
- A physics or terramechanics value without backend, calibration, units, source class, and uncertainty cannot be release-eligible.
- Accepted world mutation must go through terrain/world transaction authority.
- Mobile must expose the same command authority semantics as desktop.

## Minimum Demo That Proves PRD2

Demo name: "GIS-to-Gazebo Rehearsal With Evidence"

Steps:

1. Open GIS Workbench.
2. Select Moon / Haworth / IPEx.
3. Toggle DEM, slope, hazard, shadow, traversability.
4. Draw a keep-out and target.
5. Generate a plan.
6. Rehearse with `gazebo_sim`.
7. Record ROS bag/MCAP, Gazebo profile, RViz evidence screenshot, Godot capture.
8. Validate that observed/rehearsed outputs do not use truth inputs.
9. Show plan-vs-sim divergence.
10. Generate report with all artifacts.

Success:

- The same context drives map, plan, Gazebo, RViz, Godot, and report.
- A single evidence bundle proves what ran.
- Release remains disabled unless authority gates pass.

## Open Decisions

1. Is the target desktop wrapper Tauri, Electron, or web-only for the next two milestones? Default: web-first, wrapper-agnostic.
2. Is Godot only a sidecar/capture engine for now, or should an embedded streaming panel be a P1 requirement? Default: sidecar first.
3. Should RViz be embedded through Foxglove/rosbridge, or treated as external evidence with screenshots/status first? Default: evidence first, web bridge later.
4. Does `gazebo_sim` become a named runnable profile immediately? Default: yes.
5. Should `PRD2` rows be folded into `PRD.md` now or after v8 Wave 0 restores green? Default: after Wave 0.
