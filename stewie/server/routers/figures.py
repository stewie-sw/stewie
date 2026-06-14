"""Validation-figures router (ARCH-3): the engineer-pane gallery -- list + serve the PNGs under the
repo-root validation/ tree (served from source; empty on a wheel install). The keys /figures returns
are the allowlist, so /figure/{key} is traversal-proof. No app-module import (no cycle)."""
from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


def _validation_dir() -> str:
    from lode import mission_planner as MP
    return os.path.join(MP._REPO_ROOT, "validation")


def _validation_figures() -> dict:
    """Map 'category/file.png' -> absolute path for every PNG under validation/. Served from the source
    tree (empty if absent, e.g. a wheel install). The returned keys are the allowlist -> traversal-proof."""
    base = _validation_dir()
    out: dict = {}
    if not os.path.isdir(base):
        return out
    for root, _dirs, files in os.walk(base):
        for fn in sorted(files):
            if fn.endswith(".png"):
                rel = os.path.relpath(os.path.join(root, fn), base).replace(os.sep, "/")
                out[rel] = os.path.join(root, fn)
    return out


@router.get("/figures")
def get_figures():
    """List the validation figures (engineer pane). key = 'category/file.png'; fetch via /figure/{key}."""
    figs = _validation_figures()
    return {"ok": True, "figures": [{"key": k, "category": k.split("/")[0], "url": "/figure/" + k}
                                    for k in sorted(figs)]}


@router.get("/figure/{key:path}")
def get_figure(key: str):
    """Serve a validation PNG by allowlisted key (only the keys /figures lists -> no path traversal)."""
    p = _validation_figures().get(key)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no figure {key}"})
    return FileResponse(p, media_type="image/png")
