import numpy as np
import pytest

from solnav.perception import camera_rig as cr


def test_rig_has_eight_cameras_and_two_stereo_pairs():
    rig = cr.CameraRig()
    assert len(rig.cams) == 8
    assert len(rig.stereo_pairs()) == 2


def test_active_set_respects_four_live_and_roles():
    active = cr.CameraRig().select_active()
    assert len(active) <= cr.MAX_LIVE
    roles = {c.role for c in active}
    assert "stereo_front" in roles and "side" in roles and "drum" in roles


def test_cameras_seeing_lander_ahead():
    rig = cr.CameraRig()
    seen = rig.cameras_seeing(world_bearing_deg=0.0, rover_yaw_deg=0.0, distance_m=2.5)
    assert "front_left" in seen and "front_right" in seen


def test_horizontal_parallax_triangulation_recovers_point():
    p = cr.horizontal_parallax_triangulate([0, 0], np.degrees(np.arctan2(5, 1)),
                                           [2, 0], np.degrees(np.arctan2(5, -1)))
    assert np.allclose(p, [1, 5], atol=1e-6)


def test_wider_baseline_tightens():
    assert cr.horizontal_triangulation_sigma_m(4.0, 8.0, 0.5) < cr.horizontal_triangulation_sigma_m(1.0, 8.0, 0.5)


def test_parallel_bearings_raise():
    with pytest.raises(ValueError):
        cr.horizontal_parallax_triangulate([0, 0], 0.0, [2, 0], 0.0)


def test_f0_optical_axes_in_body_rep103():
    # The profile reproduces captured Dustgym metadata. Its side-camera *names* are opposite their
    # REP-103 lateral directions: left_mono -> -Y and right_mono -> +Y. Runtime geometry wins.
    d = cr.CameraRig()
    assert np.allclose(d.get("front_left").optical_axis(), [1, 0, 0], atol=1e-9)
    assert np.allclose(d.get("left_mono").optical_axis(), [0, -1, 0], atol=1e-9)
    assert np.allclose(d.get("right_mono").optical_axis(), [0, 1, 0], atol=1e-9)
    assert np.allclose(d.get("rear_left").optical_axis(), [-1, 0, 0], atol=1e-9)
