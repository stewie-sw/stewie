"""[REQ:EG-01] Environment modes + the per-mode authority matrix (PRD §29.1). The typed model only;
central enforcement is EG-02."""
import pytest

from stewie.contracts.governance import (
    MODE_AUTHORITY,
    EnvironmentMode,
    ModeAuthority,
    ModeAuthorityError,
    authority,
    mode_from_namespace,
    permits,
    require_authority,
)


def test_eg01_six_modes():  # [REQ:EG-01]
    assert {m.value for m in EnvironmentMode} == {"dev", "training", "rehearsal", "live", "replay", "archive"}
    assert set(MODE_AUTHORITY) == set(EnvironmentMode)                # every mode has an authority row
    assert all(isinstance(a, ModeAuthority) for a in MODE_AUTHORITY.values())


def test_eg01_only_live_commands_real_robots():  # [REQ:EG-01]
    assert [m for m in EnvironmentMode if authority(m).command_real_robot] == [EnvironmentMode.LIVE]


def test_eg01_replay_is_fully_read_only():  # [REQ:EG-01]
    a = authority(EnvironmentMode.REPLAY)
    assert not any([a.command_real_robot, a.modify_accepted_world, a.create_branches, a.publish,
                    a.delete_data, a.simulate, a.approve_merges])


def test_eg01_archive_read_only_except_export():  # [REQ:EG-01]  (§29.1: ARCHIVE publish = export only)
    a = authority(EnvironmentMode.ARCHIVE)
    assert a.publish is True
    assert not any([a.command_real_robot, a.modify_accepted_world, a.create_branches, a.delete_data,
                    a.simulate, a.approve_merges])


def test_eg01_training_rehearsal_cannot_modify_accepted_world_or_command():  # [REQ:EG-01]
    for m in (EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL):
        assert authority(m).modify_accepted_world is False
        assert authority(m).command_real_robot is False


def test_eg01_live_authority_matches_29_1():  # [REQ:EG-01]
    a = authority(EnvironmentMode.LIVE)
    assert a.command_real_robot and a.modify_accepted_world and a.create_branches
    assert a.publish and a.approve_merges
    assert a.delete_data is False                                    # §29.1: LIVE delete = no


def test_eg01_authority_accepts_string_or_enum_and_rejects_unknown():  # [REQ:EG-01]
    assert authority("live") == authority(EnvironmentMode.LIVE)
    with pytest.raises((KeyError, ValueError)):
        authority("bogus")


# ---- [REQ:EG-02] central mode-authority enforcement ---------------------------------------------
def test_eg02_require_authority_only_live_commands_and_modifies():  # [REQ:EG-02]
    require_authority(EnvironmentMode.LIVE, "command_real_robot")           # ok
    require_authority(EnvironmentMode.LIVE, "modify_accepted_world")        # ok
    for m in (EnvironmentMode.DEV, EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL,
              EnvironmentMode.REPLAY, EnvironmentMode.ARCHIVE):
        with pytest.raises(ModeAuthorityError):
            require_authority(m, "command_real_robot")                      # training never reaches live authority
    for m in (EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL, EnvironmentMode.REPLAY):
        with pytest.raises(ModeAuthorityError):
            require_authority(m, "modify_accepted_world")


def test_eg02_permits_fail_closed_and_namespace_mapping():  # [REQ:EG-02]
    assert permits(None, "command_real_robot") is False                    # no mode -> no authority (fail-closed)
    assert permits("live", "command_real_robot") is True
    assert mode_from_namespace("live") is EnvironmentMode.LIVE
    assert mode_from_namespace("sandbox") is EnvironmentMode.REHEARSAL
    assert mode_from_namespace(None) is None


def test_eg02_command_interlock_is_matrix_driven():  # [REQ:EG-02]
    # the real command interlock now derives its live-gate from the governance matrix: sandbox rejected,
    # live permitted -- byte-identical to the prior `mission_namespace != "live"` check.
    from stewie.bridge.command_eligibility import CommandContext, command_eligible
    live = CommandContext(role="operator", mission_namespace="live", target_namespace="live",
                          safed=False, ack_age_s=0.1)
    sandbox = CommandContext(role="operator", mission_namespace="sandbox", target_namespace="sandbox",
                             safed=False, ack_age_s=0.1)
    assert command_eligible(live) == (True, "eligible")
    assert command_eligible(sandbox) == (False, "unauthorized_sandbox")
