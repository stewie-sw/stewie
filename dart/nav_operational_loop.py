"""FS-07: the Navigation operational loop -- the scattered nav seams wired into ONE auditable closed loop.

The seams exist separately: the planner-scheduled relocalization stop (lode.relocalization.
schedule_relocalization_stops), the articulation/parallax observation + pose-graph factor + residual
accept/reject gate + covariance update (dart.relocalization.standstill_fix over dart.articulated_parallax
+ dart.pose_graph_se2), and the operator evidence view. This module CONNECTS them into one run:

    planner-scheduled stop  ->  observation at the stop  ->  pose-graph factor + residual/accept-reject
    gate  ->  covariance REDUCE on accept / UNTOUCHED on reject  ->  the operator evidence trail

so a single call drives the whole loop and returns an auditable per-stop evidence view. Real geometry
(articulated_parallax); no fabricated covariance -- an accepted fix reduces the covariance by information
addition, a rejected fix (out of camera-resolvable range, collinear/mirror-ambiguous, or non-PD) leaves it
untouched and never enters the graph.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import numpy as np

from dart.pose_graph_se2 import PoseGraphSE2
from dart.relocalization import insert_into_graph, standstill_fix
from lode.relocalization import schedule_relocalization_stops


def run_nav_operational_loop(traverse_m, prior_xy, prior_cov, observe, *, dh_m: float, fx_px: float,
                             drift_tol_m: float = 0.5, sigma_px: float = 1.0,
                             sigma_xy: float = 2.0, sigma_yaw: float = 1.0) -> dict:
    """Drive the Navigation operational loop over one traverse.

    ``observe(stop_index, distance_m)`` returns the landmarks seen at that scheduled stop (the camera-rig /
    shadow-parallax observation). At each planner-scheduled relocalization stop the loop runs the standstill
    parallax fix (observation -> pose-graph factor -> residual/accept-reject gate), fuses an ACCEPTED fix
    into the pose graph (covariance REDUCED) or leaves the covariance UNTOUCHED on a reject, and appends the
    stop to the operator evidence trail. Returns the schedule, the per-stop evidence view, the accept/reject
    counts, the pose graph, and the final vs prior covariance determinant.
    """
    schedule = schedule_relocalization_stops(traverse_m, drift_tol_m=drift_tol_m)
    graph = PoseGraphSE2()
    graph.add_prior(0, (float(prior_xy[0]), float(prior_xy[1]), 0.0), sigma_xy, sigma_yaw)
    cov = np.asarray(prior_cov, dtype=float)
    prior_det = float(np.linalg.det(cov))
    evidence: list[dict] = []
    n_accept = n_reject = 0
    for i, dist in enumerate(schedule["fix_distances_m"]):
        landmarks = list(observe(i, dist))                       # the observation at this scheduled stop
        det_before = float(np.linalg.det(cov))
        result = standstill_fix(prior_xy, cov, landmarks, dh_m=dh_m, fx_px=fx_px, sigma_px=sigma_px)
        inserted = insert_into_graph(graph, 0, prior_xy, result)  # gate: accepted -> a factor is added
        if result["accepted"]:
            cov = np.asarray(result["cov_post"], dtype=float)     # covariance REDUCED (information addition)
            n_accept += 1
        else:
            n_reject += 1                                         # covariance UNTOUCHED
        det_after = float(np.linalg.det(cov))
        evidence.append({
            "stop": i,
            "distance_m": float(dist),
            "n_landmarks": len(landmarks),
            "accepted": bool(result["accepted"]),
            "reasons": list(result["reasons"]),
            "inserted": bool(inserted),
            "det_prior": det_before,
            "det_post": det_after,
            "cov_reduced": det_after < det_before - 1e-12,
        })
    return {
        "schedule": schedule,
        "n_stops": int(schedule["n_fixes"]),
        "n_accepted": n_accept,
        "n_rejected": n_reject,
        "evidence": evidence,                 # the operator evidence view of the whole connected run
        "graph": graph,
        "prior_det": prior_det,
        "final_cov": cov,
        "final_det": float(np.linalg.det(cov)),
    }
