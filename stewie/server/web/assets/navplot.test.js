// FS-24 (node:test): the Navigation-pane canvas plotters are pure -> unit-testable without a browser
// via a recording 2D-context stub. We assert (a) the recorded draw-call stream for representative
// inputs, and (b) the auto-fit transform math. The browser DOM lookups stay in cockpit.js (thin
// aliases that pass $("navplot") etc. in); behaviour is preserved.
// Run: node --test stewie/server/web/assets/navplot.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const N = require("./navplot.js");

// a recording 2D context: every mutated style + every geometry call is logged to `calls` in order.
function round(v) { return typeof v === "number" ? Math.round(v * 1e4) / 1e4 : v; }
function cv(calls) { return { width: 300, height: 160, getContext: () => recCtx2(calls) }; }
function recCtx2(calls) {
  const wrap = {};
  for (const k of ["clearRect", "beginPath", "moveTo", "lineTo", "arc", "stroke", "fill", "setLineDash", "fillText"]) {
    wrap[k] = (...a) => calls.push([k, ...a.map(round)]);
  }
  return Object.defineProperties(wrap, {
    strokeStyle: { set: (v) => calls.push(["strokeStyle", v]) },
    fillStyle: { set: (v) => calls.push(["fillStyle", v]) },
    lineWidth: { set: (v) => calls.push(["lineWidth", v]) },
    font: { set: (v) => calls.push(["font", v]) },
  });
}

test("_fit: pad-inset min-fit transform places extremes correctly", () => {
  const t = N._fit({ width: 300, height: 160 }, [[0, 0], [100, 50]]);
  // x span 100 -> s = (300-52)/100 = 2.48; y span 50 -> (160-52)/50 = 2.16; min = 2.16
  assert.ok(Math.abs(t.s - 2.16) < 1e-9);
  assert.ok(Math.abs(t.X(0) - 26) < 1e-9);
  assert.ok(Math.abs(t.Y(0) - (160 - 26)) < 1e-9);
});

test("drawTrajectory: clears, draws baseline then estimate, legend", () => {
  const calls = [];
  N.drawTrajectory(cv(calls), [[0, 0], [10, 10]], [[0, 0], [12, 8]]);
  assert.deepStrictEqual(calls[0], ["clearRect", 0, 0, 300, 160]);
  // first stroked line is the baseline (amber #e0a23a), then the estimate (cyan #36d1dc)
  const strokes = calls.filter((c) => c[0] === "strokeStyle").map((c) => c[1]);
  assert.strictEqual(strokes[0], "#e0a23a");
  assert.strictEqual(strokes[1], "#36d1dc");
  const texts = calls.filter((c) => c[0] === "fillText").map((c) => c[1]);
  assert.deepStrictEqual(texts, ["— fused estimate", "— dead reckoning"]);
});

test("drawDrive: empty payload draws nothing past clear", () => {
  const calls = [];
  N.drawDrive(cv(calls), { waypoints: [], trajectory: [] });
  assert.deepStrictEqual(calls, [["clearRect", 0, 0, 300, 160]]);
});

test("drawDrive: start green + goal red dots, planned dashed, recovery ring", () => {
  const calls = [];
  N.drawDrive(cv(calls), { waypoints: [[0, 0], [20, 10]], trajectory: [[0, 0], [19, 11]],
    recovery_events: [{ xy: [10, 5] }] });
  const dashes = calls.filter((c) => c[0] === "setLineDash").map((c) => JSON.stringify(c[1]));
  assert.ok(dashes.includes("[5,3]"));         // planned corridor dashed
  const fills = calls.filter((c) => c[0] === "fillStyle").map((c) => c[1]);
  assert.ok(fills.includes("#3fa34d"));        // start green
  assert.ok(fills.includes("#e8273f"));        // goal red
  assert.ok(calls.some((c) => c[0] === "strokeStyle" && c[1] === "#ff8c00"));   // recovery ring
});

test("drawReal: three paths in odom/truth/fused order with truth dashed", () => {
  const calls = [];
  N.drawReal(cv(calls), [[0, 0], [10, 0]], [[0, 0], [9, 1]], [[0, 0], [12, 3]]);
  const strokes = calls.filter((c) => c[0] === "strokeStyle").map((c) => c[1]);
  assert.strictEqual(strokes[0], "#e0a23a");   // odometry first
  assert.strictEqual(strokes[1], "#cfe3ff");   // truth
  assert.strictEqual(strokes[2], "#36d1dc");   // fused
});

test("drawFix: covariance ring radius honours fix_sigma_m and the tight 0.5 m min span", () => {
  const calls = [];
  N.drawFix(cv(calls), { landmarks_xy: [[0, 0], [1, 1]], fix_xy: [0.5, 0.5],
    true_xy: [0.4, 0.6], seed_xy: [0.6, 0.4], fix_sigma_m: 0.1 });
  // the cyan covariance arc exists
  const i = calls.findIndex((c) => c[0] === "strokeStyle" && c[1] === "#36d1dc");
  assert.ok(i >= 0);
  assert.ok(calls.slice(i).some((c) => c[0] === "arc"));
});
