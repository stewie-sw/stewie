// PLAN-STEPPER (node:test): the step -> sidebar-section map is PURE -> unit-testable. The DOM glue
// (focusStep) lives in cockpit.js; this covers the mapping every step relies on, including that each
// of the six pipeline steps reveals SOME sections (the review/execute regression that left their
// sidebar showing the previous step's sections) and that no step's sections overflow the 1..7 range.
// Run: node --test stewie/server/web/assets/plan_stepper.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const S = require("./plan_stepper.js");

const STEPS = ["site", "fleet", "orders", "solve", "review", "execute"];

test("each pipeline step maps to its intended numbered sections", () => {
  assert.deepStrictEqual(S.sectionsForStep("site"), ["1", "2"]);
  assert.deepStrictEqual(S.sectionsForStep("fleet"), ["3", "4"]);
  assert.deepStrictEqual(S.sectionsForStep("orders"), ["5"]);
  assert.deepStrictEqual(S.sectionsForStep("solve"), ["4", "5"]);
  assert.deepStrictEqual(S.sectionsForStep("review"), ["5", "6"]);
  assert.deepStrictEqual(S.sectionsForStep("execute"), ["5", "7"]);
});

test("ALL six steps reveal at least one section (review/execute are no longer no-ops)", () => {
  for (const step of STEPS) {
    assert.ok(S.sectionsForStep(step).length >= 1, `${step} must reveal a section`);
  }
});

test("review and execute now have a mapping (the fixed regression)", () => {
  assert.ok(S.sectionsForStep("review").length >= 1);
  assert.ok(S.sectionsForStep("execute").length >= 1);
});

test("every mapped section is a real numbered sidebar section (1..7)", () => {
  const valid = new Set(["1", "2", "3", "4", "5", "6", "7"]);
  for (const step of STEPS) {
    for (const n of S.sectionsForStep(step)) {
      assert.ok(valid.has(n), `${step} -> ${n} is not a real section`);
    }
  }
});

test("sectionVisible is true only for a step's own sections, false otherwise", () => {
  assert.strictEqual(S.sectionVisible("site", "1"), true);
  assert.strictEqual(S.sectionVisible("site", 2), true);          // accepts number too
  assert.strictEqual(S.sectionVisible("site", "3"), false);
  assert.strictEqual(S.sectionVisible("execute", "7"), true);
  assert.strictEqual(S.sectionVisible("review", "6"), true);
  assert.strictEqual(S.sectionVisible("orders", "4"), false);
});

test("an unknown step maps to no sections (caller leaves the sidebar untouched)", () => {
  assert.deepStrictEqual(S.sectionsForStep("bogus"), []);
  assert.deepStrictEqual(S.sectionsForStep(undefined), []);
});

test("sectionsForStep is pure -- the returned array does not alias the internal table", () => {
  const a = S.sectionsForStep("site");
  a.push("9");
  assert.deepStrictEqual(S.sectionsForStep("site"), ["1", "2"]);
});

// GIS S-2: the Contents tree groups must stay coherent with the stepper -- each group's section is one the
// expected step reveals. Basemap/Terrain/Sun ride the Site step (1+2); Safety/Operations(orders) ride Orders (5).
test("contents_tree groups carry sections revealed by the right pipeline step", () => {
  const CT = require("./contents_tree.js");
  const expectStep = { basemap: "site", terrain: "site", sun: "site", safety: "orders", operations: "orders" };
  CT.GROUPS.forEach((g) => {
    const step = expectStep[g.id];
    assert.ok(step, `group ${g.id} has an expected step`);
    assert.ok(S.sectionVisible(step, g.section),
      `group ${g.id} (section ${g.section}) must be revealed by the ${step} step`);
  });
});
