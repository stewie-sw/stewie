"""[REQ:BD-02] the body registry loads built-in bodies + LOCAL profile paths with provenance + duplicate-id
rules, and REJECTS soil constants without provenance or a fabricated numeric field. Tested on the REAL
built-in bodies + a real body round-tripped through a local JSON (never synthetic)."""
import dataclasses
import json

import pytest

from stewie.specs.body_registry import (
    BodyRegistryError,
    body_registry,
    load_body_json,
    validate_body_data,
)
from stewie_bodies import BODIES


def test_bd02_all_builtin_bodies_are_valid_and_sourced():  # [REQ:BD-02]
    for b in BODIES.values():
        validate_body_data(dataclasses.asdict(b))            # every shipped body passes provenance enforcement


def test_bd02_local_profile_path_loads_and_registers(tmp_path):  # [REQ:BD-02]
    d = dataclasses.asdict(BODIES["moon"])                   # a REAL body written to a local profile
    d["name"], d["label"] = "moon_local", "Moon (local)"
    p = tmp_path / "moon_local.json"
    p.write_text(json.dumps(d))
    b = load_body_json(str(p))
    assert b.name == "moon_local" and b.g == BODIES["moon"].g and b.provenance
    reg = body_registry(str(p))
    assert "moon_local" in reg and set(BODIES) <= set(reg)   # built-ins + the local profile


def test_bd02_rejects_soil_constants_without_provenance():  # [REQ:BD-02]
    d = dataclasses.asdict(BODIES["moon"])
    d["name"], d["provenance"] = "x", ""                     # soil constants but no source -> fabricated
    with pytest.raises(BodyRegistryError, match="provenance"):
        validate_body_data(d)


def test_bd02_rejects_a_fabricated_numeric_field():  # [REQ:BD-02]
    base = dataclasses.asdict(BODIES["moon"])
    base["name"] = "x"
    for bad in (float("nan"), -5.0, "170"):                  # non-finite / negative / non-numeric
        with pytest.raises(BodyRegistryError):
            validate_body_data({**base, "cohesion_pa": bad})


def test_bd02_duplicate_id_rejected_unless_override(tmp_path):  # [REQ:BD-02]
    d = dataclasses.asdict(BODIES["moon"])                   # id "moon" collides with the built-in
    p = tmp_path / "moon.json"
    p.write_text(json.dumps(d))
    with pytest.raises(BodyRegistryError, match="duplicate"):
        body_registry(str(p))
    reg = body_registry(str(p), allow_override=True)         # explicit override allowed
    assert reg["moon"].label == BODIES["moon"].label
