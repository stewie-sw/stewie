"""[REQ:MP-07] F24: the §30.3 rollback/abort-rule precondition must be a REAL predicate, not constant True.

The prior expression ``"safed" in transitions or run.get("safed") is not None`` was always True (``safed`` is
always a bool, so ``is not None`` is a tautology and the first clause is dead), so the executability card
could never report the abort/rollback gate as unmet. The corrected predicate attests the rule only when the
run reached a GOVERNED terminal of the abort-capable executive (COMPLETED nominally, or SAFED via the abort
rule firing); a run stuck mid-lifecycle or a malformed record cannot attest a rollback/abort rule.
"""
from stewie.server.routers.executive import _rollback_abort_rule


def test_rollback_abort_rule_true_for_a_nominal_completed_run():
    # a nominal dig: safed=False, transitions LACK 'safed', but the run reached the COMPLETED governed
    # terminal -> the abort/rollback rule is defined + was in force (so a clean plan stays executable).
    completed = {"final_state": "completed", "transitions": ["armed", "executing", "completed"], "safed": False}
    assert _rollback_abort_rule(completed) is True


def test_rollback_abort_rule_true_for_a_safed_run():
    # the abort rule demonstrably fired -> SAFED governed terminal.
    safed = {"final_state": "safed", "transitions": ["armed", "executing", "safed"], "safed": True}
    assert _rollback_abort_rule(safed) is True


def test_rollback_abort_rule_is_not_constant_true():
    # a run stuck mid-lifecycle (no governed terminal). The OLD code returned True (safed is not None);
    # the real predicate returns False -- proving the precondition is no longer a tautology.
    stuck = {"final_state": "executing", "transitions": ["armed", "executing"], "safed": False}
    assert _rollback_abort_rule(stuck) is False
    # a malformed / empty run record likewise cannot attest a rollback/abort rule.
    assert _rollback_abort_rule({"safed": False}) is False
    assert _rollback_abort_rule({}) is False
