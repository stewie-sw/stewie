# G1 IMU / Wheel-Odometry Data Sources and IPEx Extrapolation

**Date:** 2026-06-07
**Purpose:** unblock Gate **G1** ("Acquire timestamped IMU/wheel data and a locked validation capture").
dustgym camera egress reports IMU/wheel/joint channels UNAVAILABLE, so G1 has no proprioceptive
baseline. There is no public IPEx flight IMU/wheel telemetry, so the honest path is to ground a
faithful IMU/wheel model and a locked validation capture in REAL open planetary-rover data and
extrapolate to the IPEx platform (30 kg-class, four-wheel skid-steer, lunar g 1.62 m/s^2).

All numbers below are from the cited public sources. None are fabricated.

## 1. Recommended real open datasets (timestamped IMU + wheel + ground truth)

| Dataset | Proprioception | Ground truth | Terrain | Access | Fit for G1 |
|---|---|---|---|---|---|
| **Katwijk Beach** (ESA, Hewitt et al. 2018) | **wheel odometry + IMU** (no magnetometer, ExoMars-like) | DGPS + drone ortho/DEM | 1 km natural beach, artificial rocks at Mars rock-size densities; rocker-bogie ExoMars-emulation rover | ESA Robotics Datasets (academic) | **BEST.** Has the exact passive wheel+IMU+truth triple G1 needs, on natural unstructured terrain, GNSS-denied framing. |
| **MADMAX** (DLR, Meyer et al. 2021) | **IMU (XSENS MTi-10, 100 Hz)** + stereo | 5-DoF differential-GNSS (RTKLIB, 1.285 m antenna baseline) | 8 Mars-analog sites, Morocco, 9.2 km total | datasets.arches-projekt.de/morocco2018 (free, academic, registration) | **IMU model + noise grounding.** Visual-inertial only (no wheel odom); CSV, timestamped. |
| **BASEPROD** (Nature Sci. Data, 2024) | rover proprioception (IMU/wheel) | survey-grade | Bardenas semi-desert, planetary-analog | nature.com/articles/s41597-024-03881-1 (open) | Newer cross-check / second capture. |
| **LuSNAR** (2024) | none (cameras / LiDAR / depth / pose) | UE sim labels | **Lunar** but **SIMULATED** (Unreal Engine) | GitHub (open) | NOT for G1 proprioception; useful for the perception (G2) leg only. |

**Acquisition plan for the locked G1 capture:** ingest the **Katwijk** run as the surrogate "real
capture" (real timestamped wheel odometry + IMU + DGPS truth on natural terrain). Run solnav's SE(2)
pose graph on its wheel/IMU stream and validate ATE/RPE against the DGPS track. This is an honest
real-sensor end-to-end localization result (the gap the architectural review flagged as "surface
lunar localization with real ground truth is essentially absent"), with the lunar-g terramechanics
delta supplied by the dustgym slip model (Section 3).

## 2. Grounded IMU parameters (extrapolatable directly)

IMU noise is a property of the MEMS sensor class, not the platform, so the **XSENS MTi-10** values
(the MADMAX rover IMU; a conservative analog for an IPEx-class rover, which would fly an equal-or-
better space-rated unit) transfer directly. No magnetometer is used (the Moon has no global field,
matching the Katwijk/ExoMars choice).

| Parameter | Value (MTi-10 datasheet, typical 25 C) | Standard form |
|---|---|---|
| Sample rate | 100 Hz | dt = 0.01 s |
| Gyro noise density | 0.03 deg/s/sqrt(Hz) | ARW approx 1.8 deg/sqrt(h); per-sample sigma = 0.03*sqrt(100) = 0.3 deg/s |
| Gyro in-run bias stability | 18 deg/h | = 0.005 deg/s |
| Gyro range | 450 deg/s | |
| Accel noise density | 60 ug/sqrt(Hz) | per-sample sigma = 60*sqrt(100) = 600 ug = 0.0059 m/s^2 (corrected from canonical mtidocs.xsens.com) |
| Accel in-run bias stability | 15 ug | = 1.47e-4 m/s^2 (corrected) |

In-run bias is modelled as a first-order Gauss-Markov process (steady-state sigma = the in-run bias
stability; correlation time 1000 s is an [ASSUMPTION], not a spec value), NOT a pure random walk
(which over-drifts). Each sample carries its measurement variance (I4). Packaged params:
`solnav/config/data/g1_imu_wheel_params.json` (installable; was validation/, moved so the wheel can
locate it).
| Accel range | 200 m/s^2 | MTi-10 high-range (~20 g) option; corrected from the 50 m/s^2 default |

These replace the illustrative `GYRO_BIAS = 0.4 deg/step` used in `demo/sensor_slam.py` with a
sourced in-run bias of 0.005 deg/s and the white-noise terms above.

## 3. Grounded wheel-odometry / slip model (extrapolatable via terramechanics)

Wheel odometry error is terramechanics-bound, so it is extrapolated through the dustgym slip model
at lunar g rather than copied as a fixed number. The reference figures below are a **MER autonomous-
navigation design goal / contextual check, NOT a universal measured soil-error law**:

- **Dead-reckoning error approx 10% of distance traveled** on loose soil / rugged terrain, as a MER
  design goal / contextual check (Maimone, Cheng, Matthies 2007, MER visual odometry).
- **Slip regimes:** low (< 30%, soil-strength dominated), intermediate (30-60%), high (> 60%,
  sinkage dominated) (MER wheel-mobility studies).
- **Slip up to 125%** measured by VO on 25-31 deg slopes (Spirit, Sol 206); VO convergence 97%/95%.

**Extrapolation to IPEx:** dustgym's `slip_sinkage_equilibrium` (Bekker + Janosi-Hanamoto, Moon
moduli k_c=1400, k_phi=820000, n=1.0 at g=1.62) already produces per-step slip in these regimes;
the wheel-odometry channel over-reads forward progress by exactly that slip fraction (this is the
real drift already exercised in `demo/path_nav.py`). The MER design-goal band (10%-of-distance,
regime thresholds, 125% ceiling) is the **contextual acceptance check** the synthesized wheel stream must
fall inside to be considered faithful. IPEx kinematics: four-wheel skid-steer, track 0.5207 m, wheel
radius 0.1524 m (ipex_specs / NTRS 20240008162); yaw rate from differential wheel speeds, fused with
the gyro. Encoder rate 10-50 Hz typical.

## 4. What this unblocks / still needs

- **Unblocks:** a sourced IMU/wheel sensor model (Section 2-3) and a named real capture to lock
  (Katwijk, Section 1) so the dustgym egress can publish a passive wheel/IMU/stereo baseline.
- **Still needed for G1 PASS:** (a) wire the IMU/wheel/joint channels into the dustgym egress (they
  currently report UNAVAILABLE); (b) ingest the Katwijk capture and freeze it into the (currently
  empty) `scene_manifest.json`; (c) run solnav SLAM on the real stream and record ATE/RPE vs DGPS.
  Sourcing the data (this document) is step 0; the channel wiring and the locked capture remain.

## Sources

- Katwijk Beach Planetary Rover Dataset: https://robotics.estec.esa.int/datasets/katwijk-beach-11-2015/ ; Hewitt et al., IJRR 2018, https://journals.sagepub.com/doi/10.1177/0278364917737153
- MADMAX: https://datasets.arches-projekt.de/morocco2018/ ; Meyer et al., J. Field Robotics 2021, https://onlinelibrary.wiley.com/doi/full/10.1002/rob.22016
- BASEPROD: https://www.nature.com/articles/s41597-024-03881-1
- LuSNAR: https://arxiv.org/abs/2407.06512
- Maimone, Cheng, Matthies, "Two Years of Visual Odometry on the Mars Exploration Rovers," J. Field Robotics 2007, https://www-robotics.jpl.nasa.gov/media/documents/rob-06-0081.R4.pdf
- XSENS MTi 10-series datasheet: https://www.farnell.com/datasheets/1859197.pdf
