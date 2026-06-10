"""Consumer-side proprioception types + slip-blind derived odometry for solnav.

The sensor GENERATION (the IMU/wheel noise model + the sourced params) now lives in the dustgym
PRODUCER (`terrain_authority/proprioception.py`), per the ownership split
(STANFORD_LITERATURE_ARCHITECTURE_DIFF_2026-06-08: dustgym owns sensor generation/publication; solnav
owns parsing, time-sync, derived odometry, estimation). solnav defines its OWN parsed types here -- a
DECOUPLED seam, no shared Python classes across the dustgym->solnav boundary -- plus the slip-blind
body odometry it derives from published wheel samples (I3: no slip/truth on the consumer side either).
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/sensors/imu_wheel.py, 2026-06-09 (M2)
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ImuSample:
    t: float
    gyro_z_rps: float                 # yaw rate [rad/s]
    accel_xy_mps2: np.ndarray         # planar specific force [m/s^2]
    gyro_var: float = 0.0             # measurement variance [rad/s]^2 (I4)
    accel_var: float = 0.0            # per-axis measurement variance [m/s^2]^2 (I4)
    provenance: str = "SIMULATED_SENSOR"


@dataclass
class WheelSample:
    """Parsed four-wheel encoder observation (order LF, RF, LR, RR); slip is never a field (I3)."""
    t: float
    encoder_delta_rad: np.ndarray
    encoder_count_delta: np.ndarray
    covariance: np.ndarray
    wheel_radius_m: float
    encoder_counts_per_rev: int
    sample_ids: tuple
    config_revision: str
    covariance_calibrated: bool = False
    provenance: str = "SIMULATED_SENSOR"


@dataclass
class WheelOdomSample:
    t: float
    v_mps: float
    omega_rps: float
    v_var: float = 0.0
    omega_var: float = 0.0
    provenance: str = "SIMULATED_SENSOR"


def body_odometry_from_encoders(sample, track_m: float, dt: float):
    """Slip-BLIND body odometry from a four-wheel encoder sample (order LF, RF, LR, RR): assumes wheel
    spin equals ground distance (encoder_delta_rad * r), so it over-reads under slip exactly as a real
    odometry front end would. Returns (v_mps, omega_rps). Duck-typed on the sample (works for solnav's
    parsed WheelSample or the dustgym producer's)."""
    if dt <= 0.0 or track_m <= 0.0:
        raise ValueError(f"dt and track_m must be > 0 (got dt={dt}, track_m={track_m}); "
                         "refusing to emit Inf/NaN odometry")
    d = np.asarray(sample.encoder_delta_rad, float) * sample.wheel_radius_m
    left = 0.5 * (d[0] + d[2]); right = 0.5 * (d[1] + d[3])
    return float((left + right) / (2.0 * dt)), float((right - left) / (track_m * dt))


def dead_reckon_error_fraction(wheel: list, true_xy) -> float:
    if len(wheel) < 2 or len(np.atleast_2d(true_xy)) < 2:
        raise ValueError("dead-reckon error needs >= 2 samples (a fabricated 100% on empty input "
                         "would poison any aggregate; audit M16)")
    """|odom_distance - true_distance| / true_distance from a list of WheelOdomSamples. The MER
    design-goal band puts loose-soil dead reckoning near 0.10 (a contextual check, not a soil law)."""
    true_xy = np.asarray(true_xy, float)
    true_dist = float(np.sum(np.linalg.norm(np.diff(true_xy, axis=0), axis=1)))
    if true_dist < 1e-9:
        raise ValueError("true path has zero length")
    dts = np.diff([w.t for w in wheel]) if len(wheel) > 1 else np.array([0.0])
    odom_dist = float(np.sum([w.v_mps for w in wheel[:-1]] * dts)) if len(wheel) > 1 else 0.0
    return abs(odom_dist - true_dist) / true_dist
