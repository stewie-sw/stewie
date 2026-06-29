"""#245 SIM-execute driver TDD: a RELEASED plan runs ARMED->EXECUTING->COMPLETED over clean SIM legs; a
safety-critical fault (the watchdog trip) drives SAFED and HALTS (no further legs); a non-RELEASED executive
is rejected; every run carries the SIM data label. Reuses the REAL MO-02 contract transitions + the real
lode.executive_step safety precedence -- no mocks."""
import pytest

from lode.sim_execution import SIM_LABEL, run_sim_execution
from stewie import contracts as C
from stewie.contracts import executive as X


def _released():
    """A real RELEASED MissionExecutive via the legal head DRAFT->...->RELEASED (mirrors test_executive)."""
    acc = C.AcceptanceCriterion(criterion_id="a1", statement="flat", measurable="RMSE<=0.02 m",
                                sensor="dem_overlay")
    obj = C.Objective(objective_id="O-1", revision=0, statement="flatten pad", rationale="level surface",
                      priority=C.PriorityTier.PRIMARY, mandatory=True, target_row=100.0, target_col=200.0,
                      frame="MOON_ME", acceptance=[acc], confidence_required=0.9,
                      contingency=C.Contingency(policy=C.ContingencyPolicy.REPLAN, detail="retry"),
                      approver="director", evidence="design memo")
    ex = X.MissionExecutive.start(C.MissionIntent(mission_id="M-1", revision=0, statement="prep pad",
                                                  objectives=[obj], constraints=[], task_graph_ref="ir-1"))
    ex = ex.transition(X.ExecutiveState.ANALYZED, role="planner", evidence="feasibility")
    ex = ex.transition(X.ExecutiveState.REHEARSED, role="operator", evidence="rehearsal log")
    ex = ex.transition(X.ExecutiveState.REVIEWED, role="reviewer", evidence="review minutes")
    return ex.transition(X.ExecutiveState.RELEASED, role="director", evidence="release authorization")


def test_clean_run_reaches_completed():
    out = run_sim_execution(_released(), [{"faults": []}, {}, {"faults": []}])
    assert out["final_state"] == "completed" and out["safed"] is False
    assert out["transitions"] == ["armed", "executing", "completed"]
    assert len(out["executed_legs"]) == 3 and out["n_legs_total"] == 3
    assert out["label"] == SIM_LABEL                                  # never LIVE
    assert out["executive"].state is X.ExecutiveState.COMPLETED


def test_safety_critical_fault_drives_safed_and_halts():
    legs = [{"faults": []},
            {"faults": [{"fault": "tip_over_imminent", "severity": "critical"}]},   # watchdog trip
            {"faults": []}]                                            # must NOT execute (halted)
    out = run_sim_execution(_released(), legs)
    assert out["final_state"] == "safed" and out["safed"] is True
    assert out["transitions"] == ["armed", "executing", "safed"]
    assert len(out["executed_legs"]) == 1                             # only the clean leg before the fault
    assert out["executive"].state is X.ExecutiveState.SAFED


def test_non_released_executive_is_rejected():
    draft = X.MissionExecutive.start(_released().intent)              # a fresh DRAFT
    with pytest.raises(ValueError):
        run_sim_execution(draft, [{"faults": []}])                   # cannot run an unreleased plan


def test_empty_legs_complete_immediately():
    out = run_sim_execution(_released(), [])
    assert out["final_state"] == "completed" and out["n_legs_total"] == 0


def test_malformed_fault_fails_safe_not_crash():
    # council-caught: a fault dict missing "severity" would KeyError inside executive_step. A safety driver
    # must FAIL SAFE on unevaluable input, never crash and leave the executive stuck in EXECUTING.
    out = run_sim_execution(_released(), [{"faults": [{"fault": "no_severity_field"}]}])
    assert out["final_state"] == "safed" and out["safed"] is True   # fail-safe, not an exception
    assert out["executive"].state is X.ExecutiveState.SAFED


def test_non_dict_leg_does_not_crash():
    out = run_sim_execution(_released(), [None, {"faults": []}])     # a malformed (non-dict) leg record
    assert out["final_state"] == "completed"                        # no parseable fault -> nominal, no crash
    assert out["nonnominal_legs"] == 0
