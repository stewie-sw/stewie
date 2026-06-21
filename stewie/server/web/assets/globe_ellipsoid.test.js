// GI-02 (node:test): the per-body globe ellipsoid is a pure body-key -> radii lookup, unit-testable
// without a browser or Cesium. Run: node --test stewie/server/web/assets/globe_ellipsoid.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./globe_ellipsoid.js");

test("BODY_RADII carries SOURCED radii in METERS for each globe body", () => {
  // Moon: IAU mean radius 1737.4 km. Mars: IAU volumetric mean radius 3389.5 km.
  // Earth: WGS84 (equatorial 6378137.0, polar 6356752.314245).
  assert.deepStrictEqual(G.BODY_RADII.moon, { x: 1737400, y: 1737400, z: 1737400 });
  assert.deepStrictEqual(G.BODY_RADII.mars, { x: 3389500, y: 3389500, z: 3389500 });
  assert.deepStrictEqual(G.BODY_RADII.earth, { x: 6378137.0, y: 6378137.0, z: 6356752.314245 });
});

test("radiiFor resolves a body key case-insensitively and defaults safely to Earth", () => {
  assert.deepStrictEqual(G.radiiFor("moon"), G.BODY_RADII.moon);
  assert.deepStrictEqual(G.radiiFor("MARS"), G.BODY_RADII.mars);
  // an unknown key must NOT throw inside the render path -> Earth is the safe documented fallback.
  assert.deepStrictEqual(G.radiiFor("pluto"), G.BODY_RADII.earth);
  assert.deepStrictEqual(G.radiiFor(undefined), G.BODY_RADII.earth);
});

test("bodyEllipsoid builds a Cesium.Ellipsoid from the body's sourced radii", () => {
  // A minimal Cesium stand-in: records the radii the renderer would pass to the real constructor.
  const calls = [];
  const FakeCesium = { Ellipsoid: function (x, y, z) { calls.push([x, y, z]); this.x = x; this.y = y; this.z = z; } };

  const e = G.bodyEllipsoid(FakeCesium, "mars");
  assert.deepStrictEqual(calls, [[3389500, 3389500, 3389500]]);
  assert.strictEqual(e.x, 3389500);

  // Earth keeps the WGS84 figure (real Cesium would round-trip Ellipsoid.WGS84 identically).
  G.bodyEllipsoid(FakeCesium, "earth");
  assert.deepStrictEqual(calls[1], [6378137.0, 6378137.0, 6356752.314245]);
});

test("bodyEllipsoid returns null when Cesium is absent (degrade-clean, no throw)", () => {
  assert.strictEqual(G.bodyEllipsoid(undefined, "moon"), null);
});
