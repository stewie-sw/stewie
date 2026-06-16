// Phase 2 / FS-15 (node:test): the typed frontend contract adapters are pure -> unit-testable without a
// browser. Run: node --test stewie/server/web/assets/adapters.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const A = require("./adapters.js");

test("normalizeEphemeris maps the contract + derives lit", () => {
  const vm = A.normalizeEphemeris({ ephemeris: {
    mission_t_s: 0, site_lat_deg: -87.45, site_lon_deg: 0, frame: "MOON_ME",
    sun_az_deg: 90, sun_el_deg: 6, azimuth_convention: "from_north_eastward",
    uncertainty_deg: 0, source: "analytic" } });
  assert.strictEqual(vm.sun.convention, "from_north_eastward");   // the explicit convention carries through
  assert.strictEqual(vm.site.frame, "MOON_ME");
  assert.strictEqual(vm.lit, true);                                // el 6 > 0 -> sunlit
  assert.strictEqual(A.normalizeEphemeris({}), null);              // no payload -> null
});

test("normalizeWorld maps grid + derives metric extent", () => {
  const vm = A.normalizeWorld({ world: {
    body: "moon", frame: "MOON_ME", rows: 2000, cols: 2000, cell_m: 5,
    datum_radius_m: 1737400, observed_fraction: 0, mutated: false, dem_source: "haworth_10km_5m" } });
  assert.strictEqual(vm.grid.rows, 2000);
  assert.strictEqual(vm.extentM.x, 10000);                         // 2000 * 5 m
  assert.strictEqual(vm.demSource, "haworth_10km_5m");
});

test("toViewState maps loading / ok / empty / error", () => {
  assert.strictEqual(A.toViewState({ status: "pending" }).state, "loading");
  assert.strictEqual(A.toViewState({ status: 500, json: { ok: false, error: "boom" } }).state, "error");
  assert.strictEqual(
    A.toViewState({ status: 200, json: { world: null }, normalize: A.normalizeWorld }).state, "empty");
  assert.strictEqual(
    A.toViewState({ status: 200, json: { ephemeris: { sun_el_deg: 1 } }, normalize: A.normalizeEphemeris }).state, "ok");
});

test("canAct mirrors the AG-01 role ladder (FS-15 permission mapping)", () => {
  assert.strictEqual(A.canAct("command", "trainee"), false);      // command needs operator+
  assert.strictEqual(A.canAct("command", "operator"), true);
  assert.strictEqual(A.canAct("admin", "operator"), false);       // admin needs director
  assert.strictEqual(A.canAct("plan", "guest"), true);            // reads open to guest
  assert.strictEqual(A.canAct("command", "bogus"), false);        // unknown role -> fail closed
});
