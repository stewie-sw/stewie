"""S3LI ``s3li_crater`` stereo VISUAL-INERTIAL odometry (gyro-aided VO): fuse the real DLR S3LI IMU
gyro into the committed SuperPoint+LightGlue stereo VO so the gyro constrains HEADING, which is the
drift the vision-only VO could not control (ATE 93.3 m, horizontal/heading-dominated 92.9 m). After
the VIO trajectory is frozen, DEM height-normal anchoring is RE-TESTED on it (it now has a chance: with
heading tamed the DEM is sampled near the right terrain). This is an ADDITIVE variant -- the prior
vision-only path (:mod:`dart.s3li_capstone` / ``benchmarks/s3li_crater/run_s3li_crater.py``) is untouched.

THE FORMULATION (S3LI is STEREO -> scale is already metric, so the IMU's job is ROTATION + gravity, not
scale):

  * Per-step relative ROTATION from the bias-corrected gyro, preintegrated between consecutive stereo
    keyframes. The cam-IMU extrinsic ``Tbc`` (body_T_cam0) and the time offset ``td`` = 0.015 s
    (image_clock + td = imu_clock) are applied, so the gyro increment is expressed in the CAMERA frame
    and read over the right IMU window.
  * A constant gyro BIAS (3 params) estimated JOINTLY by least-squares against the VO per-step rotations
    -- firewall-clean: the reference is the de-oracled VO, NEVER ground truth. (The VO local per-step
    rotation is unbiased; it is the ACCUMULATION of its zero-mean noise that drifts the heading. A
    debiased gyro -- angle-random-walk ~0.2 deg over the 1136 s loop -- does not accumulate that noise,
    so its heading is far steadier than the chained VO heading.)
  * Absolute roll/pitch from the accelerometer GRAVITY direction (gravity is observable + non-drifting):
    the VIO trajectory is built in a gravity-LEVELED local frame, so only the initial heading (yaw) and
    the origin remain free -- exactly what the existing firewall-clean yaw-search + the single declared
    start fix supply (the same registration the VO path uses).
  * Translation MAGNITUDE + direction from the stereo VO (metric, from the frozen camera poses), rotated
    into the world by the gyro-FUSED orientation instead of the drift-prone VO orientation. That single
    substitution is what removes the heading-driven horizontal drift.

REUSE. The frozen VO camera poses (``vo_cam_stride*.npz`` -> per-step translation + rotation are
reconstructed exactly, no VO re-run needed), the registration + anchoring + scoring helpers in
:mod:`dart.s3li_capstone`, and the DEM-anchoring Gauss-Newton solver
(:class:`dart.dem_height_graph.DemHeightPoseGraph`, via ``estimate_and_freeze``).

TRUTH FIREWALL (invariant I3). :func:`build_vio_leveled_trajectory` and :func:`estimate_vio_and_freeze`
consume ONLY the stereo-VO poses, the IMU stream, the cam-IMU calibration, the DEM (sampled at the
ESTIMATED position), and the single declared start. No ground-truth trajectory is an argument. GT enters
only downstream, at time-sync + scoring, after the estimate is frozen.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public); IMU + cam-IMU
# calibration: Cfgs/orbslam_config.yaml (public). DEM: Copernicus GLO-30 (public).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from dart.s3li_capstone import estimate_and_freeze

# --- cam-IMU calibration (Cfgs/orbslam_config.yaml) -----------------------------------------------
# Tbc = body_T_cam0 (a vector in the camera optical frame -> the IMU/body frame).
TBC = np.array(
    [
        [0.9999198, 0.00649271, -0.01087349, -0.1372],
        [-0.01079265, -0.01235939, -0.99986537, -0.0551],
        [-0.00662623, 0.99990254, -0.01228832, -0.0691],
        [0.0, 0.0, 0.0, 1.0],
    ],
    dtype=float,
)
# orthonormalise the measured calibration rotation to the nearest proper rotation (the raw 6-dp Tbc is
# non-orthonormal at ~1e-6, which would leave R_cb @ R_bc != I); scipy's from_matrix does the SVD polar.
R_BC = Rotation.from_matrix(TBC[:3, :3]).as_matrix()  # camera -> body rotation
R_CB = R_BC.T  # body -> camera rotation
# time offset: image_clock + td = imu_clock, so an image stamp t maps to imu-clock t + td.
CAM_IMU_TD_S = 0.015
# IMU.NoiseGyro from orbslam_config.yaml (rad/s/sqrt(Hz)); used for the heading-factor sigma report.
IMU_GYRO_NOISE = 1.0e-4


@dataclass(frozen=True)
class VioBuild:
    """Frozen output of the gyro-aided VIO trajectory build (no GT; invariant I3).

    ``xyz_leveled`` (N,3) is the VIO camera trajectory in a gravity-leveled (right, down, forward)
    frame -- the same convention the VO path's registration consumes. ``gyro_bias_rad_s`` is the jointly
    estimated constant gyro bias. ``vo_gyro_resid_deg_before`` / ``..._after`` are the median per-step
    gyro-vs-VO rotation disagreement before / after debiasing (the extrinsic + approach sanity check).
    """

    xyz_leveled: np.ndarray
    gyro_bias_rad_s: np.ndarray
    vo_gyro_resid_deg_before: float
    vo_gyro_resid_deg_after: float
    gravity_norm_m_s2: float
    leveling_tilt_deg: float
    n_steps: int
    n_valid_vo_steps: int
    n_imu_samples: int


# --------------------------------------------------------------------------------------------------
# small SO(3) helpers (scipy-backed; batched)
# --------------------------------------------------------------------------------------------------
def quat_wxyz_to_matrix(quat_wxyz: np.ndarray) -> np.ndarray:
    """(N,4) Hamilton quaternion (w, x, y, z) -> (N,3,3) rotation matrices."""
    q = np.atleast_2d(np.asarray(quat_wxyz, float))
    xyzw = np.column_stack([q[:, 1], q[:, 2], q[:, 3], q[:, 0]])
    return Rotation.from_quat(xyzw).as_matrix()


def _rotvec_to_matrix(rotvec: np.ndarray) -> np.ndarray:
    return Rotation.from_rotvec(np.atleast_2d(np.asarray(rotvec, float))).as_matrix()


def _matrix_to_rotvec(mats: np.ndarray) -> np.ndarray:
    return Rotation.from_matrix(np.asarray(mats, float)).as_rotvec()


# --------------------------------------------------------------------------------------------------
# reconstruct the per-step VO translation + rotation from the frozen camera poses (no VO re-run)
# --------------------------------------------------------------------------------------------------
def vo_relative_from_poses(
    xyz_cam: np.ndarray, quat_wxyz: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """From the frozen camera-to-world poses recover, per step k (k-1 -> k):

      * ``R_wc`` (N,3,3) the camera-to-world rotations (world = camera 0);
      * ``motion_prev`` (N,3) the camera displacement between k-1 and k expressed in frame c_{k-1}
        (metric, from stereo) -- ``motion_prev[0]`` is zero;
      * ``dR_vo`` (N,3,3) the VO relative rotation R_{c_{k-1} <- ... } = R_wc[k-1]^T @ R_wc[k]
        (``dR_vo[0]`` = identity).

    These are exactly the VO per-step quantities ``estimate_vo_superpoint`` chained, so substituting the
    gyro orientation for the chain is an exact gyro-aided-VO reconstruction.
    """
    xyz_cam = np.asarray(xyz_cam, float)
    R_wc = quat_wxyz_to_matrix(quat_wxyz)
    n = xyz_cam.shape[0]
    motion_prev = np.zeros((n, 3))
    dR_vo = np.tile(np.eye(3), (n, 1, 1))
    for k in range(1, n):
        Rk1 = R_wc[k - 1]
        motion_prev[k] = Rk1.T @ (xyz_cam[k] - xyz_cam[k - 1])
        dR_vo[k] = Rk1.T @ R_wc[k]
    return R_wc, motion_prev, dR_vo


# --------------------------------------------------------------------------------------------------
# gyro preintegration between keyframes (cheap exact-for-short-intervals single-axis model + td)
# --------------------------------------------------------------------------------------------------
def preintegrate_gyro_steps(
    imu_ts_ns: np.ndarray, gyro: np.ndarray, image_ts_ns: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Per stereo step k, the gyro-integrated body rotation-vector ``theta0_k`` and duration ``T_k`` over
    the imu-clock interval [t_img[k-1]+td, t_img[k]+td]. ``theta0_k`` = sum_i gyro_i * dt_i (left-endpoint
    rule, dt_i = imu sample spacing); the bias enters later as ``theta_k(b) = theta0_k - b * T_k``.

    Returns ``(theta0 (N,3), T (N,))`` with row 0 zero (no step into keyframe 0). The td offset aligns
    image time to the IMU clock before windowing.
    """
    imu_ts = np.asarray(imu_ts_ns, np.int64)
    gyro = np.asarray(gyro, float)
    kf_imu = np.asarray(image_ts_ns, np.int64) + int(round(CAM_IMU_TD_S * 1e9))
    m = imu_ts.shape[0]
    dt = np.diff(imu_ts).astype(float) / 1e9  # (m-1,) seconds between consecutive IMU samples
    rv = gyro[:-1] * dt[:, None]  # (m-1,3) per-sample integrated angle increment
    # prefix sums so a step's totals are an O(1) boundary difference
    csum_rv = np.zeros((m, 3))
    csum_rv[1:] = np.cumsum(rv, axis=0)
    csum_t = np.zeros(m)
    csum_t[1:] = np.cumsum(dt)
    bnd = np.clip(np.searchsorted(imu_ts, kf_imu), 0, m - 1)  # (N,) sample index at each keyframe time
    n = kf_imu.shape[0]
    theta0 = np.zeros((n, 3))
    tdur = np.zeros(n)
    theta0[1:] = csum_rv[bnd[1:]] - csum_rv[bnd[:-1]]
    tdur[1:] = csum_t[bnd[1:]] - csum_t[bnd[:-1]]
    return theta0, tdur


def _step_cam_rotations(theta0: np.ndarray, tdur: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Per-step CAMERA-frame relative rotation from the (debiased) gyro: dR_cam_k = R_cb @ Exp(theta0_k -
    b*T_k) @ R_bc. Row 0 is identity (theta0[0]=0)."""
    theta = np.asarray(theta0, float) - np.asarray(tdur, float)[:, None] * np.asarray(bias, float)
    dR_body = _rotvec_to_matrix(theta)  # (N,3,3)
    return R_CB @ dR_body @ R_BC


def estimate_gyro_bias(
    theta0: np.ndarray, tdur: np.ndarray, dR_vo: np.ndarray, valid: np.ndarray
) -> tuple[np.ndarray, float, float]:
    """Jointly estimate the constant gyro bias by least-squares: minimise over b the per-step rotation
    disagreement Log( dR_cam(b)^T @ dR_vo ) on the VALID VO steps. Returns ``(bias (3,), median residual
    deg BEFORE debiasing, median residual deg AFTER)``. Reads VO only (firewall I3); no GT.
    """
    sel = np.asarray(valid, bool).copy()
    sel[0] = False  # step 0 is the origin, not a measured step
    t0 = np.asarray(theta0, float)[sel]
    td = np.asarray(tdur, float)[sel]
    dvo = np.asarray(dR_vo, float)[sel]

    def resid(b: np.ndarray) -> np.ndarray:
        dR_cam = _step_cam_rotations(t0, td, b)  # (Nv,3,3)
        m = np.einsum("nji,njk->nik", dR_cam, dvo)  # dR_cam^T @ dR_vo
        return _matrix_to_rotvec(m).ravel()

    def median_deg(b: np.ndarray) -> float:
        rv = resid(b).reshape(-1, 3)
        return float(np.degrees(np.median(np.linalg.norm(rv, axis=1))))

    before = median_deg(np.zeros(3))
    sol = least_squares(resid, x0=np.zeros(3), method="trf", xtol=1e-12, ftol=1e-12)
    bias = np.asarray(sol.x, float)
    return bias, before, median_deg(bias)


# --------------------------------------------------------------------------------------------------
# gravity leveling + the gyro-fused camera trajectory
# --------------------------------------------------------------------------------------------------
def gravity_down_body(
    imu_ts_ns: np.ndarray, accel: np.ndarray, image_ts_ns: np.ndarray, *, window_s: float = 2.0
) -> tuple[np.ndarray, float]:
    """Unit gravity (DOWN) direction in the IMU/body frame from the accelerometer over the first
    ``window_s`` of the keyframe span. The accelerometer reads specific force ~= -g (up) for a slow
    rover, so DOWN = -mean(accel)/|mean(accel)|. Returns ``(down_body (3,), |mean accel| m/s^2)`` -- the
    magnitude is reported as a gravity-observability sanity check (~9.8 on Etna)."""
    imu_ts = np.asarray(imu_ts_ns, np.int64)
    accel = np.asarray(accel, float)
    t0 = int(np.asarray(image_ts_ns, np.int64)[0] + round(CAM_IMU_TD_S * 1e9))
    sel = (imu_ts >= t0) & (imu_ts <= t0 + int(window_s * 1e9))
    if int(sel.sum()) < 3:
        sel = imu_ts <= imu_ts[min(800, imu_ts.shape[0] - 1)]
    mean_a = accel[sel].mean(axis=0)
    g = float(np.linalg.norm(mean_a))
    up = mean_a / g
    return -up, g


def _leveling_rotation(down_world: np.ndarray) -> tuple[np.ndarray, float]:
    """Build R_LW (world W = camera-0 / body-at-start -> gravity-leveled (right, down, forward) frame L)
    given gravity DOWN expressed in W. The camera's initial forward (R_bc[:,2] in W) projected horizontal
    fixes L's forward. Returns ``(R_LW (3,3), leveling tilt of the camera-0 frame in deg)``."""
    down = np.asarray(down_world, float)
    down = down / np.linalg.norm(down)
    fwd0 = R_BC[:, 2]  # camera-0 forward expressed in W (R_W_c0 = R_bc since R_W_b0 = I)
    fwd_h = fwd0 - np.dot(fwd0, down) * down
    nfh = np.linalg.norm(fwd_h)
    if nfh < 1e-6:  # forward nearly along gravity (not the case here) -> fall back to a world axis
        fwd_h = np.array([1.0, 0.0, 0.0]) - down[0] * down
        nfh = np.linalg.norm(fwd_h)
    forward = fwd_h / nfh
    right = np.cross(down, forward)
    right = right / np.linalg.norm(right)
    forward = np.cross(right, down)  # re-orthogonalise (right, down, forward), right-handed
    R_WL = np.column_stack([right, down, forward])  # L axes in W
    # tilt = angle between camera-0 nominal down (body z mapped to camera... use W down vs camera y)
    cam_down_w = R_BC[:, 1]  # camera-0 'down' (optical y) expressed in W
    tilt = float(np.degrees(np.arccos(np.clip(np.dot(cam_down_w, down), -1.0, 1.0))))
    return R_WL.T, tilt


def build_vio_leveled_trajectory(
    xyz_cam: np.ndarray,
    quat_wxyz: np.ndarray,
    valid: np.ndarray,
    imu_ts_ns: np.ndarray,
    gyro: np.ndarray,
    accel: np.ndarray,
    image_ts_ns: np.ndarray,
) -> VioBuild:
    """Gyro-aided VIO camera trajectory in a gravity-leveled (right, down, forward) frame.

    Steps: (1) reconstruct per-step VO translation + rotation from the frozen poses; (2) preintegrate the
    gyro per step (td + Tbc applied); (3) jointly estimate the constant gyro bias against the VO
    rotations; (4) chain the camera orientation from the DEBIASED gyro and the camera position from the
    VO metric translations rotated by that orientation; (5) gravity-level the whole trajectory. No GT
    (invariant I3).
    """
    xyz_cam = np.asarray(xyz_cam, float)
    valid = np.asarray(valid, bool)
    n = xyz_cam.shape[0]
    _R_wc, motion_prev, dR_vo = vo_relative_from_poses(xyz_cam, quat_wxyz)
    theta0, tdur = preintegrate_gyro_steps(imu_ts_ns, gyro, image_ts_ns)
    bias, resid_before, resid_after = estimate_gyro_bias(theta0, tdur, dR_vo, valid)

    # camera orientation chain in W (= camera-0 frame) from the debiased gyro
    dR_cam = _step_cam_rotations(theta0, tdur, bias)  # (N,3,3); row 0 = I
    R_W_c = np.empty((n, 3, 3))
    R_W_c[0] = np.eye(3)
    for k in range(1, n):
        R_W_c[k] = R_W_c[k - 1] @ dR_cam[k]

    # camera position chain in W: VO metric step rotated by the gyro-fused orientation
    p_W = np.zeros((n, 3))
    for k in range(1, n):
        step = motion_prev[k] if valid[k] else np.zeros(3)  # invalid VO step -> hold (no fabricated move)
        p_W[k] = p_W[k - 1] + R_W_c[k - 1] @ step

    down_body, g_norm = gravity_down_body(imu_ts_ns, accel, image_ts_ns)
    # gravity DOWN in W: W = camera-0 = body-at-start (R_W_b0 = I), and down is a body-frame vector
    down_world = down_body
    R_LW, tilt = _leveling_rotation(down_world)
    xyz_leveled = (R_LW @ p_W.T).T

    return VioBuild(
        xyz_leveled=xyz_leveled,
        gyro_bias_rad_s=bias,
        vo_gyro_resid_deg_before=resid_before,
        vo_gyro_resid_deg_after=resid_after,
        gravity_norm_m_s2=g_norm,
        leveling_tilt_deg=tilt,
        n_steps=n - 1,
        n_valid_vo_steps=int(valid.sum()),
        n_imu_samples=int(np.asarray(imu_ts_ns).shape[0]),
    )


# --------------------------------------------------------------------------------------------------
# freeze: VIO-ENU + VIO+DEM-anchored estimates (reuses estimate_and_freeze; no GT)
# --------------------------------------------------------------------------------------------------
def estimate_vio_and_freeze(
    xyz_cam: np.ndarray,
    quat_wxyz: np.ndarray,
    valid: np.ndarray,
    ts_ns: np.ndarray,
    imu_ts_ns: np.ndarray,
    gyro: np.ndarray,
    accel: np.ndarray,
    dem: Any,
    out_dir: str,
    *,
    sigma_vo_m: float = 0.05,
    sigma_dem_m: float = 2.0,
    sigma_prior_m: float = 0.5,
    anchor_every: int = 10,
    vio_enu_name: str = "vio_enu.tum",
    anchored_name: str = "vio_dem_anchored_enu.tum",
) -> dict[str, Any]:
    """Build + FREEZE the VIO-ENU and VIO+DEM-anchored estimates from the VO poses + IMU + DEM + the
    declared start ONLY (no GT; invariant I3). Reuses :func:`dart.s3li_capstone.estimate_and_freeze` for
    the registration + DEM anchoring (the gyro-leveled VIO trajectory is fed in place of the VO one).
    """
    build = build_vio_leveled_trajectory(
        xyz_cam, quat_wxyz, valid, imu_ts_ns, gyro, accel, np.asarray(ts_ns, np.int64)
    )
    est = estimate_and_freeze(
        build.xyz_leveled,
        np.asarray(ts_ns, np.int64),
        dem,
        out_dir,
        sigma_vo_m=sigma_vo_m,
        sigma_dem_m=sigma_dem_m,
        sigma_prior_m=sigma_prior_m,
        anchor_every=anchor_every,
        vo_enu_name=vio_enu_name,
        anchored_name=anchored_name,
    )
    est["xyz_leveled"] = build.xyz_leveled
    est["vio_build"] = {
        "gyro_bias_rad_s": [float(x) for x in build.gyro_bias_rad_s],
        "vo_gyro_resid_deg_before": build.vo_gyro_resid_deg_before,
        "vo_gyro_resid_deg_after": build.vo_gyro_resid_deg_after,
        "gravity_norm_m_s2": build.gravity_norm_m_s2,
        "leveling_tilt_deg": build.leveling_tilt_deg,
        "n_steps": build.n_steps,
        "n_valid_vo_steps": build.n_valid_vo_steps,
        "n_imu_samples": build.n_imu_samples,
        "cam_imu_td_s": CAM_IMU_TD_S,
        "imu_gyro_noise_rad_s_sqrthz": IMU_GYRO_NOISE,
    }
    # rename the capstone's generic keys so the VIO artifact is unambiguous
    est["vio_enu"] = est.pop("enu_vo")
    est["vio_anchored"] = est.pop("enu_anchored")
    est["vio_enu_tum"] = est.pop("vo_enu_tum")
    return est


def load_imu_cached(reader: Any, cache_path: str, *, t_end_ns: int | None = None) -> dict[str, np.ndarray]:
    """Stream the real S3LI IMU once into ``(ts_ns, gyro, accel)`` arrays, cached to ``cache_path`` (npz)
    so re-runs skip the 26 GB bag pass. ``t_end_ns`` early-stops the stream (used by the fast firewall
    test to read only the window it needs). No GT (invariant I3 -- :meth:`S3liReader.imu` carries no pose).
    """
    if t_end_ns is None and os.path.isfile(cache_path):
        d = np.load(cache_path)
        return {"ts_ns": d["ts_ns"], "gyro": d["gyro"], "accel": d["accel"]}
    ts: list[int] = []
    gy: list[np.ndarray] = []
    ac: list[np.ndarray] = []
    for tns, g, a in reader.imu():
        ts.append(int(tns))
        gy.append(g)
        ac.append(a)
        if t_end_ns is not None and tns > t_end_ns:
            break
    out = {
        "ts_ns": np.asarray(ts, np.int64),
        "gyro": np.asarray(gy, float),
        "accel": np.asarray(ac, float),
    }
    if t_end_ns is None:
        np.savez(cache_path, ts_ns=out["ts_ns"], gyro=out["gyro"], accel=out["accel"])
    return out
