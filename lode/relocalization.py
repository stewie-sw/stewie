"""SN-10 tie-in B (#96): schedule articulation-parallax relocalization stops along a traverse.

A dead-reckoned skid-steer pose drifts ~drift_frac per metre driven (lode.autonomy.ODOM_DRIFT_FRAC =
0.05/m; "an independent pose fix corrects it"). The SN-10 articulation-parallax fix is a STANDSTILL
maneuver -- a known pose-change baseline yields a heading-free position fix -- that resets the
accumulated drift to its small residual. This schedules those fixes the way the planner schedules its
battery-aware recharge stops: walk the traverse and insert a fix whenever the predicted cumulative drift
since the last fix would exceed the tolerance, so along-track drift never crosses it. Each fix is costed
in time + energy.

PURE + deterministic, and PARAMETRIC: the drift rate and the per-fix cost are passed in (defaults mirror
their grounded sources -- autonomy.ODOM_DRIFT_FRAC, and the ARGUS fix cost = the ~8 s articulation
maneuver + dart.rassor_mass_model.arm_raise_lift_energy_j). Kept parametric (not imported) so the planner
can call this without the autonomy->mission_planner import cycle.
"""
from __future__ import annotations

import math

DEFAULT_DRIFT_FRAC = 0.05       # mirrors lode.autonomy.ODOM_DRIFT_FRAC (along-track DR drift per metre)
DEFAULT_FIX_MANEUVER_S = 8.0    # mirrors dart.comparison.operational_cost argus_maneuver_s [ASSUMPTION]


def schedule_relocalization_stops(traverse_m: float, *, drift_tol_m: float = 0.5,
                                  drift_frac: float = DEFAULT_DRIFT_FRAC, fix_residual_m: float = 0.0,
                                  fix_maneuver_s: float = DEFAULT_FIX_MANEUVER_S,
                                  per_fix_energy_j: float = 0.0) -> dict:
    """Insert a relocalization fix every ``(drift_tol_m - fix_residual_m) / drift_frac`` metres so the
    predicted along-track drift never exceeds ``drift_tol_m``. Returns the fix schedule (count, the
    along-traverse distances), the run length between fixes, the time + energy the fixes cost, and the
    worst-case (bounded) drift. ``fix_residual_m`` is the post-fix residual the parallax fix cannot remove
    (0 = an ideal fix; the dissertation's heading-free fix is ~0 m). Deterministic."""
    if traverse_m < 0:
        raise ValueError(f"traverse_m must be >= 0 (got {traverse_m})")
    if drift_frac <= 0:
        raise ValueError(f"drift_frac must be > 0 (got {drift_frac})")
    if drift_tol_m <= fix_residual_m:
        raise ValueError(f"drift_tol_m ({drift_tol_m}) must exceed the post-fix residual "
                         f"({fix_residual_m}); otherwise a fix can never bring drift under tolerance")
    max_run_m = (drift_tol_m - fix_residual_m) / drift_frac      # distance for drift to grow residual -> tol
    n_fixes = max(0, int(math.floor((traverse_m - 1e-9) / max_run_m)))   # fixes STRICTLY within the traverse
    fix_distances = [round((i + 1) * max_run_m, 3) for i in range(n_fixes)]
    if n_fixes >= 1:
        max_drift = fix_residual_m + drift_frac * max_run_m      # a full inter-fix run peaks at the tolerance
    else:
        max_drift = fix_residual_m + drift_frac * traverse_m     # no fix: drift just accrues over the traverse
    return {
        "n_fixes": n_fixes,
        "fix_distances_m": fix_distances,
        "max_run_m": round(max_run_m, 3),
        "total_time_s": round(n_fixes * fix_maneuver_s, 1),
        "total_energy_J": round(n_fixes * per_fix_energy_j, 1),
        "per_fix_energy_J": round(per_fix_energy_j, 2),
        "max_drift_m": round(max_drift, 4),
    }
