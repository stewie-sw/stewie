// #40 graticule: pure meridian/parallel/km-grid line generation. Given an injected reproject(lon,lat)->[x,y]
// (proj4 IAU_2015:30100 -> 30135 in the app; identity here), it yields the polyline coords + labels the OL
// vector layer draws. Pure + node-testable -- no OL/DOM.
const assert = require("node:assert");
const { test } = require("node:test");
const G = require("./graticule.js");
const id = (lon, lat) => [lon, lat];   // trivial reproject for testing the geometry

test("meridians: 12 constant-lon lines every 30deg, spanning latMin..latMax", () => {
  const m = G.meridians(id, { lonStep: 30, latMin: -89, latMax: -55, latSample: 0.5 });
  assert.strictEqual(m.length, 12);                       // 0,30,...,330
  assert.strictEqual(m[0].lon, 0);
  assert.strictEqual(m[0].label, "0°");
  assert.deepStrictEqual(m[0].coords[0], [0, -89]);
  assert.deepStrictEqual(m[0].coords[m[0].coords.length - 1], [0, -55]);
  assert.strictEqual(m[1].lon, 30);
});

test("parallels: constant-lat circles closing 0..360", () => {
  const p = G.parallels(id, { latStep: 5, latMin: -85, latMax: -55, lonSample: 2 });
  assert.strictEqual(p.length, 7);                        // -85,-80,...,-55
  assert.strictEqual(p[0].lat, -85);
  assert.deepStrictEqual(p[0].coords[0], [0, -85]);
  assert.deepStrictEqual(p[0].coords[p[0].coords.length - 1], [360, -85]);
});

test("kmGrid: NxN straight metric lines in the map frame with km labels", () => {
  const k = G.kmGrid({ stepKm: 100, halfKm: 200 });       // x/y each -200..200k step 100k = 5 -> 10 total
  assert.strictEqual(k.length, 10);
  assert.ok(k.some((l) => l.label === "0 km" && l.axis === "x"));
  const west = k.find((l) => l.axis === "x" && l.label === "-200 km");
  assert.deepStrictEqual(west.coords, [[-200000, -200000], [-200000, 200000]]);
});

test("selenographic: meridians + parallels combined", () => {
  const s = G.selenographic(id, { lonStep: 30, latStep: 5, latMin: -85, latMax: -55, latSample: 1, lonSample: 5 });
  assert.strictEqual(s.filter((l) => l.kind === "meridian").length, 12);
  assert.strictEqual(s.filter((l) => l.kind === "parallel").length, 7);
});
