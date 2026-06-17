"""#145 served point-cloud artifact: render the REAL front-stereo back-projected world points
(obs_map_producer.collect_world_points) into a cockpit Perception-pane asset (a top-down elevation
scatter PNG + a stats manifest). The downsample helper is pure-tested; the full emit runs on a REAL
render egress when present and SKIPs otherwise (egress is render output, not committed). No synthetic
points -- the emitter renders whatever the stereo producer returned.

Run: <venv>/bin/python -m pytest scripts/ros2_bridge/test_depth_served.py -q
"""
import json
import os

import numpy as np
import pytest

pytest.importorskip("cv2")
pytest.importorskip("matplotlib")
import obs_map_producer as P  # noqa: E402  (same-dir import, mirrors the other bridge scripts)

_EGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "stewie", "godot", "out", "cam", "crater_boulders", "000")


def test_downsample_stride_caps_count_and_is_a_subset():
    pts = np.arange(300, dtype=float).reshape(100, 3)
    out = P.downsample_stride(pts, 10)
    assert out.shape[0] <= 10 and out.shape[1] == 3
    assert out.shape[0] >= 1
    # every returned row is an actual input row (a stride sample, never a fabricated/interpolated point)
    for row in out:
        assert np.any(np.all(pts == row, axis=1))
    # a cap >= N returns all points untouched
    assert P.downsample_stride(pts, 1000).shape[0] == 100


def test_emit_served_pointcloud_on_real_render(tmp_path):
    if not os.path.exists(os.path.join(_EGRESS, "sensors.json")):
        pytest.skip("no render egress (render with sidecar.tscn --cameras first)")
    out = str(tmp_path)
    P.emit_served_pointcloud(_EGRESS, out, max_points=5000)
    assert os.path.getsize(os.path.join(out, "pointcloud.png")) > 0
    manifest = json.load(open(os.path.join(out, "pointcloud.json")))
    full = P.collect_world_points(_EGRESS)
    assert manifest["n_points"] == int(full.shape[0]) and manifest["n_points"] > 0
    assert manifest["shown_points"] <= 5000
    assert abs(manifest["elev_median_m"]) < 0.15        # ground plane recovered near datum
    assert manifest["baseline_m"] > 0.0
