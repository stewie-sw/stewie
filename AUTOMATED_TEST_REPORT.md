# Automated test report

**Artifact ID:** `ART-AUTOMATED-TEST-REPORT`
**Producer node:** `INT-010`
**Consumers:** `REV-010`, `DISS-010`
**Evidence commit:** `608c6881e9be5754ac801a7833ee1f8217c238a0`
**Status:** source, package, and repository regression gates passed.

The focused UltraBuild suite covers store, payload, schema, semantic provenance, temporal queries,
atomic promotion, concurrent CAS, supersession, conflicts, candidate derivation, reference
noninterference, controlled evaluation, perturbation, fault injection, package installation, and
persistent multi-robot behavior.

```bash
.venv/bin/pytest -ra -p no:cacheprovider \
  stewie/ultrabuild experiments/contracts scripts/test_ultrabuild_artifacts.py
STEWIE_WHEEL_SMOKE=1 .venv/bin/pytest -q -p no:cacheprovider \
  stewie/ultrabuild/test_package_integration_regressions.py
PYTHONNOUSERSITE=1 .venv/bin/pytest -n auto
.venv/bin/ruff check --select F stewie dart lode leap forge scripts viz
.venv/bin/mypy
.venv/bin/python scripts/validate_ultrabuild.py
```

Results:

- focused before the final repository gate: `90 passed, 1 skipped` in 21.59 s; the skip is the opt-in wheel test;
- clean-wheel package suite: `7 passed`;
- complete repository: `4,750 passed, 41 skipped` in 477.84 s;
- Ruff: passed on the repository-declared source surface;
- mypy: 415 source files passed;
- schema, artifact, requirement, release-manifest, and lock validators: passed.

The 41 repository skips are explicit host/optional-tier gates. The full run emitted 69 deprecation or
numerical warnings and no test failures. An unrestricted `ruff check .` also found two pre-existing
F-class warnings outside the declared lint surface, in `benchmarks/nac_shadow/nac_boulder_repro.py`
and `deploy/ros2/camera_feeder.py`; they are not represented as a green all-path lint result.

These tests prove behavior of the in-process research slice. They do not test physical sensors,
networked replicas, live ROS/Gazebo/QGIS integration, or process-kill durability at every fsync
boundary.
