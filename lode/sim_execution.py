"""#245 SIM-execute: drive a RELEASED mission through the MO-02 live chain on the SIM authority.

Turns the conserved closed-loop sim output (the per-leg records run_closed_loop emits) into a real
executive RUN: ARM the released plan, go EXECUTING, step each leg through the safety-precedence decision
(lode.executive.executive_step), and either reach COMPLETED or -- on a safety-critical fault (a watchdog
trip) -- SAFED and HALT (no further legs). Honesty firewall: every value is SIM, never LIVE. This sequences
the in-process plant only; the real-rover command path (/rc/plan_ros, /rc/command GoTo, ros_odom) stays
gated. The authority is the executive contract itself (stewie.contracts.executive enforces the legal edges,
role sets, and evidence); this module only orders the transitions and the per-leg decision and fabricates
no terrain or state. The route/persistence/HMI that call this are a separate wiring increment.
"""
from __future__ import annotations

from lode.executive import executive_step
from stewie.contracts import ExecutionEvent
from stewie.contracts.executive import ExecutiveState, MissionExecutive

SIM_LABEL = "sim"   # MO-04 DataLabel: produced on the sim authority, never promotable to LIVE here


def run_sim_execution(executive: MissionExecutive, legs, *, operator: str = "operator",
                      safety: str = "safety") -> dict:
    """Run a RELEASED ``executive`` through ARMED -> EXECUTING -> (COMPLETED | SAFED) over the SIM ``legs``.

    Each leg may carry ``faults`` -- a list of ``{"fault","severity"}`` dicts, exactly as the sim/monitors
    emit. A safety-critical fault makes executive_step return ``fail_safe`` -> the run transitions to SAFED
    under the ``safety`` role and HALTS (no further legs execute) -- the watchdog->SAFED wiring. A clean
    pass -> COMPLETED under ``operator``. The executive's own contract enforces every edge's legality, role
    set, and non-empty evidence. Returns the final state, the ordered transition log, the executed-leg
    decisions, the total leg count, and the SIM data label. Raises ValueError if the executive is not
    RELEASED (an unsigned/unreleased plan cannot be run)."""
    if executive.state is not ExecutiveState.RELEASED:
        raise ValueError(f"cannot run executive in state {executive.state.value!r}; must be RELEASED first")
    legs = list(legs)
    ex = executive.transition(ExecutiveState.ARMED, role=operator, evidence="SIM arming checklist passed")
    ex = ex.transition(ExecutiveState.EXECUTING, role=operator, evidence="SIM execute issued")
    transitions = [ExecutiveState.ARMED.value, ExecutiveState.EXECUTING.value]
    executed: list = []
    safed = False
    for i, leg in enumerate(legs):
        # ROBUST SAFETY DEFAULT: a safety driver FAILS SAFE, it does not crash. Any monitor input we cannot
        # evaluate (a malformed/incomplete fault record -- e.g. a fault dict missing "severity") is treated
        # as a fail-safe rather than propagating an exception that would leave the executive stuck in
        # EXECUTING with no SAFED/COMPLETED. A non-dict leg carries no parseable faults -> nominal continue.
        try:
            faults = list(leg.get("faults", []) or []) if isinstance(leg, dict) else []
            decision = executive_step(faults=faults)
            critical = bool(decision["safety_critical"]); action = decision["action"]; reason = decision["reason"]
        except Exception as exc:   # noqa: BLE001 -- unevaluable safety input -> SAFE by design, never continue
            critical, action, reason = True, "fail_safe", f"unparseable monitor input -> fail-safe ({exc})"
        if critical:
            ex = ex.transition(ExecutiveState.SAFED, role=safety,
                               evidence=f"SIM watchdog: leg {i} {reason}")
            transitions.append(ExecutiveState.SAFED.value)
            safed = True
            break
        executed.append({"leg": i, "action": action})
    # honesty: a COMPLETED run is only "nominal" if every executed leg was continue/persist. Non-nominal
    # decisions (pause/relocalize/replan/reverse) are surfaced via nonnominal_legs + the evidence so a caller
    # reading final_state=="completed" can tell a clean run from one that held/replanned. (v1 passes only
    # faults to executive_step, so today executed actions are continue|fail_safe; this stays honest as the
    # driver grows to feed command-ack / plan-accepted / recovery signals.)
    nonnominal = [leg for leg in executed if leg["action"] not in ("continue", "persist")]
    if not safed:
        ev = (f"SIM run complete: {len(executed)} legs nominal" if not nonnominal else
              f"SIM run complete: {len(executed)} legs, {len(nonnominal)} non-nominal (held/replanned)")
        ex = ex.transition(ExecutiveState.COMPLETED, role=operator, evidence=ev)
        transitions.append(ExecutiveState.COMPLETED.value)
    return {"label": SIM_LABEL, "final_state": ex.state.value, "transitions": transitions,
            "executed_legs": executed, "n_legs_total": len(legs), "safed": safed,
            "nonnominal_legs": len(nonnominal), "executive": ex}


def execution_events(run: dict, *, vehicle_id: str = "ipex") -> list[ExecutionEvent]:
    """Convert a ``run_sim_execution`` result into the typed FS-04 ExecutionEvent timeline: one ``leg``
    event per executed leg, then one terminal event -- ``safe``/``safed`` if the run safed, else
    ``acceptance``/``ok`` for a completed run. ``t_s`` is the leg ORDINAL (the SIM run carries no
    wall-clock); a non-nominal leg action (pause/relocalize/replan/reverse) is surfaced as
    ``outcome='blocked'`` so a reader can tell a clean leg from a held/replanned one. The discrete
    record the WorldStateService commits and the Fleet/Report panes render."""
    events: list[ExecutionEvent] = []
    executed = run.get("executed_legs", []) or []
    for leg in executed:
        i = int(leg.get("leg", len(events)))
        action = str(leg.get("action", "continue"))
        outcome = "ok" if action in ("continue", "persist") else "blocked"
        events.append(ExecutionEvent(t_s=float(i), vehicle_id=vehicle_id, kind="leg",
                                     detail=f"sim leg {i}: {action}", outcome=outcome))
    t_term = float(len(executed))
    if run.get("safed"):
        events.append(ExecutionEvent(t_s=t_term, vehicle_id=vehicle_id, kind="safe",
                                     detail="SIM watchdog: run safed", outcome="safed"))
    else:
        events.append(ExecutionEvent(t_s=t_term, vehicle_id=vehicle_id, kind="acceptance",
                                     detail=f"SIM run {run.get('final_state', 'completed')}",
                                     outcome="ok"))
    return events
