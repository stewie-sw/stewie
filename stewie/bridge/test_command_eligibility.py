"""[REQ:AS-12] command-eligibility acceptance (§25 Phase 10): unsafe / unauthorized / stale /
namespace-conflicting commands FAIL CLOSED before ROS emission; only an all-gates-pass command is
eligible."""
from stewie.bridge.command_eligibility import CommandContext, command_eligible


def _ok(**over):
    base = dict(role="operator", mission_namespace="live", target_namespace="live",
                safed=False, ack_age_s=0.5, ack_deadline_s=2.0, director_only=False)
    base.update(over)
    return CommandContext(**base)


def test_all_gates_pass_is_eligible():
    ok, reason = command_eligible(_ok())
    assert ok and reason == "eligible"


def test_unauthorized_role_fails_closed():
    for role in (None, "", "guest", "trainee", "bogus"):
        ok, reason = command_eligible(_ok(role=role))
        assert not ok and reason == "unauthorized_role", role


def test_director_only_command_blocked_for_operator():
    ok, reason = command_eligible(_ok(role="operator", director_only=True))
    assert not ok and reason == "unauthorized_director_only"
    assert command_eligible(_ok(role="director", director_only=True))[0]   # director may


def test_sandbox_mission_fails_closed():
    for ns in ("sandbox", None):
        ok, reason = command_eligible(_ok(mission_namespace=ns, target_namespace=ns))
        assert not ok and reason == "unauthorized_sandbox", ns


def test_safed_command_fails_closed():
    ok, reason = command_eligible(_ok(safed=True))
    assert not ok and reason == "unsafe_safed"


def test_stale_link_fails_closed():
    ok, reason = command_eligible(_ok(ack_age_s=5.0, ack_deadline_s=2.0))
    assert not ok and reason == "stale_link"


def test_namespace_conflict_fails_closed():
    ok, reason = command_eligible(_ok(mission_namespace="live", target_namespace="other"))
    assert not ok and reason == "namespace_conflict"


def test_missing_context_is_default_deny():
    ok, reason = command_eligible(None)
    assert not ok and reason == "no_context"
