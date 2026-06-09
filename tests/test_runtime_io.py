"""A6 consumer: parse + validate the canonical single-clock dustgym_runtime packet."""
import os
import sys

import pytest

from solnav.bridge import runtime_io as rio

_DUST = os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym")


def _canonical(clock="sim_monotonic", seq=5, cam_seq=None):
    sys.path.insert(0, _DUST)
    from terrain_authority import proprioception as pp
    from terrain_authority import runtime_packet as rp
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(3)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.3, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(2)]
    proprio = pp.runtime_proprioception_packet(imu, wheel, sequence_id=seq, imu_rate_hz=100, wheel_rate_hz=10)
    cam = {"clock": clock, "sequence_id": cam_seq if cam_seq is not None else seq,
           "reference_camera": "front_left",
           "frames": [{"name": "front_left", "t": 0.0, "path": "cam/0/front_left.png"},
                      {"name": "front_right", "t": 0.0, "path": "cam/0/front_right.png"}]}
    return rp.canonical_runtime_packet(proprio, cam, joints=rp.joint_channel(-1.0, -1.0, t=0.0), sequence_id=seq)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_round_trip_canonical_one_clock():
    p = rio.parse_canonical(_canonical())
    assert p["clock"] == "sim_monotonic" and p["sequence_id"] == 5
    assert len(p["imu"]) == 3 and len(p["wheel"]) == 2          # IMU + raw four-wheel
    assert len(p["camera_frames"]) == 2                          # camera channel on the same clock
    assert p["joints"]["arm_front_pitch_rad"] == -1.0            # measured joints
    assert len(p["joints"]["camera_heights_m"]) == 8
    assert p["unavailable"] == ["power"]                         # only power honestly unavailable


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_canonical_rejects_truth_key():
    p = _canonical()
    p["channels"]["camera"]["frames"][0]["rover_pos_m"] = [1, 2, 3]   # inject truth
    with pytest.raises(ValueError, match="truth key"):
        rio.parse_canonical(p)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_canonical_rejects_camera_ok_without_frames():
    p = _canonical()
    p["channels"]["camera"]["frames"] = []
    with pytest.raises(ValueError, match="no frames"):
        rio.parse_canonical(p)


def test_rejects_non_canonical_schema():
    with pytest.raises(ValueError, match="not a canonical"):
        rio.parse_canonical({"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0, "channels": {}})


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_camera_timing_metrics_per_keyframe():
    p = _canonical()
    p["channels"]["camera"]["frames"] += [                  # a 2nd keyframe (stereo pair) -> a cadence
        {"name": "front_left", "t": 0.1, "path": "cam/1/front_left.png"},
        {"name": "front_right", "t": 0.1, "path": "cam/1/front_right.png"}]
    ct = rio.parse_canonical(p)["camera_timing"]
    assert ct["n_frames"] == 4 and ct["n_keyframes"] == 2 and ct["n_cameras"] == 2
    assert ct["duplicates"] == 0 and abs(ct["interval_mean_s"] - 0.1) < 1e-9   # req 4 timing recorded


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_stereo_pair_shares_timestamp_ok_but_single_camera_duplicate_rejected():
    p = _canonical()
    rio.parse_canonical(p)                                  # stereo pair at t=0 (FL+FR) -> OK, not a dup
    p["channels"]["camera"]["frames"].append({"name": "front_left", "t": 0.0, "path": "cam/dup.png"})
    with pytest.raises(ValueError, match="strictly monotonic"):
        rio.parse_canonical(p)                              # front_left repeats t -> a real duplicate


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_rejects_camera_outside_proprioception_window():
    p = _canonical()
    for f in p["channels"]["camera"]["frames"]:
        f["t"] = 1000.0                                     # camera far outside the imu/wheel window
    with pytest.raises(ValueError, match="association broken"):
        rio.parse_canonical(p)


def test_input_dir_truth_isolation(tmp_path):
    (tmp_path / "front_left.png").write_text("x")
    assert rio.assert_input_dir_clean(str(tmp_path))        # clean estimator input -> ok
    (tmp_path / "ground_truth_pose.csv").write_text("x")
    with pytest.raises(ValueError, match="truth file"):
        rio.assert_input_dir_clean(str(tmp_path))           # a truth file present -> reject (I3)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_rejects_novel_camera_frame_key():
    # audit 2026-06-09: frames were denylist-only -- a NOVEL hidden-state key could ride through
    p = _canonical()
    p["channels"]["camera"]["frames"][0]["covert_state"] = 1.0
    with pytest.raises(ValueError, match="allow-list"):
        rio.parse_canonical(p)
