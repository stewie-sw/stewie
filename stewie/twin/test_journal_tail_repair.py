"""SR-05 [REQ:CT-03]: a torn journal tail must be TRUNCATED, not merely tolerated.

`from_journal` already recovered every complete record past a torn final line and re-armed the writer
-- but it left the torn bytes in place, and the writer re-arms with `open(path, "a")`. Because a torn
line has no trailing newline, the next append CONCATENATES onto it. The 2026-07-28 review reproduced
the consequence on both the observed twin and the DT-01 world log:

    torn tail -> restore recovers v1 -> a fresh resync returns ok:True, twin_version:2
              -> the NEXT cold restore silently returns v1, with that resync GONE
              -> one more resync -> ValueError: journal corrupt at interior line 1 (not the tail)

The write reported success, the next restore lost it, and the one after refused to load at all. That
falsifies the durability invariant asserted in `versioned._append` ("durable before we report success
... memory == disk, not ahead"): after a torn tail, memory was ahead of a disk the restore path could
no longer read.

The pre-existing test (`test_versioned.test_from_journal_recovers_all_complete_lines_past_a_torn_tail`)
asserts the restore ARTIFACT and never writes after recovery -- so the whole failure lived downstream
of where it stopped looking. These tests write after recovery, which is where the defect is.

Run: <venv>/bin/python -m pytest stewie/twin/test_journal_tail_repair.py -q
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from stewie.twin.journal_io import replay_journal
from stewie.twin.versioned import TwinStore

_TORN = '{"seq": 1, "provenance": "torn-mid-fsy'


def _store(jp):
    return TwinStore(np.zeros((20, 20)), cell_m=5.0, journal_path=jp)


def _restore(jp):
    return TwinStore.from_journal(np.zeros((20, 20)), cell_m=5.0, journal_path=jp)


def test_write_after_torn_tail_recovery_survives_the_next_restore(tmp_path):
    """The SR-05 sequence end to end, on the real TwinStore."""
    jp = str(tmp_path / "j.jsonl")
    tw = _store(jp)
    tw.apply_patch(np.ones((3, 3)), origin_rc=(0, 0), provenance="a")
    with open(jp, "a") as fh:                       # a crash mid-fsync tears the final record
        fh.write(_TORN)

    recovered = _restore(jp)                        # tolerated (this much already worked)
    assert recovered.version == 1

    v = recovered.apply_patch(np.full((3, 3), 2.0), origin_rc=(5, 5), provenance="after-recovery")
    assert v == 2                                   # the write reports success ...

    again = _restore(jp)                            # ... and must STILL be there (pre-fix: silently v1)
    assert again.version == 2, "the post-recovery write was lost by the next cold restore"
    assert any(e.get("provenance") == "after-recovery" for e in again.events)

    again.apply_patch(np.full((3, 3), 3.0), origin_rc=(9, 9), provenance="third")
    final = _restore(jp)                            # pre-fix: ValueError, interior corruption -> twin dead
    assert final.version == 3
    assert [e.get("provenance") for e in final.events] == ["a", "after-recovery", "third"]


def test_the_torn_bytes_are_actually_gone_from_the_file(tmp_path):
    """Truncation is the mechanism -- assert the file, not just the replay."""
    jp = str(tmp_path / "j.jsonl")
    tw = _store(jp)
    tw.apply_patch(np.ones((3, 3)), origin_rc=(0, 0), provenance="a")
    with open(jp, "a") as fh:
        fh.write(_TORN)
    _restore(jp)
    body = open(jp).read()
    assert "torn-mid-fsy" not in body, "the torn record was left in the journal"
    assert body.endswith("\n"), "the repaired journal must be newline-terminated for the next append"
    for ln in body.splitlines():
        if ln.strip():
            json.loads(ln)                          # every surviving line is a complete record


def test_interior_corruption_is_still_refused_and_the_file_is_untouched(tmp_path):
    """Interior corruption is real history loss: surface it, and do not "repair" it away."""
    jp = str(tmp_path / "j.jsonl")
    tw = _store(jp)
    tw.apply_patch(np.ones((3, 3)), origin_rc=(0, 0), provenance="a")
    tw.apply_patch(np.full((3, 3), 2.0), origin_rc=(5, 5), provenance="b")
    lines = open(jp).read().splitlines()
    with open(jp, "w") as fh:                        # corrupt the FIRST of two -> interior
        fh.write("{not json\n" + lines[1] + "\n")
    before = open(jp).read()
    with pytest.raises(ValueError, match="interior line"):
        _restore(jp)
    assert open(jp).read() == before, "a refused restore must not modify the journal"


def test_complete_final_record_without_a_newline_is_terminated(tmp_path):
    """The other half of the concatenation bug: a COMPLETE last record missing its line terminator."""
    jp = str(tmp_path / "j.jsonl")
    tw = _store(jp)
    tw.apply_patch(np.ones((3, 3)), origin_rc=(0, 0), provenance="a")
    body = open(jp).read()
    assert body.endswith("\n")
    with open(jp, "w") as fh:
        fh.write(body.rstrip("\n"))                  # strip the terminator, record still complete

    recovered = _restore(jp)
    assert recovered.version == 1, "a complete final record must not be discarded"
    recovered.apply_patch(np.full((3, 3), 2.0), origin_rc=(5, 5), provenance="b")
    again = _restore(jp)
    assert again.version == 2, "the next append was grafted onto the unterminated record"


def test_replay_journal_on_a_missing_file_is_zero(tmp_path):
    assert replay_journal(str(tmp_path / "absent.jsonl"), lambda _r: None, what="x") == 0


def test_replay_journal_counts_applied_records(tmp_path):
    p = tmp_path / "j.jsonl"
    p.write_text('{"a": 1}\n\n{"a": 2}\n')            # blank padding is not a record
    seen: list[dict] = []
    assert replay_journal(str(p), seen.append, what="x") == 2
    assert [r["a"] for r in seen] == [1, 2]
