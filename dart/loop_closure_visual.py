"""Visual loop closure for the S3LI ``s3li_crater`` stereo-VO traverse -- the SLAM leg that supplies the
HORIZONTAL drift correction the DEM height factor cannot (per arXiv:2603.17229, the DEM weakly
constrains horizontal; loop closure supplies it).

A loop closure is the constraint that the rover has RETURNED to a previously-mapped place. Here it is
formed PURELY from appearance + geometry, never from ground-truth proximity (truth firewall I3):

  1. PLACE RECOGNITION (appearance). Each keyframe carries a global appearance descriptor = the L2-mean
     of its SuperPoint local descriptors. A revisit candidate (a, b) is a TEMPORALLY-distant pair
     (node index gap >= ``min_index_gap``) whose global descriptors are similar -- the closest earlier
     keyframe per query, gated by a similarity floor. This is the candidate generator; it reads only
     image-derived descriptors and the (de-oracled) node index, never a position or GT.

  2. GEOMETRIC VERIFICATION. For each candidate the earlier keyframe's left SuperPoint features are
     LightGlue-matched to the later keyframe's; matches that carry a triangulated 3-D point (from the
     earlier keyframe's stereo cloud) feed a PnP-RANSAC solve for the relative camera pose. A candidate
     is ACCEPTED only with enough PnP inliers and a physically-plausible relative translation -- an
     appearance alias at a different place fails the inlier / translation gate.

  3. POSE-GRAPH FACTOR. The accepted relative camera motion ``C_{b in a} = -R^T t`` (the position of
     camera b's optical centre in camera a's frame) is rotated into the DEM ENU frame using the VO's own
     per-keyframe orientation ``R_wc[a]`` and the registration rotation ``R_M`` -- giving a between-factor
     ``p_b - p_a = R_M R_wc[a] C_{b in a}`` that the position pose graph (dart.dem_height_graph) fuses
     alongside the VO odometry and the DEM height-normal anchors, in ONE joint solve.

TRUTH FIREWALL (invariant I3). Every input here is image-derived (SuperPoint descriptors, LightGlue
matches, stereo-triangulated points) or VO-derived (orientations, the registration yaw); no function
takes a ground-truth pose. Candidates are proposed by APPEARANCE + node index, never by GT proximity;
the relative pose is solved by PnP on real features. GT is read only downstream, at scoring, after the
estimate is frozen.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor
from dart.stereo_vo import StereoVOConfig, _solve_pnp

log = logging.getLogger("dart.loop_closure")

# The closed vocabulary of geometric-gate rejections verify_candidate can emit ([REQ:PM-07] audit:
# every rejected closure carries exactly one of these, so an audit trail is machine-checkable).
REJECT_REASONS = ("too_few_matches", "too_few_3d_correspondences", "pnp_failed",
                  "translation_too_large")


def quat_wxyz_to_rotmat(q: np.ndarray) -> np.ndarray:
    """Unit Hamilton quaternion ``(w, x, y, z)`` -> 3x3 rotation matrix (the inverse of
    :func:`dart.s3li_capstone.rotmat_to_quat_wxyz`)."""
    q = np.asarray(q, float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


def registration_rotation(yaw_rad: float) -> np.ndarray:
    """The fixed VO-world -> DEM-ENU rotation ``R_M`` implied by :func:`dart.s3li_capstone.
    register_cam_to_enu` for heading ``yaw_rad``: for a camera-optical-frame point ``(x_r, y_d, z_f)``
    it yields ``E = c z_f + s x_r``, ``N = s z_f - c x_r``, ``U = -y_d`` (``c=cos``, ``s=sin``). So
    ``p_enu = R_M @ p_cam0frame + [0, 0, z0]``; the columns are orthonormal (a proper rotation)."""
    c, s = float(np.cos(yaw_rad)), float(np.sin(yaw_rad))
    return np.array([[s, 0.0, c], [-c, 0.0, s], [0.0, -1.0, 0.0]], float)


def global_descriptor(descriptors: np.ndarray) -> np.ndarray:
    """A single global appearance descriptor for an image: the L2-normalised mean of its L2-normalised
    SuperPoint local descriptors (a VLAD-lite bag-of-features vector). Image-derived only (I3)."""
    d = np.asarray(descriptors, float)
    if d.ndim != 2 or d.shape[0] == 0:
        raise ValueError(f"descriptors must be (N, D) with N>0; got {d.shape}")
    norms = np.linalg.norm(d, axis=1, keepdims=True)
    dn = d / np.maximum(norms, 1e-12)
    g = dn.mean(axis=0)
    return g / max(float(np.linalg.norm(g)), 1e-12)


@dataclass(frozen=True)
class LoopKeyframe:
    """One keyframe's loop-closure features (firewall-clean; image-derived only).

    ``node`` is the VO node index; ``keypoints`` (N,2) + ``descriptors`` (N,D) + ``image_size`` (2,
    [w, h]) are the left SuperPoint extraction (for LightGlue); ``points_3d`` (M,3) are the stereo-
    triangulated points in the LEFT camera optical frame; ``point_kpt_idx`` (M,) is the index into
    ``keypoints`` of each 3-D point (so a LightGlue match to a left keypoint re-identifies its 3-D
    point); ``global_desc`` (D,) is the appearance descriptor used for revisit proposal."""

    node: int
    keypoints: np.ndarray
    descriptors: np.ndarray
    image_size: np.ndarray
    points_3d: np.ndarray
    point_kpt_idx: np.ndarray
    global_desc: np.ndarray

    def feat_to_point(self) -> np.ndarray:
        """(N,) map from a left-keypoint index to its row in ``points_3d`` (or -1 if not triangulated)."""
        m = np.full(int(self.keypoints.shape[0]), -1, dtype=np.int64)
        if self.point_kpt_idx.shape[0]:
            m[self.point_kpt_idx] = np.arange(self.point_kpt_idx.shape[0], dtype=np.int64)
        return m


@dataclass(frozen=True)
class LoopClosure:
    """A verified (or rejected) visual loop closure between keyframe ``a`` (earlier) and ``b`` (later).

    ``d_enu`` (3,) is the measured ENU displacement ``p_b - p_a`` (the between-factor value);
    ``c_in_a`` (3,) the relative camera motion in camera-a's frame; ``r_ab`` (3,3) the PnP relative
    rotation ``R_{cam_b<-cam_a}`` (identity for a rejected closure) -- the rotation the position-only
    graph discarded and the SE(3) graph needs (the relative-rotation measurement in a's frame is its
    transpose, ``R_a^T R_b``); ``n_inliers`` / ``n_matches`` the PnP-inlier and LightGlue-match counts;
    ``similarity`` the appearance cosine; ``trans_m`` the relative-translation magnitude; ``accepted`` +
    ``reject_reason`` the geometric-gate decision."""

    a_node: int
    b_node: int
    d_enu: np.ndarray
    c_in_a: np.ndarray
    n_inliers: int
    n_matches: int
    similarity: float
    trans_m: float
    accepted: bool
    reject_reason: str
    r_ab: np.ndarray = field(default_factory=lambda: np.eye(3))

    def to_json(self) -> dict[str, object]:
        return {
            "a_node": int(self.a_node), "b_node": int(self.b_node),
            "d_enu_m": [float(x) for x in self.d_enu],
            "c_in_a_m": [float(x) for x in self.c_in_a],
            "r_ab": np.asarray(self.r_ab, float).tolist(),
            "trans_m": float(self.trans_m), "n_inliers": int(self.n_inliers),
            "n_matches": int(self.n_matches), "similarity": float(self.similarity),
            "accepted": bool(self.accepted), "reject_reason": self.reject_reason,
        }


def propose_candidates(
    keyframes: list[LoopKeyframe], *, min_index_gap: int, sim_min: float, max_candidates: int,
    per_query_topk: int = 8,
) -> list[tuple[int, int, float]]:
    """Propose revisit candidates by APPEARANCE + node index only (no GT, no position; I3).

    For each query keyframe (local index ``jb``) take its ``per_query_topk`` most appearance-similar
    earlier keyframes ``ja`` with ``node[jb] - node[ja] >= min_index_gap`` and cosine similarity
    >= ``sim_min``. (Top-K, not top-1: the Mt-Etna terrain is self-similar, so a true revisit is often
    out-ranked by an appearance ALIAS at the same query -- a generous candidate set is proposed and the
    geometric PnP verification, not appearance, is the real acceptance gate.) Returns the globally
    top-``max_candidates`` ``(ja, jb, similarity)`` triples (local indices), highest similarity first."""
    f = len(keyframes)
    if f < 2:
        return []
    nodes = np.array([kf.node for kf in keyframes], dtype=np.int64)
    g = np.stack([kf.global_desc for kf in keyframes], axis=0)            # (F, D), unit rows
    sim = g @ g.T                                                        # (F, F) cosine similarity
    out: list[tuple[int, int, float]] = []
    for jb in range(f):
        earlier = np.nonzero(nodes[jb] - nodes >= int(min_index_gap))[0]  # ja with a sufficient gap
        if earlier.size == 0:
            continue
        s = sim[jb, earlier]
        order = np.argsort(s)[::-1][: int(per_query_topk)]               # this query's K best earlier
        for o in order:
            c = float(s[o])
            if c >= sim_min:
                out.append((int(earlier[int(o)]), jb, c))
    out.sort(key=lambda t: t[2], reverse=True)
    return out[: int(max_candidates)]


def _feats_dict(kf: LoopKeyframe, device: Any) -> dict:
    """Rebuild the LightGlue input dict (keypoints + descriptors + image_size) from a cached keyframe."""
    import torch
    return {
        "keypoints": torch.from_numpy(np.ascontiguousarray(kf.keypoints, np.float32))[None].to(device),
        "descriptors": torch.from_numpy(np.ascontiguousarray(kf.descriptors, np.float32))[None].to(device),
        "image_size": torch.from_numpy(np.ascontiguousarray(kf.image_size, np.float32))[None].to(device),
    }


def verify_candidate(
    kf_a: LoopKeyframe, kf_b: LoopKeyframe, similarity: float, K: np.ndarray, cfg: StereoVOConfig,
    r_wc_a: np.ndarray, r_m: np.ndarray, *, min_inliers: int, max_translation_m: float,
) -> LoopClosure:
    """Geometrically verify a revisit candidate: LightGlue-match a's left features to b's, PnP-solve the
    relative camera pose from a's 3-D points to b's 2-D keypoints, and (if accepted) form the ENU
    between-factor displacement. Firewall I3: images + VO orientation only; no GT."""
    from dart.superpoint_vo import _load_frontend, _match
    _load_frontend()                                       # ensure the SuperPoint+LightGlue nets exist
    import torch
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    matches = _match(_feats_dict(kf_a, dev), _feats_dict(kf_b, dev))
    n_matches = int(matches.shape[0])
    zero3 = np.zeros(3)
    if n_matches < min_inliers:
        return LoopClosure(kf_a.node, kf_b.node, zero3, zero3, 0, n_matches, similarity, 0.0,
                           False, "too_few_matches")
    f2p = kf_a.feat_to_point()
    a_rows = f2p[matches[:, 0]]
    has_pt = a_rows >= 0
    obj = kf_a.points_3d[a_rows[has_pt]]
    img = kf_b.keypoints[matches[has_pt, 1]]
    if obj.shape[0] < min_inliers:
        return LoopClosure(kf_a.node, kf_b.node, zero3, zero3, 0, n_matches, similarity, 0.0,
                           False, "too_few_3d_correspondences")
    r_rel, t_rel, n_inl = _solve_pnp(obj, img, K, cfg)
    if r_rel is None or t_rel is None or n_inl < min_inliers:
        return LoopClosure(kf_a.node, kf_b.node, zero3, zero3, int(n_inl), n_matches, similarity, 0.0,
                           False, "pnp_failed")
    c_in_a = -r_rel.T @ t_rel                              # camera-b optical centre in camera-a frame
    trans = float(np.linalg.norm(c_in_a))
    if trans > max_translation_m:
        return LoopClosure(kf_a.node, kf_b.node, zero3, c_in_a, int(n_inl), n_matches, similarity,
                           trans, False, "translation_too_large")
    d_enu = r_m @ (r_wc_a @ c_in_a)                        # ENU displacement p_b - p_a (I3: VO frames)
    return LoopClosure(kf_a.node, kf_b.node, d_enu, c_in_a, int(n_inl), n_matches, similarity, trans,
                       True, "ok", r_ab=np.asarray(r_rel, float))


def audit_closures(attempts: list[LoopClosure]) -> dict[str, object]:
    """Audit-log a closure attempt set on the standard logging path ([REQ:PM-07]): every REJECTED
    candidate gets its own WARNING line (both node ids + the geometric-gate reject reason, so a false
    closure's rejection is on the record), acceptances get one INFO line each, and an INFO summary
    reconciles the disposition. Returns the reconciliation ``{n_attempts, n_accepted, n_rejected,
    reject_reasons}`` (per-reason histogram) -- accepted + rejected == attempts by construction."""
    reject_reasons: dict[str, int] = {}
    n_accepted = 0
    for lc in attempts:
        if lc.accepted:
            n_accepted += 1
            log.info("loop closure ACCEPTED %d->%d: inliers=%d/%d matches, sim=%.3f, |t|=%.2f m",
                     lc.a_node, lc.b_node, lc.n_inliers, lc.n_matches, lc.similarity, lc.trans_m)
        else:
            reject_reasons[lc.reject_reason] = reject_reasons.get(lc.reject_reason, 0) + 1
            log.warning("loop closure REJECTED %d->%d: %s (inliers=%d/%d matches, sim=%.3f)",
                        lc.a_node, lc.b_node, lc.reject_reason, lc.n_inliers, lc.n_matches,
                        lc.similarity)
    n_rejected = len(attempts) - n_accepted
    log.info("loop closure audit: %d attempts -> %d accepted, %d rejected %s",
             len(attempts), n_accepted, n_rejected, reject_reasons)
    return {"n_attempts": len(attempts), "n_accepted": n_accepted, "n_rejected": n_rejected,
            "reject_reasons": reject_reasons}


def detect_loops(
    keyframes: list[LoopKeyframe], quat_wxyz_cam: np.ndarray, yaw_rad: float, cfg: StereoVOConfig,
    *, min_index_gap: int = 1500, sim_min: float = 0.80, min_inliers: int = 15,
    max_translation_m: float = 25.0, max_candidates: int = 4000, per_query_topk: int = 8,
) -> dict:
    """Run the full place-recognition + geometric-verification loop-closure pipeline over a keyframe
    set. Returns the accepted + all attempted closures and the candidate count. Firewall I3: appearance
    + VO orientation + PnP only; the per-keyframe orientation ``R_wc`` comes from the frozen VO quats and
    ``R_M`` from the (firewall-clean) registration yaw -- never from GT."""
    import cv2
    cv2.setRNGSeed(0)                                      # deterministic PnP-RANSAC (reproducible set)
    try:
        import torch
        torch.manual_seed(0)
    except Exception:
        pass
    r_m = registration_rotation(yaw_rad)
    K = cfg.matrix()
    cands = propose_candidates(keyframes, min_index_gap=min_index_gap, sim_min=sim_min,
                               max_candidates=max_candidates, per_query_topk=per_query_topk)
    attempts: list[LoopClosure] = []
    accepted: list[LoopClosure] = []
    for ja, jb, sim in cands:
        kf_a, kf_b = keyframes[ja], keyframes[jb]
        r_wc_a = quat_wxyz_to_rotmat(np.asarray(quat_wxyz_cam, float)[kf_a.node])
        lc = verify_candidate(kf_a, kf_b, sim, K, cfg, r_wc_a, r_m,
                              min_inliers=min_inliers, max_translation_m=max_translation_m)
        attempts.append(lc)
        if lc.accepted:
            accepted.append(lc)
    audit = audit_closures(attempts)                       # [REQ:PM-07] rejections hit the audit log
    return {"accepted": accepted, "attempts": attempts, "n_candidates": len(cands), "audit": audit,
            "min_index_gap": int(min_index_gap), "sim_min": float(sim_min),
            "min_inliers": int(min_inliers), "max_translation_m": float(max_translation_m)}


def build_loop_factors(closures: list[LoopClosure], sigma_m: float) -> list[MeasurementFactor]:
    """One LOOP_CLOSURE between-factor per accepted closure: keyframe ``a`` carries the measured ENU
    displacement to keyframe ``b`` (metadata ``to``), isotropic sigma ``sigma_m``. Consumed by the
    pose-graph solver's between-factor path (dart.dem_height_graph)."""
    cov = np.eye(3) * float(sigma_m) ** 2
    out: list[MeasurementFactor] = []
    for lc in closures:
        if not lc.accepted:
            continue
        out.append(MeasurementFactor(
            factor_type=FactorType.LOOP_CLOSURE, keyframe=int(lc.a_node),
            value=np.asarray(lc.d_enu, float), covariance=cov, frame=Frame.WORLD,
            source="superpoint_lightglue_loop_closure", evidence_class=EvidenceClass.COMPUTED,
            metadata={"to": int(lc.b_node), "n_inliers": int(lc.n_inliers),
                      "similarity": float(lc.similarity)}))
    return out


# ----------------------------------------------------------------------------------------------------
# loop-closure feature cache (one streaming bag pass; image-derived only -- invariant I3)
# ----------------------------------------------------------------------------------------------------
def build_loop_feature_cache(stride: int, every: int, out_path: str, *, depth_min_m: float = 0.5,
                             depth_max_m: float = 30.0) -> str:
    """Stream the REAL S3LI stereo once (same ``stride`` as the frozen VO, so the k-th pair == VO node k)
    and, at every ``every``-th node, extract left+right SuperPoint, triangulate the stereo cloud, and
    cache the left keypoints + descriptors + global descriptor + the triangulated points to ``out_path``
    (CSR-packed). No GT (invariant I3 -- :meth:`stereo_pairs` carries no pose). Returns ``out_path``."""
    import time

    from dart.s3li_reader import S3liReader
    from dart.superpoint_vo import triangulate_stereo_superpoint

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    h_px, w_px = reader.image_size
    image_size = np.array([float(w_px), float(h_px)], float)            # LightGlue wants [width, height]
    nodes: list[int] = []
    kp_chunks: list[np.ndarray] = []
    desc_chunks: list[np.ndarray] = []
    pt_chunks: list[np.ndarray] = []
    pidx_chunks: list[np.ndarray] = []
    gdesc: list[np.ndarray] = []
    kp_off = [0]
    pt_off = [0]
    t0 = time.time()
    k = 0
    for _ts, left, right in reader.stereo_pairs(stride=stride):
        if k % every == 0:
            cloud, feats, kpts = triangulate_stereo_superpoint(left, right, cfg)
            feats_d: Any = feats
            desc = feats_d["descriptors"][0].detach().cpu().numpy().astype(np.float32)
            pts = cloud.points_3d.astype(np.float32)
            pkt = cloud.left_feat_idx.astype(np.int64)
            if pts.shape[0]:
                z = pts[:, 2]
                keep = (z >= depth_min_m) & (z <= depth_max_m)
                pts, pkt = pts[keep], pkt[keep]
            nodes.append(k)
            kp_chunks.append(kpts.astype(np.float32))
            desc_chunks.append(desc)
            pt_chunks.append(pts)
            pidx_chunks.append(pkt)
            gdesc.append(global_descriptor(desc))
            kp_off.append(kp_off[-1] + int(kpts.shape[0]))
            pt_off.append(pt_off[-1] + int(pts.shape[0]))
        k += 1
    dt = time.time() - t0
    np.savez(
        out_path,
        node=np.asarray(nodes, np.int64),
        keypoints=np.concatenate(kp_chunks, axis=0) if kp_chunks else np.empty((0, 2), np.float32),
        descriptors=np.concatenate(desc_chunks, axis=0) if desc_chunks else np.empty((0, 256), np.float32),
        kp_offsets=np.asarray(kp_off, np.int64),
        points_3d=np.concatenate(pt_chunks, axis=0) if pt_chunks else np.empty((0, 3), np.float32),
        point_kpt_idx=np.concatenate(pidx_chunks, axis=0) if pidx_chunks else np.empty(0, np.int64),
        pt_offsets=np.asarray(pt_off, np.int64),
        global_desc=np.stack(gdesc, axis=0) if gdesc else np.empty((0, 256), np.float32),
        image_size=image_size, every=np.int64(every), stride=np.int64(stride), n_streamed=np.int64(k),
    )
    print(f"[loop] feature cache: {len(nodes)} keyframes (every {every}) in {dt:.1f}s -> {out_path}",
          flush=True)
    return out_path


def load_loop_feature_cache(path: str) -> list[LoopKeyframe]:
    """Reconstruct the ``list[LoopKeyframe]`` from a :func:`build_loop_feature_cache` npz (CSR-unpacked)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"loop feature cache not found: {path}")
    d = np.load(path)
    node = d["node"].astype(np.int64)
    kp = d["keypoints"].astype(np.float32)
    desc = d["descriptors"].astype(np.float32)
    kpo = d["kp_offsets"].astype(np.int64)
    pts = d["points_3d"].astype(np.float32)
    pkt = d["point_kpt_idx"].astype(np.int64)
    pto = d["pt_offsets"].astype(np.int64)
    g = d["global_desc"].astype(np.float32)
    image_size = d["image_size"].astype(np.float32)
    out: list[LoopKeyframe] = []
    for i in range(node.shape[0]):
        out.append(LoopKeyframe(
            node=int(node[i]), keypoints=kp[kpo[i]:kpo[i + 1]], descriptors=desc[kpo[i]:kpo[i + 1]],
            image_size=image_size, points_3d=pts[pto[i]:pto[i + 1]],
            point_kpt_idx=pkt[pto[i]:pto[i + 1]], global_desc=g[i]))
    return out
