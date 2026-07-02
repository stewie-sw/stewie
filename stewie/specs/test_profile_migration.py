"""PO-09: mission/profile schemas are versioned and MIGRATABLE.

The profile loader already carries a schema_version and rejects an unknown one; PO-09 adds the migration
seam: a registered migrator upgrades a prior-version artifact to CURRENT_SCHEMA_VERSION, then the strict
validator runs on the upgraded artifact. A version with no registered migrator is rejected with a clear
"no migration path" error (version-detecting, not the blunt "unsupported").

HONESTY (recorded, not papered over): only the "1.0" schema exists today, so the migrator registry is
EMPTY and there is no real prior PROFILE version to migrate FROM. Fabricating a legacy profile fixture
would violate the no-synthetic-data rule, so a real cross-version PROFILE migration test is BLOCKED until
a second schema_version ships and a migrator is registered for it (see test_cross_version_profile_
migration_is_blocked_until_a_second_schema). What IS closeable and tested here: the identity path (a real
current profile passes through unchanged), the rejection path (an unregistered version is refused), and
the chaining MECHANISM itself (proven on an explicit local registry so the registry is not a stub).

Run: PYTHONNOUSERSITE=1 PYTHONPATH=. <venv>/bin/python -m pytest stewie/specs/test_profile_migration.py -q
"""
from __future__ import annotations

import json

import pytest

from stewie.specs.profiles import (
    CURRENT_SCHEMA_VERSION,
    ProfileError,
    _apply_migration_chain,
    load_profile,
    migrate_profile,
)


def test_current_version_profile_migrates_as_identity():  # [REQ:PO-09]
    # the REAL packaged profile is already at the current schema -> migrate is a no-op and it still loads.
    profile = load_profile("stewie")
    assert profile.data["schema_version"] == CURRENT_SCHEMA_VERSION
    migrated = migrate_profile(profile.data)
    assert migrated["schema_version"] == CURRENT_SCHEMA_VERSION
    assert migrated == dict(profile.data), "identity migration must not mutate a current-version artifact"


def test_unregistered_prior_version_is_rejected_with_a_clear_path_error(tmp_path):  # [REQ:PO-09]
    # a REAL profile whose only change is a schema_version the loader has no migrator for: version-detecting
    # rejection (not a blunt "unsupported"), and load_profile refuses it end-to-end.
    profile = load_profile("stewie")
    data = json.loads(json.dumps(profile.data))
    data["schema_version"] = "solnav_system_profile/0.9"          # a version with no registered migrator
    with pytest.raises(ProfileError, match="no migration path"):
        migrate_profile(data)
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ProfileError, match="no migration path"):
        load_profile(str(path))


def test_migration_registry_walks_a_registered_upgrade_chain():  # [REQ:PO-09]
    # MECHANISM proof on an EXPLICIT local registry (no global-state pollution, no pretend profile schema):
    # register 0.1 -> 0.2 -> 1.0 and confirm a 0.1 artifact is walked to 1.0 with each step's transform
    # applied and each stamped version recorded. This proves the chain is real, not a stub.
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
        "unit_schema/0.1": ("unit_schema/0.2", _to_02),
        "unit_schema/0.2": (CURRENT_SCHEMA_VERSION, _to_current),
    }
    out = _apply_migration_chain({"schema_version": "unit_schema/0.1"}, CURRENT_SCHEMA_VERSION, registry)
    assert out["schema_version"] == CURRENT_SCHEMA_VERSION
    assert out["added_at_02"] is True and out["added_at_current"] is True
    assert calls == ["0.1->0.2", "0.2->current"], "the chain did not apply both steps in order"


def test_migration_chain_detects_a_cycle():  # [REQ:PO-09]
    # a mis-registered migrator that never reaches current must fail loudly, not loop forever.
    registry = {"loop/a": ("loop/b", lambda d: d), "loop/b": ("loop/a", lambda d: d)}
    with pytest.raises(ProfileError, match="cycle"):
        _apply_migration_chain({"schema_version": "loop/a"}, CURRENT_SCHEMA_VERSION, registry)


def test_cross_version_profile_migration_is_blocked_until_a_second_schema():  # [REQ:PO-09]
    # HONESTY GATE: exactly one profile schema version exists, so the registry is empty. This test RECORDS
    # that state -- when a real "2.0" schema ships, register its migrator and add a real round-trip test on
    # a genuine prior artifact (do NOT fabricate one to make this pass sooner).
    from stewie.specs import profiles as P
    assert P._PROFILE_MIGRATORS == {}, (
        "a migrator is registered -- add a real cross-version round-trip test on a genuine prior artifact"
    )
    assert CURRENT_SCHEMA_VERSION.endswith("/1.0"), "only the 1.0 schema exists; a 2nd version now ships"
