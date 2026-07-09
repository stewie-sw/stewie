"""[REQ:MP-10] Rehearsal: a candidate plan -> deterministic conserved-physics prediction -> predicted
outcome + risk score, on SIMULATION branches only (PRD §7 MP-10 / §30 mission-planning; mode-gated per
§29 EG-02).

A rehearsal answers "if we ran this candidate, what happens and how risky is it?" WITHOUT touching live or
accepted truth. It is gated to the SIMULATE modes (DEV / TRAINING / REHEARSAL) through the EG-02 chokepoint
(``require_authority(mode, "simulate")``): LIVE, REPLAY, ARCHIVE, and a missing mode all fail closed, so a
rehearsal can never be run with real-command / accepted-world authority. Every simulate mode provably has
``modify_accepted_world = False`` (the EG-01 §29.1 matrix), and a :class:`RehearsalResult` carries no
world-transaction id -- so a rehearsal is structurally incapable of recording an accepted-world write.

The HOST-buildable core here predicts the outcome DETERMINISTICALLY from the conserved PhysicsBackend
(``physics_scoring.score_candidate``: per-wheel load -> static sinkage -> bearing-capacity feasibility) and
maps it to an MP-05 :class:`RehearsalResult` (predicted outcome + risk score). The full-fidelity
Gazebo/Chrono rehearsal (rolling the whole plan trajectory through the sensor-faithful sim on a sim branch)
is the GATED extension: it plugs in behind this same mode gate and returns the same typed RehearsalResult.
"""
from __future__ import annotations

from pydantic import Field

from stewie.contracts import Contract
from stewie.contracts.governance import (
    EnvironmentMode,
    ModeAuthorityError,
    permits,
    require_authority,
)
from stewie.contracts.physics_scoring import score_candidate
from stewie.contracts.planning_model import RehearsalResult
from stewie.physics.backend import PhysicsBackend


class RehearsalCandidate(Contract):
    """The physical configuration a rehearsal predicts: which vehicle, carrying what payload, is put through
    the conserved-physics prediction on a body. The minimal REAL candidate the HOST-buildable core needs;
    the gated full-fidelity rehearsal consumes the whole plan trajectory."""
    candidate_id: str
    payload_kg: float = Field(default=0.0, ge=0.0)
    vehicle_name: str = "ipex"


def rehearse(candidate: RehearsalCandidate, *, mode: EnvironmentMode | str,
             body: str = "moon", backend: PhysicsBackend | None = None) -> RehearsalResult:
    """Rehearse ``candidate`` on ``body`` in a SIMULATION ``mode`` and return an MP-05 RehearsalResult
    (predicted outcome + risk score). Fails closed unless ``mode`` grants ``simulate`` authority
    (DEV / TRAINING / REHEARSAL -- EG-02): LIVE / REPLAY / ARCHIVE / None raise :class:`ModeAuthorityError`,
    so a rehearsal never runs with real-command or accepted-world authority. The prediction is DETERMINISTIC
    (conserved PhysicsBackend, no randomness) and touches NO accepted truth -- a simulate mode provably
    cannot ``modify_accepted_world`` and the returned RehearsalResult carries no world-transaction id."""
    require_authority(mode, "simulate")                       # only DEV / TRAINING / REHEARSAL
    if permits(mode, "modify_accepted_world"):                # invariant guard: a rehearsal mode may never
        raise ModeAuthorityError(                             # write accepted truth (fail closed even if the
            f"rehearsal mode {getattr(mode, 'value', mode)!r} must not grant modify_accepted_world")  # noqa: E501

    score = score_candidate(body=body, payload_kg=candidate.payload_kg,
                            vehicle_name=candidate.vehicle_name, backend=backend)
    util = (score.contact_pressure_pa / score.allowable_bearing_pa
            if score.allowable_bearing_pa > 0.0 else float("inf"))
    risk_score = min(max(util, 0.0), 1.0)                     # bearing-capacity utilization, clamped to [0,1]

    if score.feasible:
        predicted_outcome = (
            f"feasible: per-wheel sinkage {score.sinkage_m:.4f} m, contact pressure "
            f"{score.contact_pressure_pa:.1f} Pa <= allowable bearing {score.allowable_bearing_pa:.1f} Pa "
            f"(utilization {risk_score:.2f})")
    elif score.contact_pressure_pa > score.allowable_bearing_pa:
        predicted_outcome = (
            f"entrapment risk: contact pressure {score.contact_pressure_pa:.1f} Pa exceeds allowable "
            f"bearing {score.allowable_bearing_pa:.1f} Pa (utilization {util:.2f}); the wheel bears more "
            f"than the regolith can carry")
    else:
        # infeasible with the STATIC bearing satisfied -> the slip-sinkage entrapment gate is what bound
        # (the dominant trafficability failure for the light IPEx); report the true cause, not a false
        # bearing-exceeded message.
        predicted_outcome = (
            f"slip-sinkage entrapment risk: contact pressure {score.contact_pressure_pa:.1f} Pa is within "
            f"the {score.allowable_bearing_pa:.1f} Pa static bearing limit, but the wheels slip-entrap on "
            f"the representative leg slope (the binding trafficability failure runs away)")

    return RehearsalResult(
        rehearsal_id=f"rh-{candidate.candidate_id}-{body}",
        candidate_id=candidate.candidate_id,
        predicted_outcome=predicted_outcome,
        risk_score=risk_score,
        mode=EnvironmentMode(mode).value)
