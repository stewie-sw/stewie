// node:test for siteSuitability.js -- the pure SS-01 client bridge. The REAL fixture below is the VERBATIM
// shape/values from GET /api/world/site-suitability?site=shackleton_rim (the real Haworth/Shackleton LOLA
// work-area crop, 2026-07-09) -- not synthetic; captured from stewie.server.gis_layers.site_suitability.
//   Run: node --test gis/qwc2/js/mission/siteSuitability.test.js
const test = require("node:test");
const assert = require("node:assert");
const S = require("./siteSuitability.js");

// VERBATIM real response (shackleton_rim): a marginal rim site, PSR-bound.
const REAL = {
  ok: true, site: "shackleton_rim", score: 68, grade: "marginal", suitable_fraction: 0.679138,
  n_cells: 16384, n_suitable: 11127, binding_constraint: "psr",
  blocking: [
    { reason: "psr", count: 5246, fraction: 0.32019 },
    { reason: "negative_obstacle", count: 10, fraction: 0.00061 },
    { reason: "slope", count: 1, fraction: 6.1e-05 }
  ],
  fields: {
    slope_deg: { mean: 5.4552, p95: 12.6138, max: 26.835 },
    roughness: { mean: 0.0678, p95: 0.1629 },
    bearing_pa: { mean: 670.826 },
    traction_margin: { mean: 0.9008, min: 0.5067 },
    sinkage_m: { mean: 0.0008, max: 0.0009 }
  },
  thresholds: { max_slope_deg: 25.0, max_sinkage_m: 0.1, max_drop_m: 2.3315 },
  grid: { rows: 128, cols: 128, cell_m: 5.0 }, sun: { el_deg: 6.0, az_deg: 90.0 },
  provenance: "FORGE costmap compose ..."
};

test("url encodes the site into the public route", () => {
  assert.strictEqual(S.url("shackleton_rim"), "/api/world/site-suitability?site=shackleton_rim");
  assert.strictEqual(S.url("a b"), "/api/world/site-suitability?site=a%20b");
});

test("gradeColor maps each stated band; unknown -> muted", () => {
  assert.strictEqual(S.gradeColor("excellent"), "#39ff14");
  assert.strictEqual(S.gradeColor("unsuitable"), "#e0564b");
  assert.strictEqual(S.gradeColor("bogus"), "#8a93a3");
});

test("reasonLabel humanizes the veto vocabulary; unknown -> itself", () => {
  assert.strictEqual(S.reasonLabel("psr"), "permanent shadow (PSR)");
  assert.strictEqual(S.reasonLabel("negative_obstacle"), "drop-off / crater rim");
  assert.strictEqual(S.reasonLabel("weird"), "weird");
});

test("buildModel normalizes the REAL response for the panel", () => {
  const m = S.buildModel(REAL);
  assert.strictEqual(m.ok, true);
  assert.strictEqual(m.site, "shackleton_rim");
  assert.strictEqual(m.score, 68);
  assert.strictEqual(m.grade, "marginal");
  assert.strictEqual(m.color, "#e0c86a");
  assert.strictEqual(m.suitablePct, 67.9);            // 0.679138 -> one-decimal percent
  assert.strictEqual(m.binding, "psr");
  assert.strictEqual(m.bindingLabel, "permanent shadow (PSR)");
  assert.strictEqual(m.blocking.length, 3);
  assert.strictEqual(m.blocking[0].reason, "psr");
  assert.strictEqual(m.blocking[0].label, "permanent shadow (PSR)");
  assert.strictEqual(m.blocking[0].pct, 32.0);        // 0.32019 -> 32.0
  assert.strictEqual(m.fields.slope_deg.mean, 5.4552);
  assert.deepStrictEqual(m.sun, { el_deg: 6.0, az_deg: 90.0 });
});

test("buildModel surfaces a backend failure honestly (no fabricated score)", () => {
  const m = S.buildModel({ ok: false, error: "no DEM bundle for site 'x'" });
  assert.strictEqual(m.ok, false);
  assert.match(m.error, /no DEM bundle/);
  // a null/garbage body degrades to a legible error, not a crash.
  assert.strictEqual(S.buildModel(null).ok, false);
});

test("a fully-suitable site has no binding constraint", () => {
  const m = S.buildModel(Object.assign({}, REAL, {
    suitable_fraction: 1.0, n_suitable: 16384, binding_constraint: null, blocking: []
  }));
  assert.strictEqual(m.binding, null);
  assert.strictEqual(m.bindingLabel, null);
  assert.strictEqual(m.suitablePct, 100);
  assert.strictEqual(m.blocking.length, 0);
});
