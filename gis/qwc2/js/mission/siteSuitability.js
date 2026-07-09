/**
 * siteSuitability — the PURE bridge to the STEWIE SITE-SURVEY SUITABILITY score for the lunar IDE's
 * Mission-Plan panel (SS-01). The backend's GET /api/world/site-suitability is a PUBLIC map-data read: for a
 * site it aggregates the REAL FORGE costmap over the framed work-area crop into a landing/construction
 * suitability score (= the fraction of real cells that pass the real physics gates -- no invented weighting),
 * its binding constraint (the dominant veto reason), and the descriptive terrain sub-fields. This module
 * builds the URL + normalizes the response for display (friendly reason labels + a grade colour); no
 * DOM/React -> node-testable, exactly like terramechClient.js / runtimeClient.js.
 *   Run: node --test gis/qwc2/js/mission/siteSuitability.test.js
 */
(function (root) {
  "use strict";
  var API_BASE = "/api";                         // same-origin mission API (nginx proxies /api/). Overridable for tests.
  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // the bounded-fetch wrapper: require() under node:test/webpack, window global in a raw browser bundle.
  var FT = (typeof module !== "undefined" && module.exports)
    ? require("./fetchWithTimeout.js") : (root && root.STEWIE_FETCH_TIMEOUT);

  // The PUBLIC site-suitability endpoint (per-site work-area survey summary).
  function url(site) { return API_BASE + "/world/site-suitability?site=" + encodeURIComponent(site); }

  function fetchSuitability(site) {
    return FT.fetchWithTimeout(url(site), {}, FT.DEFAULT_MS).then(function (r) {
      if (!r.ok) {
        // 404 = the site has no imported DEM bundle; surface the backend reason if present.
        return r.json().then(function (b) {
          throw new Error((b && b.error) || ("site-suitability HTTP " + r.status));
        }, function () { throw new Error("site-suitability HTTP " + r.status); });
      }
      return r.json();
    });
  }

  // The grade band -> a dark-IDE accent colour (matches the SS-01 rating labels; a stated decision-support
  // scale, not a physical measurement). Kept in the pure module so the panel + a node test agree.
  var GRADE_COLOR = {
    excellent: "#39ff14", good: "#7fe0a8", marginal: "#e0c86a", poor: "#e0a04f", unsuitable: "#e0564b"
  };
  function gradeColor(grade) { return GRADE_COLOR[grade] || "#8a93a3"; }

  // Friendly, human-readable label for a costmap veto reason (the binding-constraint vocabulary the backend
  // emits; MUST stay a subset of costmap_layers.BLOCKING_LEGEND_ORDER). An unknown reason falls back to itself.
  var REASON_LABEL = {
    slope: "steep slope", sinkage: "wheel sinkage", tip_risk: "tip-over risk",
    negative_obstacle: "drop-off / crater rim", psr: "permanent shadow (PSR)",
    keepout: "operator keep-out", reservation: "vehicle reservation"
  };
  function reasonLabel(reason) { return REASON_LABEL[reason] || String(reason || ""); }

  // Normalize the suitability response for the panel. Surfaces failures honestly; never fabricates a score.
  function buildModel(data) {
    if (!data || data.ok === false) {
      return { ok: false, error: (data && data.error) || "site suitability unavailable" };
    }
    var blocking = (data.blocking || []).map(function (b) {
      return {
        reason: b.reason, label: reasonLabel(b.reason), count: b.count,
        pct: Math.round((b.fraction || 0) * 1000) / 10   // one-decimal percent of the work area
      };
    });
    var grade = data.grade || "unsuitable";
    return {
      ok: true,
      site: data.site,
      score: data.score,
      grade: grade,
      color: gradeColor(grade),
      suitablePct: Math.round((data.suitable_fraction || 0) * 1000) / 10,
      nCells: data.n_cells,
      nSuitable: data.n_suitable,
      binding: data.binding_constraint || null,
      bindingLabel: data.binding_constraint ? reasonLabel(data.binding_constraint) : null,
      blocking: blocking,
      fields: data.fields || {},
      sun: data.sun || null,
      grid: data.grid || null,
      thresholds: data.thresholds || null,
      provenance: data.provenance || ""
    };
  }

  var API = {
    base: base, setApiBase: setApiBase, url: url, fetchSuitability: fetchSuitability,
    buildModel: buildModel, gradeColor: gradeColor, reasonLabel: reasonLabel
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_SUITABILITY = API; }                                     // browser (window)
})(typeof window !== "undefined" ? window : null);
