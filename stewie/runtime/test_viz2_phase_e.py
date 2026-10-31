"""Modeled drive telemetry on native Haworth terrain; not calibrated sensor evidence."""
from __future__ import annotations

import os




from stewie.runtime.viz2_runtime import Viz2Runtime


_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "samples", "lunar_dem")

SFS = os.path.join(_SAMPLES, "haworth_sfs_2km_1m")

def _runtime(tmp_path) -> Viz2Runtime:
    """A constructed-but-UNSTARTED runtime centered deep-interior on the real SfS bundle (its __init__
    recenters the WorkSite + sets the pose, so _apply_dig/_apply_dump have a seated footprint)."""
    from stewie.physics.worksite import coarse_base_from_bundle
    _base, meta = coarse_base_from_bundle(SFS)
    wb = meta["world_bounds_m"]
    cx = float(wb["x0"]) + _base.width * meta["grid"]["cell_m"] * 0.5
    cy = float(wb["y0"]) + _base.height * meta["grid"]["cell_m"] * 0.5
    return Viz2Runtime(SFS, session_dir=str(tmp_path), fine_cell_m=None, start_xy=(cx, cy))


def test_aggregate_metrics_wheel_odometry_over_reads_ground_truth(tmp_path):
    """council/metrics #31: drive the REAL conserved physics and accumulate the deterministic aggregate
    metrics. The slip-blind wheel odometry integrates the COMMANDED speed and the ground truth the ACHIEVED
    speed, so under real slip the wheel odometry >= the actual distance and the odometry_error (drift) >= 0."""
    rt = _runtime(tmp_path)
    try:
        assert rt._dist_actual_m == 0.0 and rt._dist_wheel_m == 0.0 and rt._slope_n == 0
        for _ in range(12):
            telem, _ = rt.ws.step(0.2, 0.0, rt.dt)        # commanded 0.2 m/s over the real Haworth DEM
            rt._accumulate_metrics(telem, rt.dt)
        assert rt._dist_actual_m > 0.0                    # the rover really moved (ground truth)
        assert rt._dist_wheel_m >= rt._dist_actual_m      # slip-blind encoder over-reads
        assert rt._dist_wheel_m - rt._dist_actual_m >= 0.0  # dead-reckoning drift is non-negative
        assert 0.0 <= rt._slope_sum_deg / rt._slope_n < 90.0  # a real mean grade from the traversed terrain
    finally:
        rt.stop()


def test_faithful_imu_gyro_equals_yaw_rate_and_accel_finite(tmp_path):
    """#32: the IMU is deterministic + faithful to the REAL drive — gyro IS the achieved yaw rate, the
    accelerometer reads a FINITE specific force (body accel + lunar-gravity slope projection), no rng.
    A turn gives a nonzero yaw-rate reading."""
    import math as _m
    rt = _runtime(tmp_path)
    try:
        for _ in range(6):
            telem, _ = rt.ws.step(0.2, 0.0, rt.dt)               # straight drive
            rt._accumulate_metrics(telem, rt.dt)
        assert rt._imu_gyro_z == float(telem.get("omega_achieved", 0.0))   # gyro == achieved yaw rate
        assert _m.isfinite(rt._imu_accel_long) and _m.isfinite(rt._imu_accel_lat)
        telem, _ = rt.ws.step(0.2, 0.5, rt.dt)                   # turn -> a real yaw rate on the gyro
        rt._accumulate_metrics(telem, rt.dt)
        assert rt._imu_gyro_z == float(telem.get("omega_achieved", 0.0))
        assert abs(rt._imu_gyro_z) > 0.0
    finally:
        rt.stop()
