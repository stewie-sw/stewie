"""NV-06/07: backup-recovery decisions. NV-06 fires recovery when commanded motion stops producing
progress (achieved/commanded distance below a threshold, sustained for a minimum stall time) or the
planner failed -- the NAVLAB26 reference is <25% progress for 2-3 s, kept configurable. NV-07 then
distinguishes a genuine BLOCKAGE (collision/obstacle -> reverse) from an EXPECTED slope/slip slowdown
(-> keep pushing; reversing would be a false maneuver): if the low progress is explained by the slip
predicted for the current slope, it is not a blockage. Pure decision logic; the slip prediction is
INJECTED (the caller passes the expected progress ratio = 1 - slip from the slip ladder), so this stays
decoupled and testable.
"""
from __future__ import annotations

RECOVERY_PROGRESS_THRESH = 0.25   # NAVLAB26 reference: progress < 25% of commanded ...
RECOVERY_MIN_STALL_S = 2.0        # ... sustained >= ~2-3 s triggers recovery
SLOWDOWN_TOL = 0.15               # achieved within this of slip-predicted progress -> expected, not blocked


def recovery_needed(progress_ratio: float, duration_s: float, *, planner_failed: bool = False,
                    progress_thresh: float = RECOVERY_PROGRESS_THRESH,
                    min_stall_s: float = RECOVERY_MIN_STALL_S) -> dict:
    """NV-06: should backup recovery trigger? ``progress_ratio`` = achieved/commanded distance over the
    window, ``duration_s`` = how long that low-progress state has persisted. Recovery fires on a planner
    failure, or on sustained low progress (below ``progress_thresh`` for at least ``min_stall_s``).
    Returns {recover, reason}."""
    if progress_ratio < 0.0 or duration_s < 0.0 or progress_thresh < 0.0 or min_stall_s < 0.0:
        raise ValueError("progress_ratio/duration_s/progress_thresh/min_stall_s must be >= 0")
    if planner_failed:
        return {"recover": True, "reason": "planner_failure"}
    if progress_ratio < progress_thresh and duration_s >= min_stall_s:
        return {"recover": True, "reason": "low_progress"}
    return {"recover": False, "reason": "nominal"}


def classify_stall(progress_ratio: float, expected_progress_ratio: float, *,
                   tol: float = SLOWDOWN_TOL) -> str:
    """NV-07: is a stall a BLOCKAGE or an EXPECTED slope/slip slowdown? ``expected_progress_ratio`` is the
    slip-predicted ground progress (= 1 - slip) at the current slope, injected by the caller. If the
    achieved ratio is within ``tol`` of (or above) what slip predicts, the slowdown is EXPECTED
    ('slope_slip', do NOT reverse); if achieved falls well below the slip prediction, motion is blocked
    despite the available traction ('blockage', reverse). A high achieved ratio is 'nominal'."""
    if not (0.0 <= expected_progress_ratio <= 1.0) or tol < 0.0:
        raise ValueError("expected_progress_ratio must be in [0,1] and tol >= 0")
    if progress_ratio >= expected_progress_ratio - tol:
        return "nominal" if progress_ratio >= RECOVERY_PROGRESS_THRESH else "slope_slip"
    return "blockage"


def recommend(progress_ratio: float, duration_s: float, expected_progress_ratio: float, *,
              planner_failed: bool = False, **kw) -> dict:
    """NV-06+07 combined: decide the recovery ACTION, avoiding a false reverse on an expected slowdown.
      * planner failure        -> 'replan_global'
      * blockage (NV-07)       -> 'reverse' (back out, then local replan)
      * expected slope/slip     -> 'persist' (keep pushing; reversing would be the false maneuver NV-07 guards)
      * nominal                -> 'continue'
    Returns {action, recover, reason, stall_class}."""
    need = recovery_needed(progress_ratio, duration_s, planner_failed=planner_failed,
                           **{k: kw[k] for k in ("progress_thresh", "min_stall_s") if k in kw})
    stall = classify_stall(progress_ratio, expected_progress_ratio,
                           **{k: kw[k] for k in ("tol",) if k in kw})
    if planner_failed:
        action = "replan_global"
    elif not need["recover"]:
        action = "continue"
    elif stall == "blockage":
        action = "reverse"
    else:                                              # low progress explained by slope/slip -> don't reverse
        action = "persist"
    return {"action": action, "recover": need["recover"], "reason": need["reason"], "stall_class": stall}
