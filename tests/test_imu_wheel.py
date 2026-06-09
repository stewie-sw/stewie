"""Consumer-side proprioception: parsed types + slip-blind derived odometry.
(Sensor GENERATION moved to dustgym; its tests live in terrain_authority/test_proprioception.py.)"""
import numpy as np

from solnav.sensors import imu_wheel as iw


def _wheel(deltas, r=0.1524):
    return iw.WheelSample(t=0.0, encoder_delta_rad=np.array(deltas, float),
                          encoder_count_delta=np.zeros(4, int), covariance=np.eye(4),
                          wheel_radius_m=r, encoder_counts_per_rev=4096,
                          sample_ids=("x",), config_revision="t")


def test_body_odometry_straight():
    v, w = iw.body_odometry_from_encoders(_wheel([1.0, 1.0, 1.0, 1.0]), 0.5207, 0.1)
    assert v > 0 and abs(w) < 1e-9                 # equal rotations -> forward, zero yaw


def test_body_odometry_right_wheels_faster_turns_left():
    v, w = iw.body_odometry_from_encoders(_wheel([1.0, 1.5, 1.0, 1.5]), 0.5207, 0.1)
    assert w > 0 and v > 0                         # right wheels spin more -> positive yaw


def test_dead_reckon_error_fraction_overread():
    wheel = [iw.WheelOdomSample(t=i * 0.1, v_mps=0.33, omega_rps=0.0) for i in range(11)]   # ~10% over true 0.30
    true_xy = np.column_stack([np.arange(11) * 0.30 * 0.1, np.zeros(11)])
    assert abs(iw.dead_reckon_error_fraction(wheel, true_xy) - 0.10) < 0.02


def test_parsed_types_have_no_slip_field_I3():
    assert "slip" not in vars(_wheel([1, 1, 1, 1]))
    assert "slip" not in vars(iw.WheelOdomSample(t=0.0, v_mps=0.3, omega_rps=0.0))


def test_body_odometry_rejects_zero_dt_and_track():
    # audit 2026-06-09: unguarded division emitted Inf/NaN into the estimator input
    import numpy as _np
    import pytest as _pt

    from solnav.sensors.imu_wheel import WheelSample, body_odometry_from_encoders
    w = WheelSample(t=0.0, encoder_delta_rad=_np.zeros(4), encoder_count_delta=_np.zeros(4, int),
                    covariance=_np.eye(4), wheel_radius_m=0.15, encoder_counts_per_rev=4096,
                    sample_ids=(), config_revision="rev0")
    with _pt.raises(ValueError, match="refusing"):
        body_odometry_from_encoders(w, 0.5207, 0.0)
    with _pt.raises(ValueError, match="refusing"):
        body_odometry_from_encoders(w, 0.0, 0.1)
