# STEWIE Bottom-Up Rover Autonomy Architecture Audit

Date: 2026-07-02
Scope: local full-stack lunar rover autonomy, simulation, digital twin, geospatial world model, Godot visualization, ROS 2/Gazebo/RViz runtime, terramechanics, perception, planning, live robot bridge
Prompt basis: bottom-up architecture audit for lunar rover autonomy, simulation, and digital twin
Skill applied: `lunar-mission-systems-audit`

## Verdict

STEWIE is partially coherent as a local lunar rover autonomy architecture, but it is not yet coherent as an end-to-end autonomy system. The repo has real foundations: an articulated IPEx rover xacro with wheels, drums, IMU, camera frames, depth mounts, Gazebo overlay, a frozen ROS 2 topic/frame contract, Gazebo bridge truth-denial tests, RViz config, Godot render/sensor assets, lunar terrain/world-model modules, terramechanics, costmap layers, perception algorithms, planner logic, cockpit evidence surfaces, and many tests. The weak point is integration order: the most mature autonomy logic lives in Python application modules and tests, while the ROS 2 packages are mostly skeleton nodes; Gazebo currently runs a flat regolith plane rather than the lunar terrain/world model; Godot is a render/sensor sidecar, not a live ROS 2 visualization bridge; and the observed perception -> world model -> planner -> command eligibility loop is still not closed. STEWIE should be treated as a strong autonomy/digital-twin scaffold, not as a finished rover autonomy stack.

## Current Evidence

### Implemented or strongly scaffolded

- Rover xacro: `ros2_ws/src/stewie_description/urdf/ipex.urdf.xacro:1` defines an IPEx vehicle with chassis, 4 wheels, 2 bucket drums, IMU, 8-camera rig, collision, inertials, joint limits, and TF tree.
- Gazebo overlay: `ros2_ws/src/stewie_description/urdf/ipex.gazebo.xacro:1` adds diff-drive, joint state publishing, pose publishing, IMU, contact, front stereo cameras, and simulated depth/point cloud source.
- Gazebo world: `ros2_ws/src/stewie_description/worlds/stewie_lunar.sdf:1` defines lunar gravity, low sun, sensors, IMU, contact systems, and flat regolith ground.
- Gazebo bridge: `ros2_ws/src/stewie_bringup/config/gz_bridge.yaml:1` maps `/cmd_vel`, `/clock`, `/joint_states`, IMU, wheel odom, contact, TF, stereo images, point cloud, and truth pose with truth-denial comments.
- ROS 2 autonomy contract: `stewie/bridge/autonomy_contract.py:1` freezes node roles, topics, QoS classes, frames, truth topics, command topics, and navigation-spine stages.
- RViz config: `ros2_ws/src/stewie_rviz/rviz/mission.rviz:1` binds RobotModel, TF, odometry, path, costmap, occupancy, DEM, point cloud, cameras, rocks, nav factors, covariance, and status markers.
- Godot sidecar: `stewie/godot/sidecar.gd:1` explicitly describes Godot as render and sensor model, not physics authority.
- Godot sensor schema: `stewie/godot/sensors_emit.gd:1` centralizes sensor-bridge egress and emits Godot-frame sensor metadata for conversion downstream.
- Terramechanics: `stewie/physics/terramechanics.py:1` implements Bekker pressure-sinkage and related lunar soil parameters.
- Rover terrain interaction: `stewie/physics/rover.py:1` implements wheel rut carving, 4-wheel tracks, drum terrain changes, and mass-conserving terrain state.
- Costmaps: `lode/costmap_layers.py:1` composes slope, roughness, sinkage, slip, tip risk, negative obstacles, illumination, PSR, shadow confidence, energy, keepout, and reservation layers with visible blocking reasons.
- Planner routing: `lode/planner_routing.py:1` includes slope/slip-aware Dijkstra routing, negative obstacles, illumination, uncertainty, and keepouts.
- Hazard mapping: `dart/hazard_map.py:1` builds hazard classes, confidence, slope, roughness, rock costs, no-go cells, and least-cost routes.
- World model: `stewie/twin/world_model.py:1` describes layered world-model ownership and includes an event-sourced terrain model.
- Terrain simulation spec: `ipex-terrain-sim-spec.md:38` already argues for a single physics authority, Godot render/sensor role, and ROS 2 downstream perception evaluation.

### Confirmed gaps

- ROS nodes in `ros2_ws/src/stewie_control`, `stewie_localization`, `stewie_mapping`, `stewie_perception`, `stewie_planning`, and `stewie_vehicle_interface` are skeletons. Example: `ros2_ws/src/stewie_perception/stewie_perception/node.py:1` says full domain logic lands later.
- Gazebo world is still a flat plane. It does not ingest lunar DEMs, obstacle maps, crater fields, geospatial transforms, or dynamic terrain state.
- `gz_bridge.yaml` references `/model/ipex/perception/points` at `ros2_ws/src/stewie_bringup/config/gz_bridge.yaml:63`, while the Gazebo xacro sensor topic is `/model/ipex/perception` at `ros2_ws/src/stewie_description/urdf/ipex.gazebo.xacro:90`; this needs a running-sim smoke test or correction.
- ROS 2 runtime does not yet host the Python perception, mapping, world-model, planner, or terramechanics logic.
- Godot is currently a batch/headless renderer and sensor egress tool, not a live ROS 2 visualization layer.
- Product mode and runnable profile are not consistently carried through frontend, backend, ROS, release, execute, and reports.
- No demonstrated live robot or HIL connection with `ros2_control`, hardware interfaces, calibration, time sync, and command safety in one loop.

### Verification performed

```text
.venv/bin/python -m pytest ros2_ws/test_*.py
47 passed
```

Previously run in the same audit sequence:

```text
node --test stewie/server/web/assets/*.test.js stewie/server/web/assets/panes/*.test.js
281 passed

.venv/bin/python -m pytest <focused frontend/backend/world/nav/perception suite>
129 passed

.venv/bin/python -m pytest <DART/LODE/LEAP lunar domain suite>
121 passed
```

## Corrected Bottom-Up Architecture

### Layer 0: Runtime authority and modes

This must be the first architectural primitive, before UI or mission planning.

Required runtime modes:

- `offline_demo`: local fixtures, no command authority.
- `gazebo_sim`: Gazebo produces sensors and physics, ROS 2 autonomy consumes them.
- `godot_render`: Godot produces rendered imagery/sensor corpora from canonical state fields.
- `replay`: rosbag and mission package playback, no live actuation.
- `hil`: hardware-in-loop with simulated world and real controllers or sensors.
- `bench_robot`: local testbed rover, constrained command namespace.
- `live_rover`: real robot authority, released mission only.

Every mission artifact must carry:

```text
body + site + mission + runtime_mode + runnable_profile + source_class + vehicle + role + command_namespace
```

Failure boundary:

- No low-level command is emitted unless the mode/profile and authority gates permit it.
- Truth/evaluation topics are never estimator inputs.
- UI display does not imply command capability.

### Layer 1: Canonical rover description

URDF/Xacro is the single kinematic and frame authority.

Belongs in URDF/Xacro:

- Link tree: `base_link`, wheel links, drum arm links, drum links, IMU link, camera mount links, optical frames, depth/lidar/RGB-D mounts.
- Joints: continuous wheel joints, revolute arm joints, continuous drum spin joints, fixed sensor joints.
- Visual and collision geometry sufficient for RViz/Gazebo.
- Mass, inertial tensors, actuator effort/velocity limits.
- REP-103 frame names and optical frame conventions.
- Configurable xacro args such as stereo baseline and optional payload/sensor variants.

Belongs in Gazebo/SDF:

- Sensor plugins: IMU, contact, cameras, lidar/depth.
- Physics plugins: diff-drive or ros2_control/Gazebo system plugin.
- Contact/friction coefficients, lunar gravity, lighting, terrain collision.
- World assets: DEM mesh/heightfield, craters, rocks, terrain material properties.
- Simulation-only truth publishers, isolated to truth topics.

Belongs in ROS 2 runtime state:

- Joint states and actuator state.
- TF tree from robot_state_publisher plus odom/map estimates.
- Sensor messages, timestamps, camera info, calibration, health.
- Controller state, command envelopes, watchdog/safe state.
- Localization covariance, map freshness, planner state, command acknowledgements.

Critical correction:

The URDF currently exists and is useful, but `ros2_control` is not yet the actuation authority. Add transmissions/controllers and make Gazebo and live robot both use the same controller interface.

### Layer 2: ROS 2 runtime spine

ROS 2 should own live autonomy dataflow. The current `autonomy_contract.py` is the right spine, but its packages must become real nodes.

Minimal runtime graph:

```text
Gazebo or robot drivers
  -> sensing node
  -> perception node
  -> localization node
  -> mapping node
  -> costmap/planning node
  -> control node
  -> vehicle_interface node
  -> mission_executive node
  -> diagnostics/safety node
```

Failure boundaries:

- Sensor source failure degrades perception and blocks live release when required.
- Localization covariance failure pauses/relocalizes rather than continuing blindly.
- Map freshness failure blocks route release or marks route as forecast-only.
- Planner refusal is a typed output, not an empty path.
- Control failure forces safe state.
- Vehicle interface failure stops command emission.

### Layer 3: Simulation stack

Gazebo should be the physics and sensor runtime for Phase 0/5 autonomy testing.

Gazebo owns:

- Rigid-body dynamics.
- Contact and drive dynamics.
- Simulated IMU, wheel odom, cameras, point clouds.
- Truth channel for evaluation only.
- Deterministic scenario execution.

RViz owns:

- RobotModel.
- TF.
- Sensor streams.
- Point clouds.
- Odometry/covariance.
- Costmaps.
- Planned paths and local trajectories.
- Rock/hazard markers.
- Safety and executive markers.

ROS 2 owns:

- Topic graph.
- TF tree.
- Navigation, mapping, planning, control nodes.
- Bags, replay, lifecycle, parameters, diagnostics.

Godot should not replace Gazebo for physics unless a deliberate future architecture chooses Project Chrono/Godot and retires Gazebo. Given this prompt assumes Gazebo, use Godot as render/mission visualization, not the source of dynamics.

### Layer 4: Godot visualization and render/sensor bridge

Godot should visualize:

- Terrain mesh/heightfield.
- Rover pose and articulation.
- Sensor cones and camera frustums.
- Planned global path and local trajectory.
- Traversability, hazard, costmap, uncertainty, observed mask.
- Excavation zones, planned structures, work orders.
- Sun vector, shadows, PSR/cold-trap zones.
- Localization covariance and nav factors.
- Mission progress, stage gates, command authority state.

Godot should produce:

- Rendered camera imagery for perception testing.
- Sensor metadata and camera intrinsics/extrinsics.
- Scenario screenshots/video.
- Operator/mission rehearsal visuals.

Godot should not own:

- Robot dynamics.
- Command authority.
- ROS TF authority.
- Planner truth state.
- Real robot telemetry authority.

Required bridge:

- ROS 2 to Godot: `/tf`, `/joint_states`, `/stewie/odom`, `/stewie/plan/path`, `/stewie/costmap`, `/stewie/map/*`, `/stewie/perception/rocks`, `/stewie/nav/factors`, `/stewie/exec/decision`.
- Godot to ROS 2 only in render/sensor mode: image frames, camera metadata, optional synthetic point clouds, with explicit `source_class=sim_render`.

### Layer 5: Lunar geospatial/world model

The geospatial world model must bridge three coordinate systems:

```text
Lunar body CRS / site CRS
  -> local engineering frame map
  -> odom
  -> base_link
  -> sensor frames
```

Canonical world assets:

- DEM/DTM.
- Orthomosaic/imagery.
- Slope.
- Roughness.
- Regolith/material class.
- Rock/crater maps.
- Illumination/shadow maps.
- PSR/cold-trap flags.
- Communications/line-of-sight layers.
- Traversability/cost maps.
- Observed mask.
- Uncertainty/sigma layer.
- Terrain deltas and world transactions.

ArcGIS/open geospatial boundary:

- Do not claim full ArcGIS platform support until the repo supports named service contracts.
- Immediate target should be "ArcGIS-compatible/open geospatial mission package":
  - GeoTIFF/COG DEM.
  - GeoJSON/FlatGeobuf vector features.
  - OGC WMS/WMTS where needed.
  - STAC-style metadata.
  - Mission package manifest.
  - Optional ArcGIS Feature Service adapter later.

Required transform contracts:

- `body_crs -> site_enu`.
- `site_enu -> map`.
- `map -> odom`.
- `odom -> base_link`.
- `base_link -> sensors`.
- `Godot Y-up <-> ROS REP-103`.

### Layer 6: Terramechanics-aware autonomy

Terramechanics is not decoration; it should drive costmaps and mission feasibility.

Variables:

- Simulated: sinkage, slip, wheel-soil contact state, terrain deformation, dust, excavated/dumped material, wheel rut, drum interaction.
- Sensed: wheel odom, IMU, actuator current/torque where available, camera observations, point cloud/elevation map.
- Estimated: slip ratio, traction margin, sinkage, terrain class, excavation state, regolith volume change, confidence.
- Learned: semantic terrain class, rock/hazard detection, image-depth priors, optional slip predictors, but only with calibrated uncertainty and fallback physics.

Minimum cost terms:

- Slope.
- Roughness.
- Sinkage.
- Slip risk.
- Tip risk.
- Negative obstacle/drop-off.
- Rock/hazard occupancy.
- Illumination/shadow perception risk.
- Energy.
- Keepout/reservation.
- Map uncertainty.
- Excavation resistance and tool availability for surface work.

### Layer 7: Perception, mapping, navigation

Perception pipeline:

```text
stereo images + camera_info + IMU + wheel odom
  -> synchronization/calibration gate
  -> feature tracking
  -> stereo/depth/point cloud
  -> visual/depth odometry
  -> rock/hazard classification
  -> semantic terrain classification
  -> local elevation map
  -> observed mask + uncertainty
  -> world transaction
  -> planner costmap
  -> cockpit/RViz/Godot evidence
```

Navigation pipeline:

```text
map + odom + mission intent + world layers
  -> global route
  -> local costmap
  -> local trajectory
  -> behavior tree / executive
  -> bounded command
  -> acknowledgement
  -> telemetry feedback
  -> replan/recover/safe
```

Missing critical loop:

```text
new sensor hazard
  -> classifier
  -> observed map update
  -> world transaction
  -> costmap update
  -> route or eligibility change
  -> release/execute evidence
```

This loop is the central proof that STEWIE is autonomy architecture rather than visualization.

## Subsystem Diagrams

### Runtime architecture

```text
                 +----------------+
                 | Mission Cockpit |
                 | Program/Admin  |
                 +-------+--------+
                         |
                         v
+-----------+     +-------------+     +------------------+
| Geo World | --> | Mission API | --> | ROS 2 bridge/API |
+-----+-----+     +------+------+     +---------+--------+
      |                  |                      |
      v                  v                      v
+-----------+     +-------------+     +------------------+
| World     | <-> | Planner     | <-> | ROS 2 Autonomy   |
| Twin      |     | Evidence    |     | Runtime          |
+-----+-----+     +------+------+     +---------+--------+
      |                  |                      |
      v                  v                      v
+-----------+     +-------------+     +------------------+
| Godot     |     | RViz        |     | Gazebo / Robot   |
| Viz/Render|     | Operator Viz|     | Sensors/Control  |
+-----------+     +-------------+     +------------------+
```

### ROS 2 autonomy graph

```text
/clock /tf /joint_states /stewie/imu /stewie/wheel_odom /camera/*
        |
        v
  perception
        | /features /points /rocks
        v
  localization ------------------+
        | /odom /cov /nav/factors|
        v                        |
  mapping                        |
        | /map/dem /map/occupancy|
        v                        |
  planning <---------------------+
        | /plan/path /plan/local_traj /costmap
        v
  control
        | /cmd_vel
        v
  vehicle_interface or Gazebo bridge
        |
        v
  rover actuation / simulated actuation

diagnostics + mission_executive watch all safety-critical state and publish safe/decision topics
```

### Digital twin state flow

```text
Baseline DEM + GIS layers
        |
        v
World layer manifest
        |
        v
Observed sensor update -> World transaction -> Derived terrain/current world
        |                       |
        v                       v
Perception evidence       Planner costmap
        |                       |
        +-----------> Release/Execute evidence
```

### Simulation/render authority

```text
Gazebo
  owns physics, sensors, simulated truth
  publishes ROS sensor topics and truth-only evaluation topics

ROS 2
  owns autonomy, TF, costmap, planning, control, logging

RViz
  displays ROS 2 state for engineering/operator debugging

Godot
  displays/render-rehearses mission state and produces sensor-faithful rendered imagery
  does not replace Gazebo dynamics in this architecture
```

## Required ROS 2 Packages, Nodes, Topics, Services, Actions

### Packages

Existing package names are good and should remain:

- `stewie_description`: URDF/Xacro/SDF/Gazebo world.
- `stewie_msgs`: custom messages.
- `stewie_bringup`: Gazebo, RViz, autonomy bringup.
- `stewie_perception`: feature, depth, hazard, terrain classification nodes.
- `stewie_localization`: VIO/depth odometry/fusion/pose graph nodes.
- `stewie_mapping`: elevation map, occupancy, observed mask, uncertainty, world update nodes.
- `stewie_planning`: costmap, global planner, local planner, mission task adapter.
- `stewie_control`: trajectory follower and bounded command lowering.
- `stewie_vehicle_interface`: Gazebo/live hardware interface.
- `stewie_executive`: behavior tree, safing, command eligibility, mission state machine.
- `stewie_rviz`: RViz configs and marker adapters.

Needed additions:

- `stewie_godot_bridge`: ROS 2 <-> Godot websocket/native bridge for visualization and rendered sensor ingestion.
- `stewie_geospatial`: DEM/layer package ingest, CRS transforms, map manifests.
- `stewie_terramechanics`: ROS wrappers around `stewie.physics` and `lode.costmap_layers`.
- `stewie_replay`: rosbag/mission package replay and scoring.
- `stewie_hardware`: ros2_control hardware interfaces, calibration, time sync, bench robot adapters.

### Nodes

Core nodes:

- `robot_state_publisher`
- `joint_state_broadcaster`
- `controller_manager`
- `diff_drive_controller` or rover-specific skid controller
- `stewie_sensor_mux`
- `stewie_perception_node`
- `stewie_depth_node`
- `stewie_hazard_node`
- `stewie_localization_node`
- `stewie_pose_graph_node`
- `stewie_mapping_node`
- `stewie_world_update_node`
- `stewie_costmap_node`
- `stewie_global_planner_node`
- `stewie_local_planner_node`
- `stewie_behavior_tree_node`
- `stewie_control_node`
- `stewie_vehicle_interface_node`
- `stewie_safety_watchdog_node`
- `stewie_mission_executive_node`
- `stewie_godot_bridge_node`
- `stewie_gis_bridge_node`
- `stewie_bag_recorder_node`
- `stewie_replay_node`

### Topics

Already defined in the contract and should remain:

- `/clock`
- `/tf`
- `/tf_static`
- `/joint_states`
- `/stewie/imu`
- `/stewie/wheel_odom`
- `/stewie/contact`
- `/stewie/camera/front_left/image`
- `/stewie/camera/front_right/image`
- `/stewie/perception/features`
- `/stewie/perception/points`
- `/stewie/perception/rocks`
- `/stewie/localization/visual_odom`
- `/stewie/localization/depth_odom`
- `/stewie/localization/loop_closures`
- `/stewie/odom`
- `/stewie/nav/factors`
- `/stewie/localization/cov`
- `/stewie/map/dem`
- `/stewie/map/occupancy`
- `/stewie/map/excavation_state`
- `/stewie/costmap`
- `/stewie/plan/path`
- `/stewie/plan/local_traj`
- `/stewie/plan/action_goal`
- `/cmd_vel`
- `/diagnostics`
- `/stewie/safe_state`
- `/stewie/exec/decision`

Add:

- `/stewie/camera/front_left/camera_info`
- `/stewie/camera/front_right/camera_info`
- `/stewie/camera/rear_left/image`
- `/stewie/camera/rear_right/image`
- `/stewie/camera/side_left/image`
- `/stewie/camera/drum_front/image`
- `/stewie/perception/hazards`
- `/stewie/perception/terrain_class`
- `/stewie/map/observed_mask`
- `/stewie/map/uncertainty`
- `/stewie/map/traversability`
- `/stewie/world/transactions`
- `/stewie/terramech/slip`
- `/stewie/terramech/sinkage`
- `/stewie/energy/prediction`
- `/stewie/mission/state`
- `/stewie/release/evidence`
- `/stewie/command/ack`
- `/stewie/godot/visual_state`
- `/stewie/truth/pose`
- `/stewie/truth/dem`
- `/stewie/truth/clasts`
- `/stewie/truth/excavation`

### Services

- `/stewie/load_mission_package`
- `/stewie/load_site`
- `/stewie/get_layer_manifest`
- `/stewie/commit_world_transaction`
- `/stewie/query_world_state`
- `/stewie/plan_global_route`
- `/stewie/plan_local_trajectory`
- `/stewie/validate_release`
- `/stewie/arm_execution`
- `/stewie/disarm_execution`
- `/stewie/set_runtime_profile`
- `/stewie/get_runtime_profile`
- `/stewie/reset_sim`
- `/stewie/export_mission_package`
- `/stewie/start_rosbag_record`
- `/stewie/stop_rosbag_record`

### Actions

- `/stewie/navigate_to`
- `/stewie/execute_mission`
- `/stewie/excavate`
- `/stewie/build_surface_asset`
- `/stewie/relocalize`
- `/stewie/run_rehearsal`
- `/stewie/replay_bag`

## Required File And Folder Structure

Recommended target structure:

```text
ros2_ws/
  src/
    stewie_description/
      urdf/
        ipex.urdf.xacro
        sensors.xacro
        ros2_control.xacro
      worlds/
        stewie_lunar_flat.sdf
        haworth_dem.world.xacro
      meshes/
      config/
        controllers.yaml
        sensor_profiles.yaml
    stewie_msgs/
      msg/
      srv/
      action/
    stewie_bringup/
      launch/
        phase0_gazebo.launch.py
        phase1_godot_bridge.launch.py
        autonomy_stack.launch.py
        rviz.launch.py
      config/
        gz_bridge.yaml
        params/
    stewie_perception/
      stewie_perception/
        feature_node.py
        depth_node.py
        hazard_node.py
        terrain_class_node.py
    stewie_localization/
      stewie_localization/
        vio_node.py
        pose_graph_node.py
        fusion_node.py
    stewie_mapping/
      stewie_mapping/
        elevation_map_node.py
        occupancy_node.py
        world_update_node.py
    stewie_planning/
      stewie_planning/
        costmap_node.py
        global_planner_node.py
        local_planner_node.py
        mission_adapter_node.py
    stewie_control/
      stewie_control/
        trajectory_follower_node.py
        command_limiter_node.py
    stewie_vehicle_interface/
      stewie_vehicle_interface/
        gazebo_interface_node.py
        hardware_interface_node.py
    stewie_executive/
      stewie_executive/
        behavior_tree_node.py
        safety_watchdog_node.py
    stewie_godot_bridge/
      stewie_godot_bridge/
        bridge_node.py
        visual_state.py
    stewie_geospatial/
      stewie_geospatial/
        layer_manifest.py
        crs_transform.py
        mission_package.py
    stewie_rviz/
      rviz/
        mission.rviz

stewie/
  bridge/
    autonomy_contract.py
    ros_messages.py
  physics/
    terramechanics.py
    rover.py
    column_state.py
  twin/
    world_model.py
    layer_manifest.py
    transactions.py
  geospatial/
    body_crs.py
    import_export.py
    arcgis_adapter.py
  godot/
    project.godot
    sidecar.tscn
    bridge/
    assets/
  server/
    routers/
    web/
  runtime/
    replay_loop.py
    mission_package.py

datasets/
  lunar_dem/
  mission_packages/
  calibration/

design/
  architecture/
  audits/
```

## Import, Export, And Interoperability

Canonical formats:

- Rover model: URDF/Xacro as primary; generated SDF for Gazebo; GLB for Godot visuals.
- Simulation world: SDF/world xacro generated from mission package.
- ROS logs: rosbag2 with metadata and mission manifest pointer.
- Geospatial rasters: GeoTIFF/COG for DEM, slope, roughness, illumination, uncertainty.
- Vectors: GeoJSON/FlatGeobuf for keepouts, routes, zones, surface assets, targets.
- Grid maps: `grid_map_msgs/GridMap` in ROS, with export to GeoTIFF/COG.
- Costmaps: `nav_msgs/OccupancyGrid` for ROS display/control, with richer layer manifest in mission package.
- Point clouds: `sensor_msgs/PointCloud2`, PLY/LAZ/E57 export where needed.
- Mission plans: JSON/YAML with schema version, route, tasks, constraints, authority tuple, and evidence links.
- Godot terrain: generated heightfield/mesh plus state texture fields from the same world layer manifest.
- ArcGIS adapter: Feature Service/GeoJSON/COG boundary only after explicit adapter implementation and tests.

Required conversion scripts:

- `xacro_to_sdf.py`
- `urdf_to_godot_scene.py` or a generated visual kinematic tree exporter.
- `dem_to_gazebo_heightfield.py`
- `dem_to_godot_heightfield.py`
- `gridmap_to_geotiff.py`
- `geotiff_to_gridmap.py`
- `mission_package_export.py`
- `mission_package_import.py`
- `rosbag_to_world_transactions.py`
- `world_transactions_to_replay.py`

## Implementation Roadmap

### Phase 0: Local ROS 2/Gazebo/RViz rover twin

Goal:

Run the rover locally in Gazebo, display it in RViz, publish the contract topics, record a bag, and prove truth-denial.

Work:

- Add `ros2_control.xacro` and controller config.
- Fix/verify the Gazebo point-cloud topic mismatch.
- Add `camera_info` topics.
- Add launch file that starts Gazebo, robot_state_publisher, controllers, bridge, RViz, and bag recording.
- Add running-sim smoke test in container: topics publish, `/cmd_vel` moves rover, `/stewie/truth/pose` is truth-only.

Acceptance:

- `ros2 topic hz` shows IMU, wheel odom, camera, point cloud.
- RViz shows robot, TF, odom, point cloud, path placeholder.
- A short `/cmd_vel` run produces a rosbag and no estimator subscribes truth.

### Phase 1: Godot visualization bridge

Goal:

Godot visualizes ROS state live without becoming physics authority.

Work:

- Add `stewie_godot_bridge`.
- Subscribe to TF, joint states, odom, path, costmap, hazards, and mission state.
- Publish no commands initially.
- Render the same URDF-derived articulated pose using generated Godot scene assets.

Acceptance:

- Gazebo drives ROS; Godot follows rover pose/articulation and overlays path/costmap/hazards.
- Killing Godot does not affect ROS autonomy.

### Phase 2: Lunar terrain/world model

Goal:

Use real mission packages to drive Gazebo, Godot, planner, and cockpit from one layer manifest.

Work:

- Implement `LayerManifest`.
- Generate Gazebo terrain collision from DEM.
- Generate Godot terrain/state textures from same DEM/world state.
- Add body/site CRS transforms and tests.
- Export/import mission package.

Acceptance:

- One Haworth package loads into Gazebo, Godot, ROS map topics, and cockpit with identical bounds/resolution metadata.

### Phase 3: Terramechanics-aware costmaps

Goal:

Make existing terramechanics/costmap Python logic a ROS 2 costmap node.

Work:

- Wrap `lode.costmap_layers.compose`.
- Publish layered GridMap and OccupancyGrid.
- Include slope, roughness, sinkage, slip, tip risk, energy, shadow, uncertainty, keepouts.
- Add visible blocking reasons.

Acceptance:

- A terrain slope/sinkage hazard changes the planned route.
- RViz and cockpit show the blocking reason.

### Phase 4: Perception and mapping

Goal:

Promote DART perception algorithms into ROS 2 nodes and close sensor-to-map update path.

Work:

- Implement stereo feature and depth nodes.
- Implement hazard/rock node from `dart.hazard_map` and rock modules.
- Implement local elevation map, observed mask, uncertainty.
- Add world transaction publisher.

Acceptance:

- Injected stereo/Gazebo/Godot frames produce hazards, observed map, uncertainty, and world transaction.

### Phase 5: Autonomy/navigation

Goal:

Close global/local planning, behavior tree, recovery, and command lowering.

Work:

- Global planner consumes world layer manifest and costmap.
- Local planner publishes bounded trajectory.
- Controller emits `/cmd_vel` only through safety gate.
- Executive monitors covariance, diagnostics, command ack, release state, and map freshness.

Acceptance:

- Injected hazard causes replan or refusal.
- Localization covariance failure causes relocalize/safe decision.
- Command without release in live profile is refused.

### Phase 6: Live robot integration

Goal:

Connect bench rover/testbed through the same ROS 2 interfaces.

Work:

- Implement `ros2_control` hardware interface.
- Add sensor drivers.
- Add calibration files and transforms.
- Add time synchronization.
- Add command namespace and live safety watchdog.
- Add live telemetry and bag recording.

Acceptance:

- Same autonomy launch runs with `gazebo_sim` and `bench_robot` profiles.
- Live robot commands are bounded, acknowledged, logged, and replayable.

### Phase 7: Mission rehearsal and validation

Goal:

Prove full mission rehearsal and validation loop.

Work:

- Mission package -> Gazebo/Godot/ROS/cockpit.
- Rehearsal run -> rosbag -> replay -> scoring.
- Plan-vs-actual divergence.
- Mapping accuracy, slip prediction, energy prediction, mission success metrics.
- Report artifact with evidence links.

Acceptance:

- One command runs the minimum mission scenario and produces a pass/fail report with bags, world transactions, route, costmap, hazards, and screenshots.

## Risk Register

| Risk | Severity | Evidence | Mitigation |
|---|---:|---|---|
| ROS nodes are skeletons while Python modules contain real logic | High | `ros2_ws/src/stewie_perception/stewie_perception/node.py:1` and peers | Promote Python modules into ROS nodes phase by phase; keep host-side tests plus running-sim tests |
| Gazebo world is flat and not driven by lunar DEM/world model | High | `stewie_lunar.sdf:32` flat regolith plane | Generate Gazebo terrain from mission package DEM |
| Perception-to-world-to-planner loop is not closed | High | Current audits and FANOUT PM-19/FS-29 | Build injected-hazard end-to-end acceptance test |
| Godot may be confused with simulator authority | High | Godot sidecar says render-only; terrain spec says Chrono/Godot split | Keep Gazebo/ROS as Phase 0 authority; label Godot visualization/render role |
| ArcGIS claim can overstate implemented interop | Medium | GIS tests exist, but full ArcGIS service contracts not proven | Use open geospatial mission package first; add explicit ArcGIS adapter later |
| Frame mismatch between Godot Y-up and ROS Z-up | High | `ipex-terrain-sim-spec.md:305` notes this friction | Centralize transform conversion and test with known control points |
| Gazebo bridge topic mismatch for point cloud | Medium | xacro topic `/model/ipex/perception`; bridge expects `/model/ipex/perception/points` | Run container sim smoke and fix naming |
| `ros2_control` not yet the canonical control interface | High | No controller config/transmission path in inspected files | Add ros2_control xacro and controllers in Phase 0 |
| Terramechanics calibration uncertainty | Medium | `terramechanics.py:28` notes parameter disagreement | Add calibration profiles and benchmark against Chrono/field data |
| Live robot safety not end-to-end proven | High | Teleop authority logic exists, live hardware loop not shown | Bench profile first; require release/ack/watchdog/audit for live |
| World layer manifest incomplete | High | World routes exist, unified per-cell manifest still a gap | Implement material/traversability/observed/uncertainty layer manifest |
| Product/runtime profile not consistently carried | High | Previous frontend audit FS-25 | Add authority tuple to URL, backend, ROS metadata, release, execute, report |

## Minimum Demo That Proves The Concept Works

The minimum convincing demo is not a pretty render. It is an end-to-end local autonomy loop:

1. Launch Gazebo lunar rover twin, ROS 2 autonomy stack, RViz, Godot bridge, and cockpit from one command.
2. Load a small lunar mission package containing DEM, imagery metadata, keepouts, target, and rover profile.
3. Gazebo publishes IMU, wheel odom, stereo images, point cloud, joint states, TF, and truth-only pose.
4. Perception node detects or ingests an injected rock/hazard from sensor data.
5. Mapping node updates observed mask, uncertainty, occupancy, and world transaction.
6. Costmap node recomputes layered traversal cost and blocking reasons.
7. Planner produces a new route around the hazard or a typed refusal.
8. Executive determines command eligibility from runtime profile, map freshness, covariance, release state, diagnostics, and safety.
9. Controller emits bounded `/cmd_vel` only if eligible.
10. RViz shows robot, TF, point cloud, map, costmap, path, covariance, hazard markers, and safe state.
11. Godot shows rover pose/articulation, terrain, sensor cones, hazard, uncertainty, path, shadows, and mission progress.
12. Rosbag records the run.
13. Replay reproduces the same map update, planner impact, and pass/fail report.

Acceptance command shape:

```text
make phase0_demo
make inject_hazard_demo
make replay_last_demo
make validate_last_demo
```

Pass criteria:

- A seeded hazard absent from the initial DEM changes the costmap and route.
- The same event appears in ROS topics, world transactions, cockpit evidence, RViz, and Godot.
- Truth pose is available only to evaluator/scorer, not estimators.
- The replay produces the same planner decision.
- A live-profile command without release is refused.

## Critical Redesign Principle

Do not build more UI until the ROS 2 runtime spine can carry one complete local autonomy story. The repo already has many sophisticated pieces; the next value is integration discipline. The corrected architecture is:

```text
URDF/Xacro rover
  -> Gazebo simulation
  -> ROS 2 sensor topics
  -> perception/localization/mapping
  -> world transaction and layer manifest
  -> terramechanics-aware costmap
  -> planner/executive/control
  -> RViz/Godot/cockpit evidence
  -> rosbag replay and validation report
```

Anything outside that path should be treated as secondary until this minimum loop is green.
