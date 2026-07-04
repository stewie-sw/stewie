"""[REQ:MP-09] Physics scoring: each candidate carries a real physics score from the CONSERVED PhysicsBackend
(per-wheel load → sinkage, bearing-capacity feasibility); an infeasible candidate is flagged (not silently
ranked); scoring requires a conserved backend."""
import pytest

from stewie.contracts.physics_scoring import (
    PhysicsScore,
    PhysicsScoreError,
    rank_feasible,
    score_candidate,
)


def test_mp09_candidate_carries_a_real_physics_score_from_the_conserved_backend():  # [REQ:MP-09]
    s = score_candidate(body="moon", payload_kg=10.0)
    assert isinstance(s, PhysicsScore)
    assert s.per_wheel_load_n > 0 and s.sinkage_m > 0          # real terramechanics, not fabricated
    assert s.feasible is True and s.score > 0


def test_mp09_infeasible_candidate_is_flagged():  # [REQ:MP-09]
    s = score_candidate(body="moon", payload_kg=100000.0)      # absurd overload -> bearing exceeded
    assert s.contact_pressure_pa > s.allowable_bearing_pa
    assert s.feasible is False and s.score < 0                 # flagged, not silently ranked as good


def test_mp09_rank_excludes_infeasible():  # [REQ:MP-09]
    feas = score_candidate(body="moon", payload_kg=10.0)
    infeas = score_candidate(body="moon", payload_kg=100000.0)
    assert rank_feasible([infeas, feas]) == [feas]            # infeasible never ranked


def test_mp09_requires_a_conserved_backend():  # [REQ:MP-09]
    class _Geom:                                              # a non-conserved geometry-oracle stand-in
        def conserves_mass(self) -> bool:
            return False
    with pytest.raises(PhysicsScoreError):
        score_candidate(body="moon", payload_kg=10.0, backend=_Geom())
