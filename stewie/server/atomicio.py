"""Atomic file writes for artifacts that concurrent readers touch.

`bodies.json` (and any other generated artifact a test regenerates in place) is read by
`mission_planner.body_density()`/`body_gravity()` and the GET /bodies.json route. A plain
`open(path, "w")` truncates the file before writing, so a reader that opens it mid-write sees an
empty/partial file -> JSONDecodeError. Under `pytest -n auto` that read-during-write race is real
(#122). Writing to a temp file in the SAME directory and `os.replace()`-ing it into place is atomic
on POSIX (rename(2) within one filesystem): a reader's open() resolves to either the old or the new
COMPLETE inode, never a half-written one.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any


def write_bytes_atomic(path: str, data: bytes) -> None:
    """Write `data` to `path` atomically (temp in the same dir + os.replace)."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".atomic.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_json_atomic(path: str, obj: Any, **dump_kwargs: Any) -> None:
    """Serialize `obj` to JSON and write it to `path` atomically (see write_bytes_atomic)."""
    write_bytes_atomic(path, json.dumps(obj, **dump_kwargs).encode("utf-8"))
