/**
 * selectionInspect — the PURE, framework-agnostic data layer for the STEWIE SELECTION INSPECTOR
 * ([REQ:GW-07]) in the lunar IDE (artemis.stewie.space/ide/).
 *
 * A clicked map cell drives ONE per-cell backend query (/api/world/point) whose per-layer VALUES are then
 * merged with the layer catalog's PROVENANCE + CONFIDENCE (GW-03) and the per-site FRESHNESS (GW-06) so the
 * inspector shows, for that point: the servable layers' actual values, each with where-it-came-from + how-
 * much-to-trust-it + how-fresh, the cell's runtime evidence (as-built / observed), and the mission actions
 * the cell affords. This module is the pure bridge (URL builders + response shaping); the React plugin
 * (js/plugins/SelectionInspector.jsx) owns the map click + the DOM.
 *
 * Honesty is carried straight through from the backend: an attribute the backend reports available=false
 * (a sun-parameterized / reference-grid / observed-only layer, or an out-of-tile click) is shaped as a
 * "no data" row with the backend's reason — this module never fabricates a value the backend did not return.
 *
 * REUSES catalogLayers.js (the GW-06/GW-03 module) for the confidence derivation + the freshness projection,
 * so the provenance/confidence/freshness the inspector shows is IDENTICAL to the Mission Layers panel.
 *
 * Node-testable + CSP-safe: pure data/logic + fetch helpers, no DOM, no React, no module globals.
 */
(function (root) {
  "use strict";

  // the GW-06/GW-03 catalog module: require() under node:test, window global in the browser bundle.
  var CL = (typeof module !== "undefined" && module.exports)
    ? require("./catalogLayers.js")
    : (root && root.STEWIE_CATALOG_LAYERS);
  // GW-02: the shared workspace default site (workspace.js) -- one source, not a per-builder literal.
  var WS = (typeof module !== "undefined" && module.exports) ? require("./workspace.js") : (root && root.STEWIEWorkspace);

  var API_BASE = "/api";                      // same-origin mission API (nginx proxies /api/). Overridable for tests.
  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // --- endpoint URL (pure) ---------------------------------------------------------------------------
  // The click arrives as selenographic lon/lat (the OpenLayers 30135 view coordinate reprojected to
  // IAU_2015:30100); the backend resolves it to the site DEM cell. `coords` = {lon, lat} or {x, y}.
  function pointUrl(site, coords) {
    var s = "site=" + encodeURIComponent(site || (WS ? WS.site() : "haworth"));
    var c = coords || {};
    if (c.lon != null && c.lat != null) {
      return API_BASE + "/world/point?" + s + "&lon=" + encodeURIComponent(c.lon) + "&lat=" + encodeURIComponent(c.lat);
    }
    if (c.x != null && c.y != null) {
      return API_BASE + "/world/point?" + s + "&x=" + encodeURIComponent(c.x) + "&y=" + encodeURIComponent(c.y);
    }
    return API_BASE + "/world/point?" + s;    // backend replies 400 (honest) — caller must pass a coordinate
  }

  // --- async fetch helpers (guard the global fetch so the module still imports under node) ------------
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
  function fetchPoint(site, coords) { return _getJson(pointUrl(site, coords)); }

  // --- catalog index (id -> the grouped-catalog row carrying provClass/confidence/eligibility) --------
  // Built from the SAME CL.groupCatalog the Mission Layers panel uses, so every derived field matches.
  function catalogById(catalog) {
    var by = {};
    if (!CL || !catalog) return by;
    CL.groupCatalog(catalog).forEach(function (g) {
      g.rows.forEach(function (row) { by[row.id] = row; });
    });
    return by;
  }

  // --- the merge: a per-cell attribute + its provenance/confidence/freshness --------------------------
  // For each backend attribute row, attach the catalog's PROVENANCE (source_class) + CONFIDENCE (GW-03,
  // source_class-implied uncertainty) + the site FRESHNESS (GW-06). A CONDITIONAL confidence (a live-
  // measurement token over a prior/derived baseline) is DOWNGRADED to its baseline when the site is not
  // freshly observed — the exact rule the Mission Layers panel applies (never overstate a prior DEM as
  // measured). Returns a display-ready row array in the backend's order.
  function mergeAttributes(point, catById, freshness) {
    var attrs = (point && Array.isArray(point.attributes)) ? point.attributes : [];
    var notFresh = !freshness || freshness.provClass !== "observed";
    return attrs.map(function (a) {
      var cat = (catById && catById[a.id]) || null;
      var conf = null;
      if (cat && cat.confidence && cat.confidence.cls) {
        conf = cat.confidence;
        if (conf.conditional && notFresh && CL) {
          conf = CL.confidenceBaseline(conf.basis || cat.sourceClass);
          conf = { cls: conf.cls, tier: conf.tier, basis: conf.basis, conditional: true, downgraded: true };
        }
      }
      return {
        id: a.id,
        label: a.label,
        unit: a.unit || "",
        value: (a.value === undefined ? null : a.value),
        available: !!a.available,
        note: a.note || null,
        reason: (a.reason === undefined ? null : a.reason),
        sourceClass: cat ? cat.sourceClass : null,
        provClass: cat ? cat.provClass : null,
        confidence: conf,
        planningEligible: cat ? !!cat.planningEligible : false,
        releaseEligible: cat ? !!cat.releaseEligible : false,
        freshness: freshness ? {
          provClass: freshness.provClass, demSource: freshness.demSource,
          observedPct: (typeof freshness.observedPct === "number") ? freshness.observedPct : null
        } : null
      };
    });
  }

  // Format a numeric/boolean value + unit for display, or the honest no-data placeholder. PURE.
  function formatValue(row) {
    if (!row || row.available !== true || row.value === null || row.value === undefined) return null;
    if (typeof row.value === "boolean") return row.value ? "yes" : "no";
    if (typeof row.value === "number") {
      var v = row.value;
      var s = (Math.abs(v) !== 0 && (Math.abs(v) < 0.001 || Math.abs(v) >= 100000))
        ? v.toExponential(2)
        : String(Math.round(v * 1000) / 1000);
      return row.unit ? (s + " " + row.unit) : s;
    }
    return String(row.value);
  }

  // Split the merged rows into the two honest buckets the panel renders: measured (a real per-cell value)
  // vs no-data (available=false — sun-parameterized / grid / observed-only / off-tile). PURE.
  function partition(rows) {
    var measured = [], nodata = [];
    (rows || []).forEach(function (r) { (r.available ? measured : nodata).push(r); });
    return { measured: measured, nodata: nodata };
  }

  var API = {
    base: base, setApiBase: setApiBase,
    pointUrl: pointUrl, fetchPoint: fetchPoint,
    catalogById: catalogById, mergeAttributes: mergeAttributes,
    formatValue: formatValue, partition: partition,
    // re-exported for the plugin's one-shot fetches (catalog + manifest), matching the panel's sources.
    fetchCatalog: CL ? CL.fetchCatalog : null,
    fetchLayerManifest: CL ? CL.fetchLayerManifest : null,
    freshnessFromManifest: CL ? CL.freshnessFromManifest : null
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test + `import X from`
  if (root) root.STEWIE_SELECTION_INSPECT = API;                               // browser (window)
})(typeof window !== "undefined" ? window : null);
