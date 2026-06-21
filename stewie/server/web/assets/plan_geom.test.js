// FS-24 (node:test): the Plan-pane authoring geometry/glyph helpers are pure -> unit-testable without
// a browser. planExtent/planXform are the world<->canvas math; drawGlyph is asserted via a recording
// 2D-context stub; parsePrec is the precedence-text parser. The browser DOM reads (ORDERS/KEEPOUTS/
// _placeXY/koBounds/#qprec) stay in cockpit.js as thin aliases that pass these values in.
// Run: node --test stewie/server/web/assets/plan_geom.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./plan_geom.js");

// a recording 2D context: every mutated style + every geometry call is logged to `calls` in order.
function round(v) { return typeof v === "number" ? Math.round(v * 1e4) / 1e4 : v; }
function recCtx2(calls) {
  const wrap = {};
  for (const k of ["save", "restore", "beginPath", "moveTo", "lineTo", "arc", "stroke",
                   "fill", "fillRect", "strokeRect", "closePath", "setLineDash"]) {
    wrap[k] = (...a) => calls.push([k, ...a.map(round)]);
  }
  return Object.defineProperties(wrap, {
    strokeStyle: { set: (v) => calls.push(["strokeStyle", v]) },
    fillStyle: { set: (v) => calls.push(["fillStyle", v]) },
    lineWidth: { set: (v) => calls.push(["lineWidth", v]) },
  });
}

// the keep-out AABB helper the cockpit passes in (matches keepout_geom.koBounds for a disc).
function koBoundsDisc(k) { return { x0: k.x - k.r, x1: k.x + k.r, y0: k.y - k.r, y1: k.y + k.r }; }

test("planExtent: empty -> charger-only padded around (0,0) with 10 m degenerate fallback", () => {
  const e = G.planExtent([], [], null, koBoundsDisc);
  // span < 1 -> x0-=10,x1+=10 around 0 => [-10,10]; pad = max(5, 20*0.15)=5 -> [-15,15]
  assert.deepStrictEqual(e, { x0: -15, x1: 15, y0: -15, y1: 15 });
});

test("planExtent: orders widen the box by half the footprint side + 15% pad", () => {
  const e = G.planExtent([{ x: 100, y: 0, footprint_m2: 400 }], [], null, koBoundsDisc);
  // half = sqrt(400)/2 = 10 -> xs include 0, 90, 110 ; span 110 ; pad = max(5, 110*0.15)=16.5
  assert.ok(Math.abs(e.x0 - (0 - 16.5)) < 1e-9);
  assert.ok(Math.abs(e.x1 - (110 + 16.5)) < 1e-9);
});

test("planExtent: keep-outs and the click-to-place marker enter the bounds", () => {
  const e = G.planExtent([], [{ x: 50, y: 50, r: 5 }], { x: -30, y: 0 }, koBoundsDisc);
  // xs include 0, 45, 55, -30 -> minx -30, maxx 55
  assert.ok(e.x0 < -30);   // padded beyond the marker
  assert.ok(e.x1 > 55);    // padded beyond the keep-out far edge
});

test("planXform: centred uniform-scale, Y flipped (site +y is up)", () => {
  const ext = { x0: 0, x1: 100, y0: 0, y1: 50 };
  const t = G.planXform({ width: 300, height: 160 }, ext);
  // s = min(300/100, 160/50) = min(3, 3.2) = 3
  assert.ok(Math.abs(t.s - 3) < 1e-9);
  assert.ok(Math.abs(t.X(0) - t.ox) < 1e-9);
  // Y(y0) sits at the bottom inset: H - oy
  assert.ok(Math.abs(t.Y(0) - (160 - t.oy)) < 1e-9);
  // Y is flipped: larger world y -> smaller canvas y
  assert.ok(t.Y(50) < t.Y(0));
});

// the keep-out shape predicates the cockpit passes in (match keepout_geom.js for the test shapes).
function koIsPoly(k) { return Array.isArray(k.points); }
function koIsRect(k) { return k.x0 !== undefined && k.x1 !== undefined; }
function koBoundsRect(k) { return { x0: k.x0, x1: k.x1, y0: k.y0, y1: k.y1 }; }

test("fillKeepout: disc -> single arc fill/stroke at the transformed centre", () => {
  const calls = [];
  const X = (x) => x, Y = (y) => y;
  G.fillKeepout(recCtx2(calls), { x: 10, y: 20, r: 5 }, X, Y, 2, koIsPoly, koIsRect, koBoundsDisc);
  const arc = calls.find((c) => c[0] === "arc");
  assert.deepStrictEqual([arc[1], arc[2]], [10, 20]);     // centre X(10),Y(20)
  assert.ok(Math.abs(arc[3] - 10) < 1e-9);                // radius max(2, 5*2)=10
  assert.ok(calls.some((c) => c[0] === "fill") && calls.some((c) => c[0] === "stroke"));
});

test("fillKeepout: rect -> fillRect+strokeRect using koBounds (canvas Y flipped)", () => {
  const calls = [];
  const X = (x) => x, Y = (y) => 100 - y;                 // flip
  G.fillKeepout(recCtx2(calls), { x0: 0, x1: 10, y0: 0, y1: 8 }, X, Y, 1, koIsPoly, koIsRect, koBoundsRect);
  const fr = calls.find((c) => c[0] === "fillRect");
  // x0=X(0)=0, y0=Y(y1=8)=92, w=10, h=Y(0)-Y(8)=8
  assert.deepStrictEqual(fr, ["fillRect", 0, 92, 10, 8]);
  assert.ok(calls.some((c) => c[0] === "strokeRect"));
});

test("fillKeepout: poly -> moveTo first vertex then lineTo rest, closePath", () => {
  const calls = [];
  const X = (x) => x, Y = (y) => y;
  G.fillKeepout(recCtx2(calls), { points: [[0, 0], [10, 0], [5, 8]] }, X, Y, 1, koIsPoly, koIsRect, koBoundsRect);
  assert.deepStrictEqual(calls.filter((c) => c[0] === "moveTo"), [["moveTo", 0, 0]]);
  assert.deepStrictEqual(calls.filter((c) => c[0] === "lineTo"), [["lineTo", 10, 0], ["lineTo", 5, 8]]);
  assert.ok(calls.some((c) => c[0] === "closePath"));
});

test("drawGlyph: cut -> blue chevron, save/restore wraps the draw", () => {
  const calls = [];
  G.drawGlyph(recCtx2(calls), "cut", 10, 10, 5);
  assert.deepStrictEqual(calls[0], ["save"]);
  assert.deepStrictEqual(calls[calls.length - 1], ["restore"]);
  const strokes = calls.filter((c) => c[0] === "strokeStyle").map((c) => c[1]);
  assert.strictEqual(strokes[0], "#4f9cff");
});

test("drawGlyph: charger -> green square fill + dark tick", () => {
  const calls = [];
  G.drawGlyph(recCtx2(calls), "charger", 0, 0, 6);
  const fills = calls.filter((c) => c[0] === "fillStyle").map((c) => c[1]);
  assert.strictEqual(fills[0], "#3fa34d");
  assert.ok(calls.some((c) => c[0] === "fillRect"));
});

test("drawGlyph: default radius when r falsy", () => {
  const calls = [];
  G.drawGlyph(recCtx2(calls), "goto", 0, 0);   // r omitted -> r=5
  // goto draws an arc of radius r*0.8 = 4 at (0,0)
  const arc = calls.find((c) => c[0] === "arc");
  assert.ok(Math.abs(arc[3] - 4) < 1e-9);
});

test("drawGlyph: unknown kind -> save/restore only, no geometry", () => {
  const calls = [];
  G.drawGlyph(recCtx2(calls), "nope", 0, 0, 5);
  assert.deepStrictEqual(calls, [["save"], ["restore"]]);
});

test("parsePrec: parses comma-separated before>after pairs, trims, drops malformed", () => {
  assert.deepStrictEqual(
    G.parsePrec("Grade road > Build berm, Dig pit>Fill"),
    [["Grade road", "Build berm"], ["Dig pit", "Fill"]]);
});

test("parsePrec: empty / null -> []", () => {
  assert.deepStrictEqual(G.parsePrec(""), []);
  assert.deepStrictEqual(G.parsePrec(null), []);
  assert.deepStrictEqual(G.parsePrec("no arrow here"), []);
});
