"""NV-03: a local trajectory planner. From the rover's pose + heading it samples a fan of constant-
curvature arcs (the NAVLAB26 reference primitive), rejects any arc that clips a keep-out, a rock, or a
terrain cell the caller flags unsafe, and returns the feasible arc that makes the most progress toward
the goal. The terrain check is an INJECTED predicate ``is_blocked(x, y) -> bool`` so the planner stays
decoupled from any DEM/coordinate convention (the caller wires it to the real Haworth slope/hazard map);
keep-outs and rocks are pure geometry. NV-01 discipline holds: an all-blocked fan returns feasible=False,
never a forced unsafe straight line.
"""
from __future__ import annotations

import math

import numpy as np

from stewie.specs import ipex_specs as S

DEFAULT_OMEGA_MAX = 0.20      # [ASSUMPTION] rad/s max yaw rate (skid-steer); admits the full NV-03 fan at nominal v


def constant_curvature_arc(x0: float, y0: float, th0: float, kappa: float, length_m: float,
                           n_pts: int = 12) -> np.ndarray:
    """Sample ``n_pts`` poses along a constant-curvature arc of arc-length ``length_m`` from (x0, y0, th0).
    ``kappa`` is signed curvature [1/m] (0 = straight, +ve = left turn). Returns an (n_pts, 3) array of
    (x, y, theta). Exact unicycle integral; the straight case is the kappa->0 limit (no divide-by-zero)."""
    if n_pts < 2:
        raise ValueError("n_pts must be >= 2")
    if length_m < 0:
        raise ValueError("length_m must be >= 0")
    s = np.linspace(0.0, length_m, n_pts)
    th = th0 + kappa * s
    if abs(kappa) < 1e-9:                                    # straight-line limit
        x = x0 + s * math.cos(th0)
        y = y0 + s * math.sin(th0)
    else:
        x = x0 + (np.sin(th) - math.sin(th0)) / kappa        # ∫cos(th0+ks)ds
        y = y0 - (np.cos(th) - math.cos(th0)) / kappa        # ∫sin(th0+ks)ds
    return np.column_stack([x, y, th])


def curvature_fan(max_kappa: float = 0.33, n: int = 11) -> list:
    """A symmetric fan of ``n`` curvatures in [-max_kappa, max_kappa] including 0 (straight). max_kappa
    = 1/min_turn_radius (default 0.33 -> ~3 m minimum turn radius, a skid-steer rover turning near in place
    would use a larger value)."""
    if max_kappa <= 0 or n < 1:
        raise ValueError("max_kappa must be > 0 and n >= 1")
    half = max(1, n // 2)
    ks = [0.0]
    for i in range(1, half + 1):
        k = max_kappa * i / half
        ks += [k, -k]
    return sorted(set(ks))


def _arc_feasible(arc: np.ndarray, is_blocked, keepouts, rocks, clearance_m: float) -> bool:
    """An arc is feasible if NO sampled point is inside a keep-out (+clearance), within clearance of a
    rock, or flagged unsafe by the injected terrain predicate."""
    for x, y, _th in arc:
        fx, fy = float(x), float(y)
        if is_blocked is not None and is_blocked(fx, fy):
            return False
        for kx, ky, kr in keepouts:
            if math.hypot(fx - kx, fy - ky) <= kr + clearance_m:
                return False
        for r in rocks:
            rr = r[2] if len(r) > 2 else 0.0
            if math.hypot(fx - r[0], fy - r[1]) <= rr + clearance_m:
                return False
    return True


def plan_local(pose, heading_rad: float, goal, *, is_blocked=None, keepouts=(), rocks=(),
               clearance_m: float = 1.0, curvatures=None, horizon_m: float = 8.0, n_pts: int = 12) -> dict:
    """Sample a constant-curvature fan from (pose, heading) and return the feasible arc that best
    progresses toward ``goal``. Cost = distance from the arc endpoint to the goal + a small straightness
    penalty (prefer the straightest arc among equals). Returns a dict with ``feasible``; when feasible,
    the chosen ``arc`` ((n_pts,3) array), its ``curvature``, ``endpoint``, ``heading_end``, ``progress_m``
    (goal-distance reduction), and the fan counts. When EVERY arc is blocked, feasible=False with a reason
    and n_feasible=0 -- the caller replans/recovers; the planner never returns an unsafe arc."""
    x0, y0 = float(pose[0]), float(pose[1])
    gx, gy = float(goal[0]), float(goal[1])
    if curvatures is None:
        curvatures = curvature_fan()
    best = None                                              # (cost, arc, kappa, n_feasible bookkeeping)
    n_feasible = 0
    for k in curvatures:
        arc = constant_curvature_arc(x0, y0, heading_rad, k, horizon_m, n_pts)
        if not _arc_feasible(arc, is_blocked, keepouts, rocks, clearance_m):
            continue
        n_feasible += 1
        ex, ey = float(arc[-1, 0]), float(arc[-1, 1])
        cost = math.hypot(gx - ex, gy - ey) + 0.5 * abs(k) * horizon_m   # progress + straightness preference
        if best is None or cost < best[0]:
            best = (cost, arc, k)
    if best is None:
        return {"feasible": False, "reason": "all sampled arcs blocked (terrain / keep-out / rock)",
                "n_sampled": len(curvatures), "n_feasible": 0}
    _cost, arc, k = best
    return {"feasible": True, "arc": arc, "curvature": float(k),
            "endpoint": (float(arc[-1, 0]), float(arc[-1, 1])), "heading_end": float(arc[-1, 2]),
            "progress_m": math.hypot(gx - x0, gy - y0) - math.hypot(gx - arc[-1, 0], gy - arc[-1, 1]),
            "n_sampled": len(curvatures), "n_feasible": n_feasible}


# --- NV-04: path tracker -- convert a trajectory into bounded commands + expected speed/progress ----
def bounded_twist(curvature: float, *, v_max: float = S.DRIVE_SPEED_MS,
                  omega_max: float = DEFAULT_OMEGA_MAX) -> tuple:
    """Bound a constant-curvature command so neither the linear (v_max) nor the angular (omega_max) cap is
    exceeded. For a unicycle omega = curvature*v, so v = min(v_max, omega_max/|curvature|) and omega =
    curvature*v. A gentle arc is linear-capped; a sharp arc is yaw-rate-capped (slows to keep omega bounded).
    Returns (v, omega)."""
    if v_max <= 0 or omega_max <= 0:
        raise ValueError("v_max and omega_max must be > 0")
    k = abs(curvature)
    v = v_max if k < 1e-9 else min(v_max, omega_max / k)
    return v, curvature * v


def track_arc(curvature: float, length_m: float, *, v_max: float = S.DRIVE_SPEED_MS,
              omega_max: float = DEFAULT_OMEGA_MAX, speed_scale: float = 1.0) -> dict:
    """Convert a constant-curvature arc into a bounded twist command + expected speed/progress. ``speed_scale``
    in (0, 1] derates the ground speed for slope/slip -- the caller passes ``(1 - slip)`` from the planner's
    slip ladder (1.0 = nominal flat; NO slip is fabricated here). Returns the command (``v_cmd``, ``omega_cmd``),
    the derated ``expected_speed_ms``, the ``duration_s`` to traverse, and ``arc_length_m`` (progress along the
    path)."""
    if length_m < 0 or not (0.0 < speed_scale <= 1.0):
        raise ValueError("length_m must be >= 0 and 0 < speed_scale <= 1")
    v, omega = bounded_twist(curvature, v_max=v_max, omega_max=omega_max)
    v_eff = v * speed_scale
    dur = length_m / v_eff if v_eff > 1e-9 else math.inf
    return {"v_cmd": v, "omega_cmd": omega, "expected_speed_ms": v_eff, "duration_s": dur,
            "arc_length_m": float(length_m), "curvature": float(curvature)}


def track_plan(plan: dict, *, v_max: float = S.DRIVE_SPEED_MS, omega_max: float = DEFAULT_OMEGA_MAX,
               speed_scale: float = 1.0) -> dict:
    """Track an NV-03 ``plan_local`` result: take the chosen arc's curvature + measured polyline length and
    return the bounded twist command + expected speed/progress (``track_arc``), passing the plan's
    goal-``progress_m`` through. Raises on an infeasible plan -- there is nothing safe to track (NV-01)."""
    if not plan.get("feasible"):
        raise ValueError("cannot track an infeasible plan (no safe arc was found)")
    arc = plan["arc"]
    length = float(np.sum(np.hypot(np.diff(arc[:, 0]), np.diff(arc[:, 1]))))   # measured polyline arc length
    out = track_arc(float(plan["curvature"]), length, v_max=v_max, omega_max=omega_max, speed_scale=speed_scale)
    out["progress_m"] = plan.get("progress_m")
    return out
