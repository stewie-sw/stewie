---
title: Home
nav_order: 1
---

# STEWIE

**Surface Terrain Engineering & World-model Integration Environment.**
*IPEx builds the Moon. STEWIE plans the build.* — in silico → in situ.

STEWIE is a lunar construction-planning and digital-twin platform for the IPEx/RASSOR-lineage
excavator. At its core is a conserved, mass-exact terramechanics authority (John McCardle's
provenance): Bekker pressure-sinkage, the Janosi–Hanamoto slip ladder, Lyasko low-g correction,
and mass-conserving cut/haul/dump/grade — the simulator and the reward source in one. On top of
that authority sit a mission planner with an energy-budgeted Plan IR and mission-control report, a
Gymnasium environment suite, per-planet body registries, a Godot render/sensor seam, and a ROS2
bridge. The design rule throughout: **conserved physics for the dynamics (exact, unhackable), a
learned model only for the expensive perception branch.** Owners: John McCardle & Aaron Storey
([github.com/stewie-sw/stewie](https://github.com/stewie-sw/stewie)).

## Subsystems

| Subsystem | Expansion | Role |
|---|---|---|
| **DART** | Digital Analysis of Regolith & Terrain | Perception: DEM ingest, stereo/depth, localization, mapping, hazard and shadow analysis |
| **LODE** | Lunar Operations & Development Environment | Mission planning and operations: sequencing, scheduling, energy budgeting, reports |
| **LEAP** | Lunar Excavation Analysis & Planning | Earthmoving and execution: excavation skills, worksite construction, terrain-target environments |
| **FORGE** | Foundation Operations & Regolith Generation Environment | Infrastructure: terrain generation, regolith physics substrate, foundations |
| **ARGUS** | Articulated Rover Geometry for Unified State Estimation | The vehicle digital twin — chassis, drums, arm, camera rig, and work lights as one state. Named in tribute to Jadon Schuler, IPEx Project Manager and Principal Investigator |

The vehicle is **IPEx** (the ISRU Pilot Excavator, the only flight vehicle); RASSOR is its TRL-4
precursor. See [the modelled vehicle](vehicle_ipex.md).

## Product modes (PRD §5)

| Mode | What it is |
|---|---|
| `GIS-PLAN` | 2D layered planning on the real Haworth DEM: slope/hazard/shadow/PSR rasters, build-queue authoring, fleet and vehicle selection; output is a routed, energy-budgeted Plan IR plus the mission-control report |
| `TRAIN` | Operator/director sessions over the real closed loop; the operator sees only telemetry-delivered, truth-denylisted state under a mission link profile; the director gets full state and debrief |
| `SIM-OPERATE` | The live loop on the conserved authority: a persistent runtime owning one world, ROS2 teleop and goal-level CCSDS tasks, strict truth-free producer packets, bit-exact checkpoint/restore |
| `EVALUATE` | The honesty machinery: hash-anchored evidence corpora, role-isolated produce→estimate→evaluate, geometric depth truth, dated code-enforced gate artifacts; the only mode with truth access |
| `OPERATE` | Consume real telemetry and command hardware. **Future** — unavailable until command, timing, safety, and fault requirements pass |

The API and reports label the active mode; simulated truth is never presented as a live measurement.

## Quickstart

```bash
git clone https://github.com/stewie-sw/stewie && cd stewie
pip install -e .[dev,server]
stewie-serve                                   # the mission planner + web UI
docker compose -f deploy/compose.yml up -d     # or: the containerized stack
```

```python
import stewie                  # registers the Stewie/* envs on import
import gymnasium as gym
env = gym.make("Stewie/RoverDrive-Mars-v0")    # per-body physics (gravity + Lyasko-corrected regolith)
obs, info = env.reset(seed=0)
obs, reward, terminated, truncated, info = env.step(env.action_space.sample())
```

Naming and compatibility: the pip package is `stewie` (renamed 2026-06-10 from `dustgym`).
`dustgym-serve` and `import dustgym` remain as deprecated aliases for one transition cycle; the
legacy `Dust/*` env IDs are registered as aliases of the canonical `Stewie/*` IDs. Environment
variables are `STEWIE_*` with `DUSTGYM_*` accepted as a fallback. On-disk schema strings (e.g.
`dustgym_runtime/1.0`) are frozen contracts and are unchanged by the rename.

## Documentation map

**Platform**

| Doc | What it is |
|---|---|
| [The five-layer world model](world_model.md) | Geometry / Material / Physics / Task / Uncertainty, and the conserved-vs-learned design decision |
| [Related work](related_work.md) | Where STEWIE lands across NASA autonomy, lunar mining, world models, autonomous driving, SLAM |
| [Robotics curriculum diff](robotics_curriculum_diff.md) | Coverage of the standard robotics corpus vs what the software implements |
| [Implementation plan (2026-06-06)](implementation_plan_2026-06-06.md) | The dependency-ordered execution plan for PRD v6.0 |
| [Research workspace](research_workspace.md) | Where manuscripts, reviews, grants, and references live |

**Contracts**

| Doc | What it is |
|---|---|
| [Sensor-bridge contract](sensor_bridge_contract.md) | Seam 2: the Godot → ROS2 `sensors.json` + PNG contract |
| [DEM terrain contract](dem_terrain_contract.md) | The real-DEM 10 km terrain + corridor-LOD seam |
| [WorkSite contract](worksite_contract.md) | Streaming coarse-base + rover-following fine window |
| [Demo spiral contract](demo_spiral_contract.md) | AprilTag localization vs ground truth, with observed failure modes |
| [Render fidelity spec](render_fidelity_spec.md) | The Godot render / sensor-model fidelity targets |
| [Sun-sweep manifest](sun_sweep_manifest.md) | The `sun_sweep/1.0` manifest contract |
| [Spec coverage scorecard](spec_coverage.md) | Section-by-section: built / partial / surrogate / left out, with file:line evidence |

**Subsystems**

| Doc | What it is |
|---|---|
| [ARGUS: the modelled vehicle — IPEx](vehicle_ipex.md) | The ISRU Pilot Excavator, grounded in the six NASA IPEx papers; the digital-twin architecture and the excavation gap |
| [DART: SLAM pipeline analysis](slam_pipeline_analysis.md) | Map-relative localization vs SLAM-from-scratch; the P15 build path |
| [DART: 10 km lunar DEM evaluation](lunar_dem_10km_eval.md) | Real south-polar DEM ingest, data sources, and the procgen infill plan |
| [FORGE: per-planet constants](bodies_sysrev.md) | Literature-sourced terramechanics per body, every value tagged |
| [FORGE: Chrono integration](chrono_integration.md) | Project Chrono as the physics-authority producer |
| [LODE: power calibration (2026-06-09)](power_calibration_2026-06-09.md) | The IPEx power model's lunar-environment fidelity |
| [LEAP: EZ-RASSOR assets](ezrassor_assets.md) | The EZ-RASSOR asset/integration assessment |

**Reviews**

| Doc | What it is |
|---|---|
| [Architecture review (2026-06-04)](architecture_review.md) | Production-readiness assessment |
| [Deep code review (2026-06-05)](architecture_review_2026-06-05.md) | 8-agent run-verified review + mission-readiness analysis |
| [Real-world-mission review (2026-06-05)](architecture_review_2026-06-05_realworld.md) | Gap analysis for real-world mission execution |
| [Full architectural review (2026-06-06)](architecture_review_2026-06-06_full.md) | The complete static-scope review at commit `0473312` |
| [PRD gap analysis (2026-06-06)](prd_gap_analysis_2026-06-06.md) | Requirement-by-requirement PRD-vs-code diff |
| [Autonomous planning review](autonomous_planning_review.md) | Single- and multi-vehicle planning limits |
| [UI/UX audit (2026-06-09)](uiux_audit_2026-06-09.md) | Full frontend audit against the operator KPT |

Repository-root references (rendered on GitHub):
[Product requirements (`PRD.md`)](https://github.com/stewie-sw/stewie/blob/main/PRD.md) ·
[Master technical spec](https://github.com/stewie-sw/stewie/blob/main/ipex-terrain-sim-spec.md) ·
[Building taxonomy](https://github.com/stewie-sw/stewie/blob/main/docs/archive/building_taxonomy.md) ·
[Contributing](https://github.com/stewie-sw/stewie/blob/main/CONTRIBUTING.md) ·
[Security policy](https://github.com/stewie-sw/stewie/blob/main/SECURITY.md)

## Why it is trustworthy

The terramechanics authority is exact, deterministic, mass-conserving, and sub-millisecond — it is
both the simulator *and* the reward source, so learned or searched policies only **command** while
the authority **mutates**. Every physical constant carries its source and a provenance tag
(`MEASURED` / `ESTIMATED` / `[CALIB]` / `[UNKNOWN]`); there is no synthetic data in the figures,
tests, or validation. The energy model is grounded in real IPEx data (Schuler et al., *IPEx TRL-5
Design Overview*, ASCEND 2024).

Provenance: the `terrain_authority` terramechanics core and the streaming `WorkSite` model are by
**John McCardle**; STEWIE adds the Gymnasium suite, the per-planet `Body` registry, the world
model, the mission planner + web UI, the map channel + render integration, the vehicle twin, and
the self-optimizing pipeline. License selection for the repository is pending; see the repository
for current terms.
