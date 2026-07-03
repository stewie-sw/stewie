// PO-11 (node:test): the multi-rover fleet playback model is pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/fleet_playback.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const P = require("./fleet_playback.js");

// a real-SHAPED 2-vehicle plan slice: vehicles_detail (per-rover aggregates) + vehicle-tagged per-trips
// (each {trip:{site,vehicle}, t_start}), the exact shape lode.plan_and_simulate emits.
const TOTALS2 = {
  vehicles: 2,
  vehicles_detail: [
    { vehicle: "v0", n_trips: 2, time_s: 1200, distance_m: 300, energy_J: 4e6, charges: 0,
      health: { health: "nominal", min_batt_frac: 0.62 } },
    { vehicle: "v1", n_trips: 1, time_s: 600, distance_m: 150, energy_J: 2e6, charges: 1,
      health: { health: "low_margin", min_batt_frac: 0.11 } },
  ],
};
const TRIPS2 = [
  { trip: { site: [40, 0], vehicle: "v0" }, t_start: 0 },
  { trip: { site: [80, 0], vehicle: "v0" }, t_start: 700 },
  { trip: { site: [-40, 5], vehicle: "v1" }, t_start: 0 },
];

test("N rovers -> N tracks + N telemetry streams", () => {
  const m = P.fleetPlaybackModel(TOTALS2, TRIPS2, [0, 0]);
  assert.strictEqual(m.count, 2);
  assert.strictEqual(m.tracks.length, 2, "one track per rover");
  assert.strictEqual(m.streams.length, 2, "one telemetry stream per rover");
  // each track is that rover's OWN route (charger start + its own sites, in its own visit order)
  const v0 = m.tracks.find((t) => t.vehicle === "v0");
  assert.deepStrictEqual(v0.waypoints, [[0, 0], [40, 0], [80, 0]]);
  assert.strictEqual(v0.n_stops, 2);
  const v1 = m.tracks.find((t) => t.vehicle === "v1");
  assert.deepStrictEqual(v1.waypoints, [[0, 0], [-40, 5]]);
  // each stream is that rover's INDEPENDENT telemetry, off the real vehicles_detail
  const s1 = m.streams.find((s) => s.vehicle === "v1");
  assert.strictEqual(s1.time_s, 600);
  assert.strictEqual(s1.min_batt_frac, 0.11);
  assert.strictEqual(s1.health, "low_margin");
});

test("each rover advances on its OWN timeline (independent progress)", () => {
  const m = P.fleetPlaybackModel(TOTALS2, TRIPS2, [0, 0]);
  // at simT=600s: v1 (time_s 600) has finished (progress 1) while v0 (time_s 1200) is halfway.
  const fr = P.playbackFrame(m, 600);
  const f0 = fr.find((r) => r.vehicle === "v0");
  const f1 = fr.find((r) => r.vehicle === "v1");
  assert.ok(Math.abs(f0.progress - 0.5) < 1e-9, "v0 should be halfway at 600/1200");
  assert.strictEqual(f1.progress, 1, "v1 should be done at 600/600");
  // distinct markers on distinct routes at the same wall time (not one shared marker)
  assert.notDeepStrictEqual(f0.marker, f1.marker);
  assert.strictEqual(fr.length, 2, "one marker per rover");
});

test("three rovers -> three tracks + three streams", () => {
  const totals3 = {
    vehicles_detail: [
      { vehicle: "a", n_trips: 1, time_s: 100, health: { health: "nominal" } },
      { vehicle: "b", n_trips: 1, time_s: 200, health: { health: "nominal" } },
      { vehicle: "c", n_trips: 1, time_s: 300, health: { health: "nominal" } },
    ],
  };
  const trips3 = [
    { trip: { site: [1, 1], vehicle: "a" }, t_start: 0 },
    { trip: { site: [2, 2], vehicle: "b" }, t_start: 0 },
    { trip: { site: [3, 3], vehicle: "c" }, t_start: 0 },
  ];
  const m = P.fleetPlaybackModel(totals3, trips3);
  assert.strictEqual(m.tracks.length, 3);
  assert.strictEqual(m.streams.length, 3);
  assert.strictEqual(P.playbackFrame(m, 50).length, 3);
});

test("uses the planner's per-rover track field when present (charger start + sites)", () => {
  // vehicles_detail carries the rover's OWN route directly (PO-11 backend field); no separate trips needed.
  const totals = {
    vehicles_detail: [
      { vehicle: "v0", n_trips: 2, time_s: 900, track: [[0, 0], [40, 0], [80, 0]],
        health: { health: "nominal", min_batt_frac: 0.5 } },
      { vehicle: "v1", n_trips: 1, time_s: 400, track: [[0, 0], [-40, 5]], health: { health: "nominal" } },
    ],
  };
  const m = P.fleetPlaybackModel(totals, []);   // no trips arg -> tracks come from detail.track
  assert.strictEqual(m.tracks.length, 2);
  assert.deepStrictEqual(m.tracks[0].waypoints, [[0, 0], [40, 0], [80, 0]]);
  assert.strictEqual(m.tracks[0].n_stops, 2);
  assert.strictEqual(m.streams.length, 2);
});

test("fleetPlaybackHTML renders one track + telemetry block per rover", () => {  // [REQ:PO-11]
  const m = P.fleetPlaybackModel(TOTALS2, TRIPS2, [0, 0]);
  const html = P.fleetPlaybackHTML(m, (s) => String(s), 600);
  const blocks = (html.match(/class="fbrover"/g) || []).length;
  assert.strictEqual(blocks, 2, "expected one playback block per rover");
  assert.ok(html.includes('data-vehicle="v0"') && html.includes('data-vehicle="v1"'));
  assert.strictEqual((html.match(/<polyline/g) || []).length, 2, "each rover draws its own track polyline");
  assert.strictEqual((html.match(/<circle/g) || []).length, 2, "each rover has its own marker");
  assert.ok(html.includes("low_margin"), "per-rover telemetry (health) is shown");
});

test("fleetPlaybackHTML empty-states with no rovers", () => {
  const html = P.fleetPlaybackHTML({ tracks: [], streams: [] }, (s) => String(s));
  assert.ok(/No fleet playback yet/.test(html));
});

test("roverMarkerAt clamps and interpolates along the rover's own legs", () => {
  const tr = { waypoints: [[0, 0], [10, 0], [10, 10]] };
  assert.deepStrictEqual(P.roverMarkerAt(tr, 0), [0, 0]);
  assert.deepStrictEqual(P.roverMarkerAt(tr, 0.25), [5, 0]);   // halfway along leg 1 of 2
  assert.deepStrictEqual(P.roverMarkerAt(tr, 1), [10, 10]);
  assert.deepStrictEqual(P.roverMarkerAt(tr, 5), [10, 10]);    // clamped
  assert.strictEqual(P.roverMarkerAt({ waypoints: [] }, 0.5), null);
});
