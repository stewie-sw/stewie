"""[REQ:EG-07] The immutable audit trail: every critical action records the 9 fields
(who/what/when/where/mode/reason/before/after/evidence), append-only + hash-chained, tamper-detectable."""
import dataclasses

from stewie.contracts.audit import GENESIS_HASH, AuditLog, verify_chain

_NINE = ("actor", "action", "timestamp", "location", "mode", "reason",
         "before_state", "after_state", "evidence")


def _live_command(log):
    return log.append(actor="operator:alice", action="command_real_robot", timestamp="2026-07-03T22:00:00Z",
                      location="live/haworth", mode="live", reason="scheduled dig",
                      before_state="pose:0", after_state="pose:1", evidence="bundle:abc")


def _merge(log):
    return log.append(actor="director:bob", action="merge_plan", timestamp="2026-07-03T22:01:00Z",
                      location="main", mode="live", reason="approved plan",
                      before_state="rev:1", after_state="rev:2", evidence="sig:def")


def _config_change(log):
    return log.append(actor="admin:carol", action="config_change", timestamp="2026-07-03T22:02:00Z",
                      location="config/limits", mode="dev", reason="raise cap",
                      before_state="cap:0.5", after_state="cap:0.6", evidence="pr:123")


def test_eg07_three_critical_actions_emit_9_field_records():  # [REQ:EG-07]
    log = AuditLog()
    for rec in (_live_command(log), _merge(log), _config_change(log)):
        for f in _NINE:
            assert getattr(rec, f), f"field {f} missing/empty"
    assert log.verify() is True


def test_eg07_tamper_is_detectable():  # [REQ:EG-07]
    log = AuditLog()
    _live_command(log)
    _merge(log)
    assert log.verify() is True
    recs = list(log.records())
    recs[0] = dataclasses.replace(recs[0], after_state="TAMPERED")     # mutate an earlier record
    assert verify_chain(recs) is False


def test_eg07_append_only_no_mutation_api():  # [REQ:EG-07]
    log = AuditLog()
    _live_command(log)
    assert not any(hasattr(log, m) for m in ("delete", "update", "remove", "pop", "clear"))
    assert isinstance(log.records(), tuple)                            # immutable snapshot


def test_eg07_chain_links_each_record_to_prev():  # [REQ:EG-07]
    log = AuditLog()
    r1 = _live_command(log)
    r2 = _merge(log)
    assert r1.prev_hash == GENESIS_HASH
    assert r2.prev_hash == r1.record_hash                             # hash-chained
    assert r1.record_hash != r2.record_hash
