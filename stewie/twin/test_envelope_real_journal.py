"""Recovery regressions using the recorded 2026-10-14 architecture audit journal.

Source: /tmp/stewie-architecture-runtime-20261014/twin/world.journal
SHA256: 1e39943a7eecdaa533f429c6c9f6565aec1c36ac7ad4be1ed6dbb49906829a5d
The audit resynced an unchanged DEM crop; this is not measured sensor evidence.
Fault cases truncate or alter copies; appends reuse the recorded snapshot without inventing terrain observations.
"""
from dataclasses import asdict
import hashlib
import json

import pytest

from stewie.twin.envelope import TransactionLog


@pytest.fixture
def audit_journal():
    raw = (
        b'{"authority_sha": "genesis", "belief": {}, "body": "moon", '
        b'"chain_hash": "cc1ccab9c4d210e040389b8d909dfdf3fef32e9e812d6ed1788bd694f95ea838", '
        b'"mission": "none", "mission_t_s": 0.0, "packet_sha": "", "plan_id": "none", '
        b'"prev_hash": "genesis", "provenance": "twin.resync: Architecture audit: '
        b'unchanged 2x2 source DEM crop, not sensor evidence; '
        b'samples/lunar_dem/haworth_10km_5m/heightmap.rf32", "seq": 0, "site": "haworth", '
        b'"twin_hash": "0dd84e04de81f25ae15a02b5e423958498b2edcfd92a6fffd464aecc88681ba4", '
        b'"twin_version": 1, "uncertainty_m": 0.0, "vehicle_sha": "", '
        b'"world_sha": "177c540fda1bd0d68171803a78358af20304e2e9155fda7562e65bfd7a965ce0"}\n'
    )
    assert hashlib.sha256(raw).hexdigest() == (
        "1e39943a7eecdaa533f429c6c9f6565aec1c36ac7ad4be1ed6dbb49906829a5d"
    )
    return raw


@pytest.mark.parametrize("ending", ["intact", "torn", "torn-blank-tail", "missing-newline"])
def test_recorded_journal_retains_acknowledged_appends_after_two_restarts(tmp_path, audit_journal, ending):
    journal = tmp_path / "world.journal"
    original = audit_journal
    if ending.startswith("torn"):
        original += audit_journal[:len(audit_journal) // 2]
        if ending == "torn-blank-tail":
            original += b"\n \n"
    elif ending == "missing-newline":
        original = original[:-1]
    journal.write_bytes(original)

    log = TransactionLog.from_journal(str(journal))
    expected = [json.loads(audit_journal)]
    assert [asdict(txn) for txn in log.transactions] == expected
    assert log.verify_chain()
    assert journal.read_bytes() == audit_journal
    backups = list(tmp_path.glob("world.journal.recovery-*"))
    assert len(backups) == (0 if ending == "intact" else 1)
    if backups:
        assert backups[0].read_bytes() == original

    snapshot = {key: value for key, value in expected[0].items()
                if key not in {"seq", "prev_hash", "world_sha", "chain_hash"}}
    for _ in range(2):
        acknowledged = log.commit_snapshot(**snapshot)
        expected.append(asdict(acknowledged))
        before_restart = journal.read_bytes()
        log = TransactionLog.from_journal(str(journal))
        assert [asdict(txn) for txn in log.transactions] == expected
        assert log.verify_chain()
        assert journal.read_bytes() == before_restart
        assert before_restart.startswith(audit_journal)
    assert set(tmp_path.glob("world.journal.recovery-*")) == set(backups)


def test_recorded_interior_corruption_does_not_rewrite_history(tmp_path, audit_journal):
    journal = tmp_path / "world.journal"
    original = audit_journal + audit_journal[:len(audit_journal) // 2] + b"\n" + audit_journal
    journal.write_bytes(original)
    with pytest.raises(ValueError, match="interior"):
        TransactionLog.from_journal(str(journal))
    assert journal.read_bytes() == original
    assert list(tmp_path.iterdir()) == [journal]


@pytest.mark.parametrize("field", ["chain_hash", "world_sha", "prev_hash", "seq"])
def test_recorded_hash_mismatch_prevents_tail_repair(tmp_path, audit_journal, field):
    journal = tmp_path / "world.journal"
    record = json.loads(audit_journal)
    record[field] = 1 if field == "seq" else record[field][:-1]
    original = json.dumps(record, sort_keys=True).encode() + b"\n" + audit_journal[:100]
    journal.write_bytes(original)
    with pytest.raises(ValueError, match="hash mismatch"):
        TransactionLog.from_journal(str(journal))
    assert journal.read_bytes() == original
    assert list(tmp_path.iterdir()) == [journal]
