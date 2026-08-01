"""SR-05: shared JSON-lines journal replay WITH tail repair.

Three durable journals -- the observed twin (`versioned.TwinStore`), the DT-01 canonical world log
(`envelope`) and the BR-02 mission-snapshot lineage (`mission_snapshot`) -- carried the same three-line
pattern: replay the log, `break` on a torn FINAL line (a crash mid-fsync tears only the tail), then
re-arm the writer by assigning `journal_path`. What none of them did was TRUNCATE the torn bytes.

The writer re-arms with `open(path, "a")`, so the next append lands immediately after the torn partial
record -- concatenating onto it, because a torn line has no trailing newline. The 2026-07-28 review
reproduced the consequence on both the twin and the world log:

    torn tail -> restore recovers v1 -> a fresh resync returns ok:True, twin_version:2
              -> the NEXT cold restore silently returns v1, with that resync GONE
              -> one more resync -> ValueError: journal corrupt at interior line 1 (not the tail)

So the write reported success, the next restore lost it, and the one after that refused to load at all.
That directly falsifies the durability invariant asserted in `versioned._append` ("durable before we
report success ... memory == disk, not ahead"): after a torn tail, memory was ahead of a disk the
restore path could no longer read.

This module owns the file-level concern for all three: replay complete records, tolerate exactly one
torn tail, refuse interior corruption (real history loss, never silently dropped), and leave the file
in a state the writer can safely append to.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable


def replay_journal(journal_path: str, apply_record: Callable[[dict[str, Any]], Any], *,
                   what: str) -> int:
    """Replay `journal_path`, applying each complete record, then REPAIR the file's tail.

    `apply_record` receives one parsed record at a time, in order. `what` names the journal in the
    interior-corruption error (e.g. "twin journal").

    Repairs performed, both of which make a subsequent `open(path, "a")` safe:

    * a torn FINAL line is truncated away (it is an incomplete record; the crash that wrote it never
      reported success, so nothing is lost by dropping it);
    * a complete final record with NO trailing newline gets one, so the next append starts its own line
      instead of concatenating onto it.

    Raises ValueError if a line fails to parse anywhere but the tail -- that is genuine history loss and
    is surfaced rather than silently skipped. The file is NOT modified in that case.

    Returns the number of records applied.
    """
    if not os.path.exists(journal_path):
        return 0
    with open(journal_path, encoding="utf-8") as fh:
        raw_lines = fh.readlines()                # keepends: offsets stay exact

    applied = 0
    good_end = 0                                  # byte offset just past the last COMPLETE record
    need_newline = False                          # last good record lacked its line terminator
    torn = False
    last = len(raw_lines) - 1
    for i, raw in enumerate(raw_lines):
        s = raw.strip()
        if not s:                                 # blank padding is not a record; keep its bytes
            good_end += len(raw)
            continue
        try:
            rec = json.loads(s)
        except json.JSONDecodeError:
            if i == last:                         # a crash mid-fsync tears the FINAL line only
                torn = True
                break
            raise ValueError(f"{what} corrupt at interior line {i} (not the tail) "
                             "-- refusing a partial silent restore")
        apply_record(rec)
        applied += 1
        good_end += len(raw)
        need_newline = not raw.endswith("\n")

    if torn or need_newline:
        # SR-05: leave the file exactly at the end of the last complete record, newline-terminated, so
        # the re-armed writer cannot graft its next append onto a partial one.
        with open(journal_path, "r+", encoding="utf-8") as fh:
            fh.truncate(good_end)
            if need_newline:
                fh.seek(good_end)
                fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
    return applied
