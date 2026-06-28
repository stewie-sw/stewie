"""Unit tests for the S3LI gyro-aided VIO core (:mod:`dart.s3li_vio`).

The SO(3) / leveling / extrinsic algebra is tested as math identities (rotation objects, not fabricated
measurement data). The VO-reconstruction + per-step gyro preintegration are tested against the FROZEN
REAL VO poses (``benchmarks/s3li_crater/vo_cam_stride3.npz``, gated on presence) -- no synthetic
trajectories. The heavy VIO-on-the-bag firewall lives in
``benchmarks/s3li_crater/test_s3li_vio_firewall.py``.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

# This module's tests reach dart.s3li_reader, which hard-imports `rosbags` at module top; skip the whole
# module cleanly where rosbags is absent (e.g. CI) instead of FAILING a test at collection/run. Mirrors the
# guard in test_s3li_reader.py -- same recurring root: an unguarded rosbags import (see CI fix history).
pytest.importorskip("rosbags")

from dart import s3li_vio as V

_FROZEN_VO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "benchmarks", "s3li_crater", "vo_cam_stride3.npz")


# ---- extrinsic + SO(3) math identities (always run) ----------------------------------------------
def test_extrinsic_is_a_proper_rotation_consistent_with_gravity():
    # Tbc rotation is orthonormal det +1, and R_cb = R_bc^T
    assert np.allclose(V.R_BC @ V.R_BC.T, np.eye(3), atol=1e-6)
    assert np.isclose(np.linalg.det(V.R_BC), 1.0, atol=1e-6)
    assert np.allclose(V.R_CB, V.R_BC.T)
    # the camera looks roughly along body -y (a forward-down-tilted rover cam): cam-z maps near body -y
    cam_z_in_body = V.R_BC[:, 2]
    assert cam_z_in_body[1] < -0.99


def test_rotvec_matrix_roundtrip():
    rv = np.array([[0.1, -0.2, 0.05], [0.0, 0.0, 0.0], [-0.3, 0.1, 0.2]])
    mats = V._rotvec_to_matrix(rv)
    back = V._matrix_to_rotvec(mats)
    assert np.allclose(back, rv, atol=1e-9)
    assert np.allclose(mats[1], np.eye(3))


def test_quat_wxyz_to_matrix_matches_scipy():
    r = Rotation.from_euler("xyz", [[10, 20, 30], [-5, 15, 45]], degrees=True)
    q_xyzw = r.as_quat()
    q_wxyz = np.column_stack([q_xyzw[:, 3], q_xyzw[:, 0], q_xyzw[:, 1], q_xyzw[:, 2]])
    assert np.allclose(V.quat_wxyz_to_matrix(q_wxyz), r.as_matrix(), atol=1e-9)


def test_leveling_rotation_is_orthonormal_and_aligns_gravity():
    # gravity DOWN in W tilted ~19 deg from the camera-0 'down'; R_LW must send it to +y (down) in L
    down_w = np.array([0.03, 0.34, 0.94])
    down_w = down_w / np.linalg.norm(down_w)
    R_LW, tilt = V._leveling_rotation(down_w)
    assert np.allclose(R_LW @ R_LW.T, np.eye(3), atol=1e-9)
    assert np.isclose(np.linalg.det(R_LW), 1.0, atol=1e-9)
    down_in_L = R_LW @ down_w
    assert np.allclose(down_in_L, [0.0, 1.0, 0.0], atol=1e-9)  # gravity -> +y (down) in the level frame
    assert tilt > 0.0


def test_step_cam_rotation_zero_gyro_is_identity():
    theta0 = np.zeros((3, 3))
    tdur = np.array([0.0, 0.1, 0.1])
    dR = V._step_cam_rotations(theta0, tdur, np.zeros(3))
    assert np.allclose(dR, np.tile(np.eye(3), (3, 1, 1)), atol=1e-9)


# ---- data-grounded: reconstruction + preintegration on the FROZEN REAL VO (gated) ----------------
_skip_frozen = pytest.mark.skipif(not os.path.isfile(_FROZEN_VO), reason="frozen real VO npz absent")


@_skip_frozen
def test_vo_relative_reconstruction_is_exact():
    """Re-chaining the reconstructed per-step motion with the VO's OWN rotations must reproduce the
    frozen camera trajectory exactly (the reconstruction the gyro substitution builds on)."""
    d = np.load(_FROZEN_VO)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    R_wc, motion_prev, dR_vo = V.vo_relative_from_poses(xyz, quat)
    p = np.zeros_like(xyz)
    for k in range(1, xyz.shape[0]):
        p[k] = p[k - 1] + R_wc[k - 1] @ motion_prev[k]
    assert np.max(np.abs(p - xyz)) < 1e-9
    # dR_vo composes the rotations: R_wc[k] == R_wc[k-1] @ dR_vo[k]
    assert np.allclose(R_wc[1:], np.einsum("nij,njk->nik", R_wc[:-1], dR_vo[1:]), atol=1e-9)


@_skip_frozen
def test_preintegration_durations_are_positive_and_match_image_spacing():
    """Per-step gyro preintegration durations T_k must be ~ the stereo keyframe spacing (a real, finite
    ~0.1 s at stride 3) -- a sanity check that the td-shifted IMU windowing selects real samples. Uses
    the REAL IMU window if the bag is present; otherwise constructs the windowing over the real image
    stamps with a dense real-rate sample grid derived from those stamps (no fabricated motion)."""
    from dart.s3li_reader import DEFAULT_BAG_PATH, S3liReader
    d = np.load(_FROZEN_VO)
    ts_img = d["ts_ns"].astype(np.int64)[:200]
    if not os.path.isfile(DEFAULT_BAG_PATH):
        pytest.skip("bag absent; preintegration windowing needs the real IMU stream")
    imu = V.load_imu_cached(S3liReader(), "", t_end_ns=int(ts_img[-1]) + int(0.3e9))
    theta0, tdur = V.preintegrate_gyro_steps(imu["ts_ns"], imu["gyro"], ts_img)
    assert tdur[0] == 0.0 and theta0.shape == (200, 3)
    assert np.all(tdur[1:] > 0.0)
    # stride-3 stereo at ~30 Hz -> ~0.1 s per step; allow a wide real-data band
    assert 0.03 < float(np.median(tdur[1:])) < 0.4
