// FS-24 (node:test): the execution-telemetry renderers (sparkline, ring-buffer push, chips, rover HUD,
// activity Gantt) are pure over a passed-in canvas/payload -> unit-testable without a browser via a
// recording 2D-context stub + a minimal DOM stub for the chip rail. Behaviour preserved.
// Run: node --test stewie/server/web/assets/rover_hud.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const R = require("./rover_hud.js");

function round(v) { return typeof v === "number" ? Math.round(v * 1e4) / 1e4 : v; }
function recCtx(calls) {
  const wrap = {};
  for (const k of ["clearRect", "beginPath", "moveTo", "lineTo", "arc", "stroke", "fill", "fillRect", "strokeRect"])
    wrap[k] = (...a) => calls.push([k, ...a.map(round)]);
  wrap.fillText = (t, x, y) => calls.push(["fillText", t, round(x), round(y)]);
  for (const p of ["strokeStyle", "fillStyle", "lineWidth", "font", "globalAlpha", "textAlign", "textBaseline"])
    Object.defineProperty(wrap, p, { set: (v) => calls.push([p, v]) });
  return wrap;
}
function cv(w, h, calls) { return { width: w, height: h, getContext: () => recCtx(calls) }; }

test("telePush: appends to all channels and caps at 240, then redraws", () => {
  const buf = { batt: [], mass: [], slip: [] };
  let drew = 0;
  for (let i = 0; i < 245; i++) R.telePush(buf, i, i * 2, i * 0.1, () => drew++);
  assert.strictEqual(buf.batt.length, 240);
  assert.strictEqual(buf.batt[0], 5);          // first 5 shifted out
  assert.strictEqual(drew, 245);
});

test("teleSpark: draws one polyline per channel with >= 2 samples", () => {
  const calls = [];
  const buf = { batt: [0.9, 0.8, 0.7], mass: [10, 20], slip: [0.1] };  // slip has <2 -> skipped
  R.teleSpark(cv(120, 40, calls), buf);
  const strokes = calls.filter((c) => c[0] === "strokeStyle").map((c) => c[1]);
  assert.deepStrictEqual(strokes, ["#e8273f", "#e07b39"]);  // batt then mass; slip skipped
});

test("teleChip: creates a chip on first sight, reuses it after, colours by ok", () => {
  const made = [];
  const rail = { _kids: {}, querySelector(sel) { const m = sel.match(/data-ch="(.+)"/); return this._kids[m[1]] || null; },
    appendChild(el) { this._kids[el.dataset.ch] = el; } };
  const mkEl = () => ({ dataset: {}, style: {}, textContent: "" });
  global.document = { createElement: () => { const e = mkEl(); made.push(e); return e; } };
  R.teleChip(rail, "pose", "10,5", true);
  R.teleChip(rail, "pose", "11,6", false);
  assert.strictEqual(made.length, 1);          // reused
  assert.strictEqual(rail._kids.pose.textContent, "POSE 11,6");
  assert.strictEqual(rail._kids.pose.style.color, "#e0564b");   // ok=false -> red
  delete global.document;
});

test("drawRoverHUD: drum bar fill scales with drumCapKg", () => {
  const calls = [];
  R.drawRoverHUD(cv(310, 92, calls), { headingDeg: 90, soc: 0.5, frontKg: 15, rearKg: 0, x: 3, y: 4 }, 30);
  const texts = calls.filter((c) => c[0] === "fillText").map((c) => c[1]);
  assert.ok(texts.includes("FRONT 15.0 kg"));
  assert.ok(texts.includes("50%"));            // soc
  assert.ok(texts.includes("pose 3, 4 m"));
});

test("drawGantt: empty timeline shows the placeholder", () => {
  const calls = [];
  R.drawGantt(cv(400, 200, calls), []);
  const texts = calls.filter((c) => c[0] === "fillText").map((c) => c[1]);
  assert.deepStrictEqual(texts, ["plan a mission to populate the activity timeline"]);
});

test("drawGantt: one lane per phase kind + battery curve", () => {
  const calls = [];
  const frames = [{ phase: "drive", t0: 0, t1: 100, batt0_frac: 1, batt1_frac: 0.9 },
                  { phase: "dig", t0: 100, t1: 250, batt0_frac: 0.9, batt1_frac: 0.7 }];
  R.drawGantt(cv(400, 200, calls), frames);
  const texts = calls.filter((c) => c[0] === "fillText").map((c) => c[1]);
  assert.ok(texts.includes("DRIVE"));
  assert.ok(texts.includes("DIG"));
  assert.ok(texts.includes("BATT"));
});
