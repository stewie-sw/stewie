# Changelog

## 0.1.0 (2026-06-06)
First scaffold. Real, tested primitives; no stubs, no synthetic data.

- `geometry/solar.py` (A1): lunar Sun elevation/azimuth, sub-solar point, synodic day length, daylight fraction; south-pole grazing-Sun verified.
- `geometry/shadow.py` (A2): cast-shadow height H = L*tan(e), shadow-azimuth heading, uncertainty.
- `geometry/stereo.py` + `perception/stereo_depth.py` (A4/A5): disparity->depth, triangulation, posture parallax, real cv2 SGBM depth.
- `perception/masking.py`: semantic feature filtering + self-supervised shadow mask.
- `geometry/dem.py`: real Haworth DEM I/O + scan-to-DEM registration.
- `geometry/fov.py` (A4): camera FOV + lander/AprilTag visibility across rover yaw.
- `posture/kinematics.py` (A3): posture library (Meerkat/Cobra/Iron Cross) grounded in Schuler et al. 2024; chassis lift/pitch, stability gate, parallax.
- `ipex/specs.py`: provenance-tagged IPEx constants ([SPEC]/[CONFIRM]).
- `bridge/dustgym_io.py`: reads the dustgym/LAC Seam-2 sensors.json + PNGs; writes cmd_vel/posture (no dustgym edits).
- `demo/end_to_end.py`: runs the pipeline on a real frame + real Haworth DEM with an honesty ledger.
- `demo/assets/rassor.glb`: NASA RASSOR 3D model (public, patent KSC-TOPS-7).
- 57 tests, 95% coverage, real-data subsample fixtures committed under `tests/fixtures/`.

### Not yet wired (next milestones, deliberately not stubbed)
- M3 unified GTSAM estimator (active SLAM) -- needs `gtsam`.
- M4 active-perception policy -- needs `gymnasium`.
- M5 multi-vehicle cooperative localization + coordination.
- M6 ablation / fault-injection harness (camera dropout, miscalibration).
- CARLA/Unreal LAC twin adapter; self-shadow heading cue; closed-loop multi-position trajectory.
