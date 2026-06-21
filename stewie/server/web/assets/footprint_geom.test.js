// GIS S-3 (node:test): typed footprint-shape geometry is pure -> unit-testable without a browser.
// Asserts the JS twin matches the backend CP-05 schema (area + oriented ring), that a non-square
// shape really is non-square (a 15x2 road is NOT an axis-aligned square), and that the legacy
// scalar->square default path is preserved byte-for-byte.
// Run: node --test stewie/server/web/assets/footprint_geom.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const F = require("./footprint_geom.js");

const close = (a, b, eps) => Math.abs(a - b) <= (eps || 1e-9);

test("shapeArea: rectangle = w*h", () => {
  assert.ok(close(F.shapeArea({ kind: "rectangle", w: 15, h: 2 }), 30));
});
test("shapeArea: corridor = length*width", () => {
  assert.ok(close(F.shapeArea({ kind: "corridor", length: 40, width: 3 }), 120));
});
test("shapeArea: circle = pi r^2", () => {
  assert.ok(close(F.shapeArea({ kind: "circle", r: 4 }), Math.PI * 16));
});
test("shapeArea: polygon via shoelace (unit triangle = 0.5*b*h)", () => {
  assert.ok(close(F.shapeArea({ kind: "polygon", vertices: [[0, 0], [10, 0], [0, 8]] }), 40));
});
test("shapeArea: degenerate/unknown -> NaN", () => {
  assert.ok(Number.isNaN(F.shapeArea({ kind: "rectangle", w: 0, h: 2 })));
  assert.ok(Number.isNaN(F.shapeArea({ kind: "polygon", vertices: [[0, 0], [1, 1]] })));
  assert.ok(Number.isNaN(F.shapeArea(null)));
});

test("footprintRingXY: a 15x2 rectangle is NOT an axis-aligned square", () => {
  const ring = F.footprintRingXY({ x: 0, y: 0, shape: { kind: "rectangle", w: 15, h: 2 } });
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  const spanX = Math.max(...xs) - Math.min(...xs), spanY = Math.max(...ys) - Math.min(...ys);
  assert.ok(close(spanX, 15), `spanX ${spanX}`);
  assert.ok(close(spanY, 2), `spanY ${spanY}`);
  assert.ok(Math.abs(spanX - spanY) > 1, "a real rectangle has unequal spans (not a square)");
});

test("footprintRingXY: theta_deg=90 rotates the long axis onto Y", () => {
  const ring = F.footprintRingXY({ x: 0, y: 0, shape: { kind: "rectangle", w: 15, h: 2, theta_deg: 90 } });
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  const spanX = Math.max(...xs) - Math.min(...xs), spanY = Math.max(...ys) - Math.min(...ys);
  assert.ok(close(spanX, 2), `spanX ${spanX}`);   // long side now vertical
  assert.ok(close(spanY, 15), `spanY ${spanY}`);
});

test("footprintRingXY: corridor centred + oriented at the order (x,y)", () => {
  const ring = F.footprintRingXY({ x: 5, y: 7, shape: { kind: "corridor", length: 20, width: 4 } });
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  assert.ok(close((Math.min(...xs) + Math.max(...xs)) / 2, 5));   // centred at x=5
  assert.ok(close((Math.min(...ys) + Math.max(...ys)) / 2, 7));   // centred at y=7
  assert.ok(close(Math.max(...xs) - Math.min(...xs), 20));
});

test("footprintRingXY: NO shape -> legacy axis-aligned square of side sqrt(area)", () => {
  const ring = F.footprintRingXY({ x: 0, y: 0, footprint_m2: 36 });   // side 6, half 3
  const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
  assert.ok(close(Math.max(...xs) - Math.min(...xs), 6));
  assert.ok(close(Math.max(...ys) - Math.min(...ys), 6));            // square: equal spans (preserved)
});

test("footprintRingXY: no shape and no positive scalar -> null", () => {
  assert.strictEqual(F.footprintRingXY({ x: 0, y: 0, footprint_m2: 0 }), null);
});

test("hasTypedShape: true only for a usable typed shape", () => {
  assert.strictEqual(F.hasTypedShape({ shape: { kind: "rectangle", w: 15, h: 2 } }), true);
  assert.strictEqual(F.hasTypedShape({ footprint_m2: 36 }), false);
  assert.strictEqual(F.hasTypedShape({ shape: { kind: "rectangle", w: 0, h: 2 } }), false);
});

test("shapeFromForm: builds each kind; rejects invalid/default", () => {
  assert.deepStrictEqual(F.shapeFromForm("rectangle", { w: 15, h: 2, theta_deg: 30 }),
    { kind: "rectangle", w: 15, h: 2, theta_deg: 30 });
  assert.deepStrictEqual(F.shapeFromForm("corridor", { length: 40, width: 3 }),
    { kind: "corridor", length: 40, width: 3, theta_deg: 0 });
  assert.deepStrictEqual(F.shapeFromForm("circle", { r: 4 }), { kind: "circle", r: 4 });
  assert.strictEqual(F.shapeFromForm("rectangle", { w: -1, h: 2 }), null);   // invalid
  assert.strictEqual(F.shapeFromForm("square", {}), null);                   // default -> legacy
  assert.strictEqual(F.shapeFromForm("", {}), null);
});

test("shapeFromForm: polygon needs 3+ vertices and non-zero area", () => {
  assert.deepStrictEqual(F.shapeFromForm("polygon", { vertices: [[0, 0], [10, 0], [0, 8]] }),
    { kind: "polygon", vertices: [[0, 0], [10, 0], [0, 8]] });
  assert.strictEqual(F.shapeFromForm("polygon", { vertices: [[0, 0], [1, 1]] }), null);
});

test("parsePolyVerts: 'x,y; x,y; x,y' -> [[x,y],...]; <3 -> []", () => {
  assert.deepStrictEqual(F.parsePolyVerts("0,0; 10,0; 5,8"), [[0, 0], [10, 0], [5, 8]]);
  assert.deepStrictEqual(F.parsePolyVerts(" 1,2 ; 3,4 "), []);   // only 2 vertices
  assert.deepStrictEqual(F.parsePolyVerts(""), []);
});

test("drawFootprint: walks the REAL ring on a stub 2D context (non-square)", () => {
  const calls = [];
  const ctx = {
    beginPath: () => calls.push(["begin"]),
    moveTo: (x, y) => calls.push(["move", x, y]),
    lineTo: (x, y) => calls.push(["line", x, y]),
    closePath: () => calls.push(["close"]),
    fill: () => calls.push(["fill"]),
    stroke: () => calls.push(["stroke"]),
  };
  const X = (wx) => wx, Y = (wy) => wy;   // identity transform for the test
  const ok = F.drawFootprint(ctx, { x: 0, y: 0, shape: { kind: "rectangle", w: 15, h: 2 } }, X, Y);
  assert.strictEqual(ok, true);
  const pts = calls.filter((c) => c[0] === "move" || c[0] === "line").map((c) => [c[1], c[2]]);
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  assert.ok(close(Math.max(...xs) - Math.min(...xs), 15));   // drew a 15-wide, not a square
  assert.ok(close(Math.max(...ys) - Math.min(...ys), 2));
  assert.deepStrictEqual(calls[calls.length - 2], ["fill"]);
  assert.deepStrictEqual(calls[calls.length - 1], ["stroke"]);
});

test("drawFootprint: no geometry -> false, no draw calls", () => {
  const calls = [];
  const ctx = { beginPath: () => calls.push("b") };
  assert.strictEqual(F.drawFootprint(ctx, { x: 0, y: 0, footprint_m2: 0 }, (a) => a, (a) => a), false);
  assert.strictEqual(calls.length, 0);
});

test("footprintBounds: typed shape AABB uses the real ring", () => {
  const b = F.footprintBounds({ x: 0, y: 0, shape: { kind: "rectangle", w: 15, h: 2 } });
  assert.ok(close(b.x1 - b.x0, 15));
  assert.ok(close(b.y1 - b.y0, 2));
});
