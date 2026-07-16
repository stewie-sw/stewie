"""PO-09: the persisted MISSION wire-format schema is VERSIONED and MIGRATABLE.

The browser build-order queue (planet_browser / index.html) posts a mission dict to ``/plan`` and
``mission_from_dict`` (lode.planner_model) parses it. Historically that dict carried NO version marker
-- the "v0" (pre-versioning) mission schema, still the exact shape every committed sample mission
(``stewie/server/sample_missions/*.json``) ships in. PO-09 adds the forward-compatibility seam,
mirroring ``stewie.specs.profiles``: a migrator registry upgrades a prior-version artifact to
``MISSION_SCHEMA_VERSION``, the loader detects the artifact's version and walks the registered chain,
then the strict parser runs on the upgraded artifact. A version with no registered migrator is rejected
with a clear "no migration path" error (version-detecting, not a blunt "unsupported").

Unlike the PROFILE side -- whose schema has never had a prior version, so its registry is honestly
EMPTY and a real cross-version round-trip is blocked by the no-synthetic rule -- the MISSION schema HAS
a genuine prior version: the UNVERSIONED wire format in production and in every committed sample
mission. An artifact with no ``schema_version`` enters the chain at ``LEGACY_MISSION_VERSION`` and is
walked forward, so the migration is exercised end-to-end on REAL data (no fabricated fixture).

HONESTY: v0 -> v1.0 is version ADOPTION. The mission wire format only ever grew ADDITIVELY (optional
fields default when absent: ``physics_backend_id``, ``mission_windows``, ``shared_resources``,
``observations``, ...), so a v0 artifact is field-compatible with v1.0 and the migration stamps the
marker without renaming or dropping a field. That is the honest transform -- fabricating a field change
to make the migrator "look busier" would violate the no-synthetic rule. What is real and load-bearing:
the registry walks a genuine unversioned artifact to the current version and it then validates through
the strict loader.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping

#: the schema_version a mission wire-format artifact is stamped with after migration.
MISSION_SCHEMA_VERSION = "stewie_mission/1.0"

#: the implicit version of a pre-versioning mission dict (no ``schema_version`` key) -- the genuine
#: legacy format every committed sample mission ships in. Migrated forward to MISSION_SCHEMA_VERSION.
LEGACY_MISSION_VERSION = "stewie_mission/0"

_Migrator = Callable[[MutableMapping[str, Any]], MutableMapping[str, Any]]


class MissionSchemaError(ValueError):
    """A mission artifact declares a schema_version with no registered migration path to the current one.

    A ``ValueError`` subclass so ``mission_from_dict`` callers (and the ``/plan`` route) surface it as a
    400 like every other malformed-mission error, not an uncaught 500.
    """


def _upgrade_legacy_to_v1(data: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Upgrade the pre-versioning (unversioned) mission wire format to stewie_mission/1.0.

    v0 grew only ADDITIVELY (optional fields default when absent), so a v0 artifact is field-compatible
    with v1.0: the upgrade is version adoption, no field renamed or dropped. The chain stamps the
    version marker after this returns, so a real legacy mission (e.g. a committed sample mission)
    round-trips through here to a valid v1.0 dict that the strict loader then accepts.
    """
    return data


#: from_version -> (to_version, migrator). NON-EMPTY: the genuine unversioned wire format is a real
#: prior version, so the legacy->current migrator is registered and exercised on real data.
_MISSION_MIGRATORS: dict[str, tuple[str, _Migrator]] = {
    LEGACY_MISSION_VERSION: (MISSION_SCHEMA_VERSION, _upgrade_legacy_to_v1),
}


def register_mission_migration(from_version: str, to_version: str, migrate: _Migrator) -> None:
    """Register a migrator that upgrades a mission artifact from ``from_version`` to ``to_version``. The
    migrate callable receives (and may mutate/return) the mission dict; the chain stamps ``to_version``."""
    _MISSION_MIGRATORS[from_version] = (to_version, migrate)


def _apply_mission_migration_chain(
    data: MutableMapping[str, Any],
    current_version: str,
    registry: Mapping[str, tuple[str, _Migrator]],
) -> MutableMapping[str, Any]:
    """Walk ``data`` from its declared schema_version up to ``current_version`` through ``registry``.
    An absent schema_version enters the chain at ``LEGACY_MISSION_VERSION`` (the genuine unversioned
    format). Identity when already current. Raises MissionSchemaError on an unregistered version or a
    migration cycle."""
    version = data.get("schema_version") or LEGACY_MISSION_VERSION
    seen: set[str] = set()
    while version != current_version:
        if version in seen:
            raise MissionSchemaError(f"mission migration cycle detected at schema_version {version!r}")
        seen.add(str(version))
        step = registry.get(str(version))
        if step is None:
            raise MissionSchemaError(
                f"no migration path from schema_version {version!r} to {current_version!r}; "
                f"register a migrator (register_mission_migration) for that version"
            )
        to_version, migrate = step
        data = migrate(dict(data))
        data["schema_version"] = to_version
        version = to_version
    return data


def migrate_mission(payload: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Upgrade a mission payload dict to MISSION_SCHEMA_VERSION via the registered migration chain
    (identity if it is already current; an unversioned payload is treated as ``LEGACY_MISSION_VERSION``
    and walked forward). Does NOT mutate the caller's dict. A non-mapping payload is returned unchanged
    so ``mission_from_dict`` raises its own clear "must be a JSON object" ValueError."""
    if not isinstance(payload, Mapping):
        return payload  # type: ignore[return-value]
    return _apply_mission_migration_chain(dict(payload), MISSION_SCHEMA_VERSION, _MISSION_MIGRATORS)
