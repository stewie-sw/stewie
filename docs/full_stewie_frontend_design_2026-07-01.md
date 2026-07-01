---
title: Full STEWIE Frontend Design
nav_order: 55
---

# Full STEWIE Frontend Design

This is the cockpit design contract for using STEWIE as a full mission system: planning, rehearsal,
validation, release, execution, reporting, and engineering diagnostics. It complements `PRD.md` section
26.2 and keeps RViz/Gazebo as engineering visualization tools rather than separate command surfaces.

## Operating Model

The production cockpit is one authoritative browser application. It must expose the active mode, runnable
profile, selected sensor/depth-source profile, command authority, and truth-denial state on every mission
screen.

The primary workflow is:

```text
Plan -> Rehearse -> Validate -> Release -> Execute -> Report
```

System and Admin are supporting surfaces for health, governance, roles, and evidence retention. They do not
replace the mission workflow and do not own independent command approval.

## Mission Surfaces

| Surface | Operator purpose | Required state |
|---|---|---|
| Plan | Author the mission before solving | body, site, DEM, coordinate frame, ephemeris convention, vehicle, tool configuration, depth-source profile, constraints, goals, fleet/resource reservations |
| Rehearse | Compare candidate runs before release | candidate routes, costmap explanations, time/energy budgets, scenario variants, map deltas, contingency branches |
| Validate | Inspect whether the run is technically admissible | perception health, navigation factors, mapping freshness, ROS/Gazebo status, no-truth-input status, evidence links |
| Release | Freeze an executable revision | immutable plan hash, runtime profile, namespace, sensor profile, AG-08 eligibility, sign-off, artifact links |
| Execute | Command only the bounded next segment | next command/action, acknowledgements, watchdog, link state, covariance, map freshness, SAFE/pause/replan controls |
| Report | Produce the audit bundle | metrics, requirement IDs, claim labels, pass/fail/refuted status, cockpit/RViz screenshots, bags, logs, validation JSON |

## Required Cards

| Card | Required content | Blocks action when |
|---|---|---|
| Sensor Profile | vehicle, active cameras, selected depth source, calibration ID, covariance model, range limits, provenance | profile is missing, stale, legacy without override, or mismatched to runtime |
| Depth/Cloud Health | `DepthObservation` or `/stewie/perception/points`, source profile, frame, freshness, point count or valid fraction, confidence, dropped frames | the selected profile threshold is not met |
| Map/Belief Delta | observed DEM coverage, occupancy changes, changed-terrain mask, odom-vs-belief divergence, covariance threshold | covariance, map staleness, or terrain-change thresholds require replan/relocalize |
| Command Eligibility | role, namespace, release hash, SF-01 watchdog, link ack, SAFE state, bounded command | AG-08/NV-12/SF-01 rejects the command |
| ROS/Gazebo/RViz Status | lifecycle nodes, `/clock`, `/tf`, `/joint_states`, bridge topics, bag replay, RViz display status, process/container profile | runtime evidence does not match the selected profile |
| Evidence Drawer | requirement IDs, fixtures/bags, logs, metrics, screenshots, validation JSON, Graphify diagnostics, report links | a row or claim lacks linked evidence |

## Depth-Source UX

LiDAR is swappable when a sensor is available, but the UI treats stereo, LiDAR, RGB-D, simulator output, and
bag replay as profiles behind the same downstream contract. The operator sees provenance and quality; the
planner and mapper consume only the normalized `DepthObservation` or ROS `PointCloud2` view.

The cockpit must show:

- selected source profile: `stereo_sgbm`, `stereo_neural`, `lidar`, `rgbd`, or `replay`;
- calibration identity and frame;
- freshness, range limits, confidence, valid fraction or point count;
- covariance/uncertainty model;
- degraded mode and dropped-frame state;
- whether the source is simulation, replay, bench, HIL, or live.

## RViz/Gazebo Boundary

RViz and Gazebo are required for engineering confidence, not for separate operator control. The cockpit must
surface whether the selected run has matching RViz/Gazebo evidence: expected topics, bridge freshness,
screenshots, bag links, and no-truth-input assertions.

RViz may display robot model, TF, odom, planned path, local trajectory, costmaps, point cloud, camera feeds,
covariance, Navigation factors, diagnostics, SAFE state, and command topics. Gazebo may provide simulated
robot/sensor data. Neither tool can carry independent command authority, hidden approvals, or unique release
state.

## Implementation Rules

- Use typed adapters and normalized view models for every route, replay, and ROS bridge feed.
- Render explicit empty, loading, stale, degraded, error, permission-denied, and truth-denied states.
- Keep desktop and mobile as alternate layouts over the same route/state model.
- Never show fake telemetry, evaluator truth, or simulator truth as live measurement.
- Keep the interface dense and operational: charts, maps, and 3D views exist to inspect command consequence
  and evidence, not to explain the product.
