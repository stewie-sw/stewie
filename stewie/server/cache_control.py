"""[systems-eng] Cache-Control policy for the KEYLESS PUBLIC GETs the lunar /ide binds.

The keyless reads split into two classes with DIFFERENT caching, applied by the ``_cache_control`` middleware
in ``server.py`` (keyed on the backend path -- the artemis edge strips ``/api`` before the backend, so the
paths below are what FastAPI actually sees):

* DYNAMIC world / planner state  ->  ``Cache-Control: no-store`` (OVERWRITE any header).
  These reflect MUTABLE world + planner state (site markers, per-cell / batch / transect reads, the layer
  manifest / catalog / consumption projections, the traffic + terramechanics layer readouts, the site
  suitability score, the derived hazard keep-outs). A stale edge/browser cache would show WRONG data, so they
  must never be stored.

* STATIC LOLA-DEM-derived products  ->  ``Cache-Control: public, max-age=300`` (setdefault: a route's own
  longer max-age, e.g. ``/dem/heightfield_full`` = 3600, is PRESERVED, not clobbered down).
  These are expensive-to-compute derivations of the STATIC LOLA DEM: the full-res heightfield binary + its
  meta + the analysis drape, the graticule, the legend, the globe drape PNGs + their footprint bbox, and the
  OGC WMS tiles. They are safe to edge-cache; no-store would kill the viz (a ~16 MB heightfield re-fetched
  every load).

NUANCE (verified, not assumed): the ``cost`` / ``blocking`` drapes are a PURE function of the static DEM +
sun geometry (``gis_layers._costmap_compose`` builds the FORGE CostmapContext from ``Z`` + sun ONLY -- it does
NOT receive the mutable operator keep-outs or fleet reservations), so they are STATIC. The ``traffic`` drape,
by contrast, reads the per-site persistent ``TrafficMemory`` Dr, which MUTATES as each SIM run folds new
traffic (``gis_layers`` even flags it "uncached: a cache would serve a stale corridor"). So ``traffic`` is the
one drape KIND that is DYNAMIC: a globe/layer.png/WMS request for ``traffic`` gets ``no-store``, every other
kind gets the static max-age. The bbox is the tile FOOTPRINT (kind-independent) -> always static.
"""
from __future__ import annotations

# DYNAMIC world/planner reads: exact backend paths (no path params) -> no-store.
NO_STORE_PATHS: frozenset[str] = frozenset({
    "/world/site-markers",
    "/world/point",
    "/world/points",
    "/world/transect",
    "/world/layer-manifest",
    "/world/layer-catalog",
    "/world/layer-consumption",
    "/world/traffic-layer",
    "/world/terramechanics-layers",
    "/world/site-suitability",
    "/world/keepouts-from-hazard",
})

# STATIC LOLA-derived products whose path fully determines the class (no kind param) -> public, max-age.
STATIC_EXACT_PATHS: frozenset[str] = frozenset({
    "/dem/heightfield_full",
    "/dem/heightfield_full/meta",
    "/dem/graticule",
    "/layers/legend",
})

# The one drape KIND that composes MUTABLE state (the per-site TrafficMemory Dr). cost/blocking are DEM+sun
# only (verified) -> static; ONLY traffic must not be edge-cached.
DYNAMIC_DRAPE_KINDS: frozenset[str] = frozenset({"traffic"})

STATIC_MAX_AGE = "public, max-age=300"
NO_STORE = "no-store"


def _globe_png_kind(path: str) -> str | None:
    """``/layers/globe/<kind>.png`` -> ``<kind>``; anything else -> None (``<kind>`` is a single segment)."""
    prefix = "/layers/globe/"
    suffix = ".png"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return None
    rest = path[len(prefix):-len(suffix)]
    return rest if "/" not in rest else None


def _is_globe_bbox(path: str) -> bool:
    """``/layers/globe/<kind>/bbox`` -> True (the footprint bbox; kind-independent -> always static)."""
    prefix = "/layers/globe/"
    suffix = "/bbox"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return False
    return path[len(prefix):-len(suffix)].count("/") == 0


def _wms_layer(query) -> str | None:
    """The first ``LAYERS`` value of an OGC WMS request (WMS keys are case-INsensitive, mirroring the route's
    ``_ci`` lookup). Returns None for GetCapabilities / no LAYERS."""
    if query is None:
        return None
    items = query.items() if hasattr(query, "items") else (query or {}).items()
    for key, val in items:
        if str(key).lower() == "layers" and val:
            return str(val).split(",")[0].strip()
    return None


def classify(path: str, query=None) -> tuple[str, bool] | None:
    """Cache-Control decision for a keyless public GET path (+ its query, for the kind-parameterized drapes).

    Returns ``(header_value, overwrite)`` or ``None`` (path not in either public set):
      * ``overwrite=True``  -> the middleware SETS the header unconditionally (dynamic no-store: correctness-
        critical, and applied to error statuses too so a stale error is never cached).
      * ``overwrite=False`` -> the middleware SETDEFAULTs on a 200 (static: a route's own longer max-age wins).
    """
    # 1) DYNAMIC world/planner reads (exact paths).
    if path in NO_STORE_PATHS:
        return (NO_STORE, True)

    # 2) globe drape PNG -- kind is the path segment; traffic is mutable, every other kind is DEM-derived.
    gk = _globe_png_kind(path)
    if gk is not None:
        return (NO_STORE, True) if gk in DYNAMIC_DRAPE_KINDS else (STATIC_MAX_AGE, False)

    # 3) globe bbox -- the tile footprint (kind-independent) -> static.
    if _is_globe_bbox(path):
        return (STATIC_MAX_AGE, False)

    # 4) the full-res analysis drape -- kind is a query param (route reads lowercase ``kind``; default dem).
    if path == "/dem/heightfield_full/layer.png":
        kind = (query.get("kind") if query is not None else None) or "dem"
        return (NO_STORE, True) if kind in DYNAMIC_DRAPE_KINDS else (STATIC_MAX_AGE, False)

    # 5) OGC WMS -- GetMap of the traffic layer is mutable; other layers + GetCapabilities are static.
    if path == "/ogc/wms":
        wl = _wms_layer(query)
        return (NO_STORE, True) if wl in DYNAMIC_DRAPE_KINDS else (STATIC_MAX_AGE, False)

    # 6) the remaining fully-static products.
    if path in STATIC_EXACT_PATHS:
        return (STATIC_MAX_AGE, False)

    return None
