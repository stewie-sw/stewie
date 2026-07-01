"""DT-01 (PRD §27.2.D + §6.2 W-1/W-4): the versioned world-state TRANSACTION ENVELOPE.

One hash-chained, provenance-stamped record links the four independently-read world-state sources
into ONE consistent linked snapshot: the conserved physics authority (a content sha of the
ColumnState), the observed TwinStore (version + latest event hash), the latest PlanResult id, and a
belief snapshot. A query returns this single linked record (not four independent reads that may
disagree). W-1: each commit appends durably (fsync). W-4: a cold restore rebuilds the log from the
journal alone and reproduces the latest world sha BIT-EXACT, and the chain verifies.

These tests exercise envelope linking + hash-chaining (1) and durable journal + cold restore (2).
Real ColumnState, real TwinStore, real PlanResult contract -- no synthetic stand-ins.
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.contracts import BeliefState, PlanResult
from stewie.physics.column_state import ColumnState
from stewie.twin import envelope as E
from stewie.twin import versioned as vt


def _authority() -> ColumnState:
    """A small REAL conserved column state (subsampled grid, default uniform regolith layer)."""
    return ColumnState(width=16, height=16, cell_m=0.5)


def _twin() -> vt.TwinStore:
    rng = np.random.default_rng(11)
    tw = vt.TwinStore(rng.normal(0.0, 0.05, (32, 32)), cell_m=0.5)
    tw.apply_patch(np.full((4, 4), 0.2), origin_rc=(3, 3), provenance="resync: COLMAP site A")
    return tw


def _plan() -> PlanResult:
    return PlanResult(plan_id="pad-001", feasible=True, n_orders=3, vehicles=1,
                      makespan_s=420.0, energy_j=1.2e6)


def _belief() -> BeliefState:
    return BeliefState(vehicle_id="ipex", row=4.0, col=5.0, yaw_rad=0.1, pos_sigma_m=0.3)


# ---- (1) envelope links + hash-chains -----------------------------------------------------------

def test_envelope_links_all_four_sources_into_one_record():
    """[REQ:DT-01]: one versioned transaction envelope links the conserved authority, the observed
    TwinStore, the latest PlanResult, and the belief snapshot, with mission/site/body/time/provenance."""
    log = E.TransactionLog()
    txn = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                     mission="LSP-1", site="haworth", body="moon", mission_t_s=100.0,
                     provenance="sol-1 checkpoint")
    # the single linked record carries every source's identity
    assert txn.authority_sha and len(txn.authority_sha) == 64
    assert txn.twin_version == 1 and txn.twin_hash != "genesis"
    assert txn.plan_id == "pad-001"
    assert txn.belief["vehicle_id"] == "ipex" and txn.belief["pos_sigma_m"] == 0.3
    assert txn.mission == "LSP-1" and txn.site == "haworth" and txn.body == "moon"
    assert txn.mission_t_s == 100.0 and txn.provenance == "sol-1 checkpoint"
    assert txn.seq == 0 and txn.world_sha and len(txn.world_sha) == 64


def test_world_sha_is_a_function_of_all_four_sources():
    """Changing ANY linked source changes the world sha -- the record is a consistent linked snapshot,
    not four independent reads. (If one source were dropped from the digest, its mutation wouldn't
    move the sha -- this catches that.)"""
    a, tw, pl, bl = _authority(), _twin(), _plan(), _belief()
    base = E.TransactionLog().commit(authority=a, twin=tw, plan=pl, belief=bl,
                                     mission="m", site="haworth", body="moon", mission_t_s=0.0,
                                     provenance="p")
    # mutate the authority only (cut a real boolean-masked region into the drum)
    a2 = _authority()
    mask = np.zeros((16, 16), dtype=bool); mask[0:2, 0:2] = True
    a2.cut_to_inventory(mask, 1.0)
    s_auth = E.TransactionLog().commit(authority=a2, twin=tw, plan=pl, belief=bl,
                                       mission="m", site="haworth", body="moon", mission_t_s=0.0,
                                       provenance="p").world_sha
    # mutate the twin only
    tw2 = _twin(); tw2.apply_patch(np.full((2, 2), 0.9), origin_rc=(0, 0), provenance="extra")
    s_twin = E.TransactionLog().commit(authority=a, twin=tw2, plan=pl, belief=bl,
                                       mission="m", site="haworth", body="moon", mission_t_s=0.0,
                                       provenance="p").world_sha
    # mutate the plan only
    pl2 = PlanResult(plan_id="other", feasible=True, n_orders=1, vehicles=1, makespan_s=1.0,
                     energy_j=1.0)
    s_plan = E.TransactionLog().commit(authority=a, twin=tw, plan=pl2, belief=bl,
                                       mission="m", site="haworth", body="moon", mission_t_s=0.0,
                                       provenance="p").world_sha
    # mutate the belief only
    bl2 = BeliefState(vehicle_id="ipex", row=4.0, col=5.0, pos_sigma_m=9.9)
    s_bel = E.TransactionLog().commit(authority=a, twin=tw, plan=pl, belief=bl2,
                                      mission="m", site="haworth", body="moon", mission_t_s=0.0,
                                      provenance="p").world_sha
    shas = {base.world_sha, s_auth, s_twin, s_plan, s_bel}
    assert len(shas) == 5, "each of the four sources must contribute to the world sha"


def test_transactions_are_hash_chained_and_tamper_evident():
    log = E.TransactionLog()
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="t0")
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=1.0, provenance="t1")
    assert log.verify_chain()
    assert log.transactions[1].prev_hash == log.transactions[0].chain_hash   # links to predecessor
    log.transactions[0].provenance = "FORGED"
    assert not log.verify_chain()


def test_latest_returns_one_consistent_linked_record():
    log = E.TransactionLog()
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="t0")
    last = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                      mission="m", site="haworth", body="moon", mission_t_s=2.0, provenance="t1")
    got = log.latest()
    assert got is last and got.seq == 1 and got.mission_t_s == 2.0


def test_commit_requires_provenance():
    log = E.TransactionLog()
    with pytest.raises(ValueError):
        log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                   mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="")


# ---- (2) W-1 durable journal + W-4 cold restore -------------------------------------------------

def test_w1_each_commit_is_durably_journalled(tmp_path):
    jp = str(tmp_path / "world.journal")
    log = E.TransactionLog(journal_path=jp)
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="t0")
    import os
    assert os.path.exists(jp) and os.path.getsize(jp) > 0       # written before commit returned


def test_w4_cold_restore_reproduces_the_world_sha_bit_exact(tmp_path):
    """[REQ:DT-01] W-4: rebuild the world transaction log from the journal ALONE (cold -- no
    in-process state) and reproduce the latest world sha BIT-EXACT; the chain verifies."""
    jp = str(tmp_path / "world.journal")
    log = E.TransactionLog(journal_path=jp)
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="sol-1")
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=5.0, provenance="sol-2")
    want_sha = log.latest().world_sha
    want_chain = log.latest().chain_hash
    want_n = len(log.transactions)
    del log                                                     # the process "dies"

    cold = E.TransactionLog.from_journal(jp)                    # cold restore from journal alone
    assert len(cold.transactions) == want_n
    assert cold.latest().world_sha == want_sha                 # BIT-EXACT world sha after cold restore
    assert cold.latest().chain_hash == want_chain
    assert cold.verify_chain()


def test_crash_between_checkpoints_recovers_from_the_journal(tmp_path):
    """A crash mid-fsync tears the FINAL journal line only; cold restore recovers every COMPLETE
    prior transaction (the entrapment-equivalent for the world log) rather than aborting the replay."""
    jp = str(tmp_path / "world.journal")
    log = E.TransactionLog(journal_path=jp)
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="a")
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=1.0, provenance="b")
    want_sha = log.latest().world_sha
    with open(jp, "a") as f:
        f.write('{"seq": 2, "provenance": "torn", "world_sha": "abc')   # a torn final line
    cold = E.TransactionLog.from_journal(jp)
    assert len(cold.transactions) == 2                          # both complete records recovered
    assert cold.latest().world_sha == want_sha
    assert cold.verify_chain()


def test_interior_journal_corruption_is_surfaced_not_silently_dropped(tmp_path):
    """A torn line that is NOT the tail is real history loss -- refuse a partial silent restore."""
    jp = str(tmp_path / "world.journal")
    log = E.TransactionLog(journal_path=jp)
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=0.0, provenance="a")
    log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
               mission="m", site="haworth", body="moon", mission_t_s=1.0, provenance="b")
    lines = open(jp).read().splitlines()
    lines[0] = '{"seq": 0, "provenance": "torn inte'             # corrupt an INTERIOR (non-tail) line
    with open(jp, "w") as f:
        f.write("\n".join(lines) + "\n")
    with pytest.raises(ValueError, match="interior"):
        E.TransactionLog.from_journal(jp)


# ---- (3) DT-01 extension: runtime packet + vehicle twin join the one linked envelope --------------

def _packet() -> dict:
    """A REAL runtime packet built from the module's channel functions (deterministic, not synthetic)."""
    from stewie.twin import runtime_packet as RP
    return {"joints": RP.joint_channel(0.1, 0.2, t=1.0), "power": RP.power_channel(40.0, 0.8, t=1.0)}


# a representative vehicle-twin IDENTITY (instance/vehicle/body + the physics scalars that distinguish
# two twins) -- the envelope links the identity, not the full assembled object, so this is hermetic.
_VT = {"instance": "ipex-1", "vehicle": "ipex", "body": "moon", "gravity_ms2": 1.62, "mass_kg": 300.0}


def test_envelope_links_runtime_packet_and_vehicle_twin():
    """[REQ:DT-01]: a runtime packet + a vehicle twin join the ONE linked transaction (packet_sha +
    vehicle_sha), are covered by the world_sha (linking them moves it), and the chain still verifies."""
    log = E.TransactionLog()
    base = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                      mission="LSP-1", site="haworth", body="moon", mission_t_s=1.0, provenance="p1")
    linked = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                        mission="LSP-1", site="haworth", body="moon", mission_t_s=2.0, provenance="p2",
                        packet=_packet(), vehicle_twin=_VT)
    assert base.packet_sha == "" and base.vehicle_sha == ""           # unlinked -> empty by default
    assert len(linked.packet_sha) == 64 and len(linked.vehicle_sha) == 64
    assert linked.packet_sha == E.packet_identity(_packet())
    assert linked.vehicle_sha == E.vehicle_identity(_VT)
    # the packet + vehicle are part of the snapshot: the world_sha WITH them differs from WITHOUT them
    without = E._world_sha(linked.authority_sha, linked.twin_version, linked.twin_hash, linked.plan_id,
                           linked.belief, linked.mission, linked.site, linked.body, linked.mission_t_s,
                           linked.provenance, linked.uncertainty_m)
    assert linked.world_sha != without
    assert log.verify_chain()


def test_unlinked_packet_vehicle_is_backward_compatible():
    """[REQ:DT-01]: a transaction with no packet/vehicle OMITS those keys from its hashed body, so its
    world_sha + chain_hash are byte-identical to a pre-extension record -- old journals still verify."""
    log = E.TransactionLog()
    txn = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                     mission="LSP-1", site="haworth", body="moon", mission_t_s=1.0, provenance="p")
    body = txn.linked_body()
    assert "packet_sha" not in body and "vehicle_sha" not in body     # omitted when empty
    # equals the pre-extension world_sha formula (called without the packet/vehicle args)
    assert txn.world_sha == E._world_sha(txn.authority_sha, txn.twin_version, txn.twin_hash, txn.plan_id,
                                         txn.belief, txn.mission, txn.site, txn.body, txn.mission_t_s,
                                         txn.provenance, txn.uncertainty_m)
    assert log.verify_chain()


def test_cold_restore_reproduces_packet_and_vehicle_bit_exact(tmp_path):
    """[REQ:DT-01] W-4: a cold rebuild from the journal reproduces the linked packet + vehicle
    identities bit-exact and re-verifies the chain."""
    jp = str(tmp_path / "world.journal")
    log = E.TransactionLog(journal_path=jp)
    warm = log.commit(authority=_authority(), twin=_twin(), plan=_plan(), belief=_belief(),
                      mission="LSP-1", site="haworth", body="moon", mission_t_s=1.0, provenance="p",
                      packet=_packet(), vehicle_twin=_VT)
    cold = E.TransactionLog.from_journal(jp)
    assert cold.latest().packet_sha == warm.packet_sha
    assert cold.latest().vehicle_sha == warm.vehicle_sha
    assert cold.latest().world_sha == warm.world_sha
    assert cold.verify_chain()
