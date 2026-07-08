/**
 * terramechClient — the PURE bridge to the STEWIE TERRAMECHANICS SPINE for the lunar IDE's Analyze panel
 * (the council's "surface the backend the frontend discards"). The backend's GET /api/world/terramechanics-
 * layers is a PUBLIC map-data read: for a site it returns the physics-computation decomposition -- which
 * derived layer (terrain.slope, physics.bearing, physics.sinkage, ...) is computed FROM which terms, on which
 * backend (authority tier, e.g. tier2_numpy). This module builds the URL + normalizes the response for
 * display; no DOM/React -> node-testable.
 */
(function (root) {
  "use strict";
  var API_BASE = "/api";                         // same-origin mission API (nginx proxies /api/). Overridable for tests.
  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // The PUBLIC terramechanics-spine endpoint (the per-site physics decomposition).
  function spineUrl(site) { return API_BASE + "/world/terramechanics-layers?site=" + encodeURIComponent(site); }

  function fetchSpine(site) {
    return fetch(spineUrl(site)).then(function (r) {
      if (!r.ok) { throw new Error("terramechanics-spine HTTP " + r.status); }
      return r.json();
    });
  }

  // Normalize the spine response for the Analyze panel. Groups nothing away, surfaces failures honestly.
  function buildSpineModel(data) {
    if (!data || data.ok === false) {
      return { ok: false, error: (data && data.error) || "terramechanics spine unavailable" };
    }
    var layers = (data.derived_layers || []).map(function (d) {
      var id = String(d.layer || "");
      var parts = id.split(".");
      return {
        layer: id,
        group: parts[0] || "",
        name: parts.slice(1).join(".") || id,
        terms: d.from_terms || [],
        computed: d.computed_terms || [],
        backend: d.backend || data.backend || null
      };
    });
    return { ok: true, backend: data.backend || null, count: layers.length, layers: layers };
  }

  var API = { base: base, setApiBase: setApiBase, spineUrl: spineUrl, fetchSpine: fetchSpine, buildSpineModel: buildSpineModel };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_TERRAMECH = API; }                                       // browser (window)
})(typeof window !== "undefined" ? window : null);
