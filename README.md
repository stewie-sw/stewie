# solnav

Solar/shadow/posture lunar navigation. The dissertation's navigation package (Aaron W. Storey). A **standalone** package that consumes `dustgym` read-only across its frozen seams; it does not modify dustgym. See `../SOFTWARE_PRD.md` for the full architecture and `../ALGORITHMS.md` for the formal algorithms (A1-A8).

## Status
Implemented primitives are covered by analytic fixtures, rendered-image fixtures, and
measurement-model simulations. Evidence modes must not be conflated:

| Module | Algorithm | What it does |
|---|---|---|
| `solnav/geometry/solar.py` | A1 | Lunar Sun elevation/azimuth, sub-solar point, synodic day length, daylight fraction. Real spherical astronomy; the south-pole persistent grazing Sun falls out and is tested. |
| `solnav/geometry/shadow.py` | A2 | Cast-shadow height (`H = L tan e`), shadow-azimuth heading, uncertainty propagation. |
| `solnav/geometry/shadow_metric.py` | P5 | Perspective ray/ground geometry plus a controlled orthographic rendered-sensor fixture; general caster-base/tip detection remains open. |
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
python3 -m pytest tests -q
```
External rendered-fixture tests skip cleanly when their declared assets are absent.

## Principles
No fabricated results and no unlabeled evidence modes. Geometry tests use known-answer analytic
fixtures; image tests use dustgym renders; estimator studies may use truth-generated measurements
when labeled `MEASUREMENT_MODEL_SIM`. Every IPEx `[CONFIRM]` constant must be reconciled before
locking.
