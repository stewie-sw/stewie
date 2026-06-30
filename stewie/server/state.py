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


def as_built_dem(site, dem, origin):
    """#242/#267: imprint a site's recorded TerrainMemory onto the planning DEM so EVERY consumer plans/
    renders on the AS-BUILT remembered surface, not the pristine tile. The planner (plan.py) AND the 3D
    as-built mesh (/dem/asbuilt) share this ONE helper, so they cannot diverge once prior missions have
    reshaped the site. ``dem`` is the (z, cell) pair; a fine work-area memory is resampled onto the coarse
    LOLA cell. No memory / a None DEM -> returned unchanged (opt-in = a build was recorded). Defensive: a
    bad/mismatched memory falls back to pristine and never raises (as-built is an enhancement, not a gate)."""
    if dem is None:
        return dem
    try:
        from stewie.specs.config import data_dir
        from stewie.twin import terrain_memory as TM
        mem = TM.load_site(data_dir(), site)
        if mem is None:
            return dem
        z, cell = dem
        return (mem.imprint_on_dem_resampled(z, dem_cell=cell, dem_origin=origin), cell)
    except Exception as e:   # noqa: BLE001 -- never fail a consumer on the as-built enhancement
        log.warning("as-built imprint skipped for site %r: %s", site, e)
        return dem


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
