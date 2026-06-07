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
| `solnav/config/` | - | Packaged, checksummed system profiles; validates camera/FOV/baseline closure and rejects mixed-profile runtime metadata. |
| `solnav/ipex/specs.py` | - | Profile-backed IPEx constants for Dustgym or the staged official-LAC substrate. |
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

## System profiles

`DUSTGYM_IPEX_V1` is the verified default. Select a profile once, before importing geometry or
platform modules:

```bash
SOLNAV_PROFILE=DUSTGYM_IPEX_V1 python3 demo/end_to_end.py
SOLNAV_PROFILE=OFFICIAL_LAC_2025_UNVERIFIED python3 -c \
  "from solnav.ipex import IPEX; print(IPEX.profile_id, IPEX.stereo_baseline_m)"
```

The official profile is intentionally `UNVERIFIED`; `load_profile(..., require_verified=True)`
rejects it until an installed-kit checksum and calibration bundle replace the staged facts.
`CameraRig.from_sensors(...)` validates runtime camera names, dimensions, focal length, baseline,
and fixed extrinsics against the selected profile before accepting the frame.

## Principles
No fabricated results and no unlabeled evidence modes. Geometry tests use known-answer analytic
fixtures; image tests use dustgym renders; estimator studies may use truth-generated measurements
when labeled `MEASUREMENT_MODEL_SIM`. Every IPEx `[CONFIRM]` constant must be reconciled before
locking.
