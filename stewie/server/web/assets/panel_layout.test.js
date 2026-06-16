// FS-21 (node:test): the sidebar layout order logic is PURE -> unit-testable. The DOM drag glue
// lives in cockpit.js; this covers the reconcile + move math that the glue calls.
// Run: node --test stewie/server/web/assets/panel_layout.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const L = require("./panel_layout.js");

test("mergeOrder keeps the saved order for panes that still exist", () => {
  const saved = ["fleet", "site", "plan"];
  const current = ["site", "fleet", "plan"];
  assert.deepStrictEqual(L.mergeOrder(saved, current), ["fleet", "site", "plan"]);
});

test("mergeOrder appends panes the saved layout never knew about (new panes never hidden)", () => {
  const saved = ["site", "fleet"];
  const current = ["site", "fleet", "telemetry"];      // telemetry is new
  assert.deepStrictEqual(L.mergeOrder(saved, current), ["site", "fleet", "telemetry"]);
});

test("mergeOrder drops saved keys for panes that no longer exist", () => {
  const saved = ["site", "gone", "fleet"];
  const current = ["site", "fleet"];
  assert.deepStrictEqual(L.mergeOrder(saved, current), ["site", "fleet"]);
});

test("mergeOrder with no saved layout is the current order unchanged", () => {
  const current = ["site", "fleet", "plan"];
  assert.deepStrictEqual(L.mergeOrder([], current), current);
  assert.deepStrictEqual(L.mergeOrder(null, current), current);
});

test("reorder moves a pane to sit immediately before the target", () => {
  const order = ["site", "fleet", "plan", "telemetry"];
  assert.deepStrictEqual(L.reorder(order, "telemetry", "fleet"),
    ["site", "telemetry", "fleet", "plan"]);
});

test("reorder to a null target sends the pane to the end", () => {
  const order = ["site", "fleet", "plan"];
  assert.deepStrictEqual(L.reorder(order, "site", null), ["fleet", "plan", "site"]);
});

test("reorder is pure -- it does not mutate its input", () => {
  const order = ["site", "fleet", "plan"];
  const copy = order.slice();
  L.reorder(order, "plan", "site");
  assert.deepStrictEqual(order, copy);
});

test("KEY is the stable localStorage key the glue persists under", () => {
  assert.strictEqual(L.KEY, "stewie_panel_order");
});
