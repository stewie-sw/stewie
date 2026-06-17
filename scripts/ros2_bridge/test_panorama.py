"""#183 panorama: composite the 8-camera rig egress into a heading-ordered surround. The geometry
(quaternion -> forward -> heading) is asserted pure; the full stitch runs on a REAL Godot --cameras
render egress when present and SKIPs otherwise (the egress is render output, not committed -- the same
no-fabrication convention as test_obs_map_producer).

Run: <venv>/bin/python -m pytest scripts/ros2_bridge/test_panorama.py -q
"""
import math
import os

import pytest

pytest.importorskip("PIL")
import panorama as P  # noqa: E402  (same-dir import, mirrors the other bridge scripts)

_EGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "stewie", "godot", "out", "cam", "crater_boulders", "000")


def test_quat_forward_identity_faces_minus_z():
    f = P._quat_forward([0, 0, 0, 1])                          # Godot forward is -Z
    assert abs(f[0]) < 1e-9 and abs(f[1]) < 1e-9 and abs(f[2] + 1.0) < 1e-9


def test_camera_heading_in_range():
    for q in ([0, 0, 0, 1], [0, math.sin(math.pi / 4), 0, math.cos(math.pi / 4)], [0, 1, 0, 0]):
        h = P.camera_heading_deg({"pose_in_world": {"quaternion_xyzw": q}})
        assert 0.0 <= h < 360.0


def test_panorama_on_real_render_egress():
    if not os.path.exists(os.path.join(_EGRESS, "sensors.json")):
        pytest.skip("no render egress (render with sidecar.tscn --cameras first)")
    order = P.panorama_order(_EGRESS)
    assert order, "no camera images in the egress"
    headings = [a for _, a, _ in order]
    assert headings == sorted(headings)                       # laid out left->right by heading
    assert all(0.0 <= a < 360.0 for a in headings)
    pano = P.build_panorama(_EGRESS)
    assert pano.ndim == 2 and pano.shape[0] == P.CAM_H and pano.shape[1] == P.CAM_W * len(order)
    assert int(pano.max()) > 8                                # real rendered content, not an all-black strip
