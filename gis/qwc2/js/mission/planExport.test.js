// [REQ:GI-03] node:test for the /ide plan-GeoJSON export URL builder (planExport.js). Pure logic — proves
// the download URL targets the key-injected /api/export/geojson proxy with the mission + the plan levers,
// and refuses honestly (no URL) when there is nothing exportable. The backend serialization + the live
// download are Playwright-verified against the deployed /ide; the backend contract is stewie/server's
// gis_export router ([REQ:GI-03] python is the existing GI-03 coverage).
const assert = require("node:assert");
const { test } = require("node:test");
const PE = require("./planExport.js");

const MISSION = {
  name: "artemis-ide mission", body: "moon", site: "haworth",
  algorithm: "nearest", objective: "time", max_traverse_slope_deg: 25, vehicles: 1, charger_capacity: 1,
  lat: -87.34, lon: 25.11,
  orders: [{ kind: "cut", footprint_m2: 60, depth_m: 0.4, x: 100, y: 200 }],
  keepouts: [{ kind: "circle", cx: 50, cy: 60, r: 10 }],
};

test("buildExportUrl targets /api/export/geojson with the mission + the plan levers", () => {
  const r = PE.buildExportUrl(MISSION);
  assert.strictEqual(r.ok, true);
  assert.ok(r.url.startsWith("/api/export/geojson?"), "hits the key-injected export proxy");
  // the mission JSON is URL-encoded and round-trips the authored orders + keep-outs the backend planner reads.
  const params = new URLSearchParams(r.url.split("?")[1]);
  const mission = JSON.parse(params.get("mission"));
  assert.strictEqual(mission.orders.length, 1);
  assert.strictEqual(mission.keepouts.length, 1);
  assert.strictEqual(mission.body, "moon");
  // the query levers mirror the mission so the export matches what was planned.
  assert.strictEqual(params.get("site"), "haworth");
  assert.strictEqual(params.get("algorithm"), "nearest");
  assert.strictEqual(params.get("objective"), "time");
  assert.strictEqual(params.get("max_traverse_slope_deg"), "25");
  assert.strictEqual(params.get("lat"), "-87.34");
  assert.strictEqual(params.get("lon"), "25.11");
  assert.strictEqual(r.filename, "haworth_plan.geojson");
});

test("[REQ:GI-03] place-object markers (annotations) ride the export mission through the URL", () => {
  const withMarkers = { ...MISSION, markers: [{ x: 30, y: 25, otype: "beacon", label: "LZ beacon" }, { x: 60, y: 40, otype: "sample" }] };
  const r = PE.buildExportUrl(withMarkers);
  assert.strictEqual(r.ok, true);
  const mission = JSON.parse(new URLSearchParams(r.url.split("?")[1]).get("mission"));
  assert.strictEqual(mission.markers.length, 2, "the markers are carried to the backend for Point serialization");
  assert.strictEqual(mission.markers[0].otype, "beacon");
  assert.strictEqual(mission.markers[0].label, "LZ beacon");
  assert.strictEqual(mission.markers[1].label, undefined);   // an unlabelled marker carries no label
});

test("a mission with no orders is refused (nothing planned to export), not a broken URL", () => {
  assert.strictEqual(PE.buildExportUrl({ body: "moon", site: "haworth", orders: [] }).ok, false);
  assert.strictEqual(PE.buildExportUrl({ body: "moon", site: "haworth" }).ok, false);
  assert.strictEqual(PE.buildExportUrl(null).ok, false);
  assert.strictEqual(PE.buildExportUrl("nope").ok, false);
});

test("a non-moon mission is refused (no georeferenced lunar DEM to project through)", () => {
  const r = PE.buildExportUrl({ ...MISSION, body: "mars" });
  assert.strictEqual(r.ok, false);
  assert.match(r.error, /lunar|moon/);
});

test("optional levers are omitted when absent (a minimal mission still builds a valid URL)", () => {
  const r = PE.buildExportUrl({ body: "moon", site: "shackleton_rim", orders: [{ kind: "cut", footprint_m2: 10, depth_m: 1 }] });
  assert.strictEqual(r.ok, true);
  const params = new URLSearchParams(r.url.split("?")[1]);
  assert.strictEqual(params.get("site"), "shackleton_rim");
  assert.strictEqual(params.has("algorithm"), false);   // not set on this mission -> not in the URL
  assert.strictEqual(params.has("lat"), false);
  assert.ok(params.get("mission"), "the mission is always present");
});
