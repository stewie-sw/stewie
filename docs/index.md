---
title: Home
nav_order: 1
---

# STEWIE

**Surface Terrain Engineering & World-model Integration Environment.**
*IPEx builds the Moon. STEWIE plans the build.* (in silico, then in situ.)

STEWIE is a platform for planning and rehearsing lunar surface construction. It brings the pieces an
off-world earthmoving mission needs into one workspace: a GIS mission map over real lunar terrain, a
versioned digital twin of the worksite, a conserved-physics terramechanics core, an energy-aware
mission planner, and an autonomy and runtime middleware layer. IPEx (NASA's ISRU Pilot Excavator) is
the first vehicle STEWIE plans for, not a component of it. The lineage is NASA's IPEx program and the
JHU APL Lunar Autonomy Challenge; STEWIE is an independent stack, not the official challenge entry.
Owners: John McCardle & Aaron Storey ([github.com/stewie-sw/stewie](https://github.com/stewie-sw/stewie)).

## The front door: a GIS mission-control IDE

The primary surface is a GIS mission workbench, live at
[artemis.stewie.space/ide/](https://artemis.stewie.space/ide/); the bare
[artemis.stewie.space](https://artemis.stewie.space) redirects to it, so the IDE is the single front
door. It is one persistent lunar map (QGIS Web Client 2 over a QGIS Server backend) in the Moon
south-polar stereographic frame (`IAU_2015:30135`), so the pole sits in the middle of the canvas and
coordinates stay pole-truthful (no Earth or WGS84 claim on lunar positions). It carries the real terrain
(8 Artemis III candidate-site DEMs at LOLA 5 m polar, a 1 m Haworth shape-from-shading DEM, slope,
hillshade, and LROC imagery context, with nine candidate-site pins that zoom on click); a full
mission-authoring tool palette (cut and fill build orders, structures, keep-outs, traverse-by-waypoints,
return-to-lander, and place-objects — beacon, cache, instrument, sample, antenna — all written through a
server-owned, versioned edit-session with a before/after audit trail and linear undo, plus planner
controls and a multi-vehicle fleet); plan-anywhere (pick any lat/lon, typed or by map-click; a
request-time DEM resolver crops the global LOLA to plan in that local frame); plan inspection
(candidate-future compare, plan detail, Gantt, and a simulated run); the roughly 65-layer catalog with
provenance, freshness, uncertainty, and eligibility, plus a selection inspector, an asset library, an
evidence and report bundle, a WAC-albedo drape, and a whole-Moon globe; the analysis layers (cost,
blocking, and the terramechanics terms slope, bearing, sinkage, slip, traction, energy, plus
traversal-compaction traffic); a rover HUD (an IPEx instrument — eight URDF joints plus IMU from live
`/joint_states`, and an animated kinematic wireframe with sensor and field-of-view markers); a read-only
RViz/Foxglove-style engineering panel; and an in-IDE requirement board.

The earlier single-page cockpit stays live at [app.stewie.space](https://app.stewie.space): the ConOps
spine Plan, Rehearse, Validate, Release, Execute, Report, plus the requirement board. The GIS IDE is
the direction of travel; the migration onto it is incremental.

## The conserved-physics core

At the center is a conserved, mass-exact terramechanics authority (John McCardle's provenance): Bekker
pressure-sinkage, the Janosi-Hanamoto slip ladder, a Lyasko low-gravity correction, and mass-conserving
cut, haul, dump, and grade, all in one. It is the simulator and the reward source at once, exact,
deterministic, and sub-millisecond per step, so a searched or learned policy only commands while the
authority mutates the world. The design rule throughout: conserved physics for the dynamics (exact,
unhackable), a learned model only for the expensive perception branch. The energy model is grounded in
real IPEx data (Schuler et al., *IPEx TRL-5 Design Overview*, ASCEND 2024).

## Subsystems

| Subsystem | Package | What the code does |
|---|---|---|
| **DART** | `dart/` | Perception, estimation, and localization: DEM anchoring, stereo and shadow geometry, articulated parallax, the pose-graph estimator, the evidence ledger |
| **LODE** | `lode/` | Operations and planning: the mission planner, hazard-aware routing, the executive and mission lifecycle, fleet coordination, autonomy, acceptance |
| **LEAP** | `leap/` | Earthmoving and construction: excavation skills, worksite and terrain-target environments, structures, site plans, volume evidence |
| **FORGE** | `forge/` | Physics and terramechanics services; the conserved core itself lives in `stewie/physics` |
| **`stewie/`** | platform core | Conserved physics, terrain, the versioned twin, specs, the Gymnasium envs, the FastAPI server, the sensor and runtime bridges, the Godot render sidecar, and the evaluation gates |

**STEWIE-Orbit** (communications and observation: relay, shadow prediction) is the planned orbital
layer and is design-stage, not built. The modelled vehicle is **IPEx**, the only flight vehicle;
RASSOR is its TRL-4 precursor (see [the modelled vehicle](vehicle_ipex.md)).

## Where it is (honest)

The requirement matrix (product requirements, section 7) reads **254 of 339 requirements verified done**
(about 75 percent overall; 78 percent of the 325 in-scope rows, with hardware and host gated rows
excluded from that denominator; the counts are the live tool output in `STATUS.json` and
`release_manifest.json`). By priority: P0 107/116, P1 143/188, P2 4/33. The public deploy is
**simulation-only**, and mission Release is **director-gated**. The perception loop is closed on a real
render: a rover observes its own terrain change and reacts to the self-made hazard (reroute or a logged
refusal) in a deterministic, mass-conserving loop; the cheap in-loop observability channel and the
end-to-end replay loop are shipped, while the dense reconstruction RMSE tier stays gated. On the roadmap
(planned, not shipped): a hybrid Postgres plus PostGIS persistence layer, with the durable edit-session
(Phase 0) in progress. Named and not yet built: a live ROS2 and Gazebo pit with a real rover (the
containers build; there is no live pit link yet), the PyChrono force oracle (a stub; the Tier-3
drum-force track needs a PyChrono host), dense-stereo GPU perception, the dense map-channel reward,
LAC/IPEx arm geometry, camera video, and any live hardware. STEWIE makes no flight claims and never
presents simulated truth as a live measurement. The full breakdown is the
[capability matrix](CAPABILITIES.md).

## Quickstart

```bash
git clone https://github.com/stewie-sw/stewie && cd stewie
pip install -e .[dev,server]
stewie-serve                                                    # the planner API and cockpit
docker compose -f deploy/compose.yml up -d backend frontend     # or the containerized cockpit
docker compose -f deploy/compose.yml --profile gis up -d qgis-server artemis-web   # the GIS IDE at /ide/
```

```python
import stewie                  # registers the Stewie/* envs on import
import gymnasium as gym
env = gym.make("Stewie/RoverDrive-Mars-v0")    # per-body physics (gravity + Lyasko-corrected regolith)
obs, info = env.reset(seed=0)
obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
```

Naming: the pip package is `stewie`; the console entry points are `stewie-serve`, `stewie-fetch-dem`,
and `stewie-ros2-bridge`; the canonical Gymnasium env IDs are `Stewie/*`; environment variables are
`STEWIE_*`. The on-disk and wire schema strings (for example `stewie_runtime/1.0`) are frozen contracts.

## Documentation map

**Platform**

| Doc | What it is |
|---|---|
| [Architecture (honest index)](ARCHITECTURE.md) | The GIS-IDE-first two-process shape, the design levels, and what is designed versus built |
| [Capability matrix (honest status)](CAPABILITIES.md) | Live and load-bearing / training-only or offline / unbuilt and gated, in one table |
| [Release policy & evidence](RELEASE.md) | What a release claims and the evidence it must carry |
| [The world model](world_model.md) | Geometry, material, physics, task, and uncertainty, and the conserved-vs-learned decision |
| [Related work](related_work.md) | Where STEWIE lands across NASA autonomy, lunar mining, world models, autonomous driving, and SLAM |
| [Robotics curriculum diff](robotics_curriculum_diff.md) | Coverage of the standard robotics corpus versus what the software implements |

**Contracts**

| Doc | What it is |
|---|---|
| [Sensor-bridge contract](sensor_bridge_contract.md) | The Godot to ROS2 sensor and image contract |
| [DEM terrain contract](dem_terrain_contract.md) | The real-DEM 10 km terrain and corridor-LOD seam |
| [WorkSite contract](worksite_contract.md) | Streaming coarse base plus a rover-following fine window |
| [Demo spiral contract](demo_spiral_contract.md) | AprilTag localization versus ground truth, with observed failure modes |
| [Render fidelity spec](render_fidelity_spec.md) | The Godot render and sensor-model fidelity targets |
| [Sun-sweep manifest](sun_sweep_manifest.md) | The sun-sweep manifest contract |
| [Spec coverage scorecard](spec_coverage.md) | Section by section: built, partial, surrogate, or left out, with file and line evidence |

**Subsystems**

| Doc | What it is |
|---|---|
| [The modelled vehicle: IPEx](vehicle_ipex.md) | The ISRU Pilot Excavator, grounded in the NASA IPEx papers; the digital-twin architecture and the excavation gap |
| [DART: SLAM pipeline analysis](slam_pipeline_analysis.md) | Map-relative localization versus SLAM-from-scratch |
| [FORGE: per-planet constants](bodies_sysrev.md) | Literature-sourced terramechanics per body, every value tagged |
| [FORGE: Chrono integration](chrono_integration.md) | Project Chrono as the physics-authority producer |
| [LEAP: EZ-RASSOR assets](ezrassor_assets.md) | The EZ-RASSOR asset and integration assessment |

Repository-root references (rendered on GitHub):
[Product requirements (PRD)](https://github.com/stewie-sw/stewie/blob/main/PRD.md) ·
[Deploy runbook](https://github.com/stewie-sw/stewie/blob/main/deploy/DEPLOY.md) ·
[Lunar QGIS project](https://github.com/stewie-sw/stewie/tree/main/gis) ·
[Contributing](https://github.com/stewie-sw/stewie/blob/main/CONTRIBUTING.md) ·
[Security policy](https://github.com/stewie-sw/stewie/blob/main/SECURITY.md)

## Why it is trustworthy

The terramechanics authority is exact, deterministic, mass-conserving, and sub-millisecond. It is both
the simulator and the reward source, so learned or searched policies only command while the authority
mutates. Every physical constant carries its source and a provenance tag (`MEASURED`, `ESTIMATED`,
`[CALIB]`, or `[UNKNOWN]`); there is no synthetic data in the figures, tests, or validation. The
conserved terramechanics core and the streaming WorkSite model are by John McCardle; STEWIE adds the
Gymnasium suite, the per-planet body registry, the world model, the mission planner, the GIS IDE and
cockpit, the render integration, the vehicle twin, and the self-optimizing pipeline. The repository is
currently all-rights-reserved (the prior CC0 dedication was withdrawn on 2026-06-10); see
[LICENSE](https://github.com/stewie-sw/stewie/blob/main/LICENSE).

## Citation

If you use STEWIE, please cite it (GitHub renders a "Cite this repository" button from
[CITATION.cff](https://github.com/stewie-sw/stewie/blob/main/CITATION.cff)):

```bibtex
@software{stewie,
  title  = {STEWIE: Surface Terrain Engineering \& World-model Integration Environment},
  author = {McCardle, John and Storey, Aaron W.},
  year   = {2026},
  url    = {https://github.com/stewie-sw/stewie},
  note   = {Lineage: NASA IPEx (ISRU Pilot Excavator) and the JHU APL Lunar Autonomy Challenge}
}
```
