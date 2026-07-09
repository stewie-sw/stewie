/**
 * assetLibrary — the PURE, framework-agnostic bridge to the STEWIE Asset Library
 * ([REQ:GW-04]) for the lunar IDE (artemis.stewie.space/ide/).
 *
 * The backend's GET /api/library is a PUBLIC map-data read (like /world/layer-catalog): it returns the
 * DURABLE-ASSET MANIFEST — live missions, shared structure templates, mission-control reports, per-site
 * Terrain Memory, observed-twin journals, and the real DEM bundles — each with type / id / created /
 * provenance / size_bytes / recoverable + inspect/export hrefs. This module fetches it and exposes PURE
 * helpers (group-by-type, client-side search, size/date formatting, export URL) so the panel can browse /
 * search / inspect / export WITHOUT re-deriving anything or fabricating an asset. The sensitive payload
 * (mission orders, report bytes) stays auth-gated behind payload_href — the library shows metadata only.
 *
 * Node-testable + CSP-safe: pure data/logic + fetch helpers, no DOM, no React, no module globals.
 */
(function (root) {
  "use strict";

  // Same-origin mission API (the IDE is served at /ide/; FastAPI is reverse-proxied at /api/). Overridable.
  var API_BASE = "/api";

  // Display order + label + glyph per durable asset type (mirrors backend asset_library.ASSET_TYPES).
  var TYPES = [
    { id: "mission",   label: "Missions",         glyph: "◎" },
    { id: "structure", label: "Structure Templates", glyph: "▤" },
    { id: "report",    label: "Reports",          glyph: "▦" },
    { id: "site",      label: "Terrain Memory",   glyph: "◍" },
    { id: "twin",      label: "Observed Twin",    glyph: "◈" },
    { id: "dem",       label: "DEM Bundles",      glyph: "▚" }
  ];
  var TYPE_LABEL = {};
  var TYPE_GLYPH = {};
  TYPES.forEach(function (t) { TYPE_LABEL[t.id] = t.label; TYPE_GLYPH[t.id] = t.glyph; });

  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  function libraryUrl(opts) {
    opts = opts || {};
    var qs = [];
    if (opts.q) qs.push("q=" + encodeURIComponent(opts.q));
    if (opts.type) qs.push("type=" + encodeURIComponent(opts.type));
    if (opts.includeTrash) qs.push("include_trash=1");
    return API_BASE + "/library" + (qs.length ? "?" + qs.join("&") : "");
  }
  function inspectUrl(atype, aid) { return API_BASE + "/library/" + atype + "/" + encodeURIComponent(aid); }
  function exportUrl(atype, aid) {
    return API_BASE + "/library/" + atype + "/" + encodeURIComponent(aid) + "/export";
  }

  // --- pure formatters --------------------------------------------------------------------------
  function humanSize(bytes) {
    var n = Number(bytes);
    if (!isFinite(n) || n < 0) return "";
    if (n < 1024) return n + " B";
    var units = ["KB", "MB", "GB", "TB"];
    var i = -1;
    do { n = n / 1024; i++; } while (n >= 1024 && i < units.length - 1);
    return (n < 10 ? n.toFixed(1) : Math.round(n)) + " " + units[i];
  }
  function humanTime(epochSec) {
    var t = Number(epochSec);
    if (!isFinite(t) || t <= 0) return "";
    try { return new Date(t * 1000).toISOString().slice(0, 10); } catch (e) { return ""; }
  }

  // --- pure browse/search/group logic -----------------------------------------------------------
  // Case-insensitive substring match over the browsable fields (type/id/title/provenance).
  function matchAsset(a, q) {
    if (!q) return true;
    var hay = [a.type, a.id, a.title, a.provenance].join(" ").toLowerCase();
    return hay.indexOf(String(q).toLowerCase()) >= 0;
  }
  // Filter a loaded asset list by a client-side query (snappy re-filter without a round-trip).
  function filterAssets(assets, q) {
    return (assets || []).filter(function (a) { return matchAsset(a, q); });
  }
  // Group assets into ordered { id, label, glyph, rows } sections in TYPES order; empty sections dropped;
  // an unknown type is appended as its own trailing section (never silently dropped).
  function groupByType(assets) {
    var byType = {};
    (assets || []).forEach(function (a) { (byType[a.type] = byType[a.type] || []).push(a); });
    var out = [];
    var seen = {};
    TYPES.forEach(function (t) {
      seen[t.id] = true;
      if (byType[t.id] && byType[t.id].length) {
        out.push({ id: t.id, label: t.label, glyph: t.glyph, rows: byType[t.id] });
      }
    });
    Object.keys(byType).forEach(function (k) {
      if (!seen[k]) out.push({ id: k, label: k, glyph: "•", rows: byType[k] });
    });
    return out;
  }
  // Per-type counts for the browse header.
  function counts(assets) {
    var c = {};
    (assets || []).forEach(function (a) { c[a.type] = (c[a.type] || 0) + 1; });
    return c;
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
  function fetchLibrary(opts) { return _getJson(libraryUrl(opts)); }
  function fetchAsset(atype, aid) { return _getJson(inspectUrl(atype, aid)); }

  var API = {
    TYPES: TYPES,
    TYPE_LABEL: TYPE_LABEL,
    TYPE_GLYPH: TYPE_GLYPH,
    base: base,
    setApiBase: setApiBase,
    libraryUrl: libraryUrl,
    inspectUrl: inspectUrl,
    exportUrl: exportUrl,
    humanSize: humanSize,
    humanTime: humanTime,
    matchAsset: matchAsset,
    filterAssets: filterAssets,
    groupByType: groupByType,
    counts: counts,
    fetchLibrary: fetchLibrary,
    fetchAsset: fetchAsset
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test + `import X from`
  if (root) root.STEWIE_ASSET_LIBRARY = API;                                   // browser (window)
})(typeof window !== "undefined" ? window : null);
