"""PO-09: the persisted MISSION wire-format schema is VERSIONED and MIGRATABLE.

Companion to stewie/specs/test_profile_migration.py (the PROFILE half). Where the profile schema has
never had a prior version -- so its migrator registry is honestly EMPTY and a real cross-version
profile round-trip is blocked by the no-synthetic rule -- the MISSION schema HAS a genuine prior
version: the UNVERSIONED wire format that every committed sample mission
(stewie/server/sample_missions/*.json) still ships in and the browser build-queue still posts. So this
exercises a REAL cross-version migration on a REAL legacy fixture (no fabricated data): the unversioned
sample mission is walked LEGACY_MISSION_VERSION -> MISSION_SCHEMA_VERSION and then validates through the
strict loader (mission_from_dict), which migrates before it parses.

Run: PYTHONNOUSERSITE=1 PYTHONPATH=. <venv>/bin/python -m pytest lode/test_mission_migration.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lode.mission_schema import (
    LEGACY_MISSION_VERSION,
    MISSION_SCHEMA_VERSION,
    MissionSchemaError,
    _apply_mission_migration_chain,
    migrate_mission,
)
from lode.planner_model import mission_from_dict

_SAMPLE = (
    Path(__file__).resolve().parents[1]
    / "stewie" / "server" / "sample_missions" / "01_flatten_pad.json"
)


def _real_legacy_mission() -> dict:
    # a REAL, committed, in-repo mission payload -- the unversioned (pre-PO-09) wire format the product
    # ships. Its absence of a schema_version IS the genuine legacy schema (not a fabricated fixture).
    data = json.loads(_SAMPLE.read_text())
    assert "schema_version" not in data, (
        "the committed sample mission must be the genuine legacy (unversioned) format"
    )
    return data


def test_real_legacy_mission_migrates_forward_and_validates():  # [REQ:PO-09]
    legacy = _real_legacy_mission()
    migrated = migrate_mission(legacy)
    assert migrated["schema_version"] == MISSION_SCHEMA_VERSION      # v0 (unversioned) walked to current
    assert "schema_version" not in legacy, "migration must not mutate the caller's dict"
    # the migrated artifact validates through the strict loader AND yields the SAME Mission as the raw
    # legacy dict (the loader migrates internally), so v0 stays byte-compatible with v1.0.
    from_legacy = mission_from_dict(legacy)
    from_migrated = mission_from_dict(migrated)
    assert from_legacy == from_migrated


def test_current_version_mission_migrates_as_identity():  # [REQ:PO-09]
    data = _real_legacy_mission()
    data["schema_version"] = MISSION_SCHEMA_VERSION
    migrated = migrate_mission(data)
    assert migrated["schema_version"] == MISSION_SCHEMA_VERSION
    assert migrated == dict(data), "identity migration must not change a current-version artifact"


def test_unregistered_mission_version_is_rejected_with_a_clear_path_error():  # [REQ:PO-09]
    data = _real_legacy_mission()
    data["schema_version"] = "stewie_mission/9.9"          # a version with no registered migrator
    with pytest.raises(MissionSchemaError, match="no migration path"):
        migrate_mission(data)
    # and the loader refuses it end-to-end (MissionSchemaError is a ValueError -> 400 at the route).
    with pytest.raises(ValueError, match="no migration path"):
        mission_from_dict(data)


def test_mission_migration_registry_walks_a_registered_upgrade_chain():  # [REQ:PO-09]
    # MECHANISM proof on an EXPLICIT local registry (no global-state pollution): register
    # 0.1 -> 0.2 -> current and confirm a 0.1 artifact is walked with each step's transform applied.
    calls: list[str] = []

    def _to_02(d):
        calls.append("0.1->0.2")
        d["added_at_02"] = True
        return d

    def _to_current(d):
        calls.append("0.2->current")
        d["added_at_current"] = True
        return d

    registry = {
        "unit_mission/0.1": ("unit_mission/0.2", _to_02),
        "unit_mission/0.2": (MISSION_SCHEMA_VERSION, _to_current),
    }
    out = _apply_mission_migration_chain(
        {"schema_version": "unit_mission/0.1"}, MISSION_SCHEMA_VERSION, registry
    )
    assert out["schema_version"] == MISSION_SCHEMA_VERSION
    assert out["added_at_02"] is True and out["added_at_current"] is True
    assert calls == ["0.1->0.2", "0.2->current"], "the chain did not apply both steps in order"


def test_mission_migration_chain_detects_a_cycle():  # [REQ:PO-09]
    # a mis-registered migrator that never reaches current must fail loudly, not loop forever.
    registry = {"loop/a": ("loop/b", lambda d: d), "loop/b": ("loop/a", lambda d: d)}
    with pytest.raises(MissionSchemaError, match="cycle"):
        _apply_mission_migration_chain({"schema_version": "loop/a"}, MISSION_SCHEMA_VERSION, registry)


def test_unversioned_payload_enters_the_chain_at_the_legacy_version():  # [REQ:PO-09]
    # the genuine legacy artifact carries NO schema_version -> it enters the registered chain at
    # LEGACY_MISSION_VERSION (proving the registry is real + non-empty) and is walked to current.
    from lode import mission_schema as M
    assert LEGACY_MISSION_VERSION in M._MISSION_MIGRATORS, "the legacy->current migrator must be registered"
    out = migrate_mission({"body": "moon", "orders": [], "charger": [0, 0]})   # no schema_version
    assert out["schema_version"] == MISSION_SCHEMA_VERSION
