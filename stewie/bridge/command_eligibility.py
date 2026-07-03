"""[REQ:AS-12] Unified command-eligibility interlock (§25 Phase 10).

A Plan-IR command is lowered to a ROS emission ONLY if it passes EVERY gate; any failing gate FAILS
CLOSED (no emission) with a named reason. This is the single auditable pre-emission check the rc
router and the live ROS2 node call, composing the gates that the codebase already enforces inline:

  * authorized   -- operator+ (AG-01/AG-02 role ladder; SetSim is director-only)
  * live         -- the command targets a PUBLISHED (live) mission, never a sandbox draft (AG-08)
  * safe         -- no SF-01 SAFE/safing is active (BRAKED_HOLD / hazard / watchdog)
  * fresh        -- the command/telemetry link is not stalled past the NV-12 ack deadline
  * namespaced   -- the command's target namespace matches the mission namespace (no cross-namespace)

Default-deny: a missing context, unknown role, or any unmet gate -> ineligible. Pure logic (numpy-free);
reuses the AG-01 role_rank as the single source of capability ordering.
"""
from __future__ import annotations

from dataclasses import dataclass

from stewie.contracts.governance import mode_from_namespace, permits   # [REQ:EG-02] mode-authority matrix
from stewie.server.operators import role_rank   # AG-01: the single role-ladder source

_OPERATOR = role_rank("operator")
_DIRECTOR = role_rank("director")


@dataclass
class CommandContext:
    role: str | None                 # the issuing identity's role (AG-01 ladder)
    mission_namespace: str | None    # "live" | "sandbox" | None
    target_namespace: str | None     # the command's target namespace
    safed: bool                      # SF-01 SAFE / safing active
    ack_age_s: float                 # age of the most recent consumer ack [s]
    ack_deadline_s: float = 2.0      # NV-12 link-stall deadline [s]
    director_only: bool = False      # e.g. SetSim (training time-warp)


def command_eligible(ctx: CommandContext | None) -> tuple[bool, str]:
    """Return (eligible, reason). eligible is True ONLY if every gate passes; otherwise the FIRST
    failing gate's reason. Fail-closed for a missing/None context."""
    if ctx is None:
        return False, "no_context"
    if role_rank(ctx.role) < _OPERATOR:
        return False, "unauthorized_role"                 # AG-02: guest/trainee cannot command
    if ctx.director_only and role_rank(ctx.role) < _DIRECTOR:
        return False, "unauthorized_director_only"
    if not permits(mode_from_namespace(ctx.mission_namespace), "command_real_robot"):
        return False, "unauthorized_sandbox"              # AG-08 / EG-02: only LIVE mode commands the rover
    if ctx.safed:
        return False, "unsafe_safed"                      # SF-01: SAFE/hazard active
    if not (ctx.ack_age_s <= ctx.ack_deadline_s):
        return False, "stale_link"                        # NV-12: link stalled past the ack deadline
    if ctx.target_namespace != ctx.mission_namespace:
        return False, "namespace_conflict"
    return True, "eligible"


def eligibility_report(ctx: CommandContext | None) -> dict:
    """[REQ:FS-28] the FULL per-gate verdict for the command-authority EVIDENCE card (Execute pane).

    ``command_eligible`` fails closed on the FIRST unmet gate (the right behaviour for the actual
    interlock); the operator evidence card instead needs EVERY gate's independent pass/fail so a refusal
    names all that is wrong, not just the first. Returns the overall ``eligible`` + ``reason`` plus each
    named gate (authorized / live / safe / fresh / namespaced). Fail-closed for a None context."""
    if ctx is None:
        return {"eligible": False, "reason": "no_context", "authorized": False, "live": False,
                "safe": False, "fresh": False, "namespaced": False}
    authorized = role_rank(ctx.role) >= _OPERATOR and not (
        ctx.director_only and role_rank(ctx.role) < _DIRECTOR)
    ok, reason = command_eligible(ctx)
    return {
        "eligible": ok,
        "reason": reason,
        "authorized": authorized,
        "live": ctx.mission_namespace == "live",
        "safe": not ctx.safed,
        "fresh": ctx.ack_age_s <= ctx.ack_deadline_s,
        "namespaced": ctx.target_namespace == ctx.mission_namespace,
    }
