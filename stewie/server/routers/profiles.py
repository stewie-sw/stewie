"""Profiles router (ARCH-3): saved planning-config snapshots -- a full body/soil/fleet/orders
config stored under a slug at data_dir/profiles. Self-contained: server.deps for auth, the io_fields
atomic writer, and a call-time profiles-dir resolution (a relocated data_dir is always honored, and
the test fixtures stay reload-safe). No import of the app module (no cycle)."""
from __future__ import annotations

import json
import os
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stewie.server.deps import require_auth, require_role
from stewie.twin.io_fields import atomic_write_bytes

router = APIRouter()


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)      # saved under a slug of this name
    profile: dict = Field(default_factory=dict)         # the full config snapshot (body/soil/fleet/orders/...)


def _profiles_dir() -> str:
    from stewie.specs import config as CFG
    return CFG.profiles_dir()


def _profile_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(name).lower()).strip("-") or "profile"


@router.post("/profile")
def post_profile(req: ProfileRequest, _auth: None = Depends(require_role("operator"))):
    """Save a planning profile (the full config snapshot) under a slug of its name, to profiles/.
    #304 (AG-07): the profile store is SHARED + name-keyed (no owner namespace) and loading a profile
    restores the WHOLE planning config (body/soil/fleet/orders), so WRITING it is operator+ -- a
    guest/trainee (below operator on the AG-01 ladder) must not clobber the shared library. The exact
    sibling of the #294 structures-write gate. Reads (/profiles, /profile/{name}) stay any-auth (S-06)."""
    d = _profiles_dir()
    os.makedirs(d, exist_ok=True)
    slug = _profile_slug(req.name)
    atomic_write_bytes(os.path.join(d, slug + ".json"),                  # PO-02: atomic, no partial profile
                       json.dumps({"name": req.name, "profile": req.profile}, indent=2).encode("utf-8"))
    return {"ok": True, "name": slug}


@router.get("/profiles")
def get_profiles(_auth: str = Depends(require_auth)):
    """List the saved profile slugs. S-06: operational reads require auth."""
    d = _profiles_dir()
    if not os.path.isdir(d):
        return {"ok": True, "profiles": []}
    return {"ok": True, "profiles": sorted(os.path.splitext(f)[0]
                                           for f in os.listdir(d) if f.endswith(".json"))}


@router.get("/profile/{name}")
def get_profile(name: str, _auth: str = Depends(require_auth)):
    """Load a saved profile by slug -> {name, profile}. S-06: operational reads require auth."""
    slug = _profile_slug(name)
    p = os.path.join(_profiles_dir(), slug + ".json")
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no profile {slug!r}"})
    with open(p) as fh:
        return json.load(fh)
