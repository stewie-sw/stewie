// viz.stewie.space metric km grid: pure straight-line generation in the order-local metre frame.
// Run: node --test stewie/server/web/assets/viz_grid.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./viz_grid.js");

test("niceStep snaps to a 1/2/5 x 10^k ladder", () => {
  assert.strictEqual(G.niceStep(1000, 8), 100);      // 1000/8=125 -> 100
  assert.strictEqual(G.niceStep(10000, 8), 1000);    // 10 km tile -> 1 km lines
  assert.strictEqual(G.niceStep(2000, 8), 200);      // 2000/8=250 -> 200
});

test("label: metres under 1 km, km past it", () => {
  assert.strictEqual(G.label(500), "500 m");
  assert.strictEqual(G.label(2000), "2 km");
  assert.strictEqual(G.label(1500), "1.5 km");
});

test("metricGrid: both axes, both borders, clamped to the window", () => {
  const g = G.metricGrid(1000, 250);
  assert.strictEqual(g.step, 250);
  const xs = g.lines.filter((l) => l.axis === "x");
  const ys = g.lines.filter((l) => l.axis === "y");
  // 0,250,500,750,1000 -> 5 lines each axis
  assert.strictEqual(xs.length, 5);
  assert.strictEqual(ys.length, 5);
  // a constant-x line runs from y=0 to y=win at that x
  assert.deepStrictEqual(xs[1].coords, [[250, 0], [250, 1000]]);
  assert.deepStrictEqual(ys[2].coords, [[0, 500], [1000, 500]]);
  // last line sits exactly on the far border (clamped, not overshooting)
  assert.strictEqual(xs[xs.length - 1].value, 1000);
});

test("metricGrid: auto step for the full 10 km Haworth tile", () => {
  const g = G.metricGrid(10000);
  assert.strictEqual(g.step, 1000);                  // ~8 lines target -> 1 km
  assert.ok(g.lines.every((l) => l.coords.length === 2));
  assert.ok(g.lines.some((l) => l.label === "5 km"));
});

test("metricGrid: degenerate window -> empty", () => {
  assert.deepStrictEqual(G.metricGrid(0), []);
  assert.deepStrictEqual(G.metricGrid(-5), []);
});
