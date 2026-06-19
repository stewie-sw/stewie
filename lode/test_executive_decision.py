"""[REQ:AS-13] ROS-side mission-executive acceptance (§25 Phase 11): the executive emits
continue / pause / replan / relocalize / reverse / SAFE and covers nominal, timeout, blocked path,
covariance loss, resource conflict, and SAFE escalation -- in strict safety precedence."""
from lode.executive import executive_step, to_executive_decision


def _decide(**kw):
    return to_executive_decision(executive_step(**kw))["decision"]


def test_nominal_progress_continues():
    assert _decide() == "continue"


def test_timeout_unacked_command_pauses():
    assert _decide(command_acked=False) == "pause"


def test_blocked_path_replans():
    assert _decide(reactive={"scope": "global"}) == "replan"
    assert _decide(recovery={"action": "replan_global"}) == "replan"


def test_covariance_loss_triggers_relocalize():
    assert _decide(covariance_ok=False) == "relocalize"


def test_resource_conflict_pauses():
    assert _decide(reservation_conflict=True) == "pause"


def test_safe_escalation_on_safety_critical_fault():
    faults = [{"fault": "imu_dropout", "severity": "critical"}]
    out = executive_step(faults=faults)
    assert out["action"] == "fail_safe" and out["safety_critical"]
    assert to_executive_decision(out)["decision"] == "safe"


def test_reverse_maps_through():
    assert _decide(recovery={"action": "reverse"}) == "reverse"


def test_precedence_safe_beats_relocalize_beats_replan():
    faults = [{"fault": "imu_dropout", "severity": "critical"}]
    # a critical fault wins over a lost-covariance + a demanded replan
    assert _decide(faults=faults, covariance_ok=False, recovery={"action": "replan_global"}) == "safe"
    # covariance loss (relocalize) wins over a demanded replan
    assert _decide(covariance_ok=False, recovery={"action": "replan_global"}) == "relocalize"


def test_decision_verbs_are_the_contract_set():
    verbs = {"continue", "pause", "replan", "relocalize", "reverse", "safe"}
    from lode import executive as EX
    assert set(EX._DECISION.values()) <= verbs
