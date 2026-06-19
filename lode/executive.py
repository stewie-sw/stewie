"""NV-09: the autonomy executive. The single decision point that monitors the rover's safety + progress
signals and returns the next safe action, in a STRICT safety precedence (fail-safe always wins). It
integrates the rest of the nav family rather than re-deriving anything:
  * fault state           -- faults.classify_faults / is_safety_critical (NV-08)
  * command acknowledgement -- did the last command ack? (move-and-wait: never proceed on an un-acked command)
  * recovery recommendation -- recovery.recommend (NV-06/07): reverse / persist / replan_global
  * reactive replan scope  -- reactive_nav.react (NV-05): local / global
  * acceptance state        -- is the current step approved to execute?

Pure decision logic; the signals are computed by the modules above and passed in, so the executive stays
testable and free of side effects.
"""
from __future__ import annotations

from lode import faults as F

# the executive's action vocabulary, highest safety precedence first
ACTIONS = ("fail_safe", "pause", "relocalize", "replan_global", "reverse", "persist",
           "replan_local", "continue")

# fine action -> ExecutiveDecision.msg verb (continue|pause|replan|relocalize|reverse|safe)
_DECISION = {"fail_safe": "safe", "pause": "pause", "relocalize": "relocalize",
             "replan_global": "replan", "replan_local": "replan", "reverse": "reverse",
             "persist": "continue", "continue": "continue"}


def executive_step(*, faults=(), command_acked: bool = True, plan_accepted: bool = True,
                   covariance_ok: bool = True, reservation_conflict: bool = False,
                   recovery: dict | None = None, reactive: dict | None = None) -> dict:
    """Decide the next executive action from the monitored signals, in strict safety precedence:
      1. a safety-critical fault (NV-08)        -> fail_safe   (halt to a safe state)
      2. the last command was not acknowledged  -> pause       (move-and-wait; never act on an un-acked cmd)
      3. the current step is not yet accepted    -> pause       (do not execute an unapproved step)
      4. recovery/reactive demand a global replan -> replan_global
      5. recovery says back out of a blockage     -> reverse     (NV-07)
      6. recovery says push through expected slip  -> persist     (NV-07 false-reverse guard)
      7. a reactive local detour is available      -> replan_local (NV-05)
      8. otherwise                                 -> continue
    Returns {action, reason, safety_critical}. fail_safe can never be overridden by a lower rule."""
    crit = F.is_safety_critical(list(faults))
    rec_action = (recovery or {}).get("action")
    reactive_scope = (reactive or {}).get("scope")

    if crit:
        names = sorted(f["fault"] for f in faults if f.get("severity") == "critical")
        return {"action": "fail_safe", "reason": f"safety-critical fault(s): {', '.join(names)}",
                "safety_critical": True}
    if not command_acked:
        return {"action": "pause", "reason": "last command not acknowledged (move-and-wait)",
                "safety_critical": False}
    if not plan_accepted:
        return {"action": "pause", "reason": "current step not accepted for execution",
                "safety_critical": False}
    if reservation_conflict:
        return {"action": "pause", "reason": "resource/reservation conflict -> yield to the holder",
                "safety_critical": False}
    if not covariance_ok:
        return {"action": "relocalize",
                "reason": "localization covariance lost -> standstill relocalization fix (ARGUS/DEM)",
                "safety_critical": False}
    if rec_action == "replan_global" or reactive_scope == "global":
        return {"action": "replan_global", "reason": "planner failure / no local detour -> global re-route",
                "safety_critical": False}
    if rec_action == "reverse":
        return {"action": "reverse", "reason": "blockage (progress far below slip prediction) -> back out",
                "safety_critical": False}
    if rec_action == "persist":
        return {"action": "persist", "reason": "expected slope/slip slowdown -> keep pushing (no false reverse)",
                "safety_critical": False}
    if reactive_scope == "local":
        return {"action": "replan_local", "reason": "reactive hazard -> local detour", "safety_critical": False}
    return {"action": "continue", "reason": "nominal", "safety_critical": False}


def to_executive_decision(step: dict) -> dict:
    """Map an executive_step result to the ExecutiveDecision.msg verb set
    (continue|pause|replan|relocalize|reverse|safe) + reason -- the ROS-side mission-executive output."""
    return {"decision": _DECISION[step["action"]], "reason": step["reason"]}
