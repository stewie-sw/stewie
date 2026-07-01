// FS-24 (node:test): the dig-only feasibility estimate is pure math + a pure popover table, so unit-
// testable without a browser. The badges + DOM wiring stay in cockpit.js. Behavior preserved.
// Run: node --test stewie/server/web/assets/regolith_estimate.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const R = require("./regolith_estimate.js");

// representative moon terramechanics + IPEx constants (bodies.json _ipex block shape).
const P = { density: 1500, g: 1.62 };
const IX = { drum_kg: 30, dig_j_per_kg: 4151, battery_j: 4790000, dig_rate_kg_hr: 1000, recharge_w: 700 };

test("computeEstimate: dig-dominant math is exact (cutMass drives everything)", () => {
  const e = R.computeEstimate({ padW: 10, padL: 10, cut: 0.3, bermH: 0 }, P, IX);
  assert.strictEqual(e.cutVol, 30);                    // 10*10*0.3
  assert.strictEqual(e.cutMass, 45000);                // 30 * 1500
  assert.ok(Math.abs(e.weightN - 72900) < 1e-6);       // 45000 * 1.62
  assert.strictEqual(e.bermArea, 0);                   // bermH 0 -> no berm
  assert.strictEqual(e.drumLoads, 1500);               // ceil(45000/30)
  assert.strictEqual(e.energyJ, 45000 * 4151);
  assert.ok(Math.abs(e.charges - (45000 * 4151) / 4790000) < 1e-9);
  assert.strictEqual(e.hrs, 45);                        // 45000 / 1000
  assert.strictEqual(e.digJPerKg, 4151);
});

test("computeEstimate: a berm height yields a mass-balanced footprint", () => {
  const e = R.computeEstimate({ padW: 10, padL: 10, cut: 0.3, bermH: 0.5 }, P, IX);
  assert.ok(Math.abs(e.bermArea - 45000 / (0.5 * 1500)) < 1e-6);   // cutMass / (bermH * density)
});

test("computeEstimate: recharge_w falls back to 700 when absent", () => {
  const e = R.computeEstimate({ padW: 1, padL: 1, cut: 0.1, bermH: 0 }, P, { ...IX, recharge_w: undefined });
  assert.strictEqual(e.rw, 700);
});

test("feasibilityBreakdownHTML: renders the breakdown rows + the sourced dig-energy basis", () => {
  const e = R.computeEstimate({ padW: 10, padL: 10, cut: 0.3, bermH: 0.5 }, P, IX);
  const h = R.feasibilityBreakdownHTML(e);
  assert.ok(h.includes("Feasibility breakdown"));
  assert.ok(h.includes("excavated volume") && h.includes("30 m³"));
  assert.ok(h.includes("battery charges"));
  assert.ok(h.includes("mission timeline"));
  assert.ok(h.includes("dig-energy basis: 4151 J/kg"));   // sourced from ix, not hardcoded
});
