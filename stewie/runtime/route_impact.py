"""[REQ:FR-11] Route-impact justification for the observed-world-to-planner acceptance gate.

Given the baseline vs observed-hazard RS-02 ``EvidenceBundle`` pair, attribute the reroute/refusal to the
specific baseline-route LEG the observed hazard entered, and phrase it as human-readable release evidence
("route changed because observed hazard X entered leg Y"). Pure + deterministic + truth-free: it reads only
the two evidence bundles (planner outputs + costmap blocking reasons), never ground truth.
"""
from __future__ import annotations

import math


def _point_seg_dist(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from point ``p`` to segment ``a``->``b`` in (row, col) grid space."""
    (pr, pc), (ar, ac), (br, bc) = p, a, b
    dr, dc = br - ar, bc - ac
    seg2 = dr * dr + dc * dc
    if seg2 == 0.0:
        return math.hypot(pr - ar, pc - ac)
    t = max(0.0, min(1.0, ((pr - ar) * dr + (pc - ac) * dc) / seg2))
    return math.hypot(pr - (ar + t * dr), pc - (ac + t * dc))


def _nearest_leg(route: list[tuple[float, float]], rc: tuple[float, float]) -> int:
    """Index of the route leg (segment i->i+1) whose distance to ``rc`` is smallest."""
    if len(route) < 2:
        return 0
    dists = [_point_seg_dist(rc, route[i], route[i + 1]) for i in range(len(route) - 1)]
    return min(range(len(dists)), key=dists.__getitem__)


def justify_route_change(clear, hazard, hazard_rc: tuple[int, int]) -> dict:
    """Attribute the observed-hazard impact to a baseline-route leg and phrase the release evidence.

    ``clear`` / ``hazard`` are RS-02 EvidenceBundles (baseline vs observed-hazard run over the same DEM +
    route). Returns a typed verdict: whether the route changed / was refused / justified-unchanged, the
    entered leg index, the newly-introduced blocking reason (the named cause), and the operator sentence.
    """
    clear_route = [(c.goal_row, c.goal_col) for c in clear.commands]
    hazard_route = [(c.goal_row, c.goal_col) for c in hazard.commands]
    changed = hazard_route != clear_route
    refused = bool(hazard.refused)
    leg = _nearest_leg(clear_route, (float(hazard_rc[0]), float(hazard_rc[1])))
    new_reasons = sorted(set(hazard.costmap.blocking_reasons) - set(clear.costmap.blocking_reasons))
    cause = new_reasons[0] if new_reasons else "observed_hazard"
    rc = (int(hazard_rc[0]), int(hazard_rc[1]))
    if refused:
        verdict = f"route refused because {cause} at cell {rc} blocks leg {leg}"
    elif changed:
        verdict = f"route changed because {cause} at cell {rc} entered leg {leg}"
    else:
        verdict = f"route unchanged (justified): {cause} at cell {rc} near leg {leg} did not force a reroute"
    return {"changed": changed, "refused": refused, "leg_index": leg,
            "hazard_rc": rc, "blocking_reason": cause, "justification": verdict}
