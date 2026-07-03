"""[REQ:EG-01] Environment modes + the per-mode authority matrix (PRD §29.1). The typed model only;
central enforcement is EG-02."""
import pytest

from stewie.contracts.governance import (
    MODE_AUTHORITY,
    EnvironmentMode,
    ModeAuthority,
    authority,
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
