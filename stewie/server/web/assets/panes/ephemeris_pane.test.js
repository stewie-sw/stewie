// Phase 2 / FS-15 (node:test): the ephemeris pane render is pure -> unit-testable.
// Run: node --test stewie/server/web/assets/panes/ephemeris_pane.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const P = require("./ephemeris_pane.js");
const A = require("../adapters.js");

function vsFromPayload(payload) {
  return A.toViewState({ status: 200, json: payload, normalize: A.normalizeEphemeris });
}

test("ok state renders az/el + the explicit convention + a SUNLIT badge", () => {
  const vs = vsFromPayload({ ephemeris: {
    mission_t_s: 0, site_lat_deg: -87.45, site_lon_deg: 0, frame: "MOON_ME",
    sun_az_deg: 90.4, sun_el_deg: 6.2, azimuth_convention: "from_north_eastward",
    uncertainty_deg: 0, source: "analytic" } });
  const html = P.renderEphemerisPane(vs);
  assert.match(html, /data-state="ok"/);
  assert.match(html, /90\.4/);                         // azimuth
  assert.match(html, /from_north_eastward/);           // the convention is shown verbatim (§25.3)
  assert.match(html, /SUNLIT/);                        // el > 0
});

test("shadowed when the sun is below the horizon", () => {
  const vs = vsFromPayload({ ephemeris: {
    mission_t_s: 0, site_lat_deg: -89, site_lon_deg: 0, frame: "MOON_ME",
    sun_az_deg: 10, sun_el_deg: -3, azimuth_convention: "from_north_eastward", source: "analytic" } });
  assert.match(P.renderEphemerisPane(vs), /SHADOWED/);
});

test("loading / empty / error states render placeholders, never crash", () => {
  assert.match(P.renderEphemerisPane({ state: "loading" }), /Resolving/);
  assert.match(P.renderEphemerisPane({ state: "empty" }), /No ephemeris/);
  assert.match(P.renderEphemerisPane({ state: "error", error: "boom" }), /boom/);
  assert.match(P.renderEphemerisPane(null), /loading/);   // null -> loading, no throw
});

test("error text is HTML-escaped (no injection)", () => {
  const html = P.renderEphemerisPane({ state: "error", error: "<img onerror=x>" });
  assert.ok(!html.includes("<img"));
  assert.match(html, /&lt;img/);
});
