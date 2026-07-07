<div align="center">

# STEWIE

### Surface Terrain Engineering & World-model Integration Environment

*IPEx builds the Moon. STEWIE plans the build.* &nbsp;·&nbsp; *in silico, then in situ*

[![CI](https://github.com/stewie-sw/stewie/actions/workflows/ci.yml/badge.svg)](https://github.com/stewie-sw/stewie/actions/workflows/ci.yml)
[![Docs](https://github.com/stewie-sw/stewie/actions/workflows/pages.yml/badge.svg)](https://stewie-sw.github.io/stewie/)
[![Python](https://img.shields.io/badge/python-3.11%20|%203.12%20|%203.13-blue.svg)](pyproject.toml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](pyproject.toml)
[![Types: mypy](https://img.shields.io/badge/types-mypy-blue.svg)](pyproject.toml)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-orange.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey.svg)](LICENSE)

**Live:** [GIS mission-control IDE](https://artemis.stewie.space/ide/) &nbsp;·&nbsp; [planner cockpit](https://app.stewie.space)

</div>

---

## What STEWIE is

STEWIE is a platform for planning and rehearsing lunar surface construction. It brings the pieces an
off-world earthmoving mission needs into one workspace: a GIS mission map over real lunar terrain, a
versioned digital twin of the worksite, a conserved-physics terramechanics core, an energy-aware
mission planner, and an autonomy and runtime middleware layer. IPEx (NASA's ISRU Pilot Excavator) is
the first vehicle STEWIE plans for, not a component of it. *IPEx builds the Moon; STEWIE plans the
build.*

The lineage is NASA's IPEx program and the JHU APL Lunar Autonomy Challenge. STEWIE is an independent
stack, with its own physics, GIS, planner, and render seams, and is not the official challenge entry.

## The front door: a GIS mission-control IDE

The primary surface is a GIS mission workbench, live at **<https://artemis.stewie.space/ide/>**. It is
one persistent lunar map (QGIS Web Client 2 over a QGIS Server backend) in the Moon south-polar
stereographic frame, so the pole sits in the middle of the canvas and coordinates stay pole-truthful
(no Earth or WGS84 claim on lunar positions). On that map you can:

- **browse the real terrain** — 8 Artemis III candidate-site DEMs (LOLA 5 m polar) plus a 1 m Haworth
  shape-from-shading DEM, with slope, hillshade, and LROC imagery context drapes;
- **author a mission** — cut and fill orders, structures, and keep-out barriers, with planner controls
  and a multi-vehicle fleet;
- **inspect the plan** — candidate-future compare, plan detail, and a Gantt schedule, then run a
  simulated execution;
- **read the layer catalog** — per-layer provenance, freshness, and uncertainty, with display-only
  layers visibly distinct from planning, release, and execute eligible ones;
- **work the analysis layers** — route cost, blocking, the terramechanics terms (slope, bearing,
  sinkage, slip, traction, energy), and traversal-compaction traffic;
- **keep situational awareness** — a rover HUD, an in-IDE requirement board, and plan-anywhere over the
  global DEM.

The earlier single-page cockpit stays live at **<https://app.stewie.space>** (the ConOps spine Plan,
Rehearse, Validate, Release, Execute, Report, plus the requirement board). The GIS IDE is the direction
of travel; the migration onto it is incremental.

## Subsystems

| Subsystem | Package | What the code does |
|---|---|---|
| **DART** | `dart/` | Perception, estimation, and localization: DEM anchoring, stereo and shadow geometry, articulated parallax, the pose-graph estimator, and the evidence ledger. |
| **LODE** | `lode/` | Operations and planning: the mission planner, hazard-aware routing, the executive and mission lifecycle, fleet coordination, autonomy, and acceptance. |
| **LEAP** | `leap/` | Earthmoving and construction: excavation skills, worksite and terrain-target environments, structures, site plans, and volume evidence. |
| **FORGE** | `forge/` | Physics and terramechanics services (bearing and related); the conserved core itself lives in `stewie/physics`. |
| **`stewie/`** | platform core | Conserved physics, terrain, the versioned twin, specs, the Gymnasium envs, the FastAPI server, the sensor and runtime bridges, the Godot render sidecar, and the evaluation gates. |

**STEWIE-Orbit** (communications and observation: relay, shadow prediction) is the planned orbital
layer and is design-stage, not built.

## The conserved-physics core (the differentiator)

The terramechanics authority is exact, deterministic, mass-conserving, and sub-millisecond per step.
Mass is the invariant and height is re-derived, so a runtime guard rejects any mutation that would not
conserve mass. It implements load-bearing Bekker pressure-sinkage, a real slip ladder (Coulomb-Mohr,
Janosi-Hanamoto) with discrete entrapment, a Lyasko low-gravity correction, and per-body gravity (Moon,
Mars, Earth, Ceres, and more). It is both the simulator and the reward source, so a searched or learned
policy only commands while the authority mutates the world. The energy model is grounded in real IPEx
data (Schuler et al., *IPEx TRL-5 Design Overview*, ASCEND 2024). Every physical constant carries a
provenance tag, and no synthetic values stand in for measured ones.

## Capability state (honest)

**Live and load-bearing:** the GIS IDE, mission authoring and planning, the conserved-physics core, the
analysis layers, and plan-anywhere over the global DEM. The public deploy is **simulation-only**, and
mission Release is **director-gated**.

**Progress:** the requirement matrix (product requirements, section 7) reads **251 of 339 requirements
verified done** (about 74 percent overall; 77 percent of the 325 in-scope rows, with hardware and host
gated rows excluded from that denominator). By priority: P0 106/116, P1 141/188, P2 4/33. The matrix is
projected read-only onto the in-IDE requirement board.

**Gated or not yet built (named, not hidden):** a live ROS2 and Gazebo pit with a real rover (the
containers build, but there is no live pit link yet); the PyChrono force oracle (a stub; the Tier-3
drum-force track needs a PyChrono host); dense-stereo GPU perception; the dense map-channel reward; and
any live hardware. STEWIE makes no flight claims and never presents simulated truth as a live
measurement.

## Quickstart

```bash
git clone https://github.com/stewie-sw/stewie.git && cd stewie
pip install -e .[dev]      # full toolchain (tests, lint, types, server, planner)
# or a lighter target:
pip install -e .[server]   # the planner API and cockpit only
```

Requires Python 3.11 or newer.

**Planner cockpit** (the `app.stewie.space` stack):

```bash
stewie-serve                                                   # http://127.0.0.1:8770
# or containerized (nginx frontend + backend):
docker compose -f deploy/compose.yml up -d backend frontend    # http://127.0.0.1:8000
```

**GIS mission-control IDE** (the `artemis.stewie.space` stack: QGIS Server + QWC2):

```bash
docker compose -f deploy/compose.yml --profile gis up -d qgis-server artemis-web
# http://127.0.0.1:8083/ide/  (qgis-server is on :8082; the IDE is served by artemis-web on :8083)
```

**Drive a Gymnasium environment** on the conserved physics:

```python
import stewie, gymnasium as gym        # importing stewie registers the envs
env = gym.make("Stewie/RoverDrive-v0")
obs, _ = env.reset(seed=0)
obs, reward, term, trunc, info = env.step(env.action_space.sample())
```

Environments (all `gym.make`-able after `import stewie`): `Stewie/RoverDrive-v0` (per-body `-Moon` /
`-Mars` / `-Earth` / `-Ceres`), `Stewie/Construct-v0`, `Stewie/SkillMacro-v0`, `Stewie/Scheduler-v0`,
`Stewie/WorkSite-v0`, `Stewie/ActivePerception-v0`.

The deploy runbook is [`deploy/DEPLOY.md`](deploy/DEPLOY.md). The lunar QGIS project (CRS, candidate
sites, layers, and how to rebuild) is documented under [`gis/`](gis/).

## Documentation

- **Product requirements** ([`PRD.md`](PRD.md)) — the canonical design source (section 6 is the target
  architecture, section 7 is the requirement matrix, section 7.B is the GIS mission-workbench target).
- **Docs site** — <https://stewie-sw.github.io/stewie/> — the capability matrix (honest status), the
  architecture index, the release policy, contracts, and the subsystem references.
- **Generated traceability** — [`STATUS.md`](STATUS.md), produced by the traceability tools (do not
  hand-edit).

## Quality gates

Every push runs the CI gate ([`ci.yml`](.github/workflows/ci.yml)):

- **Lint** — `ruff` pyflakes (F) across all packages.
- **Power-of-10** — bounded cyclomatic complexity on the conserved core (`stewie/physics`, `stewie/twin`).
- **Types** — `mypy` over the core and planner (a documented ratchet narrows the remaining exclusions).
- **Requirements traceability** — every `V=D` requirement must be cited by a test.
- **Tests + coverage** — `pytest` with a coverage floor of **85 percent** (py3.11), plus a py3.12/3.13
  test matrix.
- **Browser JS** — the cockpit's pure browser modules run under `node --test`.
- **Navigation-evidence gate** — a frozen, byte-reproducible validation artifact.

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

## License and provenance

**All rights reserved.** The prior CC0 dedication was withdrawn for this repository on 2026-06-10; a
permissive or commercial license is pending. Until one is committed here, no rights to copy, modify, or
redistribute are granted beyond those in GitHub's Terms of Service. See [`LICENSE`](LICENSE).

Portions of the physics core originated in `jmccardle/roversim` under its terms at the time of
publication.

## Authors

**John McCardle** and **Aaron Storey** (STEWIE Software, `stewie-sw`).
