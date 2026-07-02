// frontend-audit D (node:test): the pure activity-Gantt downsampler -- lane pixel runs + battery
// min/max envelope. Run: node --test stewie/server/web/assets/gantt_downsample.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./gantt_downsample.js");

test("shouldDownsample: raw for short runs, downsampled at mission scale", () => {
  assert.strictEqual(G.shouldDownsample(2, 462), false);        // the 2-frame smoke plan stays raw
  assert.strictEqual(G.shouldDownsample(150, 462), false);      // ~3 px per bar: still raw
  assert.strictEqual(G.shouldDownsample(155, 462), true);       // past the 1/3 density: downsample
  assert.strictEqual(G.shouldDownsample(5000, 462), true);      // the 2449 h / 92-recharge plan
});

test("laneRuns: well-separated bars stay separate runs", () => {
  const runs = G.laneRuns([{ t0: 0, t1: 100 }, { t0: 500, t1: 600 }], 1000, 100);
  assert.strictEqual(runs.length, 2);
  assert.deepStrictEqual(runs[0], [0, 10]);
  assert.deepStrictEqual(runs[1], [50, 60]);
});

test("laneRuns: sub-2px gaps merge into one run (the aliasing case)", () => {
  // 60 dig pulses, each 1 s, 1 s apart, over 120 s on a 100 px strip -> sub-px bars + sub-px gaps
  const bars = [];
  for (let i = 0; i < 60; i++) bars.push({ t0: i * 2, t1: i * 2 + 1 });
  const runs = G.laneRuns(bars, 120, 100);
  assert.strictEqual(runs.length, 1);                            // one honest block, not shimmer
  assert.strictEqual(runs[0][0], 0);
  assert.ok(runs[0][1] >= 99);
});

test("laneRuns: every bar is at least one pixel and clamps to the strip", () => {
  const runs = G.laneRuns([{ t0: 999.99, t1: 1000 }], 1000, 100);
  assert.strictEqual(runs.length, 1);
  assert.ok(runs[0][1] - runs[0][0] >= 1);
  assert.ok(runs[0][1] <= 100);
  assert.deepStrictEqual(G.laneRuns([], 1000, 100), []);         // no bars -> no runs
});

test("battEnvelope: linear discharge reproduces the ramp per column", () => {
  const env = G.battEnvelope([{ t0: 0, t1: 100, b0: 1.0, b1: 0.0 }], 100, 10);
  assert.strictEqual(env.length, 10);
  assert.ok(Math.abs(env[0].max - 1.0) < 1e-9);                  // column 0 starts at full
  assert.ok(Math.abs(env[0].min - 0.9) < 1e-9);                  // ...and ends the column at 0.9
  assert.ok(Math.abs(env[9].min - 0.0) < 1e-9);                  // last column reaches empty
  assert.ok(env[5].max <= env[4].max + 1e-9);                    // monotone down the ramp
});

test("battEnvelope: a recharge spike inside one column widens that column's min/max band", () => {
  // discharge to 0.2 then snap-charge to 1.0 inside the same pixel column
  const env = G.battEnvelope([
    { t0: 0, t1: 50, b0: 1.0, b1: 0.2 },
    { t0: 50, t1: 50.5, b0: 0.2, b1: 1.0 },
    { t0: 50.5, t1: 100, b0: 1.0, b1: 0.6 },
  ], 100, 10);
  const col = env[5];                                            // the column holding t=50..50.5
  assert.ok(col.min <= 0.2 + 1e-9);
  assert.ok(col.max >= 1.0 - 1e-9);                              // envelope keeps the spike visible
});

test("battEnvelope: uncovered columns forward-fill (continuous curve)", () => {
  const env = G.battEnvelope([{ t0: 0, t1: 10, b0: 0.8, b1: 0.7 }], 100, 10);
  assert.ok(Math.abs(env[9].min - 0.7) < 1e-9);                  // tail carries the last known value
  assert.ok(Math.abs(env[9].max - 0.7) < 1e-9);
});
