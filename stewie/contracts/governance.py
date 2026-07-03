"""[REQ:EG-01] Environment-governed operations: the six environment modes + the per-mode AUTHORITY MATRIX
(PRD §29.1). Authority is a property of the MODE a session runs in -- LIVE alone commands real robots, REPLAY
is fully read-only, ARCHIVE is read-only except export. This is the typed DATA model; central enforcement (a
guard that rejects any action a mode does not grant) is EG-02, and the DB/branch isolation is EG-03. The looser
`mission_namespace` ("live"/"sandbox", stewie.bridge.command_eligibility) and the `runtime_mode` authority-tuple
key (lode.mission_package) map onto these formal modes; this is their canonical definition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EnvironmentMode(str, Enum):
    DEV = "dev"                # local testing, fake robots, disposable data
    TRAINING = "training"      # simulated missions, sandboxes, guided workflows (training branches only)
    REHEARSAL = "rehearsal"    # mission simulation on REAL configs, no hardware writes (sim branches only)
    LIVE = "live"              # real robot / real mission authority
    REPLAY = "replay"          # read-only historical reconstruction
    ARCHIVE = "archive"        # frozen record (export only)


@dataclass(frozen=True)
class ModeAuthority:
    """The seven authority flags a mode grants (PRD §29.1). A qualified 'yes' in the spec (e.g. TRAINING
    'training branches only', ARCHIVE 'export only') is True here; the SCOPING of that authority (which
    branch/DB it applies to) is enforced by EG-02/EG-03, not by this coarse matrix."""
    command_real_robot: bool
    modify_accepted_world: bool
    create_branches: bool
    publish: bool
    delete_data: bool
    simulate: bool
    approve_merges: bool


#: PRD §29.1 authority matrix. "yes"/"qualified-yes" -> True; "no"/"n/a" -> False.
MODE_AUTHORITY: dict[EnvironmentMode, ModeAuthority] = {
    #                              cmd    modify  branch  publ   delete  sim    approve
    EnvironmentMode.DEV:       ModeAuthority(False, False,  True,  False, True,   True,  False),
    EnvironmentMode.TRAINING:  ModeAuthority(False, False,  True,  False, True,   True,  False),
    EnvironmentMode.REHEARSAL: ModeAuthority(False, False,  True,  False, False,  True,  False),
    EnvironmentMode.LIVE:      ModeAuthority(True,  True,   True,  True,  False,  False, True),
    EnvironmentMode.REPLAY:    ModeAuthority(False, False,  False, False, False,  False, False),
    EnvironmentMode.ARCHIVE:   ModeAuthority(False, False,  False, True,  False,  False, False),
}


def authority(mode: EnvironmentMode | str) -> ModeAuthority:
    """The authority a mode grants. Accepts an EnvironmentMode or its string value; raises on an unknown mode."""
    return MODE_AUTHORITY[EnvironmentMode(mode)]
