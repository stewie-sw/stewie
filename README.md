<div align="center">

# STEWIE

### Surface Terrain Engineering & World-model Integration Environment

*IPEx builds the Moon. STEWIE plans the build.* &nbsp;·&nbsp; *in silico → in situ*

[![CI](https://github.com/stewie-sw/stewie/actions/workflows/ci.yml/badge.svg)](https://github.com/stewie-sw/stewie/actions/workflows/ci.yml)
[![Docs](https://github.com/stewie-sw/stewie/actions/workflows/pages.yml/badge.svg)](https://stewie-sw.github.io/stewie/)
[![Python](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue.svg)](pyproject.toml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](pyproject.toml)
[![Types: mypy](https://img.shields.io/badge/types-mypy-blue.svg)](pyproject.toml)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey.svg)](LICENSE)

</div>

---

## Overview

STEWIE is a digital-twin and mission-planning platform for off-world surface construction, built on a
**mass-conserving terramechanics authority** parameterized per planetary body (Moon, Mars, Earth, and
more). It loads real lunar terrain, authors construction goals, produces physically valid and
energy-aware plans, simulates and renders execution, and emits a mission-control report plus a
machine-consumable plan. Its lineage is NASA's **IPEx** (ISRU Pilot Excavator) and the JHU APL
**Lunar Autonomy Challenge**; it is an independent Godot + Project Chrono + ROS2 stack, not the
official challenge entry.

One core paradigm runs through it — **terrain memory**: the excavator physically changes the surface,
and STEWIE maintains the authoritative world model rather than a rover-centric SLAM view.

## Subsystems

| Package | Role |
|---|---|
| **`stewie/`** | Platform core — conserved physics, terrain, the versioned twin, specs, Gymnasium envs, the FastAPI cockpit, the sensor/runtime bridges, the Godot render sidecar, and the evaluation gates. |
| **`dart/`** | Perception, estimation, and SLAM — shadow geometry, articulation parallax, the SE(2) pose graph, mapping. |
| **`lode/`** | Operations and planning — the mission planner, terrain-aware routing, autonomy, and acceptance. |
| **`leap/`** | Earthmoving — construction skills and scheduling environments. |
| **`forge/`** | Infrastructure and physics services. |

## Install

```bash
git clone https://github.com/stewie-sw/stewie.git && cd stewie
pip install -e .[dev]      # full toolchain (tests, lint, types, server, planner)
# or a lighter target:
pip install -e .[server]   # the mission-planning cockpit only
```

Requires Python ≥ 3.11.

## Quickstart

```bash
# Launch the mission-planning cockpit (FastAPI + Cesium globe)
stewie-serve                                            # http://localhost:8000
# or containerized:
docker compose -f deploy/compose.yml up -d
```

```python
# Drive a Gymnasium environment on the conserved physics authority
import stewie, gymnasium as gym        # importing stewie registers the envs
env = gym.make("Stewie/RoverDrive-v0")
obs, _ = env.reset(seed=0)
obs, reward, term, trunc, info = env.step(env.action_space.sample())
```

**Gymnasium environments** (all `gym.make`-able after `import stewie`):
`Stewie/RoverDrive-v0` (per-body variants `-Moon` / `-Mars` / `-Earth` / `-Ceres`), `Stewie/Construct-v0`,
`Stewie/SkillMacro-v0`, `Stewie/Scheduler-v0`, `Stewie/WorkSite-v0`, `Stewie/ActivePerception-v0`.

## Documentation

- **`PRD.md`** — the canonical design source (the STEWIE PRD; §16 is the subsystem map + phase gates;
  §27 is the dated actionable backlog + 2-week sprint).
- **`docs/CAPABILITIES.md`** — the honest capability matrix (shipped / training-only / unbuilt).
- **`docs/ui_overhaul_plan_2026-06-20.md`** — the full-fidelity cockpit overhaul plan.
- **Docs site** — <https://stewie-sw.github.io/stewie/>

## Quality gates

Every push runs the CI gate ([`ci.yml`](.github/workflows/ci.yml)):

- **Lint** — `ruff` pyflakes (F) across all packages.
- **Power-of-10** — bounded cyclomatic complexity (≤ 10) on the conserved core (`stewie/physics`, `stewie/twin`).
- **Types** — `mypy` over the core and planner (a documented ratchet narrows the remaining exclusions).
- **Requirements traceability** — every `V=D` requirement must be cited by a test.
- **Tests + coverage** — `pytest` with a coverage floor of **85%**, across Python 3.11–3.13.
- **G1/G2 validation** — a frozen, byte-reproducible navigation-evidence gate.

```bash
pytest                    # the configured suite
ruff check --select F .   # lint
mypy                      # types
```

## Citation

If you use STEWIE in your work, please cite it. GitHub renders a "Cite this repository" button from
[`CITATION.cff`](CITATION.cff); a BibTeX form:

```bibtex
@software{stewie,
  title  = {STEWIE: Surface Terrain Engineering \& World-model Integration Environment},
  author = {McCardle, John and Storey, Aaron W.},
  year   = {2026},
  url    = {https://github.com/stewie-sw/stewie},
  note   = {Lineage: NASA IPEx (ISRU Pilot Excavator) and the JHU APL Lunar Autonomy Challenge}
}
```

## License & provenance

**All rights reserved.** The prior CC0 dedication was withdrawn for this repository on 2026-06-10; a
permissive or commercial license is pending. Until one is committed here, no rights to copy, modify,
or redistribute are granted beyond those in GitHub's Terms of Service. See [`LICENSE`](LICENSE).

Portions of the physics core originated in `jmccardle/roversim` under its terms at the time of
publication.

## Authors

**John McCardle** & **Aaron Storey** — STEWIE Software (`stewie-sw`).
