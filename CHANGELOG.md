# Changelog

All notable changes to STEWIE are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

`0.x` is pre-release: STEWIE is a trainer/simulator surface plus a navigation
research track, not a production flight-autonomy release (see PRD §0). The
exported version lives in `stewie.__version__` and `pyproject [project].version`;
`stewie/server/test_version.py` keeps them in lockstep (PO-13).

## [Unreleased]

### Added
- DT-02: least-privilege `/twin/version` (authenticated minimal version token) +
  director-only `/twin/history` audit route, replacing the unauthenticated
  full-history read.
- `dart/render_traverse.py`: the render→cue→fuse→score SLAM-seam adapter
  (stereo-VO + articulation-parallax extractors → `run_integrated_slam` →
  ATE-vs-truth), validated on committed renders and a fresh bounded Godot
  render (parallax fused beats odometry on a turning traverse).
- Cockpit Plan 3D: first-person fly/move-through camera and a 3D plotting
  toolbox (live coordinate readout, plotted coordinate markers, 3D measure).
- `CHANGELOG.md` + exported `stewie.__version__` + SemVer policy (PO-13).

### Changed
- `stewie/godot/render.sh`: documented the working sensor-capture recipe
  (never `--headless`; run `res://sidecar.tscn` with `--layers …,rover`).

## [0.1.0] — pre-release baseline

Initial tagged baseline of the consolidated monorepo (`code/`): the conserved
NumPy terrain authority, the LODE mission planner (multi-algorithm optimizer,
multi-vehicle, plan IR, PDF report), the DART perception/ARGUS estimator spine,
the FastAPI server + cockpit (Plan/Navigation/Perception/Metrics/Report,
auth/role ladder, GIS globe), the ROS2 bridge seam, and the Gymnasium env suite.
See PRD §0 for the authoritative status model and release blockers.
