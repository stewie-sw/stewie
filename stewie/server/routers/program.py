"""Program board (PO lane): the /program page + its committed snapshot of the PRD section-7 matrix.

The deployed backend has no PRD.md (the image ships only the installed packages), so the board serves
stewie/server/program_snapshot.json -- generated from the COMMITTED PRD + FANOUT_SPECS + [REQ:] citations
by scripts/gen_program_snapshot.py (the bodies.json pattern). Provenance (source hashes + the PRD's
last-touch commit) is inside the payload and rendered on the page, so a stale snapshot is visible, never
silent. GET-only, read-only, no secrets (the sources are the public repo) -> open, like the other GET
surfaces."""
from __future__ import annotations

import json
import os
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()

_SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SNAPSHOT = os.path.join(_SERVER_DIR, "program_snapshot.json")
_PAGE = os.path.join(_SERVER_DIR, "web", "program.html")


@lru_cache(maxsize=1)
def _snapshot() -> dict:
    # the artifact is baked into the image -> immutable for the process lifetime, cache the parse
    with open(_SNAPSHOT, encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/program")
def program_page():
    if not os.path.exists(_PAGE):
        raise HTTPException(status_code=404, detail="program board page missing from this build")
    return FileResponse(_PAGE, media_type="text/html; charset=utf-8")


@router.get("/program/snapshot")
def program_snapshot():
    try:
        return _snapshot()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="program_snapshot.json missing from this build; "
                                                    "regenerate: scripts/gen_program_snapshot.py") from None
