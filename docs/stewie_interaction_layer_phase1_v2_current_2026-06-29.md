---
title: "STEWIE Interaction Layer Phase 1 v2, Current Names"
nav_order: 52
project: STEWIE
component: INT (Interaction Layer)
status: Coverage map, current implementation plus planned Phase 1 rows
schema_version: 2.0-current
entry_count: 60
created: 2026-06-29
source_current_graph: "docs/stewie_digital_twin_interaction_map_2026-06-28.md"
graphify_current: "graphify-out/graph.json"
---

# STEWIE Interaction Layer Phase 1 v2, Current Names

## Purpose

This file accounts for the full 60-row Phase 1 interaction taxonomy using the names STEWIE actually uses
today. It is a coverage map, not a renumbering of the current implementation graph.

- Current implementation graph: `INT-001..INT-051`, 18 state blocks, generated into `graphify-out/graph.json`.
- Phase 1 target taxonomy: 60 rows in family ranges `INT-010`, `INT-030`, `INT-040`, etc.
- This v2 map: target taxonomy plus current STEWIE source/target blocks, current variable names,
  `legacy_current_id` links, status, and next build.

## Status Legend

| Status | Meaning |
|---|---|
| complete | Current STEWIE has a load-bearing implementation. |
| partial | One side exists, but the full row is not closed end to end. |
| started | Code/artifacts exist, but a producer, message, calibration, or runtime wire is missing. |
| planned | Required by the taxonomy, not built as a current row. |
| sim_only | Lunar physics cannot be hardware-validated on STEWIE and remains simulation/reference only. |
| external_gated | Requires ROS host, pit link, hardware, Chrono, GPU model, or external data. |

## State Block Registry

### Current Blocks

`LunarSite`, `Ephemeris`, `TerrainMesh`, `RegolithState`, `ThermalEnvironment`, `LightingModel`,
`MutableTerrainLedger`, `RoverPose`, `RoverBelief`, `WheelDynamics`, `ExcavatorDrum`,
`ArticulationState`, `CameraRig`, `PerceptionState`, `MissionPlan`, `ExecutiveState`,
`PowerThermalState`, `SurveyedMonuments`.

### Added Phase 1 Target Blocks

| Block | Status | Why it is needed |
|---|---|---|
| `DustDynamics` | planned | Dust is a world-mediated state that affects optics, power, thermal, and mechanisms. |
| `CommunicationState` | planned | Line of sight, relay windows, latency, command ack, and comm-loss autonomy need a state block. |
| `MultiAgentCoordination` | planned | Shared terrain, map merge, path reuse, and deconfliction require explicit coordination state. |
| `HealthMonitoring` | planned | Wear, thermal faults, dust degradation, and mechanism life need explicit state. |
| `FaultDetection` | partial | Safety decisions exist, but fault state is not first-class in the interaction graph. |
| `ResourceModeling` | planned | Ice/volatile/resource value maps need a planning-facing state block. |
| `PredictionModels` | partial | Self-optimizing energy and active perception exist, but predictors are not a named graph block. |
| `DigitalTwinSync` | partial | `TransactionLog` exists, but runtime sync is not a first-class interaction block. |
| `PersistenceWorldState` | partial | `TerrainMemory`, `TwinStore`, and `TransactionLog` exist but are not unified behind one runtime service. |

## Phase 1 Interaction Coverage Table

| v2 ID | Family | Current source -> target | Current variables | Governing model | legacy_current_id | Status | Next build |
|---|---|---|---|---|---|---|---|
| INT-010 | A terramechanics | `TerrainMesh -> WheelDynamics` | `slope_deg`, `roughness`, `traversability`, `slip`, `power_w` | slope force balance, slip ladder | `INT-005` | complete | measured wheel telemetry |
| INT-011 | A terramechanics | `RegolithState -> WheelDynamics` | `cohesion_kpa`, `friction_angle_deg`, `density`, `slip` | Mohr-Coulomb, Janosi-Hanamoto | `INT-006` | complete | calibration against measured drawbar/current |
| INT-012 | A terramechanics | `RegolithState -> WheelDynamics` | `density`, `bearing_strength_kpa`, `sinkage_m`, `contact_pressure` | Bekker-Wong pressure-sinkage | `INT-006` | complete | `k_phi` calibration |
| INT-013 | A terramechanics | `TerrainMesh -> ArticulationState` | `obstacle_height_m`, `impact_accel`, `suspension_deflection` | contact impulse, suspension transfer | none | planned | add rock-impact and suspension response row |
| INT-014 | A terramechanics | `RegolithState -> WheelDynamics` | `density`, `traffic_count`, `rolling_resistance`, `power_w` | compaction/bulldozing resistance | `INT-015` | partial | compaction calibration and planner feedback |
| INT-015 | A terramechanics | `TerrainMesh + RegolithState -> WheelDynamics` | `slope_deg`, `bearing_strength_kpa`, `sinkage_m`, `entrapped` | progressive sinkage and rim collapse | none | planned | crater-rim entrapment scenario and detector |
| INT-030 | B excavation | `MissionPlan -> ExcavatorDrum` | `cut_depth_m`, `scoop_depth_m`, `torque_nm`, `dig_e` | excavation force and drum work | `INT-012` | partial | hardware command adapter and torque evidence |
| INT-031 | B excavation | `ExcavatorDrum -> MutableTerrainLedger` | `dheight_m`, `displaced_volume`, `kind`, `events[]` | mass-conserving cut event | `INT-013` | complete | real drum pass evidence |
| INT-032 | B excavation | `ExcavatorDrum -> TerrainMesh` | `fill_kg`, `dheight_m`, `radius_m`, `slope_deg` | conserved fill and repose | `INT-014` | complete | as-built stereo validation |
| INT-033 | B excavation | `WheelDynamics -> RegolithState` | `normal_load`, `traffic_count`, `density`, `bearing_strength_kpa` | compaction accumulation | `INT-015` | partial | density-channel calibration |
| INT-034 | B excavation | `ExcavatorDrum -> RegolithState + ResourceModeling` | `ice_frac`, `density`, `dig_energy_per_kg` | stratigraphic layer and volatile model | `INT-047` | planned | ice/resource dataset and layer model |
| INT-040 | C optical | `LightingModel -> CameraRig` | `scene_radiance`, `exposure`, `irradiance` | lunar BRDF and exposure model | `INT-003` | sim_only | camera noise/exposure model |
| INT-041 | C optical | `TerrainMesh + LightingModel -> CameraRig` | `heightmap`, `shadow_mask`, `contrast`, `exposure` | shadow casting and dynamic range | `INT-004`, `INT-025` | started | terrain-event shadow residuals |
| INT-042 | C optical | `LightingModel + RegolithState -> PerceptionState` | `phase_angle`, `albedo`, `feature_count` | Hapke phase function | none | planned | phase-angle feature degradation row |
| INT-043 | C optical | `TerrainMesh + LightingModel -> PerceptionState` | `shadow_mask`, `valid_disparity_fraction`, `disparity_confidence` | shadow volume and stereo matching | `INT-025` | started | covariance propagation |
| INT-044 | C optical | `LightingModel -> CameraRig + PowerThermalState` | `irradiance`, `exposure`, `power_w`, `soc_frac` | PSR radiometry and active illumination | `INT-003`, `INT-049` | sim_only | active illumination/power coupling |
| INT-047 | C optical | `LightingModel -> PerceptionState` | `sun_azimuth_deg`, `contrast`, `shadow_bearing_body`, `covariance` | sun-shadow geometry over time | `INT-025`, `INT-033` | started | full-row shadow confidence integration |
| INT-050 | D dust | `WheelDynamics + ExcavatorDrum -> DustDynamics` | `disturbance`, `lofted_mass`, `particle_velocity` | ballistic/electrostatic lofting | none | planned | add `DustDynamics` state and sim-only model |
| INT-051 | D dust | `DustDynamics -> CameraRig` | `dust_opacity`, `lens_coverage`, `exposure`, `feature_count` | deposition and transmittance loss | `INT-048` | planned | dust/occlusion camera degradation model |
| INT-052 | D dust | `DustDynamics -> PowerThermalState` | `radiator_emissivity`, `surface_temp_k`, `thermal_w` | dust-altered thermal rejection | none | planned | radiator contamination row |
| INT-053 | D dust | `DustDynamics -> PowerThermalState` | `array_obscuration`, `generated_power_w`, `soc_frac` | panel obscuration and I-V degradation | none | planned | solar panel dust model |
| INT-054 | D dust | `DustDynamics -> HealthMonitoring` | `joint_friction`, `wear_rate`, `actuator_current` | abrasive wear accumulation | none | planned | mechanism wear/health row |
| INT-060 | E thermal | `ThermalEnvironment -> PowerThermalState` | `absorbed_flux`, `surface_temp_k`, `heater_power_w` | radiative balance | `INT-022` | started | day heating row and telemetry |
| INT-061 | E thermal | `LightingModel + ThermalEnvironment -> PowerThermalState` | `shadow_mask`, `sink_temp_c`, `heater_power_w` | radiative cooling to cold sky | `INT-022`, `INT-049` | started | shadow thermal transient model |
| INT-062 | E thermal | `TerrainMesh + ThermalEnvironment -> WheelDynamics` | `surface_temp_k`, `conductive_flux`, `wheel_temp_c` | regolith contact conduction | none | planned | wheel/contact thermal row |
| INT-063 | E thermal | `Ephemeris + ThermalEnvironment -> PowerThermalState` | `extended_darkness_s`, `heater_power_w`, `soc_frac` | lunar night survival budget | none | sim_only | long-duration survival scenario |
| INT-064 | E thermal | `ThermalEnvironment -> HealthMonitoring` | `thermal_cycles`, `fatigue_index`, `failure_probability` | thermal fatigue accumulation | none | planned | long-horizon degradation row |
| INT-080 | F power | `Ephemeris + LightingModel -> PowerThermalState` | `sun_elevation_deg`, `incidence_angle`, `generated_power_w`, `soc_frac` | cosine-law generation | `INT-049` | started | solar generation model |
| INT-081 | F power | `ExcavatorDrum + WheelDynamics -> PowerThermalState` | `drive_torque_nm`, `torque_nm`, `current_a`, `power_w` | load-power mapping | `INT-007`, `INT-041` | partial | measured current and payload estimate |
| INT-082 | F power | `PowerThermalState -> ExecutiveState` | `soc_frac`, `reserve_frac`, `safe_reason`, `decision` | energy-aware mode arbitration | `INT-021`, `INT-043` | partial | SoC-to-executive policy topic |
| INT-083 | F power | `PowerThermalState -> MissionPlan` | `heater_power_w`, `mobility_budget_J`, `reserve_frac` | shared power budget arbitration | `INT-021`, `INT-022` | partial | thermal-aware planning objective |
| INT-084 | F power | `LightingModel -> PowerThermalState` | `shadow_mask`, `generated_power_w`, `soc_frac` | illumination-gated generation | `INT-049` | started | abrupt shadow generation drop |
| INT-100 | G localization | `SurveyedMonuments + TerrainMesh -> PerceptionState` | `feature_count`, `landmark_distribution`, `covariance` | feature/landmark observability | `INT-028`, `INT-029` | started | runtime landmark factor |
| INT-101 | G localization | `RegolithState + LightingModel -> PerceptionState` | `texture_density`, `contrast`, `inlier_ratio`, `drift_rate` | low-texture VO degradation | `INT-025` | planned | low-texture drift model |
| INT-102 | G localization | `WheelDynamics -> RoverBelief` | `slip`, `odom_drift_frac`, `pos_sigma_m` | slip-corrupted odometry | `INT-009` | complete | typed belief topic |
| INT-103 | G localization | `TerrainMesh -> PerceptionState + MutableTerrainLedger` | `changed_cells`, `observed_dem`, `resid` | map invalidation and change detection | `INT-040`, `INT-046` | partial | benchmark ingestion and read-back wire |
| INT-104 | G localization | `LightingModel -> PerceptionState` | `descriptor_stability`, `loop_closure`, `match_score` | appearance-variant loop closure | `INT-035` | partial | measured loop closure producer |
| INT-105 | G localization | `CameraRig -> PerceptionState` | `camera_name`, `coverage_overlap`, `map_completeness` | multi-view fusion | `INT-024` | partial | six-camera mapping expansion |
| INT-120 | H planning | `TerrainMesh -> MissionPlan` | `obstacle_height_m`, `keepout_mask`, `costmap` | cost-based path planning | `INT-010`, `INT-011` | complete | live detector input |
| INT-121 | H planning | `PredictionModels + RegolithState -> MissionPlan` | `predicted_slip`, `commanded_speed`, `traversability` | traction-aware velocity planning | `INT-005`, `INT-041` | partial | predictor block and planner objective integration |
| INT-122 | H planning | `RoverBelief -> MissionPlan + ExecutiveState` | `pos_sigma_m`, `dig_sigma_gate_m`, `decision` | uncertainty-aware planning | `INT-037`, `INT-043` | complete in sim | live covariance topic |
| INT-123 | H planning | `PredictionModels + LightingModel -> MissionPlan` | `forecast_shadow_map`, `activity_window`, `time_utc` | illumination-window scheduling | `INT-002`, `INT-049` | started | forecast window scheduler |
| INT-124 | H planning | `ResourceModeling -> MissionPlan` | `resource_value_map`, `ice_frac`, `goal_priority` | utility-based goal selection | `INT-047` | planned | resource map and goal selector |
| INT-140 | I fault/autonomy | `WheelDynamics -> FaultDetection -> ExecutiveState` | `current_a`, `slip`, `entrapped`, `safe_reason` | entrapment detector and recovery | `INT-005`, `INT-045` | partial | entrapment fault row and recovery action |
| INT-141 | I fault/autonomy | `ThermalEnvironment -> FaultDetection -> ExecutiveState` | `surface_temp_k`, `camera_operational`, `decision` | thermal fault response | `INT-023`, `INT-043` | planned | thermal fault producer |
| INT-142 | I fault/autonomy | `PerceptionState -> FaultDetection -> MissionPlan` | `disparity_confidence`, `valid_disparity_fraction`, `decision` | perception-health monitor | `INT-025`, `INT-043` | started | disparity floor gate |
| INT-143 | I fault/autonomy | `HealthMonitoring -> ExecutiveState` | `health_index`, `remaining_life`, `decision` | prognostics and derating | none | planned | health monitoring block |
| INT-144 | I fault/autonomy | `CommunicationState -> ExecutiveState` | `link_state`, `ack_deadline_s`, `safe_reason` | comm-loss contingency | none | planned | communication state and comm-loss policy |
| INT-160 | J multi-agent | `TerrainMesh -> MultiAgentCoordination -> MissionPlan` | `changed_cells`, `agent_id`, `route` | shared-world mediation | `INT-046` | planned | second-agent route update scenario |
| INT-161 | J multi-agent | `TerrainMesh + RegolithState -> MultiAgentCoordination` | `track_geometry`, `density`, `traversability` | path reuse or rut avoidance | `INT-015` | planned | track/rut interpretation |
| INT-162 | J multi-agent | `DustDynamics -> CameraRig` | `dust_density`, `agent_id`, `contrast` | spatial dust transmittance | none | planned | shared dust field |
| INT-163 | J multi-agent | `PerceptionState -> MultiAgentCoordination -> PersistenceWorldState` | `map_completeness`, `coverage_gaps`, `task_split` | map merging and coverage planning | none | planned | multi-agent map merge row |
| INT-164 | J multi-agent | `MultiAgentCoordination + PersistenceWorldState -> MissionPlan` | `relative_positions`, `reservation`, `right_of_way` | deconfliction/reservation | none | planned | reservation and collision-avoidance row |
| INT-180 | K communication | `TerrainMesh + Ephemeris -> CommunicationState` | `line_of_sight`, `link_state`, `position` | terrain-masked visibility | none | planned | LOS/relay geometry model |
| INT-181 | K communication | `Ephemeris -> CommunicationState -> ExecutiveState` | `one_way_light_time_s`, `ack_latency_s`, `bandwidth` | link budget and light-time delay | none | planned | latency injection and ack policy |
| INT-182 | K communication | `Ephemeris -> CommunicationState -> MissionPlan` | `contact_window`, `downlink_timing`, `store_forward` | relay pass scheduling | none | planned | contact-window scheduler |
| INT-200 | L sync/persistence | `RoverPose -> DigitalTwinSync -> PersistenceWorldState` | `x_m`, `y_m`, `yaw_rad`, `sequence_id`, `frame_id` | pose-indexed world update | `INT-044`, `INT-050` | partial | first-class sync service |
| INT-201 | L sync/persistence | `PersistenceWorldState -> DigitalTwinSync -> PerceptionState` | `state_diff`, `world_sha`, `divergence_metric` | state reconciliation | `INT-040`, `INT-046` | partial | transaction-linked reconciliation |
| INT-202 | L sync/persistence | `PersistenceWorldState -> all subsystems` | `checkpoint`, `chain_hash`, `world_sha`, `replay_diff` | checkpoint/restore and deterministic replay | none | partial | replay route and metric |
| INT-203 | L sync/persistence | `PredictionModels -> DigitalTwinSync` | `prediction_error`, `correction_event`, `uncertainty_m` | predictor-corrector update | `INT-041`, `INT-051` | partial | prediction residual into transaction log |

## Coverage Summary

| Status | Count |
|---|---:|
| complete | 8 |
| partial | 22 |
| started | 9 |
| planned | 18 |
| sim_only | 3 |

Interpretation:

- All 60 target interactions are now accounted for.
- Every row has a current STEWIE source and target name.
- Every row is either linked to a current `legacy_current_id` or explicitly marked as a planned v2 row.
- The weak families remain dust, multi-agent, communication, health/fault depth, and synchronization as a
  first-class runtime service.

## Current Completion Boundary

The layers are not complete, but they are now accountable:

1. The current 51-row graph remains the implementation status graph.
2. This 60-row table is the Phase 1 coverage graph.
3. The next implementation milestone is to export this v2 table to Graphify as a second graph and keep it
   separate from the current graph until rows graduate from planned to implemented.
