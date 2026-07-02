"""FS-13: record / version / replay / compare / approve movement primitives.

The construction + self-docking skills (excavate, dump, berm, dock) are recorded as versioned, approvable
movement PRIMITIVES: a ConstructionSkill (the contract that already carries version + approval + the
closed_loop invariant) paired with the taught setpoint path. A recording REPLAYS closed-loop -- at each
taught setpoint the estimator's BELIEF of the current pose corrects the command back onto the taught path
(never a blind open-loop replay, which the contract forbids) -- and is SAFETY-BOUNDED: if the believed
tracking error exceeds a bound the replay HALTS rather than driving through a large error. Two recordings
COMPARE by path RMSE, and staging is gated on approval.

Scope (honest): this is the KINEMATIC, conserved-authority replay -- setpoint tracking with belief
feedback + a safety halt, on the 2-D site frame. Force-accurate excavation replay (drum reaction / soil
interaction) is the Tier-3 / Chrono-gated tier and is NOT modelled here; a recording's `kind` names which
primitive it is, and the force tier is deferred, not faked.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from stewie.contracts import ConstructionSkill

_KINDS = ("excavate", "dump", "berm", "traverse", "dock")


@dataclass
class SkillRecording:
    """A recorded, versioned movement primitive: the ConstructionSkill (kind/version/approval/closed_loop
    invariant) + the taught setpoint path (N x 2 site-frame waypoints the primitive should follow)."""
    skill: ConstructionSkill
    reference: np.ndarray            # (N, 2) taught setpoints in the site frame (m)

    def __post_init__(self) -> None:
        self.reference = np.asarray(self.reference, dtype=float)
        if self.reference.ndim != 2 or self.reference.shape[1] != 2 or len(self.reference) < 1:
            raise ValueError("a recording needs a (N>=1, 2) taught setpoint path")

    @property
    def version(self) -> str:
        return self.skill.version

    @property
    def kind(self) -> str:
        return self.skill.kind

    @property
    def approved(self) -> bool:
        return self.skill.approved


def record_primitive(kind: str, version: str, waypoints, *, skill_id: str | None = None,
                     name: str | None = None, approved: bool = False,
                     acceptance_note: str = "") -> SkillRecording:
    """Record a movement primitive from a taught setpoint path. The ConstructionSkill enforces the
    closed_loop invariant (an open-loop primitive is rejected at construction), so a recording is
    closed-loop by definition; version + approval travel with it."""
    if kind not in _KINDS:
        raise ValueError(f"unknown primitive kind {kind!r}; expected one of {_KINDS}")
    wp = np.asarray(waypoints, dtype=float)
    skill = ConstructionSkill(skill_id=skill_id or f"{kind}-{version}", name=name or f"{kind} pass",
                              kind=kind, version=version, n_steps=int(len(wp)), closed_loop=True,
                              approved=approved, acceptance_note=acceptance_note)
    return SkillRecording(skill=skill, reference=wp)


@dataclass
class ReplayResult:
    """The outcome of a belief-corrected, safety-bounded replay."""
    executed: np.ndarray                    # (M, 2) the belief-corrected executed path (M <= N on a halt)
    halted: bool
    halt_reason: str | None
    max_deviation_m: float                  # worst executed-vs-taught error (m) over the steps that ran
    steps_run: int
    corrected: bool = field(default=False)  # did belief feedback actually reduce the error vs open-loop?


def replay_with_belief_correction(rec: SkillRecording, believe, *, gain: float = 0.6,
                                  safety_bound_m: float = 1.0) -> ReplayResult:
    """Replay the taught path CLOSED-LOOP with belief feedback and a safety bound.

    At taught setpoint ``i`` the estimator reports its BELIEVED current pose ``believe(i, pos)`` (drifted
    from the command). The controller forms the tracking error ``ref[i] - belief`` and applies a
    proportional correction (``gain``), so the executed pose returns TOWARD the taught path -- belief
    feedback, not a blind open-loop replay. If the believed error at any step exceeds ``safety_bound_m``
    the replay HALTS (it will not drive through a large error). Returns the executed path + halt state,
    and whether the correction reduced the error below the raw believed drift (``corrected``).
    """
    if not (0.0 < gain <= 1.0):
        raise ValueError("gain must be in (0, 1]")
    ref = rec.reference
    executed: list[np.ndarray] = []
    raw_errs: list[float] = []
    corr_errs: list[float] = []
    pos = ref[0].copy()
    for i in range(len(ref)):
        bel = np.asarray(believe(i, pos), dtype=float)
        if bel.shape != (2,):
            raise ValueError("believe(i, pos) must return a 2-vector (believed x, y)")
        raw = float(np.linalg.norm(bel - ref[i]))          # open-loop error the belief reports
        if raw > safety_bound_m:
            ex = np.array(executed) if executed else ref[:1].copy()
            maxdev = float(max(corr_errs)) if corr_errs else raw
            return ReplayResult(ex, True,
                                f"believed tracking error {raw:.3f}m > {safety_bound_m}m safety bound at step {i}",
                                maxdev, len(executed), corrected=bool(corr_errs and max(corr_errs) < max(raw_errs)))
        pos = bel + gain * (ref[i] - bel)                  # belief-corrected command -> back toward the path
        corr = float(np.linalg.norm(pos - ref[i]))
        executed.append(pos.copy())
        raw_errs.append(raw)
        corr_errs.append(corr)
    ex = np.array(executed)
    maxdev = float(max(corr_errs)) if corr_errs else 0.0
    corrected = bool(corr_errs and raw_errs and max(corr_errs) < max(raw_errs))
    return ReplayResult(ex, False, None, maxdev, len(executed), corrected=corrected)


def compare_recordings(a: SkillRecording, b: SkillRecording) -> float:
    """Path RMSE (m) between two recordings' taught setpoints -> how alike two taught primitives are.
    Requires the same number of setpoints (comparing the same primitive across versions/rerecords)."""
    if a.reference.shape != b.reference.shape:
        raise ValueError("recordings must have the same setpoint count to compare")
    return float(np.sqrt(np.mean(np.sum((a.reference - b.reference) ** 2, axis=1))))


class NotApproved(PermissionError):
    """A recording may not be staged for execution until it is approved."""


def stage_for_execution(rec: SkillRecording) -> dict:
    """Approval gates staging: an unapproved recording cannot be staged (raises NotApproved). An approved
    recording returns its staging descriptor (kind/version/step count + acceptance note)."""
    if not rec.skill.approved:
        raise NotApproved(f"{rec.kind} v{rec.version} is not approved -- record review + approval first")
    return {"skill_id": rec.skill.skill_id, "kind": rec.kind, "version": rec.version,
            "n_steps": rec.skill.n_steps, "acceptance_note": rec.skill.acceptance_note}
