// [REQ:GW-07] (node:test): the QWC2 SELECTION-INSPECTOR data layer is pure data/logic (no DOM, no OL, no
// React), so its URL builder + the value/provenance/confidence/freshness MERGE serialize + unit-test in bare
// node. This asserts the REAL outputs of selectionInspect.js against catalog + point fixtures shaped exactly
// like the live /api/world/layer-catalog + /api/world/point payloads: the merge attaches each cell VALUE to
// its GW-03 confidence + GW-06 freshness, applies the not-fresh confidence DOWNGRADE, preserves the backend's
// honest no-data rows verbatim, and formats values with units. The Python backend contract for GW-07 is
// stewie/server/test_gw07_point_inspect.py; the live panel binding is gis/qwc2/proof/drive_gw07_inspector.cjs.
// Run: node --test gis/qwc2/js/mission/selectionInspect.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const S = require("./selectionInspect.js");

// a mini catalog shaped like /api/world/layer-catalog (the fields groupCatalog reads): a measured DEM over a
// prior baseline (conditional confidence), a derived physics layer, a display-only illumination layer.
const CATALOG = { layers: [
  { id: "base.dem", domain: "base", type: "raster", purpose: "elevation",
    source_class: "prior/observed", planning_eligible: true, release_execute_eligible: false },
  { id: "physics.bearing", domain: "physics", type: "raster", purpose: "contact pressure",
    source_class: "derived", planning_eligible: true, release_execute_eligible: false },
  { id: "terrain.illumination", domain: "terrain", type: "raster", purpose: "lit/shadow",
    source_class: "forecast", planning_eligible: false, release_execute_eligible: false }
]};

// a point payload shaped like /api/world/point (a measured DEM + physics value + an honest no-data layer).
const POINT = { ok: true, site: "haworth",
  cell: { row: 1395, col: 835, cell_m: 5.0, in_bounds: true },
  attributes: [
    { id: "base.dem", label: "Elevation", unit: "m", value: 1101.0847, available: true },
    { id: "physics.bearing", label: "Bearing (contact pressure)", unit: "Pa", value: 673.44, available: true },
    { id: "terrain.illumination", label: "Illumination", unit: "", value: null, available: false,
      note: "sun-parameterized (horizon shadowing) -- set the sun to query per cell" }
  ],
  runtime_evidence: { cell_source: "pristine", as_built_delta_m: 0.0, as_built_version: 0,
    twin_version: 18, observed_fraction: 0.0, observed_at_cell: false },
  actions: [
    { id: "plan_here", label: "Plan here", enabled: true, reason: null },
    { id: "place_structure", label: "Place structure", enabled: false, reason: "cell is impassable (blocked terrain)" },
    { id: "add_keepout", label: "Add keep-out", enabled: true, reason: null }
  ]
};

test("pointUrl: lon/lat, x/y, and the honest empty coordinate", () => {
  assert.strictEqual(S.pointUrl("haworth", { lon: -26.6384, lat: -86.1152 }),
    "/api/world/point?site=haworth&lon=-26.6384&lat=-86.1152");
  assert.strictEqual(S.pointUrl("haworth", { x: 60, y: 60 }),
    "/api/world/point?site=haworth&x=60&y=60");
  assert.strictEqual(S.pointUrl("haworth", {}), "/api/world/point?site=haworth");   // backend 400s (honest)
});

test("catalogById: indexes the grouped catalog by layer id with derived provenance/confidence", () => {
  const by = S.catalogById(CATALOG);
  assert.ok(by["base.dem"] && by["physics.bearing"] && by["terrain.illumination"]);
  assert.strictEqual(by["base.dem"].provClass, "observed");           // strongest token in prior/observed
  assert.strictEqual(by["base.dem"].confidence.cls, "measured");       // observed -> measured (GW-03)
  assert.strictEqual(by["base.dem"].confidence.conditional, true);     // measured over a prior baseline
  assert.strictEqual(by["physics.bearing"].confidence.cls, "derived"); // derived -> derived/medium
});

test("mergeAttributes: attaches value + provenance + confidence + freshness per attribute", () => {
  const by = S.catalogById(CATALOG);
  const fresh = { provClass: "observed", demSource: "haworth_10km_5m", observedPct: 42 };
  const rows = S.mergeAttributes(POINT, by, fresh);
  const dem = rows.find((r) => r.id === "base.dem");
  assert.strictEqual(dem.value, 1101.0847);
  assert.strictEqual(dem.available, true);
  assert.strictEqual(dem.provClass, "observed");
  assert.strictEqual(dem.confidence.cls, "measured");                  // fresh site -> keeps measured grade
  assert.strictEqual(dem.confidence.downgraded, undefined);            // not downgraded when observed
  assert.strictEqual(dem.freshness.demSource, "haworth_10km_5m");
  assert.strictEqual(dem.freshness.observedPct, 42);
});

test("mergeAttributes: DOWNGRADES a conditional confidence when the site is NOT freshly observed", () => {
  const by = S.catalogById(CATALOG);
  const prior = { provClass: "prior", demSource: "haworth_10km_5m", observedPct: 0 };
  const rows = S.mergeAttributes(POINT, by, prior);
  const dem = rows.find((r) => r.id === "base.dem");
  // the DEM's measured grade is conditional on fresh observation; a prior/unobserved site -> baseline.
  assert.strictEqual(dem.confidence.downgraded, true);
  assert.strictEqual(dem.confidence.cls, "reference");                 // prior -> reference (not measured)
});

test("mergeAttributes: preserves the backend's honest no-data row verbatim (never fabricated)", () => {
  const by = S.catalogById(CATALOG);
  const rows = S.mergeAttributes(POINT, by, { provClass: "prior" });
  const ill = rows.find((r) => r.id === "terrain.illumination");
  assert.strictEqual(ill.available, false);
  assert.strictEqual(ill.value, null);
  assert.ok(ill.note && ill.note.indexOf("sun-parameterized") === 0);  // the backend's reason, carried through
});

test("formatValue: numbers with units, booleans, and no-data -> null", () => {
  assert.strictEqual(S.formatValue({ available: true, value: 1101.0847, unit: "m" }), "1101.085 m");
  assert.strictEqual(S.formatValue({ available: true, value: 673.44, unit: "Pa" }), "673.44 Pa");
  assert.strictEqual(S.formatValue({ available: true, value: 0.0008, unit: "m" }), "8.00e-4 m");
  assert.strictEqual(S.formatValue({ available: true, value: false, unit: "" }), "no");
  assert.strictEqual(S.formatValue({ available: false, value: null }), null);
});

test("partition: splits merged rows into measured vs honest no-data", () => {
  const by = S.catalogById(CATALOG);
  const { measured, nodata } = S.partition(S.mergeAttributes(POINT, by, null));
  assert.deepStrictEqual(measured.map((r) => r.id), ["base.dem", "physics.bearing"]);
  assert.deepStrictEqual(nodata.map((r) => r.id), ["terrain.illumination"]);
});
