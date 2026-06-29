"""SE(2) (heading-optimizing) loop-closure pose graph for the S3LI ``s3li_crater`` recipe -- the FIX
for the residual the position-only graph (dart.dem_height_graph) left open.

THE PROBLEM. A position-only pose graph optimises node POSITIONS with orientations held at their VO
values. On a single-loop traverse it can close the loop but cannot redistribute the accumulated HEADING
drift that BOWS the trajectory, so it bottoms out at ~50 m horizontal (half the endpoint drift). The
paper reaches 21 m because its full pose graph also corrects orientation.

THE FIX (validated: 50.5 m -> ~7.5 m horizontal on s3li_crater). Optimise ``(x, y, yaw)`` per node on
the SE(2) manifold (dart.pose_graph_se2.PoseGraphSE2), fusing:
  * VO odometry between-factors  -- the relative SE(2) motion in body frame (from the registered VO),
  * visual loop-closure between-factors -- the relative SE(2) (dx, dy, dyaw) from the SAME LightGlue+PnP
    closures (the ``dyaw`` recovered from the PnP relative rotation ``LoopClosure.r_ab``),
  * a single declared start prior.
Closing the loop now forces the heading chain to relax, which un-bends the crater traverse.

SCALE. PoseGraphSE2 uses dense numerical Jacobians (built for small graphs), so the SE(2) solve runs on
a DOWNSAMPLED KEYFRAME graph (every ``step`` nodes + the exact loop endpoints), then the correction is
lifted back to every node by a continuous SE(2) DEFORMATION (per-keyframe global correction transform,
interpolated along each segment and applied to the original VO pose). The lift matches the corrected
keyframes exactly and re-stitches the fine VO motion in between.

TRUTH FIREWALL (invariant I3). Every input is VO-derived (the registered ENU trajectory, per-node
headings from the frozen VO orientation, the loop closures' visual relative poses) or the declared
start; no function takes a ground-truth pose. GT is read only downstream at scoring.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public).
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from dart.loop_closure_visual import LoopClosure, quat_wxyz_to_rotmat
from dart.pose_graph_se2 import PoseGraphSE2


def _wrap(a: float) -> float:
    """Wrap an angle to (-pi, pi]."""
    return (float(a) + math.pi) % (2.0 * math.pi) - math.pi


def _wrap_arr(a: np.ndarray) -> np.ndarray:
    return (np.asarray(a, float) + math.pi) % (2.0 * math.pi) - math.pi


def _relative_se2(pi: np.ndarray, pj: np.ndarray) -> np.ndarray:
    """SE(2) relative pose of ``pj`` in ``pi``'s body frame: (dx, dy, dyaw). Poses are (x, y, yaw)."""
    c, s = math.cos(pi[2]), math.sin(pi[2])
    dxw, dyw = pj[0] - pi[0], pj[1] - pi[1]
    return np.array([c * dxw + s * dyw, -s * dxw + c * dyw, _wrap(pj[2] - pi[2])])


def node_headings_enu(quat_wxyz_cam: np.ndarray, r_m: np.ndarray) -> np.ndarray:
    """Per-node ENU heading (rad, CCW from East) of the rover's forward (camera +z) axis:
    ``yaw = atan2(N, E)`` of ``R_M @ R_wc[k] @ [0,0,1]``. VO-derived only (invariant I3)."""
    q = np.asarray(quat_wxyz_cam, float)
    r_m = np.asarray(r_m, float)
    out = np.empty(q.shape[0])
    fwd = np.array([0.0, 0.0, 1.0])
    for k in range(q.shape[0]):
        v = r_m @ (quat_wxyz_to_rotmat(q[k]) @ fwd)
        out[k] = math.atan2(v[1], v[0])
    return out


def loop_se2_measurement(
    lc: LoopClosure, quat_wxyz_cam: np.ndarray, enu_vo: np.ndarray, headings: np.ndarray,
    r_m: np.ndarray,
) -> tuple[int, int, np.ndarray]:
    """The SE(2) loop-closure measurement (a, b, (dx, dy, dyaw)) in keyframe a's body frame, from a
    verified visual closure: translation from ``lc.d_enu`` (already the measured ENU displacement
    p_b - p_a), heading change from the PnP relative rotation ``lc.r_ab`` (R_wc[b] = R_wc[a] R_ab^T).
    Firewall I3: VO orientation + the visual relative pose only; no GT."""
    a, b = lc.a_node, lc.b_node
    r_wc_b = quat_wxyz_to_rotmat(np.asarray(quat_wxyz_cam, float)[a]) @ np.asarray(lc.r_ab, float).T
    fwd_b = np.asarray(r_m, float) @ (r_wc_b @ np.array([0.0, 0.0, 1.0]))
    yaw_b = math.atan2(fwd_b[1], fwd_b[0])
    pose_a = np.array([enu_vo[a, 0], enu_vo[a, 1], headings[a]])
    pose_b = np.array([enu_vo[a, 0] + lc.d_enu[0], enu_vo[a, 1] + lc.d_enu[1], yaw_b])
    return a, b, _relative_se2(pose_a, pose_b)


def keyframe_indices(n_nodes: int, step: int, extra: list[int]) -> list[int]:
    """Sorted keyframe node indices: every ``step`` node + the endpoints + any ``extra`` (loop
    endpoints), so the loop closures connect EXACT keyframes."""
    s = set(range(0, n_nodes, max(1, int(step)))) | {0, n_nodes - 1} | {int(e) for e in extra}
    return sorted(i for i in s if 0 <= i < n_nodes)


@dataclass(frozen=True)
class Se2Result:
    """Frozen SE(2) loop-closure solve: ``xyz`` (N,3) the full-resolution corrected ENU trajectory (x,y
    from the SE(2) deformation, z from the VO), ``kf_idx`` the keyframe nodes, ``n_keyframes`` /
    ``n_loops`` the graph size, ``converged`` + ``final_cost`` the SE(2) solver diagnostics, and
    ``mean_abs_horizontal_correction_m`` how far the heading optimisation moved the trajectory."""

    xyz: np.ndarray
    kf_idx: np.ndarray
    n_keyframes: int
    n_loops: int
    converged: bool
    final_cost: float
    mean_abs_horizontal_correction_m: float


def solve_se2_keyframes(
    enu_vo: np.ndarray, headings: np.ndarray, kf_idx: list[int],
    loop_meas: list[tuple[int, int, np.ndarray]], *,
    sigma_odom_xy: float = 0.1, sigma_odom_yaw: float = 0.01,
    sigma_loop_xy: float = 0.5, sigma_loop_yaw: float = 0.05,
    prior_sigma_xy: float = 0.2, prior_sigma_yaw: float = 0.02, iters: int = 50,
    shadow_yaw: list[tuple[int, float, float]] | None = None,
) -> tuple[dict, dict]:
    """Build + solve the keyframe SE(2) pose graph (VO odometry between + loop closures + start prior).
    Returns ({node: (x, y, yaw)}, solver_status). ``iters`` caps the LM iterations (the Gauss-Newton
    runs ONCE -- pose + status from the same solve). ``shadow_yaw`` is an optional list of
    ``(node, measured_yaw_rad, sigma_rad)`` weak ABSOLUTE-heading factors (anti-solar shadow direction),
    which pin the heading globally between loop closures. Firewall I3: VO + loop + shadow measurements."""
    g = PoseGraphSE2(robust=True)
    p0 = np.array([enu_vo[kf_idx[0], 0], enu_vo[kf_idx[0], 1], headings[kf_idx[0]]])
    g.add_prior(kf_idx[0], p0, sigma_xy=prior_sigma_xy, sigma_yaw=prior_sigma_yaw)
    for i in range(len(kf_idx) - 1):
        a, b = kf_idx[i], kf_idx[i + 1]
        pa = np.array([enu_vo[a, 0], enu_vo[a, 1], headings[a]])
        pb = np.array([enu_vo[b, 0], enu_vo[b, 1], headings[b]])
        g.add_between(a, b, _relative_se2(pa, pb), sigma_xy=sigma_odom_xy, sigma_yaw=sigma_odom_yaw)
    kf_set = set(kf_idx)
    n_loops = 0
    for a, b, meas in loop_meas:
        if a in kf_set and b in kf_set:
            g.add_between(a, b, meas, sigma_xy=sigma_loop_xy, sigma_yaw=sigma_loop_yaw)
            n_loops += 1
    n_shadow = 0
    for node, myaw, sig in shadow_yaw or []:
        if node in kf_set:
            g.add_shadow_yaw(node, float(myaw), float(sig))
            n_shadow += 1
    order, X, _H = g._solve(iters=iters)                                # ONE solve (pose + status)
    pose = {nid: (float(X[k, 0]), float(X[k, 1]), float(X[k, 2])) for k, nid in enumerate(order)}
    return pose, {**g._status, "n_loops": n_loops, "n_shadow": n_shadow}


def lift_se2_to_full(enu_vo: np.ndarray, headings: np.ndarray, kf_idx: list[int], corr: dict) -> np.ndarray:
    """Lift the corrected KEYFRAME SE(2) poses to a full-resolution ENU trajectory by a continuous SE(2)
    deformation: at each keyframe k the global correction transform ``G_k`` satisfies
    ``P_corr[k] = G_k . P_orig[k]`` (rotate-then-translate); for an interior node it is interpolated
    (shortest-arc yaw, linear translation) between the bracketing keyframes and applied to the original
    VO pose. Matches the corrected keyframes exactly and re-stitches the fine VO motion. z is unchanged."""
    n = enu_vo.shape[0]
    kf = np.asarray(kf_idx, int)
    yaw_orig = headings[kf]
    yaw_corr = np.array([corr[int(k)][2] for k in kf])
    xy_corr = np.array([[corr[int(k)][0], corr[int(k)][1]] for k in kf])
    phi = _wrap_arr(yaw_corr - yaw_orig)                                  # per-keyframe yaw correction
    c0, s0 = np.cos(phi), np.sin(phi)
    p_orig = enu_vo[kf, :2]
    # g_k = p_corr - R(phi_k) @ p_orig_k
    rot_orig = np.column_stack([c0 * p_orig[:, 0] - s0 * p_orig[:, 1],
                                s0 * p_orig[:, 0] + c0 * p_orig[:, 1]])
    g_kf = xy_corr - rot_orig

    idx = np.arange(n)
    seg = np.clip(np.searchsorted(kf, idx, side="right") - 1, 0, len(kf) - 2)
    lo, hi = kf[seg], kf[seg + 1]
    t = (idx - lo) / np.maximum(hi - lo, 1)
    phi_n = phi[seg] + _wrap_arr(phi[seg + 1] - phi[seg]) * t            # shortest-arc yaw interp
    g_n = g_kf[seg] + (g_kf[seg + 1] - g_kf[seg]) * t[:, None]
    cn, sn = np.cos(phi_n), np.sin(phi_n)
    x, y = enu_vo[:, 0], enu_vo[:, 1]
    out_x = cn * x - sn * y + g_n[:, 0]
    out_y = sn * x + cn * y + g_n[:, 1]
    return np.column_stack([out_x, out_y, enu_vo[:, 2]])


def estimate_se2_loopclosure(
    enu_vo: np.ndarray, quat_wxyz_cam: np.ndarray, r_m: np.ndarray,
    accepted_closures: list[LoopClosure], *, step: int = 30, **solver_kw,
) -> Se2Result:
    """End-to-end: per-node headings -> keyframe SE(2) graph (VO odometry + the visual loop closures) ->
    solve -> deformation lift to a full-resolution corrected trajectory. Firewall I3: VO + loop
    measurements + declared start only."""
    enu_vo = np.asarray(enu_vo, float)
    n = enu_vo.shape[0]
    headings = node_headings_enu(quat_wxyz_cam, r_m)
    loop_meas = [loop_se2_measurement(lc, quat_wxyz_cam, enu_vo, headings, r_m)
                 for lc in accepted_closures if lc.accepted]
    extra = [a for a, _b, _m in loop_meas] + [b for _a, b, _m in loop_meas]
    kf_idx = keyframe_indices(n, step, extra)
    pose, status = solve_se2_keyframes(enu_vo, headings, kf_idx, loop_meas, **solver_kw)
    xyz = lift_se2_to_full(enu_vo, headings, kf_idx, pose)
    corr = float(np.mean(np.linalg.norm(xyz[:, :2] - enu_vo[:, :2], axis=1)))
    return Se2Result(
        xyz=xyz, kf_idx=np.asarray(kf_idx, int), n_keyframes=len(kf_idx),
        n_loops=int(status.get("n_loops", 0)), converged=bool(status.get("converged", False)),
        final_cost=float(status.get("final_cost", float("nan"))),
        mean_abs_horizontal_correction_m=corr,
    )
