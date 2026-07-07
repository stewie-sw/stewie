/**
 * catalogLayers — the PURE, framework-agnostic bridge from the STEWIE mission LAYER CATALOG to
 * QWC2 map layers, for the lunar IDE (artemis.stewie.space/ide/).
 *
 * REBIND, not invent: it fetches the backend's own 65-row semantic catalog + the served raster
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
 *   servable  = /layers/globe/{kind}.png returns a real PNG for these 15 globe kinds:
 *               dem, slope, hazard, illumination, incidence, psr, grid, cost, blocking, and the six T12
 *               PHYSICS (TM) drapes bearing, sinkage, slip_risk, traction_margin, energy_cost,
 *               excavation_resistance.
 *               (dem..grid verified live by curl 2026-07-06; cost + blocking added 2026-07-06 -- the
 *               plan-independent traversability-COST heatmap + the categorical BLOCKING-reason grid,
 *               both from the REAL lode.costmap_layers costmap on the site DEM; the 6 physics drapes added
 *               2026-07-06 -- each a REAL terramechanics-spine per-cell field on the site DEM slope; all
 *               live after a backend rebuild.)
 *   NOT served = every other catalog row (physics.compaction [OBSERVED support state, not a per-cell DEM
 *               field], the remaining traffic.*, map.*, design.*,
 *               vector/mission/robot/runtime/evidence rows) has no independent raster endpoint;
 *               /world/traffic-layer -> 404 "no route". These rows are SHOWN in the tree (with
 *               provenance + eligibility) but carry no map layer, and the plugin reports the gap
 *               rather than fabricating one.
 *
 * Node-testable + CSP-safe: pure data/logic + fetch helpers, no DOM, no React, no module globals.
 */
(function (root) {
  "use strict";

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

  // catalog id -> served globe kind (/layers/globe/{kind}.png + /bbox). ONLY these 9 render; grounded
  // in the backend's _GLOBE_KINDS allow-list. Everything else is catalog-only (no raster endpoint).
  //   cost     = traffic.cost_global   -> the plan-independent traversability-cost heatmap (green->red)
  //   blocking = traffic.traversability -> the categorical blocking-reason grid (why a cell is no-go)
  // both are the REAL lode.costmap_layers costmap surfaced as map layers (AS-11 "visible blocking reason").
  //   The 6 physics.* rows below are the T12 PHYSICS (TM) drape -- each the REAL terramechanics-spine
  //   per-cell field (stewie.specs.terramechanics_spine binds each row to a live solver in
  //   stewie.physics.sinkage / slip), draped on the map (added 2026-07-06; live after a backend rebuild).
  //   physics.compaction is deliberately absent: it is an OBSERVED compaction/support STATE (TrafficMemory
  //   Dr family), not a plan-independent per-cell DEM field, so it stays catalog-only (honest 6/7).
  var SERVABLE = {
    "base.dem": "dem",
    "base.grid": "grid",
    "terrain.slope": "slope",
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
    "physics.excavation_resistance": "excavation_resistance"
  };

  // globe kind -> key in the /layers/legend payload (grid is a bare reference grid, no legend entry).
  var LEGEND_KEY = {
    dem: "dem", slope: "slope", hazard: "hazard",
    illumination: "illumination", incidence: "incidence", psr: "psr",
    cost: "cost", blocking: "blocking",
    bearing: "bearing", sinkage: "sinkage", slip_risk: "slip_risk",
    traction_margin: "traction_margin", energy_cost: "energy_cost",
    excavation_resistance: "excavation_resistance"
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
    var site = opts.site || "haworth";
    var b = (opts.bust != null) ? opts.bust : Date.now();
    return "sun_el=" + el + "&sun_az=" + az + "&site=" + encodeURIComponent(site) + "&b=" + b;
  }

  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // --- endpoint URLs (pure) --------------------------------------------------------------------
  function catalogUrl() { return API_BASE + "/world/layer-catalog"; }
  function legendUrl() { return API_BASE + "/layers/legend"; }
  function terramechUrl() { return API_BASE + "/world/terramechanics-layers"; }
  function trafficUrl(site) { return API_BASE + "/world/traffic-layer?site=" + encodeURIComponent(site || "haworth"); }
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
  function _fetch() { return (typeof fetch !== "undefined") ? fetch : null; }
  function _getJson(url) {
    var f = _fetch();
    if (!f) return Promise.reject(new Error("no fetch"));
    return f(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status + " for " + url);
      return r.json();
    });
  }
  function fetchCatalog() { return _getJson(catalogUrl()); }
  function fetchLegend() { return _getJson(legendUrl()); }
  function fetchTerramechanics() { return _getJson(terramechUrl()); }
  function fetchTraffic(site) { return _getJson(trafficUrl(site)); }
  function fetchBbox(kind, opts) { return _getJson(globeBboxUrl(kind, opts)); }

  var API = {
    GROUPS: GROUPS,
    SERVABLE: SERVABLE,
    LEGEND_KEY: LEGEND_KEY,
    LUNAR_GEOG_CRS: LUNAR_GEOG_CRS,
    provClass: provClass,
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
    globePngUrl: globePngUrl,
    globeBboxUrl: globeBboxUrl,
    imageLayerFor: imageLayerFor,
    legendFor: legendFor,
    fetchCatalog: fetchCatalog,
    fetchLegend: fetchLegend,
    fetchTerramechanics: fetchTerramechanics,
    fetchTraffic: fetchTraffic,
    fetchBbox: fetchBbox
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test + `import X from`
  if (root) root.STEWIE_CATALOG_LAYERS = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
