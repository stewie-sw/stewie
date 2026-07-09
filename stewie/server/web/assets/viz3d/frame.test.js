// viz3d/frame.js (node:test): the frame manager is pure render-space geometry (ENU scaling, body-fixed
// sphere placement, recentre+orient, bilinear metres->lonlat), unit-testable without a browser or server.
// Run: node --test stewie/server/web/assets/viz3d/frame.test.js
//
// Fixtures here are MATH, not data: a linear/bilinear lon/lat grid is a known-answer input for the
// interpolation, and the globe round-trip grid is derived ANALYTICALLY from the local ENU->lon/lat
// linearization anchored at the REAL Haworth tile origin (lat -86.112509, lon -26.651421, from
// stewie.terrain.site_dem.dem_origin_to_latlon(0,0) on samples/lunar_dem/haworth_10km_5m). No fabricated
// measurements -- these are transform-correctness tests (the globe_ellipsoid.test.js FakeCesium pattern).
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const F = require("./frame.js");

const R_MOON = 1737400.0;                          // MOON_ME (IAU_2015:30135)
const DEG = Math.PI / 180.0;
function close(a, b, tol) { assert.ok(Math.abs(a - b) <= tol, `expected ${a} ~= ${b} (tol ${tol})`); }

// ---- bodyFixed: hand-computed values on R = 1737400 (design §5) -------------------------------------
test("bodyFixed (pure) matches hand-computed sphere points on R=1737400", () => {
  // exported pure form: bodyFixed(bodyRadius, latDeg, lonDeg, rDisp)
  const bf = F.bodyFixed;
  // equator/prime meridian sits on +x at exactly the radius.
  let p = bf(R_MOON, 0, 0, 0);
  close(p.x, R_MOON, 1e-6); close(p.y, 0, 1e-6); close(p.z, 0, 1e-6);
  // lon=90 rotates the equatorial point onto +y.
  p = bf(R_MOON, 0, 90, 0);
  close(p.x, 0, 1e-3); close(p.y, R_MOON, 1e-6); close(p.z, 0, 1e-6);
  // the north pole is +z, the south pole is -z.
  close(bf(R_MOON, 90, 0, 0).z, R_MOON, 1e-3);
  close(bf(R_MOON, -90, 0, 0).z, -R_MOON, 1e-3);
  // lat=-89, lon=0 (near the south pole -- the tile-latitude regime): x=R*cos(89deg), z=-R*sin(89deg).
  p = bf(R_MOON, -89, 0, 0);
  close(p.x, R_MOON * Math.cos(89 * DEG), 1e-6);   // ~30319.79 m
  close(p.y, 0, 1e-6);
  close(p.z, -R_MOON * Math.sin(89 * DEG), 1e-6);  // ~-1737135.36 m
  close(p.x, 30321.811, 1e-2);                     // literal anchor (locks the axis assignment + sign): R*cos(89deg)
  close(p.z, -1737135.386, 1e-2);                  // -R*sin(89deg)
  // rDisp adds to the radius along the same ray (elevation above the sphere).
  close(bf(R_MOON, 0, 0, 100).x, R_MOON + 100, 1e-6);
});

test("frame.bodyFixed wires vex + meanElev through exaggerate() into the radial displacement", () => {
  const f = F.makeFrame({ bodyRadius: R_MOON, vex: 2, meanElev: 100 });
  // rDisp = exaggerate(150) = 100 + 2*(150-100) = 200 -> r = R + 200 at lat=lon=0.
  close(f.bodyFixed(0, 0, 150).x, R_MOON + 200, 1e-6);
  // default frame (vex=1, meanElev=0) reduces to the pure form.
  const g = F.makeFrame({ bodyRadius: R_MOON });
  assert.deepStrictEqual(g.bodyFixed(-89, 0, 0), F.bodyFixed(R_MOON, -89, 0, 0));
});

// ---- exaggeration is ABOUT the mean (design §8 balloon trap) ----------------------------------------
test("exaggerate() scales relief about the tile mean, not raw |h|", () => {
  const f = F.makeFrame({ vex: 2, meanElev: 100 });
  assert.strictEqual(f.exaggerate(100), 100);       // a point AT the mean never moves, any vex
  assert.strictEqual(f.exaggerate(150), 200);       // +50 above mean -> +100 above mean
  assert.strictEqual(f.exaggerate(50), 0);          // -50 below mean -> -100 below mean
  assert.strictEqual(f.exaggerate(0), -100);        // 100 below mean -> 200 below mean
  // at vex=1 exaggerate is the identity regardless of the mean.
  const g = F.makeFrame({ vex: 1, meanElev: 500 });
  assert.strictEqual(g.exaggerate(37), 37);
  // setMeanElev / setVex re-reference live.
  f.setMeanElev(0); f.setVex(1);
  assert.strictEqual(f.exaggerate(42), 42);
});

// ---- ENU place round-trips exactly ------------------------------------------------------------------
test("ENU place() is an exact, invertible map of the source metres", () => {
  const f = F.makeFrame({});                         // default enu, S=1, vex=1, meanElev=0
  assert.deepStrictEqual(f.place(100, 50, 10), { x: 100, y: 10, z: 50 });   // exact (multiply by 1)
  // with a scale + exaggeration: x=e*S, y=exaggerate(elev)*S, z=n*S.
  const g = F.makeFrame({ scale: 2, vex: 3, meanElev: 0 });
  const p = g.place(100, 50, 10);
  assert.deepStrictEqual(p, { x: 200, y: 60, z: 100 });                     // exaggerate(10)=30, *2=60
  // invert exactly: e=x/S, n=z/S, elev = meanElev + (y/S - meanElev)/vex.
  const S = 2, vex = 3, meanElev = 0;
  close(p.x / S, 100, 1e-12);
  close(p.z / S, 50, 1e-12);
  close(meanElev + (p.y / S - meanElev) / vex, 10, 1e-12);
});

// ---- bilinear metresToLonLat interpolates a known grid exactly (design §8 trap #1/#3) ----------------
test("metresToLonLat bilinear-interpolates a linear lon/lat grid exactly", () => {
  // lon linear in E, lat linear in N over a 3x3 grid on [0,200]^2 (dE=dN=100).
  const cols = 3, rows = 3, lon = [], lat = [];
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    lon[j * cols + i] = -26 + 0.001 * (i * 100);     // lon(E) = -26 + 0.001*E
    lat[j * cols + i] = -86 + 0.0005 * (j * 100);    // lat(N) = -86 + 0.0005*N
  }
  const f = F.makeFrame({});
  f.setLonLatGrid({ x0: 0, y0: 0, dE: 100, dN: 100, cols, rows, lon, lat });
  const q = f.metresToLonLat(150, 50);               // interior, off-node
  close(q.lon, -26 + 0.001 * 150, 1e-12);            // -25.85
  close(q.lat, -86 + 0.0005 * 50, 1e-12);            // -85.975
  // node points reproduce exactly.
  assert.strictEqual(f.metresToLonLat(0, 0).lon, -26);
  assert.strictEqual(f.metresToLonLat(200, 200).lat, -86 + 0.0005 * 200);
});

test("metresToLonLat is exact for a true BILINEAR field (cross term) and clamps out-of-range", () => {
  // f(E,N) = 1 + 2E + 3N + 0.01*E*N is bilinear -> bilinear interpolation reproduces it exactly.
  const cols = 3, rows = 3, lon = [], lat = [];
  const fval = (E, N) => 1 + 2 * E + 3 * N + 0.01 * E * N;
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    lon[j * cols + i] = fval(i * 100, j * 100);
    lat[j * cols + i] = 0;
  }
  const f = F.makeFrame({});
  f.setLonLatGrid({ x0: 0, y0: 0, dE: 100, dN: 100, cols, rows, lon, lat });
  close(f.metresToLonLat(150, 50).lon, fval(150, 50), 1e-9);     // 1+300+150+75 = 526
  // out-of-range clamps to the edge node (never extrapolates past the sampled tile).
  assert.strictEqual(f.metresToLonLat(-500, 0).lon, lon[0]);
  assert.strictEqual(f.metresToLonLat(1e6, 1e6).lon, lon[rows * cols - 1]);
});

test("globe place() and metresToLonLat throw without a grid (no client-side CRS re-derivation)", () => {
  const f = F.makeFrame({ mode: "globe" });
  assert.throws(() => f.metresToLonLat(0, 0), /setLonLatGrid/);
  assert.throws(() => f.place(0, 0, 0), /setLonLatGrid/);
});

// ---- globe placement: recentre+orient round-trip on an analytic grid at the real Haworth origin ------
// Build a lon/lat grid from the first-order local-ENU linearization at the REAL tile origin so a metre
// offset (E,N) maps to the lon/lat of the point that IS E metres east / N metres north on the sphere.
// worldFromBody must then return that point back as ~(E, dElev, N) -- the full metres->lonlat->bodyFixed->
// recentre round-trip, proving the globe cap locally reduces to ENU (curvature is second-order over a tile).
function haworthGlobeFrame() {
  const lat0 = -86.112509, lon0 = -26.651421;        // dem_origin_to_latlon(0,0) on the committed Haworth bundle
  const cosLat0 = Math.cos(lat0 * DEG);
  const cols = 3, rows = 3, dE = 200, dN = 200, lon = [], lat = [];
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    const E = i * dE, N = j * dN;
    lon[j * cols + i] = lon0 + (E / (R_MOON * cosLat0)) / DEG;   // east offset -> longitude
    lat[j * cols + i] = lat0 + (N / R_MOON) / DEG;               // north offset -> latitude
  }
  const f = F.makeFrame({ bodyRadius: R_MOON, meanElev: 0, mode: "globe" });
  f.setLonLatGrid({ x0: 0, y0: 0, dE, dN, cols, rows, lon, lat });
  f.setOrigin(0, 0);
  return f;
}

test("globe place() recentres the tile origin to ~(0,0,0) and keeps float coords small", () => {
  const f = haworthGlobeFrame();
  const o = f.place(0, 0, 0);
  close(o.x, 0, 1e-6); close(o.y, 0, 1e-6); close(o.z, 0, 1e-6);   // recentred to world origin (§8 trap #7)
});

test("globe place() locally reduces to ENU near the origin (x=East, y=up, z=North)", () => {
  const f = haworthGlobeFrame();
  const east = f.place(100, 0, 0);      // 100 m east
  close(east.x, 100, 0.05); assert.ok(Math.abs(east.y) < 0.05); assert.ok(Math.abs(east.z) < 0.05);
  const north = f.place(0, 100, 0);     // 100 m north
  close(north.z, 100, 0.05); assert.ok(Math.abs(north.x) < 0.05); assert.ok(Math.abs(north.y) < 0.05);
  const up = f.place(0, 0, 50);         // +50 m elevation at the origin -> straight up
  close(up.y, 50, 1e-4); assert.ok(Math.abs(up.x) < 1e-4); assert.ok(Math.abs(up.z) < 1e-4);
});

test("globe place() is deterministic and exaggeration lifts along local up", () => {
  const f = haworthGlobeFrame();
  assert.deepStrictEqual(f.place(150, 60, 12), f.place(150, 60, 12));   // pure function of inputs+state
  f.setVex(2);                                                          // relief x2 about mean 0
  close(f.place(0, 0, 50).y, 100, 1e-4);                               // exaggerate(50)=100 -> +100 up
});

// ---- flat<->globe switch re-places the SAME source metres (overlay registration, §8 trap #2) --------
test("switching enu<->globe<->enu re-places the same source metres identically", () => {
  const f = haworthGlobeFrame();
  f.setMode("enu");
  const a = f.place(100, 50, 10);
  assert.deepStrictEqual(a, { x: 100, y: 10, z: 50 });                 // ENU exact
  f.setMode("globe");
  const g = f.place(100, 50, 10);                                      // a valid, finite globe placement
  assert.ok(Number.isFinite(g.x) && Number.isFinite(g.y) && Number.isFinite(g.z));
  assert.notDeepStrictEqual(g, a);                                     // the globe curves the flat position
  f.setMode("enu");
  assert.deepStrictEqual(f.place(100, 50, 10), a);                     // returning to ENU re-places identically
});

// ---- configurable body radius ------------------------------------------------------------------------
test("bodyRadius defaults to MOON_ME and is configurable per body", () => {
  assert.strictEqual(F.MOON_ME, R_MOON);
  assert.strictEqual(F.makeFrame({}).bodyRadius, R_MOON);
  assert.strictEqual(F.makeFrame({ bodyRadius: 3389500 }).bodyRadius, 3389500);   // Mars volumetric mean radius
  // the configured radius drives bodyFixed.
  close(F.makeFrame({ bodyRadius: 3389500 }).bodyFixed(0, 0, 0).x, 3389500, 1e-6);
});

test("makeFrame exposes the documented API surface + live mode/vex", () => {
  const f = F.makeFrame({});
  for (const k of ["place", "setMode", "setVex", "setLonLatGrid", "bodyFixed", "metresToLonLat"]) {
    assert.strictEqual(typeof f[k], "function", `missing ${k}`);
  }
  assert.strictEqual(f.mode, "enu");
  f.setMode("globe"); assert.strictEqual(f.mode, "globe");
  f.setVex(4); assert.strictEqual(f.vex, 4);
});
