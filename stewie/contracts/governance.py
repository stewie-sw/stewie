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


# ---- [REQ:EG-02] central mode-authority ENFORCEMENT ---------------------------------------------
class ModeAuthorityError(PermissionError):
    """Raised when an action is attempted in an environment mode that does not grant it. The single typed
    rejection the enforcement guard raises, so training can never reach live authority."""


def permits(mode: EnvironmentMode | str | None, flag: str) -> bool:
    """True iff `mode` grants the authority `flag` (a ModeAuthority field name). A None mode grants NOTHING
    (fail-closed: no mode = no authority). Raises on an unknown mode string or an unknown flag."""
    if mode is None:
        return False
    return bool(getattr(MODE_AUTHORITY[EnvironmentMode(mode)], flag))


def require_authority(mode: EnvironmentMode | str | None, flag: str) -> None:
    """The central enforcement chokepoint: raise ModeAuthorityError unless `mode` grants `flag`. Call this at
    every world-write / asset-command site so no action crosses a mode boundary it is not authorized for."""
    if not permits(mode, flag):
        raise ModeAuthorityError(f"environment mode {getattr(mode, 'value', mode)!r} does not grant {flag!r}")


def mode_from_namespace(namespace: str | None) -> EnvironmentMode | None:
    """Map the operational `mission_namespace` (stewie.bridge.command_eligibility: 'live'/'sandbox'/None) onto a
    formal EnvironmentMode. 'live' -> LIVE (real authority); 'sandbox' -> REHEARSAL (mission sim on real
    configs, no hardware writes); None -> None (no context -> no authority)."""
    if namespace == "live":
        return EnvironmentMode.LIVE
    if namespace == "sandbox":
        return EnvironmentMode.REHEARSAL
    return None


# ---- [REQ:EG-04] role / permission model ---------------------------------------------------------
class Role(str, Enum):
    """The eleven platform roles (PRD §7 EG-04). WHO a principal is; the environment MODE is WHEN they act.
    Effective authority = the role's capability set AND the mode's authority (see can_command_live)."""
    ADMIN = "admin"                      # system administration (users/roles/config), not a live driver
    SAFETY_OFFICER = "safety_officer"    # approves live transitions; does not drive
    MISSION_DIRECTOR = "mission_director"  # runs the mission: plan + command + approve
    OPERATOR = "operator"                # drives the robot (live command), executes plans
    PLANNER = "planner"                  # authors + rehearses plans
    SCIENTIST = "scientist"              # analysis + planning
    ENGINEER = "engineer"                # full workbench EXCEPT live command (non-live)
    TRAINER = "trainer"                  # runs training/rehearsal
    TRAINEE = "trainee"                  # training-only
    VIEWER = "viewer"                    # read-only
    AI_AGENT = "ai_agent"                # may plan + rehearse; never gets live-command or approve authority


@dataclass(frozen=True)
class RolePermissions:
    """A role's capability set (WHO can do WHAT), independent of the environment mode (WHEN). Live command +
    world writes are additionally gated by the mode (EG-01/EG-02); a role granting a capability is necessary,
    not sufficient. `view` is the read-only floor every role has."""
    view: bool = False
    plan: bool = False
    write_training: bool = False
    command_real_robot: bool = False
    modify_accepted_world: bool = False
    approve_live_transition: bool = False
    administer: bool = False


#: PRD §7 EG-04 per-role permission set. The four named FLOORS are load-bearing: VIEWER = view only;
#: TRAINEE = view+training only; ENGINEER = everything but live command; SAFETY_OFFICER = approves live.
ROLE_PERMISSIONS: dict[Role, RolePermissions] = {
    #                            view   plan   train  cmd    modify appr   admin
    Role.ADMIN:            RolePermissions(True, True, True, False, True, True, True),
    Role.SAFETY_OFFICER:   RolePermissions(True, False, True, False, False, True, False),
    Role.MISSION_DIRECTOR: RolePermissions(True, True, True, True, True, True, False),
    Role.OPERATOR:         RolePermissions(True, False, True, True, False, False, False),
    Role.PLANNER:          RolePermissions(True, True, True, False, False, False, False),
    Role.SCIENTIST:        RolePermissions(True, True, True, False, False, False, False),
    Role.ENGINEER:         RolePermissions(True, True, True, False, True, False, False),
    Role.TRAINER:          RolePermissions(True, True, True, False, False, False, False),
    Role.TRAINEE:          RolePermissions(True, False, True, False, False, False, False),
    Role.VIEWER:           RolePermissions(True, False, False, False, False, False, False),
    Role.AI_AGENT:         RolePermissions(True, True, True, False, False, False, False),
}


def role_permissions(role: Role | str) -> RolePermissions:
    """The capability set a role grants. Accepts a Role or its string value; raises on an unknown role."""
    return ROLE_PERMISSIONS[Role(role)]


def role_permits(role: Role | str, capability: str) -> bool:
    """True iff `role` grants `capability` (a RolePermissions field name). An unknown capability -> False
    (fail-closed: an unrecognized permission is never granted)."""
    return bool(getattr(ROLE_PERMISSIONS[Role(role)], capability, False))


def can_command_live(role: Role | str, mode: EnvironmentMode | str | None) -> bool:
    """Explicit live-command eligibility (EG-04): the role must grant `command_real_robot` AND the mode must
    permit it (only LIVE does, EG-01). Both floors -- the role floor (Engineer/Trainee/Viewer/AI cannot) AND
    the mode floor (no live command outside LIVE) -- must clear."""
    return role_permits(role, "command_real_robot") and permits(mode, "command_real_robot")
