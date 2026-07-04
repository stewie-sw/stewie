"""[REQ:EG-04] The role/permission model: 11 roles, a per-role capability set, and explicit live-command
eligibility (role floor AND mode floor). The four named role floors hold: Viewer read-only, Trainee
training-only, Engineer non-live-only, SafetyOfficer approves live transitions."""
from stewie.contracts.governance import (
    EnvironmentMode,
    Role,
    can_command_live,
    role_permissions,
    role_permits,
)


def test_eg04_all_eleven_roles_present():  # [REQ:EG-04]
    assert len(Role) == 11
    for name in ("ADMIN", "SAFETY_OFFICER", "MISSION_DIRECTOR", "OPERATOR", "PLANNER", "SCIENTIST",
                 "ENGINEER", "TRAINER", "TRAINEE", "VIEWER", "AI_AGENT"):
        assert hasattr(Role, name)


def test_eg04_viewer_is_read_only():  # [REQ:EG-04]
    p = role_permissions(Role.VIEWER)
    assert p.view is True
    assert not any((p.plan, p.write_training, p.command_real_robot, p.modify_accepted_world,
                    p.approve_live_transition, p.administer))


def test_eg04_trainee_is_training_only():  # [REQ:EG-04]
    p = role_permissions(Role.TRAINEE)
    assert p.view and p.write_training
    assert not p.command_real_robot and not p.modify_accepted_world and not p.plan


def test_eg04_engineer_is_non_live():  # [REQ:EG-04]
    p = role_permissions(Role.ENGINEER)
    assert p.command_real_robot is False       # the floor: an engineer cannot command a live robot
    assert p.plan and p.write_training         # but can plan + rehearse


def test_eg04_safety_officer_approves_live_transitions():  # [REQ:EG-04]
    assert role_permits(Role.SAFETY_OFFICER, "approve_live_transition") is True
    assert role_permits(Role.OPERATOR, "approve_live_transition") is False


def test_eg04_live_command_needs_both_role_and_mode():  # [REQ:EG-04]
    # explicit live-command eligibility = the role grants command_real_robot AND the mode is LIVE
    assert can_command_live(Role.OPERATOR, EnvironmentMode.LIVE) is True
    assert can_command_live(Role.OPERATOR, EnvironmentMode.TRAINING) is False   # mode floor
    assert can_command_live(Role.ENGINEER, EnvironmentMode.LIVE) is False       # role floor
    assert can_command_live(Role.VIEWER, EnvironmentMode.LIVE) is False


def test_eg04_role_permits_unknown_capability_fail_closed():  # [REQ:EG-04]
    assert role_permits(Role.ADMIN, "nonexistent_capability") is False
