// [REQ:GW-09] dual-mode planning graticule (extends GW-05): selenographic lon/lat densely sampled +
// reprojected so it curves in polar-stereographic, plus a straight metric km-grid with labels, overlaid on
// the lunar map given an injected reproject(lon,lat)->[x,y]. These node tests prove gridline + label
// generation (proj4 IAU_2015:30100 -> 30135 in the app; identity here) + the off-map reproject guards; the
// static wiring gate — that Graticule.jsx injects the reproject + overlays the map — is
// stewie/server/test_gw09_graticule.py, the python [REQ:GW-09] citation req_trace.py counts.
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

// #60 hardening: bad step / bad reproject must degrade safely, never hang or crash.
test("#60 _range guard: bad step/bounds degrade to a bounded range, never hang", () => {
  assert.deepStrictEqual(G._range(0, 10, 2), [0, 2, 4, 6, 8, 10]);   // happy path unchanged
  assert.ok(G._range(0, 10, 0).length <= 1);          // zero step -> degenerate single point, no infinite loop
  assert.ok(G._range(0, 10, -1).length <= 1);         // negative step (truthy, slips past ||default) -> degenerate
  assert.ok(G._range(0, 10, NaN).length <= 1);        // NaN step -> degenerate
  assert.deepStrictEqual(G._range(NaN, 10, 1), []);   // non-finite bound -> empty
  assert.ok(G._range(0, 1e12, 1e-6).length <= 100000);  // pathological span/tiny-step -> hard-capped
});

test("#60 reproject guard: a NaN-returning reproject skips the gridlines (no malformed polyline)", () => {
  const nanRe = () => [NaN, NaN];
  assert.strictEqual(G.meridians(nanRe, { lonStep: 30, latMin: -89, latMax: -55 }).length, 0);
  assert.strictEqual(G.parallels(nanRe, { latStep: 5, latMin: -85, latMax: -55 }).length, 0);
});

test("#60 reproject guard: a THROWING reproject is caught, not a crash", () => {
  const throwRe = () => { throw new Error("proj4 boom"); };
  assert.doesNotThrow(() => G.meridians(throwRe, {}));
  assert.strictEqual(G.meridians(throwRe, {}).length, 0);
});

test("#60 reproject guard: a partial-finite reproject keeps only the finite points", () => {
  const partial = (lon, lat) => (lat >= -70 ? [lon, lat] : [NaN, NaN]);   // finite only for lat >= -70
  const m = G.meridians(partial, { lonStep: 30, latMin: -89, latMax: -55, latSample: 1 });
  assert.strictEqual(m.length, 12);                  // still 12 meridians (each keeps >=2 finite pts: -70..-55)
  assert.ok(m[0].coords.every((p) => isFinite(p[0]) && isFinite(p[1])));   // no NaN points survive
  assert.ok(m[0].coords[0][1] >= -70);               // the -89..-71 points were dropped
});
