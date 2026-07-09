/**
 * catalogLayers — the PURE, framework-agnostic bridge from the STEWIE mission LAYER CATALOG to
 * QWC2 map layers, for the lunar IDE (artemis.stewie.space/ide/).
 *
 * REBIND, not invent: it fetches the backend's own 68-row semantic catalog + the served raster
 * drapes + the physics legend, groups the catalog the way stewie/server/web/assets/contents_tree.js
 * groups the cockpit's layer tree (ordered, section-coherent groups + a row shape carrying a badge),
 * and turns each SERVABLE catalog row into a QWC2 `image` layer object the plugin adds to the map.
 *
 * WHY `image` (ImageStatic) and not `wms`: the backend's globe drape (/layers/globe/{kind}.png) is a
 * north-up SELENOGRAPHIC (lon/lat, IAU_2015:30100) equirectangular image with a matching geographic
 * bbox (/layers/globe/{kind}/bbox). The QWC2 map is IAU_2015:30135 (polar stereographic). An
 * ol.source.ImageStatic declared in 30100 with imageExtent = the geographic bbox is REPROJECTED by
 * OpenLayers to the 30135 view (both proj4 defs are registered in config.json). The alternative
 * (/ogc/wms) advertises only CRS:84 / EPSG:4326 / IAU_2015:30100 and returns InvalidCRS for a 30135
 * GetMap, so a QWC2 `wms` layer (which requests in the map CRS) cannot render it. See README/report.
 *
 * SERVABILITY is grounded in the backend endpoint's _GLOBE_KINDS allow-list, never faked:
 *   servable  = /layers/globe/{kind}.png returns a real PNG for these 19 globe kinds:
 *               dem, slope, hazard, illumination, incidence, psr, grid, cost, blocking, the LY-05
 *               DEM-derivative drapes aspect, curvature, roughness, the six T12 PHYSICS (TM) drapes
 *               bearing, sinkage, slip_risk, traction_margin, energy_cost, excavation_resistance, and the
 *               TW-11 traffic drape.
 *               (dem..grid verified live by curl 2026-07-06; cost + blocking added 2026-07-06 -- the
 *               plan-independent traversability-COST heatmap + the categorical BLOCKING-reason grid,
 *               both from the REAL lode.costmap_layers costmap on the site DEM; the 6 physics drapes added
 *               2026-07-06 -- each a REAL terramechanics-spine per-cell field on the site DEM slope; the
 *               traffic drape added 2026-07-07 -- the OBSERVED traversal-compaction (Dr) from the site's
 *               persistent TrafficMemory over the work-area crop; all live after a backend rebuild.)
 *   NOT served = every other catalog row (physics.compaction [OBSERVED support state, not a per-cell DEM
 *               field], the remaining traffic.* [cost_local/backlink], map.*, design.*,
 *               vector/mission/robot/runtime/evidence rows) has no independent raster endpoint. These rows
 *               are SHOWN in the tree (with provenance + eligibility) but carry no map layer, and the
 *               plugin reports the gap rather than fabricating one.
 *
 * Node-testable + CSP-safe: pure data/logic + fetch helpers, no DOM, no React, no module globals.
 */
(function (root) {
  "use strict";

  // GW-02: the site default now comes from the shared workspace (workspace.js) -- ONE source, not a
  // per-builder "haworth" literal. require() under node/webpack, window global in a raw browser bundle.
  var WS = (typeof module !== "undefined" && module.exports) ? require("./workspace.js") : (root && root.STEWIEWorkspace);
  function _site(s) { return s || (WS ? WS.site() : "haworth"); }

  // Same-origin mission API. The IDE is served at /ide/; the FastAPI backend is reverse-proxied at
  // /api/ on the same origin (deploy/artemis-nginx.conf `location /api/`). Overridable for tests.
  var API_BASE = "/api";

  // The geodetic CRS the globe drape is authored in (config.json declares this proj4 def). OpenLayers
  // reprojects an ImageStatic from here to the map's IAU_2015:30135 view.
  var LUNAR_GEOG_CRS = "IAU_2015:30100";

  // Ordered catalog DOMAIN groups (the catalog's `domain` field is what yields terrain/hazard/physics/
  // traffic/... — `source_class` is provenance, carried as the per-row badge). Order + section mirror
  // contents_tree.js GROUPS / plan_stepper coherence: site context first, then operational layers.
  var GROUPS = [
    { id: "base",     name: "Base",             section: "1" },
    { id: "terrain",  name: "Terrain",          section: "1" },
    { id: "hazard",   name: "Hazard",           section: "4" },
    { id: "physics",  name: "Physics (TM)",     section: "4" },
    { id: "traffic",  name: "Traffic",          section: "4" },
    { id: "regolith", name: "Regolith",         section: "1" },
    { id: "mission",  name: "Mission",          section: "5" },
    { id: "design",   name: "Design",           section: "5" },
    { id: "map",      name: "Map",              section: "6" },
    { id: "robot",    name: "Robot",            section: "6" },
    { id: "runtime",  name: "Evidence/Runtime", section: "6" },
    { id: "evidence", name: "Evidence/Runtime", section: "6" }
  ];

  // catalog id -> served globe kind (/layers/globe/{kind}.png + /bbox). ONLY these render; grounded
  // in the backend's _GLOBE_KINDS allow-list. Everything else is catalog-only (no raster endpoint).
  //   cost     = traffic.cost_global   -> the plan-independent traversability-cost heatmap (green->red)
  //   blocking = traffic.traversability -> the categorical blocking-reason grid (why a cell is no-go)
  // both are the REAL lode.costmap_layers costmap surfaced as map layers (AS-11 "visible blocking reason").
  //   The 6 physics.* rows below are the T12 PHYSICS (TM) drape -- each the REAL terramechanics-spine
  //   per-cell field (stewie.specs.terramechanics_spine binds each row to a live solver in
  //   stewie.physics.sinkage / slip), draped on the map (added 2026-07-06; live after a backend rebuild).
  //   traffic  = traffic.compaction -> the TW-11 OBSERVED traversal-compaction (Dr) from the site's
  //   persistent TrafficMemory, draped over the work-area crop (added 2026-07-07): real where the rover has
  //   driven, transparent where it has not. This is the OBSERVED-state sibling of the plan-independent
  //   physics rows; physics.compaction stays deliberately absent (it re-labels the SAME TrafficMemory Dr
  //   family under the Physics group, so it is not doubled as a second raster -- honest 6/7).
  //   The three LY-05 DEM-derivative analysis drapes (added 2026-07-08): aspect (gradient azimuth) +
  //   curvature (Laplacian) from the SAME heightfield gradient the slope drape uses, and roughness (the
  //   window-RMS-slope, reusing lode.costmap_layers._roughness as the one source of truth). All render via
  //   /layers/globe/{kind}.png like slope; aspect/curvature are display-only, roughness is planning-eligible.
  var SERVABLE = {
    "base.dem": "dem",
    "base.grid": "grid",
    "terrain.slope": "slope",
    "terrain.aspect": "aspect",
    "terrain.curvature": "curvature",
    "terrain.roughness": "roughness",
    "terrain.illumination": "illumination",
    "terrain.incidence": "incidence",
    "terrain.psr": "psr",
    "hazard.slope_nogo": "hazard",
    "traffic.cost_global": "cost",
    "traffic.traversability": "blocking",
    "physics.bearing": "bearing",
    "physics.sinkage": "sinkage",
    "physics.slip_risk": "slip_risk",
    "physics.traction_margin": "traction_margin",
    "physics.energy_cost": "energy_cost",
    "physics.excavation_resistance": "excavation_resistance",
    "traffic.compaction": "traffic"
  };

  // globe kind -> key in the /layers/legend payload (grid is a bare reference grid, no legend entry).
  var LEGEND_KEY = {
    dem: "dem", slope: "slope", hazard: "hazard",
    aspect: "aspect", curvature: "curvature", roughness: "roughness",
    illumination: "illumination", incidence: "incidence", psr: "psr",
    cost: "cost", blocking: "blocking",
    bearing: "bearing", sinkage: "sinkage", slip_risk: "slip_risk",
    traction_margin: "traction_margin", energy_cost: "energy_cost",
    excavation_resistance: "excavation_resistance",
    traffic: "traffic"
  };

  // Coarse provenance class from a source_class string (e.g. "prior/observed" -> "observed"), used
  // only for the badge accent colour. Strongest evidence token wins (live > observed > ... > prior).
  var PROV_RANK = ["live", "sim", "replay", "observed", "reconciled", "measured", "released",
                   "derived", "estimated", "learned", "belief", "forecast", "user", "prior"];
  function provClass(sourceClass) {
    var toks = String(sourceClass || "").split("/");
    var best = null, bestRank = 1e9;
    toks.forEach(function (t) {
      var r = PROV_RANK.indexOf(t);
      if (r >= 0 && r < bestRank) { bestRank = r; best = t; }
    });
    return best || (toks[0] || "prior");
  }

  function shortName(id) {
    var parts = String(id).split(".");
    return (parts.length > 1 ? parts[1] : parts[0]).replace(/_/g, " ");
  }

  // [REQ:GW-03] Per-layer UNCERTAINTY as a source_class-implied CONFIDENCE class + tier. The catalog declares
  // each layer's source_class (observed/prior/derived/forecast/belief/...) and THAT provenance IS the honest
  // per-layer confidence signal — a directly-observed layer is trustworthy, a forecast/belief layer is not. So
  // this classifies the REAL declared source_class; it never fabricates a numeric uncertainty. This mirrors the
  // backend layer_confidence() in stewie/server/routers/world.py exactly (the endpoint may also serve a
  // `confidence` field once the backend is rebuilt; the panel prefers that and falls back to this local
  // derivation so per-layer uncertainty renders on the currently-deployed catalog with no backend change).
  var CONF_TOKEN = {
    live: ["measured", "high"], observed: ["measured", "high"], measured: ["measured", "high"],
    reconciled: ["measured", "high"], sim_truth: ["measured", "high"], released: ["approved", "high"],
    derived: ["derived", "medium"], estimated: ["modeled", "medium"], learned: ["modeled", "medium"],
    forecast: ["predicted", "low"], belief: ["predicted", "low"],
    prior: ["reference", "medium"], user: ["authored", "n/a"],
    sim: ["evidence", "n/a"], replay: ["evidence", "n/a"], evidence: ["evidence", "n/a"]
  };
  // grounding strength, strongest first — the strongest provenance token sets the confidence class (mirrors
  // the provClass badge). Kept identical to _CONF_RANK in stewie/server/routers/world.py.
  var CONF_RANK = ["live", "observed", "measured", "reconciled", "sim_truth", "released",
                   "derived", "estimated", "learned", "forecast", "belief", "prior", "user",
                   "sim", "replay", "evidence"];
  var CONF_MEASURED = { live: 1, observed: 1, measured: 1, reconciled: 1 };
  var CONF_BASELINE = { prior: 1, derived: 1, estimated: 1, learned: 1, forecast: 1, belief: 1 };

  function confidenceFromSourceClass(sourceClass) {
    var toks = String(sourceClass || "").split("/").filter(function (t) { return !!t; });
    var best = null, bestRank = CONF_RANK.length;
    toks.forEach(function (t) {
      var r = CONF_RANK.indexOf(t);
      if (r >= 0 && r < bestRank) { bestRank = r; best = t; }
    });
    if (best === null) return { cls: "unknown", tier: "n/a", basis: sourceClass || "", conditional: false };
    var ct = CONF_TOKEN[best];
    var conditional = !!CONF_MEASURED[best] && toks.some(function (t) { return !!CONF_BASELINE[t]; });
    return { cls: ct[0], tier: ct[1], basis: sourceClass, conditional: conditional };
  }

  // The confidence a CONDITIONAL layer falls back to when it is NOT freshly observed: strip the live
  // measurement tokens and classify the remaining baseline (a `prior/observed` DEM -> prior/reference; a
  // `forecast/observed` layer -> forecast/predicted). Uses the site's REAL observed coverage as the gate.
  function confidenceBaseline(sourceClass) {
    var toks = String(sourceClass || "").split("/").filter(function (t) { return t && !CONF_MEASURED[t]; });
    return confidenceFromSourceClass(toks.join("/"));
  }

  // Build the ordered, grouped tree from the raw /world/layer-catalog payload. PURE.
  //   catalog = { layers: [ {id, domain, type, purpose, source_class, planning_eligible,
  //                          release_execute_eligible, ...}, ... ] }  (or the bare array)
  // Returns [ { id, name, section, rows: [ {id, domain, type, purpose, sourceClass, provClass,
  //             planningEligible, releaseEligible, servable, kind, legendKey, label}, ... ] } ]
  // in GROUPS order; empty groups dropped; a domain with no GROUPS entry is appended as its own group.
  function groupCatalog(catalog) {
    var layers = (catalog && catalog.layers) ? catalog.layers : (Array.isArray(catalog) ? catalog : []);
    var byDomain = {};
    layers.forEach(function (l) {
      var kind = Object.prototype.hasOwnProperty.call(SERVABLE, l.id) ? SERVABLE[l.id] : null;
      var row = {
        id: l.id,
        domain: l.domain,
        type: l.type,
        purpose: l.purpose,
        sourceClass: l.source_class,
        provClass: provClass(l.source_class),
        planningEligible: !!l.planning_eligible,
        releaseEligible: !!l.release_execute_eligible,
        // [REQ:GW-03] per-layer uncertainty: prefer the backend's served `confidence` (once rebuilt), else
        // derive it locally from the same real source_class so the panel renders it on the deployed catalog.
        confidence: l.confidence || confidenceFromSourceClass(l.source_class),
        servable: !!kind,
        kind: kind,
        legendKey: kind ? (LEGEND_KEY[kind] || null) : null,
        label: shortName(l.id)
      };
      (byDomain[l.domain] = byDomain[l.domain] || []).push(row);
    });

    var out = [];
    var seen = {};
    GROUPS.forEach(function (g) {
      if (seen[g.id]) return;
      seen[g.id] = true;
      // Evidence/Runtime is two domains (runtime + evidence) folded into one display group.
      var rows = [];
      GROUPS.forEach(function (g2) {
        if (g2.name === g.name && byDomain[g2.id]) { rows = rows.concat(byDomain[g2.id]); seen[g2.id] = true; }
      });
      if (rows.length) out.push({ id: g.id, name: g.name, section: g.section, rows: rows });
    });
    // Any domain not covered by GROUPS -> its own trailing group (future-proofing; never silently drop).
    Object.keys(byDomain).forEach(function (dom) {
      var known = GROUPS.some(function (g) { return g.id === dom; });
      if (!known) out.push({ id: dom, name: dom, section: "", rows: byDomain[dom] });
    });
    return out;
  }

  // Count servable vs total across the grouped tree (for the panel summary + honest gap reporting).
  function servableSummary(tree) {
    var total = 0, servable = 0;
    tree.forEach(function (g) { g.rows.forEach(function (r) { total++; if (r.servable) servable++; }); });
    return { total: total, servable: servable, nonServable: total - servable };
  }

  // The sun query string for the sun-parameterized drapes (illumination/incidence/psr/hazard + the
  // costmap cost/blocking, whose illumination/psr/shadow layers follow the sun). Manual el/az default
  // matches the backend defaults; `b` is a cache-bust. T7 (sun-time slider) rebinds this.
  function sunQS(opts) {
    opts = opts || {};
    var el = (opts.sunEl != null) ? opts.sunEl : 15;
    var az = (opts.sunAz != null) ? opts.sunAz : 90;
    var site = _site(opts.site);
    var b = (opts.bust != null) ? opts.bust : Date.now();
    return "sun_el=" + el + "&sun_az=" + az + "&site=" + encodeURIComponent(site) + "&b=" + b;
  }

  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // --- endpoint URLs (pure) --------------------------------------------------------------------
  function catalogUrl() { return API_BASE + "/world/layer-catalog"; }
  function legendUrl() { return API_BASE + "/layers/legend"; }
  function terramechUrl() { return API_BASE + "/world/terramechanics-layers"; }
  function trafficUrl(site) { return API_BASE + "/world/traffic-layer?site=" + encodeURIComponent(_site(site)); }
  // [REQ:GW-06] the PUBLIC per-site layer manifest -> the REAL freshness/provenance the layer tree shows.
  // The auth-gated /world 401s for the keyless public /ide/, so the panel binds this key-free projection.
  function layerManifestUrl(site) { return API_BASE + "/world/layer-manifest?site=" + encodeURIComponent(_site(site)); }
  function globePngUrl(kind, opts) { return API_BASE + "/layers/globe/" + kind + ".png?" + sunQS(opts); }
  function globeBboxUrl(kind, opts) { return API_BASE + "/layers/globe/" + kind + "/bbox?" + sunQS(opts); }

  // Build the QWC2 `image` layer object for a servable row. PURE (no dispatch, no OL). `bbox` is the
  // /bbox payload {west,south,east,north} in selenographic degrees; the ImageStatic is declared in
  // IAU_2015:30100 so OpenLayers reprojects it onto the 30135 map.
  //   layerId is stable (stewie-mission:<catalog id>) so the plugin can add/remove/track it and the
  //   stock LayerTree shows one toggleable/removable row per active mission raster.
  function imageLayerFor(row, bbox, opts) {
    if (!row || !row.servable || !bbox) return null;
    var groupName = (GROUPS.filter(function (g) { return g.id === row.domain; })[0] || {}).name || row.domain;
    return {
      id: "stewie-mission:" + row.id,
      type: "image",
      name: "stewie:" + row.id,
      title: groupName + " · " + capitalize(row.label),
      url: globePngUrl(row.kind, opts),
      projection: LUNAR_GEOG_CRS,
      imageExtent: [bbox.west, bbox.south, bbox.east, bbox.north],
      // provenance + eligibility carried onto the layer entry (harmless extras; QWC2 ignores unknowns).
      stewie: {
        catalogId: row.id,
        domain: row.domain,
        kind: row.kind,
        sourceClass: row.sourceClass,
        provClass: row.provClass,
        planningEligible: row.planningEligible,
        releaseEligible: row.releaseEligible,
        legendKey: row.legendKey
      }
    };
  }

  function capitalize(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }

  // The legend entry (from the /layers/legend payload) for a servable row, or null.
  function legendFor(row, legend) {
    if (!row || !row.legendKey || !legend) return null;
    return legend[row.legendKey] || null;
  }

  // --- async fetch helpers (guard the global fetch so the module still imports under node) --------
  // the bounded-fetch wrapper: require() under node:test/webpack, window global in a raw browser bundle.
  var FT = (typeof module !== "undefined" && module.exports)
    ? require("./fetchWithTimeout.js") : (root && root.STEWIE_FETCH_TIMEOUT);
  function _fetch() { return (typeof fetch !== "undefined") ? fetch : null; }
  function _getJson(url) {
    var f = _fetch();
    if (!f) return Promise.reject(new Error("no fetch"));
    // bounded read: a hung backend aborts after DEFAULT_MS and surfaces a legible error, never hangs the panel.
    return FT.fetchWithTimeout(url, { credentials: "same-origin" }, FT.DEFAULT_MS, f).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }
  function fetchCatalog() { return _getJson(catalogUrl()); }
  function fetchLegend() { return _getJson(legendUrl()); }
  function fetchTerramechanics() { return _getJson(terramechUrl()); }
  function fetchTraffic(site) { return _getJson(trafficUrl(site)); }
  function fetchLayerManifest(site) { return _getJson(layerManifestUrl(site)); }   // [REQ:GW-06]
  function fetchBbox(kind, opts) { return _getJson(globeBboxUrl(kind, opts)); }

  // [REQ:GW-06] PURE freshness/provenance projection from the /world/layer-manifest payload, for the
  // layer tree's per-layer freshness readout. Returns null (no claim) when the manifest is absent, so a
  // panel binding it degrades to "no freshness yet" rather than fabricating one. The freshness (observed
  // coverage) + provenance (dem_source id + observed|prior class) are SITE-level: every servable globe
  // layer is derived from the same site DEM at the same observed-twin coverage, so this readout is the
  // honest, shared freshness of that DEM-derived layer family (not a per-layer fabricated timestamp).
  function freshnessFromManifest(manifest) {
    var f = manifest && manifest.freshness;
    if (!f) return null;
    var frac = (typeof f.observed_fraction === "number") ? f.observed_fraction : null;
    return {
      observed: !!f.observed,
      observedFraction: frac,
      observedPct: (frac == null) ? null : Math.round(frac * 100),
      provClass: f.provenance_class || (frac && frac > 0 ? "observed" : "prior"),
      demSource: f.dem_source || null,
      twinVersion: f.twin_version || 0,
      asBuiltVersion: f.as_built_version || 0,
      mutated: !!f.mutated
    };
  }

  var API = {
    GROUPS: GROUPS,
    SERVABLE: SERVABLE,
    LEGEND_KEY: LEGEND_KEY,
    LUNAR_GEOG_CRS: LUNAR_GEOG_CRS,
    provClass: provClass,
    confidenceFromSourceClass: confidenceFromSourceClass,   // [REQ:GW-03]
    confidenceBaseline: confidenceBaseline,                 // [REQ:GW-03]
    shortName: shortName,
    groupCatalog: groupCatalog,
    servableSummary: servableSummary,
    sunQS: sunQS,
    base: base,
    setApiBase: setApiBase,
    catalogUrl: catalogUrl,
    legendUrl: legendUrl,
    terramechUrl: terramechUrl,
    trafficUrl: trafficUrl,
    layerManifestUrl: layerManifestUrl,
    globePngUrl: globePngUrl,
    globeBboxUrl: globeBboxUrl,
    imageLayerFor: imageLayerFor,
    legendFor: legendFor,
    freshnessFromManifest: freshnessFromManifest,
    fetchCatalog: fetchCatalog,
    fetchLegend: fetchLegend,
    fetchTerramechanics: fetchTerramechanics,
    fetchTraffic: fetchTraffic,
    fetchLayerManifest: fetchLayerManifest,
    fetchBbox: fetchBbox
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test + `import X from`
  if (root) root.STEWIE_CATALOG_LAYERS = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
