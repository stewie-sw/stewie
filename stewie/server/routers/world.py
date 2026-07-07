"""World-state authority route (FS-02 / TW-05, §25 Phase 1). Returns the typed WorldState DESCRIPTOR
for a site -- the grid geometry (rows/cols/cell_m), the lunar datum, and provenance (a dart.dem_sources
id) the cockpit + planner reason over. The raw rasters live in the twin/DEM store; this is the typed
metadata. DT-05: observed_fraction/mutated are now the REAL enrichment (measured from the site's own
observed twin + as-built memory), and an `enrichment` block declares completeness + freshness explicitly.
Public read. Delegates to server.state.moon_dem; no app-module import (no cycle)."""
from __future__ import annotations

import io
import os
from dataclasses import asdict

import numpy as np
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from stewie.contracts import WorldState
from stewie.server import state as S
from stewie.server.deps import require_auth
from stewie.specs.sites import SITES

router = APIRouter()

# site -> dart.dem_sources id, derived from the imported-bundle registry so EVERY imported site reports
# its real bundle id as provenance (not just Haworth). The bundle dir basename IS the dem_sources id
# (e.g. nobile_rim -> nobile_rim1_10km_5m), so a newly imported site is wired automatically.
_SITE_SOURCE = {name: os.path.basename(s.bundle_dir) for name, s in SITES.items() if s.bundle_dir}

_LAYER_CATALOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "layer_catalog.json")

# [REQ:GW-03] Per-layer UNCERTAINTY, surfaced as a source_class-implied CONFIDENCE class + tier. The catalog
# declares each layer's `source_class` (its provenance: observed / prior / derived / forecast / belief / ...),
# and THAT provenance IS the honest per-layer confidence signal — a directly-observed layer is trustworthy, a
# forecast or belief layer is not. So the confidence is a faithful epistemic classification of the REAL declared
# source_class, NOT a fabricated numeric uncertainty (no synthetic number is invented). A layer with no
# recognizable provenance token reads `unknown`/`n/a` honestly rather than guessing a value.
#: provenance token -> (confidence class, tier). Grouped: measurement-grounded (values come, or can come, from
#: a real observation) -> high; computed/modeled -> medium; predicted/probabilistic -> low; static reference /
#: authored design intent / runtime evidence carry their own honest classes (a prior is authoritative but not
#: freshly-measured here; a user design is intent not a measurement; sim/replay capture is evidence, not autonomy input).
_CONF_TOKEN = {
    "live": ("measured", "high"), "observed": ("measured", "high"),
    "measured": ("measured", "high"), "reconciled": ("measured", "high"),
    "sim_truth": ("measured", "high"), "released": ("approved", "high"),
    "derived": ("derived", "medium"), "estimated": ("modeled", "medium"), "learned": ("modeled", "medium"),
    "forecast": ("predicted", "low"), "belief": ("predicted", "low"),
    "prior": ("reference", "medium"), "user": ("authored", "n/a"),
    "sim": ("evidence", "n/a"), "replay": ("evidence", "n/a"), "evidence": ("evidence", "n/a"),
}
#: grounding strength, strongest first — mirrors the frontend provClass badge: the STRONGEST provenance token a
#: layer carries sets its confidence class (best-available grounding).
_CONF_RANK = ("live", "observed", "measured", "reconciled", "sim_truth", "released",
              "derived", "estimated", "learned", "forecast", "belief", "prior", "user",
              "sim", "replay", "evidence")
_CONF_MEASURED = frozenset({"live", "observed", "measured", "reconciled"})
_CONF_BASELINE = frozenset({"prior", "derived", "estimated", "learned", "forecast", "belief"})
_CONF_TIERS = frozenset({"high", "medium", "low", "n/a"})


def layer_confidence(source_class: str) -> dict:
    """[REQ:GW-03] the per-layer confidence (uncertainty) implied by a layer's declared ``source_class``.
    Returns ``{cls, tier, basis, conditional}``: ``cls``/``tier`` = the epistemic class of the strongest
    grounding token (best-available provenance, matching the provClass badge); ``basis`` = the raw source_class
    string (full transparency — every token the caller can inspect); ``conditional`` = True when the strongest
    token is a live measurement (observed/live/measured/reconciled) BUT a weaker baseline token (prior/derived/
    forecast/belief/...) is ALSO present — i.e. the high confidence is CONDITIONAL on fresh observation (a
    ``prior/observed`` DEM is only measured-grade once the site is actually observed; until then it is its prior).
    No synthetic uncertainty is fabricated — the tier is a classification of the real declared source_class."""
    toks = [t for t in str(source_class or "").split("/") if t]
    best, best_rank = None, len(_CONF_RANK)
    for t in toks:
        if t in _CONF_RANK:
            r = _CONF_RANK.index(t)
            if r < best_rank:
                best_rank, best = r, t
    if best is None:
        return {"cls": "unknown", "tier": "n/a", "basis": source_class or "", "conditional": False}
    cls, tier = _CONF_TOKEN[best]
    conditional = best in _CONF_MEASURED and any(t in _CONF_BASELINE for t in toks)
    return {"cls": cls, "tier": tier, "basis": source_class, "conditional": conditional}


@router.get("/world/layer-catalog")
def layer_catalog():   # public read (map-data catalog); nginx proxies /api/ without a key by design
    """[REQ:LY-01] the GIS layer catalog/registry — the ~65 named layers (`base.*`…`evidence.*`) each declaring
    type, source_class, planning-eligibility, and release/execute-eligibility. This is the SUPERSET the GIS
    workbench layer tree (GW-06) binds; the per-site /world layer_manifest is the live subset carrying real
    freshness/provenance. Single source of truth = the PRD2 catalog table; served from layer_catalog.json
    (regenerated by scripts/gen_layer_catalog.py, kept in-sync by [REQ:LY-01] test).

    [REQ:GW-03] Each served layer is additionally annotated with a ``confidence`` (its source_class-implied
    per-layer UNCERTAINTY) so the workbench layer tree can differentiate a trustworthy directly-observed layer
    from a forecast/belief one. The annotation is derived at SERVE time from the real declared ``source_class``;
    the committed layer_catalog.json + the LY-01 sync test (which read the raw file) are untouched."""
    import json
    with open(_LAYER_CATALOG_PATH, encoding="utf-8") as fh:
        cat = json.load(fh)
    for ly in cat.get("layers", []):
        ly["confidence"] = layer_confidence(ly.get("source_class", ""))   # [REQ:GW-03] per-layer uncertainty
    return cat


@router.get("/world/layer-consumption")
def layer_consumption():   # public read (catalog projection)
    """[REQ:LY-02] the layer-consumption inspector: for each LY-01 catalog layer, WHERE it is consumed across
    the mission surface (display / planner / costmap / rehearsal / release / execute / report / export).
    Consumption is DERIVED from the catalog eligibility (planning/release-execute + domain + source class), so
    it is a faithful projection of LY-01, never a drifting hand-map -- a layer feeds the planner only if it is
    planning-eligible, and feeds release/execute only if it is release/execute-eligible."""
    import json

    from stewie.server.layer_consumption import CONSUMERS, consumers_for
    with open(_LAYER_CATALOG_PATH, encoding="utf-8") as fh:
        cat = json.load(fh)
    rows = [{"id": ly["id"], "domain": ly["domain"], "consumers": consumers_for(ly)} for ly in cat["layers"]]
    return {"ok": True, "consumers": CONSUMERS, "layers": rows, "count": len(rows)}


@router.get("/world/traffic-layer")
def traffic_layer(site: str = "haworth"):   # public read (TW-11 traffic layer, map data)
    """[REQ:TW-11] the traversal-hardening readout for a site: the per-cell traffic.compaction Dr field the
    persistent TrafficMemory has accumulated -- how much of the work area is trafficked, the peak relative
    density, cells hardened past Dr>0.5, the bearing UPLIFT the traffic produced (a compacted haul road is a
    firmer future pad), and the accumulator's version + provenance-chain head. ``committed: False`` before any
    SIM run has folded traffic for the site. The raster is served at /layers/raster/traffic.png. Public read."""
    from stewie.specs.config import data_dir
    from stewie.twin import traffic_memory as TW
    mem = TW.load_site(data_dir(), site)
    if mem is None:
        return {"ok": True, "site": site, "committed": False,
                "note": "no traffic hardening recorded for this site yet"}
    s = mem.summary()
    chain_head = mem.chain[-1]["hash"] if mem.chain else ""
    return {"ok": True, "site": site, "committed": True, "summary": s,
            "grid": {"rows": mem.rows, "cols": mem.cols, "cell_m": mem.cell_m, "origin": list(mem.origin)},
            "provenance": {"version": mem.version, "chain_head": chain_head, "verified": mem.verify_chain(),
                           "sigma_c_n": mem.sigma_c_n, "mass_areal_kg_m2": mem.mass_areal,
                           "calibration": {"sigma_c_n": "[CALIB]", "road_layer_mass_areal": "[CALIB]"}}}


@router.get("/world/terramechanics-layers")
def terramechanics_layers():   # public read (physics-layer provenance, map data)
    """[REQ:TM-03] the derived catalog layers the terramechanics spine generates: each LY-01 physics/traffic/
    terrain layer + the TM-02 spine terms it is computed FROM + which of those are real solver outputs + the
    producing backend. Every derived layer id is a real LY-01 catalog layer and every source term is a real
    TM-02 spine term (validated at import), so a slip-risk / traversability / energy-cost / costmap layer is
    provably built from the terramechanics, not a fabricated map."""
    from stewie.specs.terramechanics_spine import terra_derived_layers
    rows = terra_derived_layers()
    return {"ok": True, "backend": "tier2_numpy", "derived_layers": rows, "count": len(rows)}


def _site_enrichment(site: str) -> dict | None:
    """DT-05 shared core: measure the REAL per-site freshness + provenance from the site's own observed
    twin (DT-04) + as-built memory. Returns grid geometry + ``dem_source`` (the dart.dem_sources bundle
    id = provenance), ``observed_fraction`` (measured coverage of the observed twin -- the freshness),
    ``observed`` (an observed twin exists), and the twin / as-built versions + ``mutated`` flag. Returns
    ``None`` when the site's DEM bundle is absent (degraded). Both the auth-gated rich /world descriptor
    and the PUBLIC /world/layer-manifest read this SAME core, so the freshness the two report can never
    drift. No synthetic timestamps -- a site with no fresh observation reports observed_fraction 0.0."""
    dem, _anchor = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return None
    arr = np.asarray(base)
    rows, cols = int(arr.shape[0]), int(arr.shape[1])
    cell_m = float(dem[1]) if (isinstance(dem, tuple) and len(dem) >= 2 and dem[1]) else 5.0
    observed = False
    observed_fraction = 0.0
    twin_version = 0
    try:
        tw = S.twin(site)
        if tuple(tw.base.shape) == (rows, cols):          # same tile grid -> the coverage is 1:1
            m = tw.observed_mask()
            observed = True
            observed_fraction = float(m.mean())
            twin_version = int(getattr(tw, "version", 0))
    except Exception:   # noqa: BLE001 -- the observed overlay is an enhancement; never fail the descriptor
        observed = False
    mutated = False
    as_built_version = 0
    try:
        from stewie.specs.config import data_dir
        from stewie.twin import terrain_memory as TM
        mem = TM.load_site(data_dir(), site)
        if mem is not None:
            as_built_version = int(getattr(mem, "version", 0))
            mutated = as_built_version > 0                 # a recorded build mutated the terrain vs the prior DEM
    except Exception:   # noqa: BLE001
        mutated = False
    return {"rows": rows, "cols": cols, "cell_m": cell_m, "dem_source": _SITE_SOURCE.get(site, site),
            "observed": observed, "observed_fraction": observed_fraction,
            "twin_version": twin_version, "as_built_version": as_built_version, "mutated": mutated}


@router.get("/world/layer-manifest")
def world_layer_manifest(site: str = "haworth"):   # public read (per-site map-data freshness/provenance)
    """[REQ:GW-06] the PUBLIC per-site layer manifest the GIS workbench layer tree (GW-06) binds for its
    per-layer FRESHNESS + PROVENANCE. It is the key-free projection of the auth-gated /world descriptor's
    DT-05 enrichment (same ``_site_enrichment`` core -> no drift): ``freshness`` carries the REAL measured
    ``observed_fraction`` of the site's observed twin, the ``provenance_class`` (``observed`` iff the site
    has fresh coverage, else ``prior``), the ``dem_source`` provenance id, and the observed / mutated +
    twin / as-built versions; ``layer_manifest`` is the typed per-layer manifest (each layer's provenance +
    consumer eligibility). Public (map-data read, like /world/traffic-layer) so the public /ide/ can bind
    it without a key. No synthetic timestamps -- a site with no fresh observation reports observed_fraction
    0.0 + provenance 'prior', never a faked age. 404 if the site's DEM bundle is absent (degraded)."""
    enr = _site_enrichment(site)
    if enr is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    w = WorldState(rows=enr["rows"], cols=enr["cols"], cell_m=enr["cell_m"], dem_source=enr["dem_source"],
                   observed_fraction=enr["observed_fraction"], mutated=enr["mutated"])
    from stewie.contracts import LayerManifest   # [REQ:FR-10] the unified typed layer manifest
    manifest = LayerManifest.for_world(w, transaction_id=f"world:{site}")
    prov_class = "observed" if enr["observed_fraction"] > 0.0 else "prior"
    return {"ok": True, "site": site,
            "freshness": {"observed": enr["observed"], "observed_fraction": enr["observed_fraction"],
                          "provenance_class": prov_class, "dem_source": enr["dem_source"],
                          "twin_version": enr["twin_version"], "as_built_version": enr["as_built_version"],
                          "mutated": enr["mutated"]},
            "layer_manifest": manifest.model_dump()}   # [REQ:FR-10] per-layer typed manifest w/ provenance + eligibility


@router.get("/world")
def world(site: str = "haworth", _auth: str = Depends(require_auth)):
    """[REQ:DT-05] the AUTHORITATIVE rich world descriptor for `site`: grid geometry + lunar datum +
    provenance PLUS the REAL observed/mutated enrichment (no longer contract defaults deferred to a
    later phase). ``observed_fraction`` is the measured coverage of the site's own observed twin (DT-04),
    ``mutated`` is whether construction has recorded a build into its as-built TerrainMemory, and the
    ``enrichment`` block declares completeness + freshness EXPLICITLY so a consumer can never mistake an
    incomplete descriptor for the full world model. 404 if the site's DEM bundle is absent (degraded)."""
    enr = _site_enrichment(site)
    if enr is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    world_committed = S.world_state_service().transaction_count() > 0
    w = WorldState(rows=enr["rows"], cols=enr["cols"], cell_m=enr["cell_m"], dem_source=enr["dem_source"],
                   observed_fraction=enr["observed_fraction"], mutated=enr["mutated"])
    from stewie.contracts import LayerManifest   # [REQ:FR-10] the unified typed layer manifest
    manifest = LayerManifest.for_world(w, transaction_id=f"world:{site}:{S.world_state_service().transaction_count()}")
    return {"ok": True, "world": w.model_dump(),
            "layer_manifest": manifest.model_dump(),   # [REQ:FR-10] per-layer typed manifest w/ consumer eligibility

            # DT-05: the completeness/freshness declaration -- `complete` states this descriptor carries
            # its enrichment (not deferred); a consumer keys on it rather than guessing.
            "enrichment": {"complete": True, "observed": enr["observed"], "twin_version": enr["twin_version"],
                           "as_built_version": enr["as_built_version"], "mutated": enr["mutated"],
                           "world_committed": world_committed}}


@router.get("/world/transaction")
def world_transaction(_auth: str = Depends(require_auth)):
    """Gap A1 / DT-01: the single most recent consistent linked world-state transaction -- the one
    query that returns the conserved authority, observed twin, plan, and belief as ONE snapshot (not
    four independent reads). ``committed: False`` before any transition has been recorded. Auth-gated."""
    wss = S.world_state_service()
    if wss.transaction_count() == 0:
        return {"ok": True, "committed": False, "count": 0}
    return {"ok": True, "committed": True, "count": wss.transaction_count(),
            "transaction": asdict(wss.latest())}


@router.get("/world/transactions")
def world_transactions(limit: int = 50, _auth: str = Depends(require_auth)):
    """Gap A1 / FS-04: the recent linked world-state transactions (chronological) -- the world/execution
    timeline the cockpit Report pane renders (each entry's provenance carries plan/terrain/resync/leg/
    safe and its outcome). Auth-gated; ``limit`` clamped to [1, 500]."""
    lim = max(1, min(500, int(limit)))
    wss = S.world_state_service()
    return {"ok": True, "count": wss.transaction_count(), "transactions": wss.recent(lim)}


# --- CurrentTerrainView provenance (gap A2 viz): measured vs remembered vs modeled terrain -----------
from stewie.twin.terrain_view import CurrentTerrainView  # noqa: E402  (co-located with the routes below)

_PROV_COLORS = np.array([[90, 90, 90],          # PRISTINE  -> gray (modeled)
                         [40, 110, 220],        # AS_BUILT  -> blue (remembered build)
                         [40, 190, 90]],        # OBSERVED  -> green (measured)
                        dtype=np.uint8)


def _block_max_classes(src: np.ndarray, max_px: int) -> np.ndarray:
    """Downsample the class map to <= max_px on the long side by BLOCK-MAX, so a small measured/built
    region (a higher class) survives instead of being averaged away by a plain thumbnail."""
    r, c = src.shape
    factor = max(1, int(np.ceil(max(r, c) / max(1, max_px))))
    if factor == 1:
        return src
    pr, pc = (-r) % factor, (-c) % factor
    padded = np.pad(src, ((0, pr), (0, pc)), constant_values=CurrentTerrainView.PRISTINE)
    rr, cc = padded.shape
    return padded.reshape(rr // factor, factor, cc // factor, factor).max(axis=(1, 3))


@router.get("/world/terrain_view")
def world_terrain_view(site: str = "haworth", _auth: str = Depends(require_auth)):
    """Gap A2 viz: the per-cell provenance of the composed planning surface (CurrentTerrainView) -- how
    many cells are PRISTINE (modeled) / AS_BUILT (remembered build) / OBSERVED (measured resync), plus
    the as-built version, observed twin version, and observed fraction. Auth-gated; 404 if the DEM is
    absent. No fabricated terrain -- read from the live TerrainMemory + observed twin."""
    dem, origin = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    view = S.current_terrain_view(site, dem, origin)
    src = np.asarray(view.source)
    return {"ok": True, "site": site, "provenance": {
        "as_built_version": view.as_built_version, "twin_version": view.twin_version,
        "observed_fraction": view.observed_fraction, "cell_m": view.cell_m,
        "rows": int(src.shape[0]), "cols": int(src.shape[1]),
        "cells": {"pristine": int(np.count_nonzero(src == CurrentTerrainView.PRISTINE)),
                  "as_built": int(np.count_nonzero(src == CurrentTerrainView.AS_BUILT)),
                  "observed": int(np.count_nonzero(src == CurrentTerrainView.OBSERVED))}}}


@router.get("/world/terrain_view.png")
def world_terrain_view_png(site: str = "haworth", max_px: int = 512,
                           _auth: str = Depends(require_auth)):
    """Gap A2 viz: the CurrentTerrainView source map as a colored raster -- PRISTINE gray / AS_BUILT
    blue / OBSERVED green -- downsampled by class-max so small measured/built regions survive. Auth-
    gated; 404 if the DEM is absent."""
    dem, origin = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    from PIL import Image
    view = S.current_terrain_view(site, dem, origin)
    src = _block_max_classes(np.asarray(view.source, dtype=np.uint8), max(16, min(int(max_px), 2048)))
    rgb = _PROV_COLORS[np.clip(src, 0, 2)]
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})
