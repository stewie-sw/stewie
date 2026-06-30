"""Shared server state for the cockpit (ARCH-3): the process-wide caches the planner / twin /
session / perception routes all read -- the per-site DEM cache and the lazy, durable digital twin.

Extracted from server.py so those routers can reach the state WITHOUT importing the app module
(which would cycle: server imports the routers to include them). Self-contained: lode.mission_planner
(DEM load) and stewie.twin.versioned (the twin) are imported lazily so this module stays light and
free of the matplotlib import-time cost until a route actually needs the DEM/twin.
"""
from __future__ import annotations

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
    try:                                                 # layer 2 (#280): observed twin, where measured
        if site == "haworth":                            # the single global observed/perception twin is Haworth's
            tw = twin()
            import numpy as _np
            if tuple(tw.base.shape) == tuple(_np.asarray(z).shape):   # same tile grid -> 1:1, no resample
                m = tw.observed_mask()
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


# ---- the lazy, durable digital twin (RC-02 / W-1) --------------------------------------------
_TWIN: "TwinStore | None" = None
_TWIN_LOCK = threading.Lock()   # RC-02: serialize the lazy cold-restore


def twin() -> "TwinStore":
    """Lazy twin over the Haworth observed map (the planner's site); base = the loaded DEM. W-1
    (PRD 6.2): the server twin is DURABLE -- cold restore from the journal, then journal on."""
    global _TWIN
    from stewie.twin import versioned as VT
    if _TWIN is not None:                                 # fast path (no lock once built)
        return _TWIN
    with _TWIN_LOCK:                                      # RC-02: only ONE thread runs from_journal
        if _TWIN is None:
            dem, _anchor = moon_dem()
            base = dem[0] if isinstance(dem, tuple) else dem
            import numpy as _np
            if base is None:
                base = _np.zeros((64, 64))              # degraded mode mirrors moon_dem's fallback
            from stewie.specs import config as _CFG
            _jdir = os.path.join(_CFG.data_dir(), "twin")
            os.makedirs(_jdir, exist_ok=True)
            _jp = os.path.join(_jdir, "haworth.journal")
            _TWIN = VT.TwinStore.from_journal(_np.asarray(base, dtype=float), cell_m=5.0,
                                              journal_path=_jp)
    return _TWIN


# ---- the lazy, durable world-state authority (gap A1 / DT-01 runtime path) --------------------
_WSS = None
_WSS_LOCK = threading.Lock()


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
            _WSS = WorldStateService(twin=twin, journal_path=_jp)
    return _WSS
