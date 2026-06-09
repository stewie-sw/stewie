"""Canonical single-clock runtime packet (P0-3): unify camera+imu+wheel+joints on one clock."""
import json

import pytest

from terrain_authority import proprioception as pp
from terrain_authority import runtime_packet as rp


def _proprio():
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(3)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.3, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(2)]
    return pp.runtime_proprioception_packet(imu, wheel, sequence_id=5, imu_rate_hz=100, wheel_rate_hz=10)


def _camera(clock="sim_monotonic", seq=5):
    return {"clock": clock, "sequence_id": seq, "reference_camera": "front_left", "baseline_m": 0.07,
            "frames": [{"name": "front_left", "t": 0.0, "path": "cam/0/front_left.png"},
                       {"name": "front_right", "t": 0.0, "path": "cam/0/front_right.png"}]}


def test_canonical_unifies_all_channels_on_one_clock():
    j = rp.joint_channel(0.65, 0.65, t=0.0)
    pkt = rp.canonical_runtime_packet(_proprio(), _camera(), joints=j)
    assert pkt["schema_version"] == "dustgym_runtime/1.0" and pkt["clock"] == "sim_monotonic"
    ch = pkt["channels"]
    assert ch["imu"]["status"] == "OK" and ch["wheel"]["status"] == "OK"
    assert ch["camera"]["status"] == "OK" and len(ch["camera"]["frames"]) == 2
    assert ch["joints"]["status"] == "OK" and ch["power"]["status"] == "UNAVAILABLE"


def test_rejects_mismatched_camera_clock():
    with pytest.raises(ValueError, match="canonical clock"):
        rp.canonical_runtime_packet(_proprio(), _camera(clock="wall_clock"))


def test_rejects_mismatched_sequence():
    with pytest.raises(ValueError, match="sequences disagree"):
        rp.canonical_runtime_packet(_proprio(), _camera(seq=99))


def test_joint_channel_carries_arm_angles_and_eight_camera_heights():
    j = rp.joint_channel(-1.0, -1.0, t=0.0)            # MEERKAT
    s = j["samples"][0]
    assert s["arm_front_pitch_rad"] == -1.0 and s["chassis_lift_m"] > 0.1
    assert len(s["camera_heights_m"]) == 8


def test_no_truth_in_canonical_packet():
    pkt = rp.canonical_runtime_packet(_proprio(), _camera(), joints=rp.joint_channel(0.2, 0.65, t=0.0))
    blob = json.dumps(pkt).lower()
    assert not any(k in blob for k in ("ground_truth", "true_slip", "rover_pos", "lander_pos"))


def test_power_channel_emits_bms_telemetry():
    from terrain_authority import ipex_specs as sp
    from terrain_authority import runtime_packet as rp
    ch = rp.power_channel(sp.drive_power_w(), 0.85, t=0.0)
    s = ch["samples"][0]
    assert ch["status"] == "OK" and s["soc_frac"] == 0.85
    assert abs(s["voltage_v"] - sp.BATTERY_SERIES_CELLS * sp.LIION_NOMINAL_V_PER_CELL) < 1e-9
    assert abs(s["current_a"] - s["power_w"] / s["voltage_v"]) < 1e-9    # I = P / V
