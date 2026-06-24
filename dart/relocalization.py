"""[REQ:AS-09] Standstill relocalization (Navigation): accept/reject + covariance reduction (§25 Phase 7).

A commanded posture change (chassis lift dh) gives the camera a known vertical parallax baseline;
ranges to known shadow-tip / map landmarks then fix the rover (x,y) by trilateration from a
STANDSTILL, HEADING-FREE (dart.articulated_parallax). This module gates that fix and shows the
AS-09 acceptance: an ACCEPTED standstill NavFactor, fused into the standstill node, REDUCES the position
covariance (information addition); a REJECTED factor (parallax not camera-resolvable at range, or
mirror-ambiguous collinear landmarks, or a non-PD covariance) is NOT inserted -- the covariance is
unchanged.

For a standstill single node the posterior marginal is exactly the information sum of the prior and
the absolute fix: C_post = (C_prior^-1 + C_fix^-1)^-1 -- the same reduction add_absolute_cov applies
in dart.pose_graph_se2. Real geometry (articulated_parallax); no fabricated covariance.
"""
from __future__ import annotations

import numpy as np

from dart import articulated_parallax as ap


def _is_pd(cov: np.ndarray) -> bool:
    c = np.asarray(cov, float)
    return bool(c.shape == (2, 2) and np.all(np.isfinite(c)) and np.allclose(c, c.T)
                and float(np.min(np.linalg.eigvalsh(c))) > 0.0)


def standstill_fix(prior_xy, prior_cov, landmarks_xy, *, dh_m: float, fx_px: float,
                         sigma_px: float = 1.0, min_pixel_shift: float = 1.0) -> dict:
    """Gate the standstill parallax fix and fuse it into the prior.

    accepted iff: every landmark range is camera-resolvable at the commanded dh (parallax >=
    min_pixel_shift px), the landmarks are NOT collinear (no trilateration mirror ambiguity), and the
    derived fix covariance is finite + positive-definite. Returns the prior/posterior covariance, the
    fix covariance, whether it was accepted+inserted, and the covariance determinant reduction."""
    L = np.asarray(landmarks_xy, float)
    p = np.asarray(prior_xy, float)
    C_prior = np.asarray(prior_cov, float)
    ranges = [float(np.linalg.norm(li - p)) for li in L]
    r_max = ap.camera_resolvable_range_m(dh_m, fx_px, min_pixel_shift=min_pixel_shift)

    reasons = []
    if len(L) < 3:
        reasons.append("need >=3 landmarks to trilaterate (x,y)")
    if any(r > r_max for r in ranges):
        reasons.append(f"landmark beyond camera-resolvable range ({r_max:.2f} m) -> sub-pixel parallax")
    if ap._landmarks_are_collinear(L):
        reasons.append("collinear landmarks -> trilateration mirror ambiguity (H-14)")

    C_fix = None
    if not reasons:
        sig = [ap.range_sigma_from_pixel_noise(r, dh_m, fx_px, sigma_px) for r in ranges]
        C_fix = np.asarray(ap.position_fix_covariance(L, p, sig), float)
        if not _is_pd(C_fix):
            reasons.append("fix covariance not finite/positive-definite")

    accepted = not reasons
    if accepted and C_fix is not None:      # C_fix is set iff not reasons; the explicit check (not a bare
        C_post = np.linalg.inv(np.linalg.inv(C_prior) + np.linalg.inv(C_fix))   # assert: CT-06) narrows it
    else:                                                                       # for mypy + survives python -O
        C_post = C_prior                                                        # nothing inserted
    return {
        "accepted": accepted,
        "reasons": reasons,
        "cov_prior": C_prior,
        "cov_fix": C_fix,
        "cov_post": C_post,
        "det_prior": float(np.linalg.det(C_prior)),
        "det_post": float(np.linalg.det(C_post)),
        "resolvable_range_m": r_max,
    }


def insert_into_graph(graph, node_id: int, fix_xy, result: dict) -> bool:
    """Insert the standstill fix into a PoseGraphSE2 iff accepted (the contract: rejected -> not inserted).
    Returns True if a factor was added."""
    if not result["accepted"]:
        return False
    graph.add_absolute_cov(int(node_id), (float(fix_xy[0]), float(fix_xy[1])), result["cov_fix"])
    return True
