// FS-24 (node:test): the site-frame bearing + lat/lon formatting helpers are pure -> unit-testable
// without a browser. These are the angle math + coordinate formatting the #174 "where are we" locator
// renders; the DOM glue (updateLocator) lives in cockpit.js.
// Run: node --test stewie/server/web/assets/geofmt.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./geofmt.js");

test("bearingFrom: due North is 0 deg N (+y = North, no East offset)", () => {
  assert.strictEqual(G.bearingFrom(0, 1), "0° N");
});

test("bearingFrom: due East is 90 deg E (+x = East)", () => {
  assert.strictEqual(G.bearingFrom(1, 0), "90° E");
});

test("bearingFrom: due South is 180 deg S", () => {
  assert.strictEqual(G.bearingFrom(0, -1), "180° S");
});

test("bearingFrom: due West wraps the negative angle to 270 deg W", () => {
  // atan2(-1, 0) = -90 deg -> +360 = 270 deg (the negative-angle wrap branch)
  assert.strictEqual(G.bearingFrom(-1, 0), "270° W");
});

test("bearingFrom: a NE diagonal is 45 deg NE (the 16-point rose midpoint)", () => {
  assert.strictEqual(G.bearingFrom(1, 1), "45° NE");
});

test("bearingFrom: the sector rounds to the nearest 22.5 deg point", () => {
  // ~22.5 deg falls on the NNE sector boundary; ~67.5 deg on ENE.
  assert.match(G.bearingFrom(Math.tan((22.5 + 1) * Math.PI / 180), 1), /NNE$/);
  assert.match(G.bearingFrom(1, Math.tan((22.5 + 1) * Math.PI / 180)), /ENE$/);
});

test("bearingFrom: 360-deg wrap lands back on N (Math.round(b/22.5) % 16)", () => {
  // a hair west of due North: ~359.x deg -> rounds to 16 -> %16 = 0 -> N, never out of bounds
  assert.match(G.bearingFrom(-0.001, 1), /N$/);
});

test("fmtLL: a {lat, lon} prints both at 4 decimals with degree marks", () => {
  assert.strictEqual(G.fmtLL({ lat: -87.4523, lon: 12.5 }), "-87.4523°, 12.5000°");
});

test("fmtLL: a missing fix is the em-dash placeholder, never a crash", () => {
  assert.strictEqual(G.fmtLL(null), "—");
  assert.strictEqual(G.fmtLL(undefined), "—");
});
