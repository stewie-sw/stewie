"""NV-09: the autonomy executive's safety precedence. Drives executive_step with the real outputs of the
NV-05/06/07/08 modules (faults.classify_faults, recovery.recommend, reactive_nav.react) and asserts the
fail-safe-wins ordering."""
from lode import executive as EX
from lode import faults as F


def test_nv09_safety_critical_fault_fails_safe_over_everything():
    """[REQ:NV-09] a safety-critical fault halts to a safe state, overriding any recovery/reactive signal."""
    faults = F.classify_faults(tip_margin_deg=-1.0)                 # critical tip
    out = EX.executive_step(faults=faults, recovery={"action": "persist"}, reactive={"scope": "local"})
    assert out["action"] == "fail_safe" and out["safety_critical"] is True


def test_nv09_unacked_command_pauses():
    out = EX.executive_step(command_acked=False, reactive={"scope": "local"})
    assert out["action"] == "pause" and "acknowledg" in out["reason"]


def test_nv09_unaccepted_step_pauses():
    out = EX.executive_step(plan_accepted=False)
    assert out["action"] == "pause" and "accept" in out["reason"]


def test_nv09_global_replan_from_recovery_or_reactive():
    assert EX.executive_step(recovery={"action": "replan_global"})["action"] == "replan_global"
    assert EX.executive_step(reactive={"scope": "global"})["action"] == "replan_global"


def test_nv09_reverse_and_persist_from_recovery():
    assert EX.executive_step(recovery={"action": "reverse"})["action"] == "reverse"
    assert EX.executive_step(recovery={"action": "persist"})["action"] == "persist"


def test_nv09_reactive_local_detour():
    assert EX.executive_step(reactive={"scope": "local"})["action"] == "replan_local"


def test_nv09_nominal_continues():
    out = EX.executive_step()
    assert out["action"] == "continue" and out["safety_critical"] is False


def test_nv09_precedence_fault_beats_ack_beats_recovery():
    # a fault outranks a missing ack; a missing ack outranks a recovery action
    f = F.classify_faults(slip=0.97)                                # critical entrapment
    assert EX.executive_step(faults=f, command_acked=False, recovery={"action": "reverse"})["action"] == "fail_safe"
    assert EX.executive_step(command_acked=False, recovery={"action": "reverse"})["action"] == "pause"
