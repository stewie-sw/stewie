// FS-24 (node:test): keep-out shape classification + bounding-box + label are pure -> unit-testable
// without a browser. These are the #178 keep-out geometry helpers; the canvas drawing (fillKeepout)
// and DOM listing (renderKeepouts) stay in cockpit.js and call these.
// Run: node --test stewie/server/web/assets/keepout_geom.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const K = require("./keepout_geom.js");

const POLY = { points: [[0, 0], [10, 0], [5, 8]] };
const RECT = { x0: 2, y0: 3, x1: 12, y1: 9 };
const RECT_REVERSED = { x0: 12, y0: 9, x1: 2, y1: 3 };
const DISC = { x: 5, y: 6, r: 3 };

test("koIsPoly: 3+ points is a polygon", () => {
  assert.strictEqual(K.koIsPoly(POLY), true);
});

test("koIsPoly: 2 points is NOT a polygon", () => {
  assert.strictEqual(K.koIsPoly({ points: [[0, 0], [1, 1]] }), false);
});

test("koIsPoly: a rect/disc is not a polygon", () => {
  assert.strictEqual(K.koIsPoly(RECT), false);
  assert.strictEqual(K.koIsPoly(DISC), false);
});

test("koIsRect: no radius + has a corner is a rect", () => {
  assert.strictEqual(K.koIsRect(RECT), true);
});

test("koIsRect: a disc (has r) is NOT a rect", () => {
  assert.strictEqual(K.koIsRect(DISC), false);
});

test("koBounds(poly): min/max over vertices", () => {
  assert.deepStrictEqual(K.koBounds(POLY), { x0: 0, y0: 0, x1: 10, y1: 8 });
});

test("koBounds(rect): normalizes corner order", () => {
  assert.deepStrictEqual(K.koBounds(RECT), { x0: 2, y0: 3, x1: 12, y1: 9 });
  assert.deepStrictEqual(K.koBounds(RECT_REVERSED), { x0: 2, y0: 3, x1: 12, y1: 9 });
});

test("koBounds(disc): centre +/- radius box", () => {
  assert.deepStrictEqual(K.koBounds(DISC), { x0: 2, y0: 3, x1: 8, y1: 9 });
});

test("koLabel(poly): vertex count", () => {
  assert.strictEqual(K.koLabel(POLY), "polygon (3 pts)");
});

test("koLabel(rect): rounded corners with the en-dash separator", () => {
  assert.strictEqual(K.koLabel({ x0: 2.4, y0: 3.6, x1: 11.5, y1: 8.9 }),
    "box [2,4]–[12,9] m");
});

test("koLabel(disc): centre + radius", () => {
  assert.strictEqual(K.koLabel(DISC), "circle @ 5,6 · r 3 m");
});
