# Changelog

## Unreleased

- Added strict `sensor_bridge_runtime/1.0` and physically separate
  `sensor_bridge_evaluation_truth/1.0` ingestion. Legacy combined `sensors.json` is rejected by the
  estimator bridge, including the former truth leak through `SensorFrame.raw`.
- Replaced the downsampled/mismatched camera fixture with a complete real 1024x768 Dustgym
  eight-camera capture and validates every declared image dimension.
- Added fixed-reference `DepthFrame`, left-right consistency, validity masks, propagated depth
  sigma, and a guard that prevents claiming calibrated covariance without development and held-out
  evidence.
- Added shadow segment image-to-ground/body mapping with explicit 180/360-degree periodicity and
  an explicit ephemeris-only solar fallback contract.
- Added immutable scene hashes and `scripts/validate_g1_g2.py`. The June 7 evidence passes
  implementation checks but correctly leaves G1/G2 release gates open for missing IMU/wheel
  ingress and independent held-out covariance validation.
- Added packaged `DUSTGYM_IPEX_V1` and `OFFICIAL_LAC_2025_UNVERIFIED` system profiles.
- Added schema, checksum, FOV/intrinsics, stereo-baseline, and runtime compatibility validation.
- Camera rig, IPEx specifications, posture geometry, and lunar terramechanics now use the selected
  `SOLNAV_PROFILE`.
- Runtime Dustgym camera metadata is rejected when an official/mismatched profile is selected.
- Corrected the fallback side-camera axes to match captured Dustgym geometry.

## 0.1.0 (2026-06-06)
First scaffold with analytic, rendered-fixture, and substrate-backed primitives.

- `geometry/solar.py` (A1): lunar Sun elevation/azimuth, sub-solar point, synodic day length, daylight fraction; south-pole grazing-Sun verified.
- `geometry/shadow.py` (A2): cast-shadow height H = L*tan(e), shadow-azimuth heading, uncertainty.
- `geometry/shadow_metric.py` (P5): calibrated ray/ground geometry and a controlled
  `RENDERED_SENSOR_SIM` fixture recovering a configured post height; caster-base detection remains
  supplied by scene configuration.
- `geometry/stereo.py` + `perception/stereo_depth.py` (A4/A5): disparity->depth, triangulation, posture parallax, real cv2 SGBM depth.
- `perception/masking.py`: semantic feature filtering + self-supervised shadow mask.
- `geometry/dem.py`: real Haworth DEM I/O + scan-to-DEM registration.
- `geometry/fov.py` (A4): camera FOV + lander/AprilTag visibility across rover yaw.
- `posture/kinematics.py` (A3): posture library (Meerkat/Cobra/Iron Cross) grounded in Schuler et al. 2024; chassis lift/pitch, stability gate, parallax.
- `ipex/specs.py`: provenance-tagged IPEx constants ([SPEC]/[CONFIRM]).
- `bridge/dustgym_io.py`: reads the dustgym/LAC Seam-2 sensors.json + PNGs; writes cmd_vel/posture (no dustgym edits).
- `demo/end_to_end.py`: component demonstration combining a rendered frame and Haworth DEM from
  different scenes; not end-to-end SLAM.
- `demo/assets/rassor.glb`: NASA RASSOR 3D model (public, patent KSC-TOPS-7).
- 57 tests, 95% coverage, real-data subsample fixtures committed under `tests/fixtures/`.

### Not yet wired (next milestones, deliberately not stubbed)
- M3 unified GTSAM estimator (active SLAM) -- needs `gtsam`.
- M4 active-perception policy -- needs `gymnasium`.
- M5 multi-vehicle cooperative localization + coordination.
- M6 ablation / fault-injection harness (camera dropout, miscalibration).
- CARLA/Unreal LAC twin adapter; self-shadow heading cue; closed-loop multi-position trajectory.
