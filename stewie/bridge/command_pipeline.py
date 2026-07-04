"""[REQ:EG-06] The command-safety pipeline (PRD §29.6).

A command flows: UI -> mission-service (validate task) -> safety-service (constraints) -> execution-service
(mode) -> ROS2 bridge -> audit. `lower_command` is the single named ordered pipeline: it validates the task,
then runs the AS-12 `command_eligible` interlock (which already composes safety + execution-mode + role + link
+ namespace), failing CLOSED at the FIRST unmet stage with that stage's reason. It does NOT duplicate the
interlock -- it formalizes the ordered pipeline over it.

INVARIANTS (§29.6): no UI panel sends commands directly to ROS2; the execution-service path (the rc router's
`lower_plan_ir` egress) is the SOLE ROS2 command egress; no live command lowers without passing this pipeline.
The single-egress invariant is guarded by test_command_pipeline.test_eg06_sole_ros2_command_egress_is_rc.
"""
from __future__ import annotations

from stewie.bridge.command_eligibility import CommandContext, command_eligible

#: the ordered §29.6 stages `lower_command` runs (for the operator evidence surface + the stage-order test).
PIPELINE_STAGES = ("validate_task", "safety_and_mode_interlock", "emit")


def lower_command(ctx: CommandContext | None, *, task_valid: bool = True) -> tuple[bool, str]:
    """Run the §29.6 command-safety pipeline. Returns ``(emit, stage_reason)``; ``emit`` is True only if every
    stage passes, else the FIRST unmet stage's reason (fail-closed). Stage 1 is mission-service task
    validation; stages 2-4 are the AS-12 ``command_eligible`` interlock (safety + execution mode + role + link
    + namespace). A command reaches the ROS2 bridge only when this returns ``(True, "emit")`` -- and only via
    the single rc-router egress."""
    if not task_valid:
        return False, "invalid_task"                    # stage 1: mission-service rejects a malformed task
    ok, reason = command_eligible(ctx)                  # stages 2-4: safety + mode + role/link/namespace
    return (ok, "emit" if ok else reason)
