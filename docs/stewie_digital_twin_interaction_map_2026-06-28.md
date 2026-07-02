---
title: "Digital twin interaction map (2026-06-28)"
nav_order: 49
---

# STEWIE Digital Twin Interaction Map

Date: 2026-06-28

Scope: STEWIE directly. This map treats the digital twin as a directed
edge set between state blocks. Architecture diagrams, ROS 2 message flows, causal cascades, influence
graphs, and Graphify exports are all generated views of this same table.

## Direct STEWIE Evidence Base

| Area | STEWIE authority | Current reading |
|---|---|---|
| product definition | `README.md`, `PRD.md` | STEWIE is a lunar construction digital-twin and mission-planning platform around a mass-conserving terrain authority. |
| capability status | `docs/CAPABILITIES.md` | Strong planner/physics/trainer core; live mission-ops and operational twin remain gated. |
| world model | `docs/world_model.md`, `stewie/physics/*`, `stewie/twin/*` | Five-layer terrain-transformation model exists; conserved dynamics are real; learned perception remains the intended thin layer. |
| bridge and autonomy seam | `stewie/bridge/ros2_bridge.py`, `stewie/bridge/rc_contract.py`, `ros2_ws/src/stewie_msgs/msg/*.msg` | Pure ROS translation and watchdog path are implemented/tested; live ROS node remains host/deploy gated. |
| planning | `lode/mission_planner.py`, `lode/planner_*`, `lode/autonomy.py` | Deterministic mission planner and belief overlay are implemented. |
| navigation integration | `dart/factors.py`, `dart/evidence_ledger.py` | Typed navigation factor contract exists; measured/de-oracled producers are still the frontier. |

## Status Legend

| Status | Meaning |
|---|---|
| complete | Implemented, wired, and covered by tests or shipped artifacts. |
| partial | Implemented in one layer but not complete end to end. |
| started | Code or artifact exists, but the intended claim is not yet supported. |
| planned | Needed by the architecture, but no current implementation path is complete. |
| sim_only | Simulation/render evidence only, not hardware-validated. |
| external_gated | Blocked by ROS host, pit link, hardware, Chrono, GPU model, or missing external data. |
| refused_currently | STEWIE has a gate and correctly refuses the present evidence. |

## Digital Twin Layout

| Layer | Owner | Canonical variables | Artifact / topic surface | Status | Rule |
|---|---|---|---|---|---|
| `L0_orbital_base` | world | `dem_id`, `heightmap_0`, `cell_m`, `dem_origin_m`, `site_id`, `body` | DEM samples, `heightmap.rf32`, site DEM services | complete for samples | immutable after site selection |
| `L1_environment` | world | `sun_azimuth_deg`, `sun_elevation_deg`, `time_utc`, `sink_temp_c`, `psr_flag` | `sensors.json.sun`, `/ephemeris`, thermal config | started | computed from site/time, not tuned to metrics |
| `L2_current_terrain` | world | `heightmap`, `slope_deg`, `normal_xyz`, `roughness`, `traversability`, `shadow_mask` | `WorldModel.current_terrain()`, scene rasters, route cost maps | complete in sim | derived from `L0 + reduce(L4)` |
| `L3_material_state` | world | `mass_areal`, `density`, `cohesion_kpa`, `friction_angle_deg`, `bearing_strength_kpa`, `disturbance`, `ice_frac` | `mass_areal.rf32`, `density.rf32`, `state_label.r8`, `ice.rf32` | partial | conserved fields first, calibration second |
| `L4_event_log` | world/robot | `ExcavationEvent.id`, `x`, `y`, `radius_m`, `dheight_m`, `t_s`, `robot_id`, `kind` | `WorldModel.events`, terrain mutation products | complete in code | terrain mutation is event-sourced |
| `L5_mission_task` | planner | `Mission`, `BuildOrder`, `target_height`, `trips`, `flows`, `PlanResult`, `objective`, `algorithm` | Plan IR, reports, `WorkGoal` | complete planner | all outputs are views of one `PlanResult` |
| `L6_belief_estimate` | robot | `x`, `y`, `yaw_rad`, `pos_sigma_m`, `energy_J`, `drum_kg`, `soc_frac` | `Belief`, `/stewie/odom`, factor ledgers | partial | estimator consumes factors, not scoring truth |
| `L7_observation_layer` | robot/world | `image`, `camera_info`, `feature_count`, `disparity_confidence`, `height_uncertainty`, `nav_factors` | camera egress, `NavFactorArray`, map products | partial | observations need covariance and provenance |
| `L8_evaluation_truth` | audit only | `truth_pose`, `truth_terrain`, `error_m`, `ATE`, `RPE` | validation artifacts and metrics | complete as audit concept | forbidden to factor producers |

## State Blocks And Variables

| Block | Variable names | Current source | Status |
|---|---|---|---|
| `LunarSite` | `site_id`, `lat_deg`, `lon_deg`, `dem_id`, `dem_origin_m`, `cell_m`, `body` | `stewie/terrain/site_dem.py`, server DEM endpoints | complete for named sites |
| `Ephemeris` | `time_utc`, `time_delta_s`, `sun_azimuth_deg`, `sun_elevation_deg`, `solar_vector_world` | Godot sun, `/ephemeris`, `docs/sun_sweep_manifest.md` | started |
| `TerrainMesh` | `heightmap`, `slope_deg`, `normal_xyz`, `roughness`, `traversability`, `shadow_mask` | `column_state`, route maps, Godot render | complete in sim |
| `RegolithState` | `mass_areal`, `density`, `cohesion_kpa`, `friction_angle_deg`, `bearing_strength_kpa`, `disturbance`, `ice_frac` | `stewie/physics/material.py`, `io_fields.py`, `ipex_specs.py` | partial |
| `ThermalEnvironment` | `sink_temp_c`, `surface_temp_k`, `heater_power_w`, `camera_operational` | `stewie/specs/ipex_specs.py` | started |
| `LightingModel` | `shadow_volume`, `scene_radiance`, `contrast`, `valid_disparity_fraction`, `exposure` | Godot, map channel, render products | started |
| `MutableTerrainLedger` | `events[]`, `ExcavationEvent.id`, `x`, `y`, `radius_m`, `dheight_m`, `t_s`, `robot_id`, `kind` | `stewie/twin/world_model.py` | complete in code |
| `RoverPose` | `x_m`, `y_m`, `yaw_rad`, `row`, `col`, `frame_id`, `sequence_id` | `ros2_bridge.pose_to_odom`, RC contract | complete pure |
| `RoverBelief` | `x`, `y`, `pos_sigma_m`, `energy_J`, `energy_sigma_J`, `drum_kg`, `drum_sigma_kg`, `soc_frac`, `t_s` | `lode/autonomy.py` | complete in sim |
| `WheelDynamics` | `wheel_rate_rad_s`, `drive_torque_nm`, `slip`, `sinkage_m`, `drawbar_pull_n`, `entrapped` | `terramechanics.py`, `slip.py`, `drive.py` | complete in sim |
| `ExcavatorDrum` | `drum_speed_rpm`, `scoop_depth_m`, `torque_nm`, `current_a`, `fill_kg`, `regolith_per_cycle_kg` | `ipex_specs.py`, `rassor_mass_model.py` | partial |
| `ArticulationState` | `arm_front_pitch_rad`, `arm_back_pitch_rad`, `chassis_lift_m`, `camera_heights_m`, `posture_name` | `posture_kinematics.py`, `runtime_packet.py` | complete in sim |
| `CameraRig` | `camera_name`, `image`, `width`, `height`, `fx`, `fy`, `cx`, `cy`, `baseline_m`, `extrinsic_in_base_link` | `docs/sensor_bridge_contract.md`, Godot egress | complete file seam |
| `PerceptionState` | `feature_count`, `disparity_confidence`, `height_uncertainty`, `factor_type`, `covariance` | `dart/*`, map channel, evidence ledger | partial |
| `MissionPlan` | `Mission`, `BuildOrder`, `PlanResult`, `trips`, `flows`, `per_trip`, `tl`, `totals` | `lode/mission_planner.py` | complete |
| `ExecutiveState` | `decision`, `reason`, `safe`, `safe_reason`, `cmd_vel`, `go_to`, `replan_required` | ROS bridge and `stewie_msgs` | partial |
| `PowerThermalState` | `voltage_v`, `current_a`, `power_w`, `soc_frac`, `thermal_w` | `runtime_packet.power_channel`, `ipex_specs.py` | started |

## Canonical Interaction Edge Schema

```text
INT-###
trigger_event
source_block -> target_block
coupled_variables
governing_model
effect
observability_or_topic
stewie_realization
status
needed_next
```

## Phase 1 STEWIE Interaction Set

| ID | Trigger / event | Edge | Coupled variables | Governing model | Effect | Observability / topic | STEWIE realization | Status | Needed next |
|---|---|---|---|---|---|---|---|---|---|
| INT-001 | site selected | `LunarSite -> TerrainMesh` | `dem_id`, `dem_origin_m`, `cell_m`, `heightmap` | DEM ingest | sets base terrain | `heightmap.rf32`, DEM API | named-site DEM services | complete | mission-scale site registry hardening |
| INT-002 | mission time advances | `Ephemeris -> LightingModel` | `time_delta_s`, `sun_azimuth_deg`, `sun_elevation_deg` | lunar sun geometry | changes shadows and exposure | `/ephemeris`, `sensors.json.sun` | Godot and cockpit sun authority | started | UTC ephemeris provenance |
| INT-003 | PSR / low light | `LightingModel -> CameraRig` | `irradiance`, `scene_radiance`, `exposure` | no-atmosphere optics | lower signal, higher noise | image histogram, camera metadata | render/lab analog only | sim_only | camera noise/exposure model |
| INT-004 | relief under grazing sun | `TerrainMesh -> LightingModel` | `heightmap`, `normal_xyz`, `shadow_mask` | terrain shadow cast | long shadows and occlusion | shadow render products | Godot render | started | terrain-event shadow residuals |
| INT-005 | slope encountered | `TerrainMesh -> WheelDynamics` | `slope_deg`, `roughness`, `traversability` | slip ladder | +slip, +energy, +uncertainty | `/stewie/odom.slip`, route costs | slip-aware planner/autonomy | complete | measured wheel telemetry |
| INT-006 | weak regolith under wheel | `RegolithState -> WheelDynamics` | `density`, `cohesion_kpa`, `friction_angle_deg`, `sinkage_m` | Bekker / Janosi-Hanamoto | +sinkage, -traction | IMU pitch, wheel slip | terramechanics core | complete in sim | `k_phi` calibration |
| INT-007 | drum payload carried | `ExcavatorDrum -> WheelDynamics` | `fill_kg`, `haul_mass_capped_kg`, `normal_load` | load coupling | +slip, +drive energy | motor current, `/stewie/odom.slip` | K10 weight coupling | complete in sim | live payload estimate |
| INT-008 | `/cmd_vel` received | `ExecutiveState -> WheelDynamics` | `linear_x`, `angular_z`, `GoTo` | unicycle projection | motion carrot | `/cmd_vel` | `ros2_bridge.twist_to_command` | complete pure | live ROS deploy |
| INT-009 | odometry integrates | `WheelDynamics -> RoverBelief` | `drive_m`, `slip`, `odom_drift_frac` | process update | +pos covariance | `Belief.pos_sigma_m` | `autonomy.predict` | complete in sim | typed belief topic |
| INT-010 | obstacle above clearance | `TerrainMesh -> MissionPlan` | `obstacle_height_m`, `keepout_mask` | obstacle gate | route cost / keep-out | hazard map | route planner | complete | live detector input |
| INT-011 | negative obstacle detected | `TerrainMesh -> MissionPlan` | `slope_deg`, `negative_obstacle_mask` | hazard routing | re-route or safe | cost map | planner routing | complete | live sensor producer |
| INT-012 | cut order lowered | `MissionPlan -> ExcavatorDrum` | `cut_depth_m`, `footprint_m2`, `dig_e` | volumetric cut | drum work begins | `WorkGoal` | planner order lowering | complete plan | hardware command adapter |
| INT-013 | excavation pass | `ExcavatorDrum -> MutableTerrainLedger` | `dheight_m`, `displaced_volume`, `kind=cut` | mass conservation | -elevation, +drum fill | event log, stereo diff | `WorldModel.add_event` | complete in code | real drum pass evidence |
| INT-014 | spoil dumped | `ExcavatorDrum -> TerrainMesh` | `fill_kg`, `dheight_m`, `radius_m` | conserved fill | +elevation, changed slope | event log | event-sourced fill | complete in code | as-built stereo validation |
| INT-015 | compaction pass | `WheelDynamics -> RegolithState` | `normal_load`, `traffic_count`, `density` | compaction model | +density, +bearing | pass count, density field | field slot exists | partial | compaction calibration |
| INT-016 | terrain event committed | `MutableTerrainLedger -> TerrainMesh` | `events[]`, `delta_field`, `current_terrain` | event reduction | current terrain updates | `current_terrain()` | event-sourced world model | complete | transactionally bind to PlanResult |
| INT-017 | mutation changes shadow | `MutableTerrainLedger -> LightingModel` | `dheight_m`, `shadow_mask`, `sun_azimuth_deg` | DEM + sun shadow | changed predicted shadow | shadow residual panel | world-model artifact path | started | factorized residual producer |
| INT-018 | protected zone authored | `MissionPlan -> MutableTerrainLedger` | `ProtectedZone.x`, `y`, `radius_m` | keep-out overlap | refuses excavation | plan validation | protected-zone logic | complete | expose live terrain-event topic |
| INT-019 | target grade specified | `MissionPlan -> TerrainMesh` | `target_height`, `cut_m3`, `fill_m3` | cut/fill balance | planned terrain delta | Plan report | mission planner | complete | operational execution binding |
| INT-020 | plan optimized | `MissionPlan -> ExecutiveState` | `trips`, `tl`, `algorithm`, `objective` | TSP / battery sim | ordered work queue | Plan IR, `WorkGoal` | planner facade | complete | ROS work-order bridge |
| INT-021 | reserve low | `PowerThermalState -> MissionPlan` | `soc_frac`, `reserve_frac`, `recharge_power_w` | recharge policy | insert recharge | timeline battery | planner sim | complete | measured BMS feedback |
| INT-022 | cold sink | `ThermalEnvironment -> PowerThermalState` | `sink_temp_c`, `heater_power_w` | heat balance | +power draw | thermal telemetry | thermal model | started | real thermal telemetry |
| INT-023 | camera below operational range | `ThermalEnvironment -> CameraRig` | `camera_temp_c`, `camera_min_operational_c` | operating limit | camera unavailable | camera health | spec variable only | planned | health producer |
| INT-024 | stereo pair captured | `CameraRig -> PerceptionState` | `front_left`, `front_right`, `fx`, `baseline_m` | stereo disparity | depth estimate | `/front_left/image_raw`, `/camera_info` | file seam and ROS mapping | complete file, partial live | live bag/node |
| INT-025 | shadows reduce texture | `LightingModel -> PerceptionState` | `contrast`, `valid_disparity_fraction` | stereo confidence | -depth confidence | confidence map | map channel diagnostics | started | covariance propagation |
| INT-026 | observed patch matched | `TerrainMesh -> PerceptionState` | `observed_patch`, `search_window`, `dem_xy` | DEM scan matching | absolute position cue | `MeasurementFactor(dem_xy)` | navigation integration plan | planned | accepted producer |
| INT-027 | DEM factor accepted | `PerceptionState -> RoverBelief` | `fix_xy`, `covariance`, `frame` | pose graph / Kalman | -pos covariance | `NavFactorArray` | typed factor contract | partial | covariance-rich message |
| INT-028 | AprilTag observed | `SurveyedMonuments -> PerceptionState` | `apriltag_id`, `tag_size_m`, `pose_in_lander` | PnP fiducial pose | local fix | `/lander/apriltag_truth` currently eval | sensor bridge | started | runtime detection factor |
| INT-029 | landmark fix accepted | `PerceptionState -> RoverBelief` | `fix_xy`, `sigma_m`, `factor_type` | measurement update | -pose covariance | `NavFactor` | closed-loop beacon model | partial | runtime measured factor |
| INT-030 | posture changes | `ArticulationState -> CameraRig` | `chassis_lift_m`, `camera_heights_m`, `extrinsic_in_base_link` | forward kinematics | viewpoint baseline | joint state, extrinsics | posture kinematics | complete in sim | measured joint readback |
| INT-031 | articulation parallax pair | `ArticulationState -> PerceptionState` | `dh_m`, `pixel_shift`, `range_span_m` | `R=fx*dh/dv` | local position opportunity | render-pair images | articulation bridge | started | truth-free association |
| INT-032 | parallax factor accepted | `PerceptionState -> RoverBelief` | `parallax_xy`, `covariance`, `frame` | absolute factor | -local position uncertainty | `MeasurementFactor(parallax_xy)` | factor type exists | planned | accepted producer |
| INT-033 | shadow bearing observed | `LightingModel -> PerceptionState` | `sun_azimuth_deg`, `shadow_bearing_body` | anti-solar direction | yaw correction | `shadow_yaw` factor | body-frame shadow path | complete for factors | full-row integration |
| INT-034 | shadow yaw accepted | `PerceptionState -> RoverBelief` | `shadow_yaw`, `covariance` | heading factor | -yaw covariance | typed factor | evidence ledger | complete | measured cue expansion |
| INT-035 | loop closure detected | `PerceptionState -> RoverBelief` | `loop_closure`, feature track, covariance | pose graph closure | global consistency | `/slam/odom` | baseline lane | partial | measured LC producer |
| INT-036 | command integrated | `ExecutiveState -> RoverBelief` | `yaw_command`, `odometry_between`, `imu_yaw` | command integration | surrogate propagation | factor ledger | command/proprioception path | complete but claim-limited | measured telemetry |
| INT-037 | belief uncertainty high | `RoverBelief -> MissionPlan` | `pos_sigma_m`, `dig_sigma_gate_m` | uncertainty gate | observe before dig | closed-loop log | autonomy overlay | complete in sim | live map confidence |
| INT-038 | map uncertainty high | `PerceptionState -> MissionPlan` | `height_uncertainty`, `dig_ready_mask`, `info_gain` | next-best-view | inspect before act | uncertainty layer | active perception env | complete in sim | learned render predictor |
| INT-039 | action executed | `ExecutiveState -> MutableTerrainLedger` | `WorkGoal`, `robot_id`, `t_s`, `kind` | event sourcing | audit trail grows | event log | world model | partial | live command provenance |
| INT-040 | terrain diff observed | `PerceptionState -> MutableTerrainLedger` | `observed_dem`, `resid`, `min_dheight_m` | reconcile observation | infer events | before/after map | `reconcile_observation` | complete in code | benchmark ingestion |
| INT-041 | energy gap learned | `PowerThermalState -> MissionPlan` | `true_energy_J`, `nominal_energy_J`, `slope_deg` | online regression | route repriced | validation/self_optimizing | self-optimizing loop | partial | planner objective integration |
| INT-042 | rock classified | `PerceptionState -> MissionPlan` | `Rock.center`, `radius_m`, nav class | semantic obstacle | avoid/landmark/excavate | `RockArray` | message exists | partial | live rock detector |
| INT-043 | operator pause / safe | `ExecutiveState -> MissionPlan` | `decision`, `reason`, `safe` | executive policy | pause/replan/safe | `ExecutiveDecision`, `SafeState` | messages/contracts | partial | live executive node |
| INT-044 | odom published | `RoverPose -> ExecutiveState` | `x`, `y`, `yaw`, `slip`, `sinkage_m` | ROS odom egress | autonomy observes state | `/stewie/odom` | pure bridge tested | partial | live ROS node |
| INT-045 | command stream stalls | `ExecutiveState -> ExecutiveState` | deadline, `safe_reason` | SF-01 watchdog | safe state | `SafeState`, RC Safe | watchdog | complete pure | hardware transport |
| INT-046 | mutation affects route | `MutableTerrainLedger -> MissionPlan` | `delta_field`, `slope_deg`, hazard cost | replan on changed terrain | route changes | planner route | dynamic world model | started | full operational twin log |
| INT-047 | volatile or ice layer | `RegolithState -> ExcavatorDrum` | `ice_frac`, `density`, `dig_energy_per_kg` | material-dependent excavation | +energy | ice raster | schema slot | planned | dataset/model |
| INT-048 | excavation dust | `RegolithState -> CameraRig` | `disturbance`, `dust_opacity`, `exposure` | occlusion | -feature count | image quality | not modeled | planned | dust/occlusion model |
| INT-049 | PSR route | `LunarSite -> PowerThermalState` | `psr_flag`, `sink_temp_c`, `sun_elevation_deg` | thermal survival | +heater load | thermal estimate | thermal model | started | PSR layer |
| INT-050 | frame registry exported | `MissionPlan -> SurveyedMonuments` | `dem_origin_m`, `frame_id`, `map` | frame contract | aligns map/landmarks | `/tf_static`, metadata | sensor bridge | partial | unified frame registry |
| INT-051 | factor emitted | `PerceptionState -> MissionPlan` | `factor_type`, `accepted`, `evidence_class`, `refusal_reason` | evidence ledger | gates claims and rows | evidence ledger | factor contract | complete | continue enforcing |

## ROS / Bridge Inventory View

| Boundary | Edges | Current transport | Target ROS / Gazebo topic | Message / artifact | Status |
|---|---|---|---|---|---|
| world -> robot camera | INT-003, INT-004, INT-024, INT-025 | `sensors.json` + PNG | `/front_left/image_raw`, `/front_right/image_raw`, `/camera_info` | `sensor_msgs/Image`, `CameraInfo` | file complete, live partial |
| world -> robot sun | INT-002, INT-033 | `sensors.json.sun`, `/ephemeris` | `/stewie/sun` | custom or `Vector3Stamped` | started |
| world -> robot terrain | INT-001, INT-026, INT-040 | DEM/raster products | `/stewie/terrain_patch`, `/stewie/nav_factors` | DEM raster, `NavFactorArray` | partial |
| robot -> world motion | INT-008, INT-009, INT-044 | pure bridge, sim backend | `/cmd_vel`, `/stewie/odom` | `Twist`, `Odometry` | pure complete, live gated |
| robot -> world excavation | INT-012, INT-013, INT-014, INT-039 | planner orders, event log | `/stewie/work_goal`, `/stewie/terrain_events` | `WorkGoal`, event message needed | partial |
| robot -> world articulation | INT-030, INT-031 | joint channel, render-pair artifact | `/joint_states`, `/stewie/articulation_pair` | `JointState`, artifact | partial |
| perception -> estimator | INT-027, INT-032, INT-034, INT-035, INT-051 | factor ledger | `/stewie/nav_factors` | `NavFactorArray` needs covariance upgrade | partial |
| executive -> safety | INT-043, INT-045 | RC watchdog | `/stewie/safe_state`, `/stewie/executive_decision` | `SafeState`, `ExecutiveDecision` | partial |

## Cascade Index

| Cascade | Path | What it demonstrates | Current status |
|---|---|---|---|
| `CAS-001 slip_to_replan` | INT-006 -> INT-005 -> INT-009 -> INT-037 -> INT-020 | weak regolith raises slip, belief uncertainty, and replanning pressure | complete in sim |
| `CAS-002 excavation_mutates_shadow` | INT-012 -> INT-013 -> INT-016 -> INT-017 -> INT-025 | digging changes terrain, which changes rendered/observed shadow quality | started |
| `CAS-003 articulation_parallax_fix` | INT-030 -> INT-031 -> INT-032 | posture change creates a local position cue, but accepted producer is still needed | planned |
| `CAS-004 dem_anchor_loop` | INT-024 -> INT-026 -> INT-027 -> INT-037 | stereo/depth should become a DEM fix and lower uncertainty | planned |
| `CAS-005 build_plan_to_world_event` | INT-019 -> INT-020 -> INT-012 -> INT-013 -> INT-016 -> INT-046 | plan executes into terrain events, then routes update over changed terrain | partial |
| `CAS-006 safety_timeout` | INT-008 -> INT-044 -> INT-045 -> INT-043 | command stream must publish odom and safe on timeout | complete pure, live gated |

## Graphify Export

Graphify uses a regular `DiGraph`, so repeated state-block couplings can collapse if each table row is
exported only as `source -> target`. The STEWIE exporter therefore represents every `INT-###` row as a
first-class interaction node, with `source_block -> INT-### -> target_block`. This preserves all 51
interactions while keeping direction explicit.

| Artifact | Purpose |
|---|---|
| `scripts/export_stewie_interaction_graph.py` | Regenerates the Graphify extraction and built graph from this table. |
| `graphify-out/stewie_interaction_extraction_2026-06-28.json` | Graphify extraction JSON with 18 state blocks, 51 interaction nodes, and 102 directed graph hops. |
| `graphify-out/graph.json` | Queryable Graphify graph. |
| `graphify-out/STEWIE_INTERACTION_TREE.html` | Local HTML tree view of the STEWIE interaction graph. |

The `graphify-out/` files are untracked analysis output (see `.gitignore`); regenerate them with
`scripts/export_stewie_interaction_graph.py`. The `graphify` commands below are the local
graph-analysis CLI used for the diagnostics — the export script alone rebuilds the JSON.

Validation:

```bash
python3 scripts/export_stewie_interaction_graph.py
graphify diagnose multigraph --graph graphify-out/graph.json --json
graphify path "MissionPlan" "MutableTerrainLedger" --graph graphify-out/graph.json
graphify explain "INT-039" --graph graphify-out/graph.json
```

Current Graphify diagnostic result: 69 nodes, 102 directed edges, zero dangling endpoints, zero duplicate
edges, zero self-loops, and all 51 `INT-###` interactions retained.

## Current STEWIE Build Map

### Complete Or Load-Bearing

| Area | Evidence | Status |
|---|---|---|
| conserved physics and terrain mutation | `stewie/physics/*`, `stewie/twin/world_model.py` | complete in code |
| deterministic mission planning | `lode/mission_planner.py`, `lode/planner_*` | complete planner |
| belief overlay | `lode/autonomy.py` | complete in sim |
| command/odom bridge translation | `stewie/bridge/ros2_bridge.py`, bridge tests | complete pure |
| sensor file seam | `docs/sensor_bridge_contract.md`, Godot egress | complete file seam |
| typed factor contract | `dart/factors.py`, `dart/evidence_ledger.py` | complete contract |
| active perception env | `Stewie/ActivePerception-v0` | complete in sim |
| safing watchdog | `rc_contract`, `SafeState`, bridge tests | complete pure |

### Incomplete Or Gated

| Gap | Why it matters | Blocking edges |
|---|---|---|
| operational digital-twin unification | PRD still names authority + TwinStore + packets + PlanResult + belief as a forward item | INT-016, INT-039, INT-046 |
| live ROS node and pit backend | pure bridge exists but live mission operations are not fully deployed | INT-008, INT-044, INT-045 |
| covariance-rich `NavFactorArray` | current message is scalar and too narrow for typed factor contract | INT-027, INT-032, INT-034, INT-051 |
| truth-free `dem_xy` producer | DEM anchoring is planned but not operationally accepted | INT-026, INT-027 |
| truth-free `parallax_xy` producer | articulation parallax exists as geometry/render evidence but needs accepted producer | INT-031, INT-032 |
| measured joint readback | posture channel is simulated/measured-like, not hardware telemetry | INT-030 |
| thermal/PSR operational validation | thermal model is assumption-heavy | INT-022, INT-023, INT-049 |
| dust/occlusion model | excavation effects on perception are not coupled | INT-048 |
| Chrono force-accurate drum | PRD marks Tier-3 force drum and live Chrono producer as gated | INT-013 |

## Direct STEWIE Assessment

STEWIE is currently strongest as a construction-planning, conserved-physics simulation, and training
environment. It has real code for terrain conservation, route and energy planning, belief-state overlay,
safing, render egress, and typed navigation-factor contracts. The system should not yet be described as
a fully operational lunar construction digital twin, because the live ROS/pit path, transactionally
unified operational world-state log, covariance-rich factor transport, and de-oracled DEM/parallax
producers remain incomplete or gated.

## Claim Boundary

Claimable now:

- STEWIE has a real mass-conserving terrain transformation authority.
- STEWIE has deterministic mission planning with energy, recharge, cut/fill, and route accounting.
- STEWIE has a tested pure ROS command/odom bridge and safing watchdog.
- STEWIE has a documented sensor bridge and Godot render egress.
- STEWIE has a typed navigation-factor contract and evidence-ledger concept.
- STEWIE has simulation-level active perception and belief-state loops.

Not claimable yet:

- Fully operational live mission-operations digital twin.
- Hardware-validated lunar excavation autonomy.
- Truth-free DEM/parallax navigation factors end to end.
- Production ROS/Gazebo/Isaac bridge inventory.
- Hardware validation of lunar vacuum, one-sixth gravity, PSR thermal behavior, electrostatics, or no-atmosphere optics.
