"""Regression checks for the UltraBuild graph and foundation artifact registry."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import validate_ultrabuild as validator
from scripts import validate_ultrabuild_requirements as requirement_validator


def test_ultrabuild_foundation_registry_is_closed() -> None:
    validator.validate_required_files()
    validator.validate_json_files()
    validator.validate_contract_fixtures()
    validator.validate_manifest(validator.load_manifest())


def test_ultrabuild_json_schemas_are_draft_2020_12_objects() -> None:
    root = Path(__file__).resolve().parents[1]
    schemas = sorted((root / "schemas" / "ultrabuild").glob("*.schema.json"))
    assert len(schemas) >= 15
    for path in schemas:
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False


def test_ultrabuild_adversarial_contract_fixtures() -> None:
    """[REQ:SEM-01] [REQ:SEM-02] [REQ:SEM-06] [REQ:TMP-01] [REQ:PRV-01]
    [REQ:UNC-01] [REQ:REC-02] [REQ:REC-03] [REQ:SPA-01] [REQ:EVT-04] [REQ:EVT-05]
    """
    validator.validate_contract_fixtures()


def test_accepted_barrier_cannot_outrun_nodes() -> None:
    manifest = validator.load_manifest()
    manifest["barriers"][0]["status"] = "accepted"
    try:
        validator.validate_manifest(manifest)
    except ValueError as error:
        assert "accepted ahead of nodes" in str(error)
    else:
        raise AssertionError("validator accepted Barrier 1 ahead of its required nodes")


def test_ultrabuild_requirement_registry_is_owned_and_parseable() -> None:
    result = requirement_validator.validate_requirements()
    assert result["total"] == 51
    assert not (set(result["cited_ids"]) - set(result["owners"]))
