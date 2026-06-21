// FS-03 (node:test): the Construction-pane renderers are pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/construction_render.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const C = require("./construction_render.js");

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// a real /construction payload shape (leap/structures.py + lode/planner_acceptance.py).
const CON = {
  ok: true, count: 2, balanced_count: 1, probe_origin_m: [0, 0],
  templates: [
    { id: "blast_berm", doc: "A loose fill ridge supplied by a nearby borrow pit.", n_orders: 2,
      n_cut: 1, n_fill: 1, balanced: true,
      orders: [
        { action: "Borrow pit (berm)", kind: "cut", footprint_m2: 15.2, depth_m: 0.3, note: "source" },
        { action: "Blast berm", kind: "fill", footprint_m2: 45.0, depth_m: 0.5, note: "ridge to spec" },
      ] },
    { id: "borrow_pit", doc: "Material source.", n_orders: 1, n_cut: 1, n_fill: 0, balanced: false,
      orders: [{ action: "Borrow pit", kind: "cut", footprint_m2: 36.0, depth_m: 0.3, note: "material source" }] },
  ],
  acceptance: {
    checks: [
      { id: "mass_conservation", what: "all-cuts-then-all-fills balance" },
      { id: "slope_siting", what: "no order on slope above max", max_slope_deg: 15.0 },
      { id: "as_built_flatness", what: "executed-surface flatness RMSE within tol", tol_m: 0.02 },
      { id: "repose_stability", what: "as-built flank slope <= phi" },
      { id: "bearing_capacity", what: "Terzaghi/Vesic allowable bearing", factor_of_safety: 3.0 },
    ],
    defers_to_totals: ["route_feasibility", "battery_reserve", "time_budget"],
  },
};

test("constructionCatalogHTML: renders one row per real structure template with its primitives", () => {
  const html = C.constructionCatalogHTML(CON, esc);
  assert.ok(html.includes("blast_berm"), "blast_berm template present");
  assert.ok(html.includes("borrow_pit"), "borrow_pit template present");
  assert.ok(html.includes("Blast berm"), "primitive fill order action rendered");
  assert.ok(html.includes("cut") && html.includes("fill"), "cut/fill kinds rendered");
  assert.ok(html.includes("balanced"), "balanced flag rendered");
  assert.ok(html.includes("2 templates"), "catalog count footer");
  assert.ok(html.includes("leap/structures.py"), "provenance named");
});

test("constructionCatalogHTML: honest empty when no templates", () => {
  assert.ok(C.constructionCatalogHTML({ templates: [] }, esc).includes("No structure catalog"));
});

test("constructionAcceptanceHTML: criteria definition always rendered (with tolerances)", () => {
  const html = C.constructionAcceptanceHTML(CON, null, esc);
  assert.ok(html.includes("mass_conservation"), "check id rendered");
  assert.ok(html.includes("as_built_flatness"), "flatness check rendered");
  assert.ok(html.includes("2.0 cm"), "flatness tol (0.02 m) rendered in cm");
  assert.ok(html.includes("15") && html.includes("°"), "slope tolerance rendered");
  assert.ok(html.includes("FS 3"), "bearing factor of safety rendered");
  assert.ok(html.includes("defers to plan totals"), "deferred checks named");
});

test("constructionAcceptanceHTML: honest empty as-built when no plan has been run", () => {
  const html = C.constructionAcceptanceHTML(CON, null, esc);
  assert.ok(html.includes("No as-built acceptance yet"), "empty as-built state shown");
});

test("constructionAcceptanceHTML: renders the live as-built result from the last plan validation", () => {
  const validation = {
    feasible: true, mass_conserved: true, mass_drift_kg: 0.0,
    as_built_on_real_dem: true, as_built_flatness_rmse_m: 0.013, as_built_tol_m: 0.02, as_built_pass: true,
    berm_profile: [{}], berm_profile_pass: true,
    repose: [{}], repose_pass: false, repose_limit_deg: 35.0,
    bearing: [{}, {}], bearing_pass: true,
  };
  const html = C.constructionAcceptanceHTML(CON, validation, esc);
  assert.ok(html.includes("as-built flatness"), "flatness result row");
  assert.ok(html.includes("1.3 cm"), "as-built RMSE (0.013 m) rendered");
  assert.ok(html.includes("✓ pass"), "a passing verdict rendered");
  assert.ok(html.includes("✗ fail"), "the failing repose verdict rendered");
  assert.ok(html.includes("limit 35") && html.includes("φ"), "repose limit rendered");
  assert.ok(html.includes("bearing capacity"), "bearing result row");
});
