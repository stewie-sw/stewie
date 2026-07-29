"""Shared server state for the cockpit (ARCH-3): the process-wide caches the planner / twin /
session / perception routes all read -- the per-site DEM cache and the lazy, durable digital twin.

Extracted from server.py so those routers can reach the state WITHOUT importing the app module
(which would cycle: server imports the routers to include them). Self-contained: lode.mission_planner
(DEM load) and stewie.twin.versioned (the twin) are imported lazily so this module stays light and
free of the matplotlib import-time cost until a route actually needs the DEM/twin.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stewie.twin.versioned import TwinStore

log = logging.getLogger("stewie.server")

# ---- the per-site DEM cache (REG-01) ---------------------------------------------------------
_MOON_DEM = None   # (dem, flattest-anchor) for haworth -- the canonical default, loaded once
_SITE_DEMS: dict = {}


def moon_dem(site: str = "haworth"):
    """Load the real DEM for ``site`` (REG-01: any imported site, not just Haworth) + its
    auto-selected flattest buildable anchor, cached PER SITE so Moon plans get live slope-gating on
    the chosen terrain. Degrades to (None, (0,0)) -> flat check if the bundle is absent."""
    global _MOON_DEM
    from lode import mission_planner as MP
    if site in _SITE_DEMS:
        return _SITE_DEMS[site]
    try:
        dem = MP.load_site_dem(site)
        out = (dem, MP.flattest_anchor(dem))
    except Exception as e:   # noqa: BLE001 -- degrade to flat-check, but surface it
        log.warning("DEM for site %r unavailable; falling back to flat slope-check: %r", site, e)
        out = (None, (0.0, 0.0))
    _SITE_DEMS[site] = out
    if site == "haworth":
        _MOON_DEM = out
    return out


# DT-03 / #58.3: the resync critical-section lock. twin_resync (routers/twin.py) holds it across
# apply_patch..world-log-commit..compensating-undo; current_terrain_view holds it while reading the twin's
# mask+heights+version, so a planner can never observe an uncommitted patch that is about to be rolled back.
_RESYNC_LOCK = threading.Lock()


def current_terrain_view(site, dem, origin):
    """#242/#267/#280 + gap A2: the ONE composed planning surface every consumer (planner + 3D as-built
    mesh + cockpit) reads, as a typed ``CurrentTerrainView`` that RETAINS provenance -- the precedence
    stack OBSERVED-where-measured > AS-BUILT remembered > pristine, plus a per-cell source map and the
    provenance counters (as-built version, observed twin version, observed fraction). ``dem`` is the
    (z, cell) pair; a None DEM returns None.
      1. AS-BUILT (#242/#267): imprint a site's recorded TerrainMemory (a fine work-area memory resampled
         onto the coarse LOLA cell). No memory -> pristine unchanged.
      2. OBSERVED (#280): overlay the durable perception/resync TwinStore's current() heights, but ONLY
         where it has MEASURED coverage (twin.observed_mask()), so a thin/empty resync can never degrade a
         plan. Gated to Haworth (the single global observed twin) + an exact grid match. Measured reality
         wins. Defensive: a bad memory / twin is ignored (the composer drops a wrong-shaped layer); the
         gather never raises (planning must not fail on the world-model overlay)."""
    if dem is None:
        return None
    z, cell = dem
    as_built_z = None
    as_built_version = 0
    try:                                                 # layer 1: as-built TerrainMemory
        from stewie.specs.config import data_dir
        from stewie.twin import terrain_memory as TM
        mem = TM.load_site(data_dir(), site)
        if mem is not None:
            as_built_z = mem.imprint_on_dem_resampled(z, dem_cell=cell, dem_origin=origin)
            as_built_version = int(getattr(mem, "version", 0))
    except Exception as e:   # noqa: BLE001 -- never fail a consumer on the as-built enhancement
        log.warning("as-built imprint skipped for site %r: %s", site, e)
        as_built_z, as_built_version = None, 0
    observed_heights = observed_mask = None
    twin_version = 0
    try:                                                 # layer 2 (#280 / DT-04): the observed twin for THIS
        tw = twin(site)                                  # site (per-(site,source) keyed; was hard-coded to haworth)
        import numpy as _np
        if tuple(tw.base.shape) == tuple(_np.asarray(z).shape):   # same tile grid -> 1:1, no resample
            with _RESYNC_LOCK:   # #58.3: read mask+heights+version as ONE consistent triple so a concurrent
                m = tw.observed_mask()   # twin_resync (apply_patch..commit..undo) can't be observed mid-rollback
                if m.any():
                    observed_heights, observed_mask = tw.current(), m
                    twin_version = int(getattr(tw, "version", 0))
    except Exception as e:   # noqa: BLE001 -- the observed overlay is an enhancement; never fail a plan
        log.warning("observed-twin overlay skipped for site %r: %s", site, e)
        observed_heights = observed_mask = None
        twin_version = 0
    from stewie.twin.terrain_view import compose_terrain_view
    return compose_terrain_view(z, cell, as_built_z=as_built_z, as_built_version=as_built_version,
                                observed_heights=observed_heights, observed_mask=observed_mask,
                                twin_version=twin_version)


def as_built_dem(site, dem, origin):
    """The (z, cell) planning-surface contract every #242/#267/#280 call site uses. Delegates to
    ``current_terrain_view`` (the one composition path) and returns just its composed heights -- so the
    planner/mesh keep their array contract while the typed view + provenance is available to callers
    that want it. A None DEM passes through unchanged."""
    view = current_terrain_view(site, dem, origin)
    if view is None:
        return dem
    return (view.heights, view.cell_m)


# ---- the lazy, durable digital twin (RC-02 / W-1 / DT-04) ------------------------------------
#: DT-04: the observed twin is keyed by (site, depth-source profile). The DEFAULT key -- (haworth,
#: DEFAULT_TWIN_SOURCE) -- keeps its own module global + journal filename ("haworth.journal") so the
#: existing durable journal and the test fixtures that reset ``_TWIN`` are untouched; every OTHER
#: (site, source) lives in ``_TWINS`` with its own ``<site>[__<source>].journal``. So an imported site
#: or a non-default depth source each carries an INDEPENDENT observed twin instead of overwriting Haworth.
DEFAULT_TWIN_SITE = "haworth"
DEFAULT_TWIN_SOURCE = "stereo_sgbm"
_TWIN: "TwinStore | None" = None
_TWIN_LOCK = threading.Lock()   # RC-02: serialize the lazy cold-restore of the DEFAULT twin
_TWINS: "dict[tuple[str, str], TwinStore]" = {}   # DT-04: the per-(site, source) non-default twins
_TWINS_LOCK = threading.Lock()


class TwinJournalMigrationRequired(RuntimeError):
    """A lossy legacy journal filename cannot be assigned to one site without operator evidence."""


_TWIN_IDENTITY_SCHEMA = "stewie.twin-journal-identity/v1"


def _canonical_twin_component(value: str) -> str:
    """Normalize spelling without discarding identity-bearing punctuation."""
    return str(value).strip().lower()


def _legacy_safe_site(site: str) -> str:
    """The pre-SR-03 lossy filename mapping, used only to detect history needing migration."""
    import re
    raw = _canonical_twin_component(site)
    return re.sub(r"[^a-z0-9]+", "_", raw).strip("_") or "site"


def _journal_identity_path(journal_path: str) -> str:
    return journal_path + ".identity.json"


def _read_journal_identity(journal_path: str) -> tuple[str, str] | None:
    marker = _journal_identity_path(journal_path)
    if not os.path.exists(marker):
        return None
    try:
        with open(marker, encoding="utf-8") as f:
            body = json.load(f)
        if not isinstance(body, dict) or body.get("schema") != _TWIN_IDENTITY_SCHEMA:
            raise ValueError("invalid identity schema")
        site = _canonical_twin_component(body["site"])
        source = _canonical_twin_component(body["source"])
        return site, source
    except (OSError, KeyError, TypeError, ValueError) as e:
        raise TwinJournalMigrationRequired(
            f"twin journal identity marker {marker!r} is invalid: {e}") from e


def _write_journal_identity(journal_path: str, site: str, source: str) -> None:
    """Persist the collision-safe identity epoch before a new journal can receive observations."""
    from stewie.twin.io_fields import atomic_write_bytes
    marker = _journal_identity_path(journal_path)
    body = {
        "schema": _TWIN_IDENTITY_SCHEMA,
        "site": _canonical_twin_component(site),
        "source": _canonical_twin_component(source),
    }
    atomic_write_bytes(marker, (json.dumps(body, indent=1, sort_keys=True) + "\n").encode())
    dir_fd = os.open(os.path.dirname(marker), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _guard_raw_legacy_source_path(raw_site: str, raw_source: str,
                                  canonical_site: str, canonical_source: str) -> None:
    """Detect journals created by the old raw source-equality filename branch.

    Before SR-03, ``source='Stereo_SGBM'`` normalized to the default stem as a filename component but
    failed the raw ``source == 'stereo_sgbm'`` branch, producing
    ``haworth__stereo_sgbm.journal``. The canonical legacy calculation alone cannot see that path.
    """
    from stewie.specs import config as _CFG
    jdir = os.path.join(_CFG.data_dir(), "twin")
    old_stem = (
        _legacy_safe_site(raw_site)
        if str(raw_source) == DEFAULT_TWIN_SOURCE
        else f"{_legacy_safe_site(raw_site)}__{_legacy_safe_site(raw_source)}")
    current_stem = (
        _safe_site(canonical_site)
        if canonical_source == DEFAULT_TWIN_SOURCE
        else f"{_safe_site(canonical_site)}__{_safe_site(canonical_source)}")
    old_path = os.path.join(jdir, f"{old_stem}.journal")
    current_path = os.path.join(jdir, f"{current_stem}.journal")
    if old_path == current_path or not os.path.exists(old_path):
        return
    identity = _read_journal_identity(old_path)
    expected = (canonical_site, canonical_source)
    if identity is None:
        raise TwinJournalMigrationRequired(
            f"raw-source legacy twin journal {old_path!r} has no identity marker for {expected!r}; "
            "inspect it and explicitly migrate/quarantine it")
    if identity == expected:
        raise TwinJournalMigrationRequired(
            f"raw-source legacy twin journal {old_path!r} is assigned to {expected!r}; move it and "
            f"its identity marker to canonical path {current_path!r}")


def _safe_site(site: str) -> str:
    """Sanitize a site name into a stable journal-filename stem (the same normalization idea the
    TerrainMemory .npz path uses: lowercase, trim, non-alnum -> '_'), so two spellings of one site do
    not fork its journal and a name can never escape the twin dir.

    SR-03 (2026-07-28 review): the substitution is LOSSY, and two DIFFERENT sites could collapse onto
    one stem -- ``adhoc_-88500_-25500`` and ``adhoc_88500_25500`` (opposite hemispheres) both became
    ``adhoc_88500_25500``, so one site's observed patches were served as another's. When sanitizing
    actually rewrote a meaningful character, a short digest of the normalized name disambiguates. A name
    already in ``[a-z0-9_]`` form is returned unchanged, so ``haworth.journal`` and every other existing
    journal filename stays byte-compatible.
    """
    import hashlib
    import re
    raw = _canonical_twin_component(site)
    stem = re.sub(r"[^a-z0-9]+", "_", raw).strip("_") or "site"
    if stem != raw:
        stem = f"{stem}_{hashlib.sha1(raw.encode()).hexdigest()[:8]}"
    return stem


def _build_twin(site: str, source: str):
    """Cold-restore (or create) the durable observed twin for (site, source): base = that site's loaded
    DEM (REG-01: moon_dem takes a site), journal = the per-(site, source) file. DURABLE -- restore from
    the journal, then journal on (W-1)."""
    from stewie.specs import config as _CFG
    from stewie.twin import versioned as VT
    import numpy as _np
    site = _canonical_twin_component(site)
    source = _canonical_twin_component(source)
    dem, _anchor = moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        base = _np.zeros((64, 64))                        # degraded mode mirrors moon_dem's fallback
    _jdir = os.path.join(_CFG.data_dir(), "twin")
    os.makedirs(_jdir, exist_ok=True)
    # SR-03: compare the NORMALIZED source, not the raw string -- "Stereo_SGBM" is the default source
    # and must not be written to a separate "<site>__stereo_sgbm.journal".
    stem = (_safe_site(site) if _safe_site(source) == _safe_site(DEFAULT_TWIN_SOURCE)
            else f"{_safe_site(site)}__{_safe_site(source)}")
    _jp = os.path.join(_jdir, f"{stem}.journal")
    legacy_stem = (_legacy_safe_site(site)
                   if _legacy_safe_site(source) == _legacy_safe_site(DEFAULT_TWIN_SOURCE)
                   else f"{_legacy_safe_site(site)}__{_legacy_safe_site(source)}")
    legacy_jp = os.path.join(_jdir, f"{legacy_stem}.journal")
    identity = (site, source)
    from stewie.specs.sites import SITES
    legacy_ambiguous = (
        site not in SITES or source != DEFAULT_TWIN_SOURCE or legacy_jp != _jp)
    legacy_identity = _read_journal_identity(legacy_jp)
    current_identity = _read_journal_identity(_jp)

    if legacy_ambiguous and os.path.exists(legacy_jp):
        if legacy_identity is None:
            # Even when `_jp == legacy_jp` (the positive ad-hoc sign), the old file could have been
            # produced by a different spelling/sign that collapsed onto this stem.
            raise TwinJournalMigrationRequired(
                f"legacy twin journal {legacy_jp!r} has no identity marker and is ambiguous for "
                f"{identity!r}; inspect it, then migrate/quarantine it and create "
                f"{_journal_identity_path(legacy_jp)!r}")
        if legacy_identity != identity and legacy_jp == _jp:
            raise TwinJournalMigrationRequired(
                f"twin journal {legacy_jp!r} is assigned to {legacy_identity!r}, not {identity!r}")
        if legacy_identity == identity and legacy_jp != _jp:
            raise TwinJournalMigrationRequired(
                f"legacy twin journal {legacy_jp!r} is explicitly assigned to {identity!r}; move it "
                f"and its identity marker to collision-safe path {_jp!r} before continuing")

    if os.path.exists(_jp):
        if current_identity is None and legacy_ambiguous:
            raise TwinJournalMigrationRequired(
                f"twin journal {_jp!r} has no collision-safe identity marker for {identity!r}")
        if current_identity is not None and current_identity != identity:
            raise TwinJournalMigrationRequired(
                f"twin journal {_jp!r} is assigned to {current_identity!r}, not {identity!r}")
    elif current_identity is not None and current_identity != identity:
        raise TwinJournalMigrationRequired(
            f"twin journal marker {_journal_identity_path(_jp)!r} is assigned to "
            f"{current_identity!r}, not {identity!r}")

    if current_identity is None:
        # Safe curated legacy paths are adopted once; every new/unknown path gets an identity epoch
        # before TwinStore can lazily create its journal.
        _write_journal_identity(_jp, site, source)
    return VT.TwinStore.from_journal(_np.asarray(base, dtype=float), cell_m=5.0, journal_path=_jp)


def twin(site: str = DEFAULT_TWIN_SITE, source: str = DEFAULT_TWIN_SOURCE) -> "TwinStore":
    """[REQ:DT-04] Lazy, DURABLE observed twin for ``(site, source)`` -- each keyed independently, so an
    imported site or a non-default depth source accumulates + reloads its OWN observed surface without
    overwriting Haworth's. The default key ((haworth, stereo_sgbm)) keeps the original ``_TWIN`` global +
    ``haworth.journal`` (backward-compatible); every other key lives in ``_TWINS``.

    SR-03 (2026-07-28 review): dispatch is on the NORMALIZED key. This previously compared the RAW
    strings while ``_build_twin`` derived the journal filename through ``_safe_site``, so ``"Haworth"``
    missed the default fast path, got its own store object and its own lock, and then wrote the SAME
    ``haworth.journal`` as the default twin. Two writers on one append-only journal interleave versions,
    and the next cold restore raises ``ValueError: replay hash mismatch`` -- permanently, taking
    ``/twin/version`` and ``/twin/history`` to 500 and silently dropping the observed layer from every
    plan. Normalizing once, here at the boundary, is what makes one site resolve to one writer.
    """
    global _TWIN
    canonical_site = _canonical_twin_component(site)
    canonical_source = _canonical_twin_component(source)
    _guard_raw_legacy_source_path(str(site), str(source), canonical_site, canonical_source)
    nsite, nsource = _safe_site(canonical_site), _safe_site(canonical_source)
    if nsite == _safe_site(DEFAULT_TWIN_SITE) and nsource == _safe_site(DEFAULT_TWIN_SOURCE):
        if _TWIN is not None:                            # fast path (no lock once built)
            return _TWIN
        with _TWIN_LOCK:                                 # RC-02: only ONE thread runs from_journal
            if _TWIN is None:
                _TWIN = _build_twin(DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE)
        return _TWIN
    key = (nsite, nsource)
    tw = _TWINS.get(key)
    if tw is not None:
        return tw
    with _TWINS_LOCK:
        if key not in _TWINS:
            _TWINS[key] = _build_twin(canonical_site, canonical_source)
        return _TWINS[key]


# ---- the lazy, durable world-state authority (gap A1 / DT-01 runtime path) --------------------
_WSS = None
_WSS_LOCK = threading.Lock()


def _world_txn_projection_sink():
    """[PG-01] The durable-projection sink for the WorldStateService: mirror each committed WorldTransaction
    to the Postgres/PostGIS read-model ONLY when a durable store is configured (``STEWIE_DATABASE_URL`` set)
    -- so prod persists the provenance chain while CI/dev (no URL, in-memory/SQLite fallback) adds no per-
    transaction DB write. Best-effort + non-authoritative (WorldStateService swallows a mirror failure)."""
    if not os.environ.get("STEWIE_DATABASE_URL"):
        return None
    from stewie.server import db
    return db.mirror_world_txn


def world_state_service():
    """Lazy, process-wide WorldStateService -- the one route-level facade that commits a
    ``WorldTransaction`` for every meaningful world-state transition (plan / terrain record / resync /
    belief / execution). Durable: its TransactionLog cold-restores from ``data_dir/twin/world.journal``
    and journals on. Wraps the same lazy observed twin (``twin``) so a resync route's mutation is
    captured live. Built once (RC-02-style single-restore under lock)."""
    global _WSS
    if _WSS is not None:                                  # fast path (no lock once built)
        return _WSS
    with _WSS_LOCK:
        if _WSS is None:
            from stewie.server.world_state import WorldStateService
            from stewie.specs import config as _CFG
            _jdir = os.path.join(_CFG.data_dir(), "twin")
            os.makedirs(_jdir, exist_ok=True)
            _jp = os.path.join(_jdir, "world.journal")
            _WSS = WorldStateService(twin=twin, journal_path=_jp,
                                     projection_sink=_world_txn_projection_sink())   # PG-01 durable projection
    return _WSS
