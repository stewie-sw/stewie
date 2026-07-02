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

// UPDATED for the 2026-07-01 frontend-audit finding "live-data plots don't scale": _fit now CENTERS
// the data bounding box with ~10% padding (was min-corner anchored at pad), so the transform for the
// same input legitimately changes. x span 100*1.1=110 -> (300-52)/110; y span 50*1.1=55 -> (160-52)/55
// = 1.9636… (binding). Center (50,25) -> canvas center (150,80); extremes sit inside the pad frame.
test("_fit: pad-inset min-fit transform centers the bbox with 10% padding", () => {
  const t = N._fit({ width: 300, height: 160 }, [[0, 0], [100, 50]]);
  assert.ok(Math.abs(t.s - 108 / 55) < 1e-9);
  assert.ok(Math.abs(t.X(50) - 150) < 1e-9);                // bbox center -> canvas center
  assert.ok(Math.abs(t.Y(25) - 80) < 1e-9);
  assert.ok(Math.abs(t.X(0) - (150 - 50 * (108 / 55))) < 1e-9);
  assert.ok(t.X(0) > 26 && t.X(100) < 300 - 26);            // 10% padding keeps data off the frame
  assert.ok(t.Y(0) < 160 - 26 && t.Y(50) > 26);
});

// 2026-07-01 frontend-audit finding "live-data plots don't scale": a real traverse whose extent is
// tiny (or a single fix) used to render as one dot pinned at the bottom-left pad corner. The site-frame
// default minimum span is now 10 m, and a degenerate point lands at the canvas center.
test("_fit: 10 m minimum span centers degenerate site-frame data", () => {
  const t = N._fit({ width: 300, height: 160 }, [[50, 20]]);
  assert.ok(Math.abs(t.s - 108 / 11) < 1e-9);               // min(248, 108) / (10 m * 1.1)
  assert.ok(Math.abs(t.X(50) - 150) < 1e-9);                // centered, NOT (26, 134)
  assert.ok(Math.abs(t.Y(20) - 80) < 1e-9);
});

test("_fit: an explicit tight minSpan (drawFix's 0.5 m rig) is preserved", () => {
  const t = N._fit({ width: 300, height: 160 }, [[0, 0], [0.1, 0.1]], 26, 0.5);
  assert.ok(Math.abs(t.s - 108 / 0.55) < 1e-9);             // min span 0.5 m * 1.1 padding
  assert.ok(Math.abs(t.X(0.05) - 150) < 1e-9);
});

// 2026-07-01 frontend-audit finding: through the shared seam, a near-degenerate drive preview must
// draw its start marker near the canvas center inside a >=10 m viewport instead of the corner.
test("drawDrive: a short drive renders centered via the 10 m minimum span", () => {
  const calls = [];
  N.drawDrive(cv(calls), { waypoints: [[40, 40], [40.5, 40]], trajectory: [[40, 40], [40.4, 40.1]] });
  const arcs = calls.filter((c) => c[0] === "arc");
  assert.ok(arcs.length >= 2);                              // start + goal dots
  const [sx, sy] = [arcs[0][1], arcs[0][2]];                // start dot at [40, 40]
  assert.ok(Math.abs(sx - 150) < 15 && Math.abs(sy - 80) < 15);   // near center, not (26, 134)
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

test("drawDrive: empty payload clears then renders the explicit empty state", () => {
  const calls = [];
  N.drawDrive(cv(calls), { waypoints: [], trajectory: [] });
  assert.deepStrictEqual(calls[0], ["clearRect", 0, 0, 300, 160]);
  const texts = calls.filter((c) => c[0] === "fillText").map((c) => c[1]);
  assert.deepStrictEqual(texts, ["No drive yet — press ▶ Run drive preview"]);
  // the empty state is text-only: no paths, dots, or rings are drawn
  assert.ok(!calls.some((c) => c[0] === "stroke" || c[0] === "arc"));
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
