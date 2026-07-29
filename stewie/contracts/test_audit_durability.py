"""[REQ:EG-07] SR-04: the executive audit chain must SURVIVE a process restart, and an EMPTY chain must
never report itself verified.

The 2026-07-28 review found the EG-07 hash chain was a module-global list with no persistence path: a
redeploy -- the routine operation in deploy/DEPLOY.md -- destroyed every director release, SIM run and
reconciliation record, after which GET /executive/audit answered {"verified": true, "count": 0}. An
operator could not distinguish "no privileged action was ever taken" from "the entire authority record
was destroyed", and the EV-01 evidence bundle embedded that same positive verdict as proof.

Two properties are asserted here:
  - DURABILITY: records written by one AuditLog are readable, in order, hash-chain intact, by a fresh
    AuditLog over the same journal (the restart).
  - HONEST EMPTINESS: an empty chain reports integrity None ("nothing to verify"), not True.

Real on-disk journal against a tmp dir. No mocks -- the restart is a genuinely new object over the file.

Run: <venv>/bin/python -m pytest stewie/contracts/test_audit_durability.py -q
"""
from __future__ import annotations

import os

import pytest

from stewie.contracts.audit import AuditIntegrityError, AuditLog, GENESIS_HASH, verify_chain


def _append(lg, action, *, actor="director:alice@x.com", ts="2026-07-28T00:00:00+00:00"):
    return lg.append(actor=actor, action=action, timestamp=ts, location="pad-a@haworth",
                     mode="sim", reason="test", before_state="a", after_state="b", evidence="sha:beef")


def test_empty_chain_reports_none_not_verified(tmp_path):
    """An empty log has nothing to attest. Reporting True let a wiped chain masquerade as a clean one."""
    lg = AuditLog(journal_path=str(tmp_path / "chain.jsonl"))
    assert lg.records() == ()
    assert lg.integrity() is None            # NOT True -- 'no records' is not 'verified'


def test_records_survive_a_restart(tmp_path):
    """The SR-04 core: a fresh AuditLog over the same journal reconstructs the chain a redeploy used to erase."""
    p = str(tmp_path / "chain.jsonl")
    lg = AuditLog(journal_path=p)
    _append(lg, "executive.release")
    _append(lg, "executive.run")
    assert lg.integrity() is True and len(lg.records()) == 2

    restarted = AuditLog(journal_path=p)      # the redeploy
    assert len(restarted.records()) == 2, "a restart erased the authority record"
    assert [r.action for r in restarted.records()] == ["executive.release", "executive.run"]
    assert restarted.integrity() is True
    assert verify_chain(restarted.records()) is True


def test_restart_preserves_chain_linkage_so_a_later_append_extends_it(tmp_path):
    """A reloaded chain must keep its tail hash, or the next append silently starts a second chain."""
    p = str(tmp_path / "chain.jsonl")
    lg = AuditLog(journal_path=p)
    first = _append(lg, "executive.release")
    restarted = AuditLog(journal_path=p)
    nxt = _append(restarted, "executive.reconcile")
    assert nxt.prev_hash == first.record_hash, "reloaded chain lost its tail -> forked chain"
    assert restarted.integrity() is True
    assert AuditLog(journal_path=p).integrity() is True


def test_tampered_journal_line_is_detected_after_restart(tmp_path):
    """Durability must not cost tamper-evidence: editing a persisted field breaks the chain on reload."""
    p = str(tmp_path / "chain.jsonl")
    lg = AuditLog(journal_path=p)
    _append(lg, "executive.release")
    _append(lg, "executive.run")
    body = open(p).read().replace('"reason": "test"', '"reason": "tampered"', 1)
    open(p, "w").write(body)
    assert AuditLog(journal_path=p).integrity() is False, "a mutated persisted field must break the chain"


def test_truncated_tail_line_is_detected_not_silently_dropped(tmp_path):
    """A torn last line is corruption of the authority record -- it must surface, not vanish."""
    p = str(tmp_path / "chain.jsonl")
    lg = AuditLog(journal_path=p)
    _append(lg, "executive.release")
    _append(lg, "executive.run")
    body = open(p).read()
    open(p, "w").write(body[: body.rindex("\n", 0, len(body) - 1) + 1] + '{"actor": "trunc')
    assert AuditLog(journal_path=p).integrity() is False


@pytest.mark.parametrize("damage", ["tamper", "truncate"])
def test_corrupt_journal_cannot_be_extended(tmp_path, damage):
    """Fail closed: appending must neither bless nor concatenate onto a damaged authority record."""
    p = str(tmp_path / "chain.jsonl")
    lg = AuditLog(journal_path=p)
    _append(lg, "executive.release")
    original = open(p).read()
    if damage == "tamper":
        damaged = original.replace('"reason": "test"', '"reason": "tampered"', 1)
    else:
        damaged = original.rstrip("\n")[:-12]
    open(p, "w").write(damaged)

    restarted = AuditLog(journal_path=p)
    before = open(p, "rb").read()
    with pytest.raises(AuditIntegrityError):
        _append(restarted, "executive.run")
    assert open(p, "rb").read() == before, "a corrupt journal was modified while append was refused"


def test_two_independent_log_instances_extend_one_chain(tmp_path):
    """Two backend workers must reload the tail under an OS lock instead of creating sibling records."""
    p = str(tmp_path / "chain.jsonl")
    first_worker = AuditLog(journal_path=p)
    second_worker = AuditLog(journal_path=p)
    first = _append(first_worker, "executive.release")
    second = _append(second_worker, "executive.run")
    assert second.prev_hash == first.record_hash
    assert len(first_worker.records()) == 2, "read-side snapshot did not observe the other worker's append"

    cold = AuditLog(journal_path=p)
    assert [r.action for r in cold.records()] == ["executive.release", "executive.run"]
    assert cold.integrity() is True


@pytest.mark.parametrize("damage", ["delete", "zero"])
def test_audit_head_refuses_journal_regression(tmp_path, damage):
    """A durable high-water mark prevents deletion/truncation from becoming a fresh genesis chain."""
    p = str(tmp_path / "chain.jsonl")
    live = AuditLog(journal_path=p)
    _append(live, "executive.release")
    if damage == "delete":
        os.unlink(p)
    else:
        open(p, "w").close()

    with pytest.raises(AuditIntegrityError, match="regressed"):
        _append(live, "executive.run")
    assert live.integrity() is False

    restarted = AuditLog(journal_path=p)
    assert restarted.integrity() is False
    with pytest.raises(AuditIntegrityError, match="regressed"):
        _append(restarted, "executive.run")


def test_in_memory_log_still_works_without_a_journal(tmp_path):
    """Back-compat: an AuditLog with no path stays a pure in-memory chain (the pre-SR-04 contract)."""
    lg = AuditLog()
    assert lg.integrity() is None
    r = _append(lg, "executive.release")
    assert r.prev_hash == GENESIS_HASH
    assert lg.integrity() is True


def test_append_raises_when_the_journal_cannot_be_written(tmp_path):
    """An authority record that was NOT durably written must not report success (the AR-004 posture)."""
    p = tmp_path / "nodir"
    p.mkdir()
    p.chmod(0o500)                                   # read+execute, not writable
    lg = AuditLog(journal_path=str(p / "chain.jsonl"))
    try:
        with pytest.raises(OSError):
            _append(lg, "executive.release")
    finally:
        p.chmod(0o700)
