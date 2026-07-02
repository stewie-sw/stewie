"""FS-13: record / version / replay / compare / approve construction + self-docking primitives.

A movement primitive (excavate / dump / berm / dock) records as a versioned, approvable ConstructionSkill
+ its taught path; replay is CLOSED-LOOP (belief feedback corrects onto the taught path -- an open-loop
primitive is rejected at the contract) and SAFETY-BOUNDED (a large believed error HALTS the replay); two
recordings compare by path RMSE; and staging is gated on approval. Kinematic conserved-authority replay;
the force-accurate excavation tier is Tier-3/Chrono-gated and out of scope here.
"""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from stewie import contracts as C
from dart import skill_record_replay as SRR


def _straight(n: int = 8, dx: float = 0.5):
    return [[i * dx, 0.0] for i in range(n)]


def test_record_carries_version_approval_and_closed_loop_invariant():  # [REQ:FS-13]
    rec = SRR.record_primitive("berm", "1.0", _straight())
    assert rec.kind == "berm" and rec.version == "1.0"
    assert rec.skill.closed_loop is True and rec.approved is False and rec.skill.n_steps == 8
    # the closed_loop invariant is enforced at the contract: an open-loop primitive is rejected outright.
    with pytest.raises(ValidationError):
        C.ConstructionSkill(skill_id="x", name="x", kind="berm", version="1", n_steps=3, closed_loop=False)
    # all four construction/docking kinds record.
    for k in ("excavate", "dump", "berm", "dock"):
        assert SRR.record_primitive(k, "1", _straight(3)).kind == k
    with pytest.raises(ValueError):
        SRR.record_primitive("teleport", "1", _straight(3))     # unknown kind rejected


def test_replay_is_belief_corrected_and_tracks_the_taught_path():  # [REQ:FS-13]
    rec = SRR.record_primitive("dock", "1", _straight())
    drift = np.array([0.2, 0.15])

    def believe(i, pos):
        return np.asarray(rec.reference[i]) + drift          # estimator believes it drifted off the path

    res = SRR.replay_with_belief_correction(rec, believe, gain=0.6, safety_bound_m=1.0)
    assert res.halted is False and res.steps_run == len(rec.reference)
    # belief feedback pulled the executed path BACK toward the taught path: corrected error < raw drift.
    assert res.corrected is True
    assert res.max_deviation_m < float(np.linalg.norm(drift)), "belief correction did not reduce the error"


def test_replay_safety_halts_on_a_large_believed_error():  # [REQ:FS-13]
    rec = SRR.record_primitive("excavate", "1", _straight())

    def believe(i, pos):
        d = 0.1 if i < 4 else 2.0                             # in-bound, then a jump past the safety bound
        return np.asarray(rec.reference[i]) + np.array([d, 0.0])

    res = SRR.replay_with_belief_correction(rec, believe, safety_bound_m=1.0)
    assert res.halted is True and "safety bound" in (res.halt_reason or "")
    assert res.steps_run == 4, "the replay must run the in-bound steps then halt at the breach"


def test_two_recordings_compare_by_path_rmse():  # [REQ:FS-13]
    a = SRR.record_primitive("berm", "1", _straight())
    b = SRR.record_primitive("berm", "2", _straight())       # an identical re-record
    assert SRR.compare_recordings(a, b) == pytest.approx(0.0)
    c = SRR.record_primitive("berm", "3", [[x, y + 0.5] for x, y in _straight()])   # shifted 0.5 m
    assert SRR.compare_recordings(a, c) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        SRR.compare_recordings(a, SRR.record_primitive("berm", "4", _straight(3)))   # length mismatch


def test_approval_gates_staging():  # [REQ:FS-13]
    rec = SRR.record_primitive("dump", "1", _straight())
    with pytest.raises(SRR.NotApproved):
        SRR.stage_for_execution(rec)                         # unapproved -> refused
    approved = SRR.record_primitive("dump", "1", _straight(), approved=True, acceptance_note="reviewed")
    staged = SRR.stage_for_execution(approved)
    assert staged["kind"] == "dump" and staged["acceptance_note"] == "reviewed" and staged["n_steps"] == 8
