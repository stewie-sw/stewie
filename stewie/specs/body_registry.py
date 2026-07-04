"""[REQ:BD-02] The body registry: the built-in bodies + LOCAL profile JSON paths, with provenance +
duplicate-id rules. A body that sets soil constants WITHOUT provenance, or carries a fabricated (non-finite /
non-numeric / negative) numeric field, is REJECTED -- the registry ENFORCES that every body constant is
sourced (the project's no-fabrication rule, at the data-ingest boundary). Pure stdlib + stewie_bodies; on-host.
"""
from __future__ import annotations

import dataclasses
import json
import math
from typing import Any

from stewie_bodies import BODIES, Body

#: soil constants -- if any is set, the body MUST carry provenance + a confidence tag (else it is unsourced)
_SOIL = ("bulk_density", "cohesion_pa", "friction_deg", "repose_deg", "bekker")
#: scalar numeric fields that, if present, must be a finite non-negative real number
_NUMERIC = ("g", "bulk_density", "cohesion_pa", "friction_deg", "repose_deg", "ellipsoid_radius_m")


class BodyRegistryError(ValueError):
    """A body profile is invalid: missing a required field, missing provenance for its soil constants, a
    fabricated/invalid numeric field, or a duplicate id."""


def _finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_body_data(data: dict) -> None:
    """Reject an invalid body profile: required fields, positive-finite g, finite non-negative numerics, a
    valid bekker triple, and -- crucially -- provenance + a confidence tag whenever soil constants are set."""
    name = data.get("name", "?")
    for req in ("name", "label", "g", "bekker_regime"):
        if data.get(req) in (None, ""):
            raise BodyRegistryError(f"body {name!r} missing required field {req!r}")
    if not _finite_number(data["g"]) or data["g"] <= 0:
        raise BodyRegistryError(f"body {name!r}: g must be a positive finite number, got {data['g']!r}")
    for f in _NUMERIC:
        v = data.get(f)
        if v is not None and not (_finite_number(v) and v >= 0):
            raise BodyRegistryError(
                f"body {name!r}: field {f!r}={v!r} is not a valid non-negative number (fabricated/invalid)")
    bek = data.get("bekker")
    if bek is not None and not (isinstance(bek, (list, tuple)) and len(bek) == 3
                                and all(_finite_number(x) and x > 0 for x in bek)):
        raise BodyRegistryError(f"body {name!r}: bekker must be 3 positive finite numbers, got {bek!r}")
    if any(data.get(k) is not None for k in _SOIL):
        if not str(data.get("provenance", "")).strip():
            raise BodyRegistryError(f"body {name!r}: soil constants set without provenance (unsourced/fabricated)")
        if not str(data.get("confidence", "")).strip():
            raise BodyRegistryError(f"body {name!r}: soil constants set without a confidence tag")


def body_from_data(data: dict) -> Body:
    """Validate + build a Body from a JSON dict (only the Body fields are used; bekker -> tuple)."""
    validate_body_data(data)
    fields = {f.name for f in dataclasses.fields(Body)}
    kw = {k: v for k, v in data.items() if k in fields}
    if kw.get("bekker") is not None:
        kw["bekker"] = tuple(kw["bekker"])
    return Body(**kw)


def load_body_json(path: str) -> Body:
    """Load + validate one LOCAL body-profile JSON file."""
    with open(path) as f:
        return body_from_data(json.load(f))


def body_registry(*local_paths: str, allow_override: bool = False) -> dict[str, Body]:
    """The built-in BODIES plus any LOCAL profile JSONs. Duplicate-id rule: a local body whose id collides
    with an existing one is REJECTED unless allow_override=True (then the local profile wins)."""
    reg: dict[str, Body] = dict(BODIES)
    for p in local_paths:
        b = load_body_json(p)
        if b.name in reg and not allow_override:
            raise BodyRegistryError(
                f"duplicate body id {b.name!r}: a local profile collides with a built-in "
                f"(pass allow_override=True to override intentionally)")
        reg[b.name] = b
    return reg
