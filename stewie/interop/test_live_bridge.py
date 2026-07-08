"""#63 drive-in-Godot, increment 1a — the persistent-render CONTROL SEAM (FastAPI -> Godot half).

The realtime Godot "drive" view needs the render to run as a LONG-LIVED process (not render.sh's
one-shot spawn->render->quit); the FastAPI side writes a ControlState (driven rover pose / drum-arm
posture / sun / camera) to control.json and the persistent Godot process polls it each frame, mirroring
stewie.physics.drive.poll_cmd_vel's safe polled-dir pattern. This is the JSON control half only -- the
frame sink (Godot -> FastAPI PNGs) is increment 2, so there are deliberately NO frame fixtures here and
nothing fabricates a render.
"""
import json
import math

import pytest

from stewie.interop.live_bridge import (
    CAMERAS,
    ControlState,
    control_path,
    frame_sink_path,
    latest_pointer_path,
    read_control,
    write_control,
)


def _state(**kw):
    base = dict(
        seq=1, pose_x=2.0, pose_z=3.0, pose_yaw=0.5,
        arm_front_pitch=0.65, arm_back_pitch=0.65,
        sun_elev_deg=8.0, sun_azim_deg=215.0, camera="grid",
    )
    base.update(kw)
    return ControlState(**base)


def test_control_state_round_trips_all_fields(tmp_path):
    st = _state(seq=7, pose_x=1.25, pose_yaw=-1.0, camera="drum_front_cam")
    write_control(str(tmp_path), st)
    got = read_control(str(tmp_path))
    assert got == st                                   # exact frozen-dataclass round-trip
    assert got.seq == 7 and got.camera == "drum_front_cam"


def test_read_control_missing_dir_or_file_is_none(tmp_path):
    assert read_control(str(tmp_path / "nope")) is None    # no dir -> safe None (not a crash)
    assert read_control(str(tmp_path)) is None             # dir exists, no control.json


def test_read_control_bad_json_is_none(tmp_path):
    control_path(str(tmp_path)).write_text("{not json", encoding="utf-8")
    assert read_control(str(tmp_path)) is None             # malformed -> safe None, like poll_cmd_vel's stop


def test_write_control_is_atomic_no_tmp_residue(tmp_path):
    write_control(str(tmp_path), _state())
    assert json.loads(control_path(str(tmp_path)).read_text(encoding="utf-8"))["seq"] == 1
    assert not list(tmp_path.glob("*.tmp"))               # os.replace left no half-written partial behind


def test_control_state_rejects_non_finite_pose():
    with pytest.raises(ValueError):
        _state(pose_x=math.inf)            # a non-finite pose/sun would break the render (council #55 discipline)
    with pytest.raises(ValueError):
        _state(sun_elev_deg=math.nan)


def test_control_state_rejects_unknown_camera():
    with pytest.raises(ValueError):
        _state(camera="not_a_camera")
    assert "grid" in CAMERAS and "front_left" in CAMERAS   # the real EZ-RASSOR/IPEx panes + the composite


def test_path_helpers_are_stable_and_namespaced(tmp_path):
    d = str(tmp_path)
    assert control_path(d) == tmp_path / "control.json"
    assert latest_pointer_path(d) == tmp_path / "latest.json"
    assert frame_sink_path(d, 42) == tmp_path / "frames" / "frame_000042.png"
