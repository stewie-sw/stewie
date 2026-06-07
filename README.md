# solnav

Solar/shadow/posture lunar navigation. The dissertation's navigation package (Aaron W. Storey). A **standalone** package that consumes `dustgym` read-only across its frozen seams; it does not modify dustgym. See `../SOFTWARE_PRD.md` for the full architecture and `../ALGORITHMS.md` for the formal algorithms (A1-A8).

## Status (what is real and tested now)
Implemented with real, tested code (41 tests passing, no stubs, no synthetic data):

| Module | Algorithm | What it does |
|---|---|---|
| `solnav/geometry/solar.py` | A1 | Lunar Sun elevation/azimuth, sub-solar point, synodic day length, daylight fraction. Real spherical astronomy; the south-pole persistent grazing Sun falls out and is tested. |
| `solnav/geometry/shadow.py` | A2 | Cast-shadow height (`H = L tan e`), shadow-azimuth heading, uncertainty propagation. |
| `solnav/geometry/stereo.py` | A4/A5 | Disparity to depth, back-projection, midpoint triangulation, posture vertical-parallax baseline. |
| `solnav/perception/masking.py` | A2/A5 | Semantic-mask feature filtering (keep ground/rock; drop sky/lander/fiducial/shadow), self-supervised shadow mask for eval mode, overlay. |
| `solnav/ipex/specs.py` | - | Provenance-tagged IPEx constants ([SPEC]/[CONFIRM]); real intrinsics/baseline/sun from a LAC-twin sensors.json. |
| `solnav/bridge/dustgym_io.py` | - | Reads the real dustgym/LAC Seam-2 `sensors.json` (cameras, stereo, Sun, poses) and PNGs; writes `cmd_vel` and posture commands. No dustgym edits. |

## Next milestones (not stubbed; require deps not yet installed)
- `estimator/` (A5 unified GTSAM factor graph) -- needs `gtsam` (`pip install .[estimator]`).
- `policy/` (A6 active perception) -- needs `gymnasium` (`pip install .[policy]`).
- `fleet/` (A7/A8 cooperative localization + coordination).
These are real future work per the PRD build plan (M3-M6), deliberately not created as empty stubs.

## Run
```
pip install -e .            # numpy/scipy/imageio/opencv
python -m pytest tests -q   # 41 tests; real-fixture tests use dustgym renders + sensors.json
```
Real-fixture tests skip cleanly if the dustgym renders are absent (honest env-gate, not a fake pass).

## Principles (carried from project rules)
No stubs, no synthetic data, no fabricated values. Geometry/physics tests are known-answer; image/sensor tests use real dustgym renders and a real sensors.json. Every IPEx [CONFIRM] constant must be reconciled against the LAC geometry page before locking.
