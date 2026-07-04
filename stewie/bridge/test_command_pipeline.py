"""[REQ:EG-06] The command-safety pipeline: the ordered stages fail closed at the FIRST unmet stage, and the
ROS2 command egress is the sole rc-router path (no UI/router publishes commands to ROS2 directly)."""
import pathlib

from stewie.bridge.command_eligibility import CommandContext
from stewie.bridge.command_pipeline import lower_command


def _live_ok() -> CommandContext:
    return CommandContext(role="operator", mission_namespace="live", target_namespace="live",
                          safed=False, ack_age_s=0.1)


def test_eg06_pipeline_fails_closed_at_first_unmet_stage():  # [REQ:EG-06]
    # stage 1 (mission-service): an invalid task is rejected BEFORE the interlock
    assert lower_command(_live_ok(), task_valid=False) == (False, "invalid_task")
    # stages 2-4 (safety + mode + role/link/namespace): each unmet gate surfaces its own stage reason
    sandbox = CommandContext(role="operator", mission_namespace="sandbox", target_namespace="sandbox",
                             safed=False, ack_age_s=0.1)
    assert lower_command(sandbox) == (False, "unauthorized_sandbox")     # not LIVE -> execution-mode gate
    safed = CommandContext(role="operator", mission_namespace="live", target_namespace="live",
                           safed=True, ack_age_s=0.1)
    assert lower_command(safed) == (False, "unsafe_safed")               # safety-service gate
    assert lower_command(None)[0] is False                               # fail-closed on no context


def test_eg06_pipeline_emits_when_every_stage_passes():  # [REQ:EG-06]
    assert lower_command(_live_ok(), task_valid=True) == (True, "emit")


def test_eg06_sole_ros2_command_egress_is_rc():  # [REQ:EG-06]
    # §29.6 single-egress invariant: ONLY the rc router imports the ROS2 command egress (lower_plan_ir);
    # no other router / UI path publishes commands to ROS2 directly.
    routers = pathlib.Path(__file__).resolve().parents[2] / "stewie" / "server" / "routers"
    importers = sorted(f.name for f in routers.glob("*.py")
                       if "lower_plan_ir" in f.read_text(encoding="utf-8"))
    assert importers == ["rc.py"], f"ROS2 command egress imported outside the rc router: {importers}"
