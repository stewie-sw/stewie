import os

import numpy as np

from solnav.perception import camera_rig as cr

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "frame", "sensors.json")


def test_exact_stereo_baseline_from_real_extrinsics():
    rig = cr.CameraRig.from_sensors(FIX)
    # front_left/right exact mounts differ by the 0.07 m stereo baseline
    assert abs(rig.baseline_m("front_left", "front_right") - 0.07) < 1e-3


def test_front_rear_baseline_is_wide():
    rig = cr.CameraRig.from_sensors(FIX)
    assert abs(rig.baseline_m("front_left", "rear_left") - 0.6) < 1e-2   # ~0.6 m fore-aft


def test_front_and_rear_axes_oppose():
    rig = cr.CameraRig.from_sensors(FIX)
    # front cameras look forward, rear look back -> ~180 deg between optical axes
    assert rig.axis_angle_deg("front_left", "rear_left") > 150.0


def test_f0_default_and_loaded_rigs_agree_on_frame():
    # after F0, the default and loaded rigs return the SAME body axis for the same physical
    # camera (previously they lived in different frames -- HIGH-02).
    d = cr.CameraRig()
    loaded = cr.CameraRig.from_sensors(FIX)
    assert np.allclose(d.get("front_left").optical_axis(),
                       loaded.get("front_left").optical_axis(), atol=1e-6)
    assert np.allclose(loaded.get("front_left").optical_axis(), [1, 0, 0], atol=1e-3)


def test_camera_world_xy_with_rover_pose():
    rig = cr.CameraRig.from_sensors(FIX)
    fl = rig.get("front_left").pos_m
    ground = np.array([fl[0], -fl[2]])      # Godot->ROS ground offset (x, -z), not (x, y)
    w = rig.camera_world_xy("front_left", 0.0)
    assert np.allclose(w, ground, atol=1e-6)
    w90 = rig.camera_world_xy("front_left", np.pi / 2)
    assert np.allclose(w90, [-ground[1], ground[0]], atol=1e-6)
    # the stereo pair must NOT collapse to one ground point (the frame bug)
    assert not np.allclose(rig.camera_world_xy("front_left", 0.0),
                           rig.camera_world_xy("front_right", 0.0))


def test_default_rig_baselines_without_sensors():
    rig = cr.CameraRig()
    assert rig.baseline_m("front_left", "front_right") > 0
    assert rig.baseline_m("front_left", "rear_left") > rig.baseline_m("front_left", "front_right")
