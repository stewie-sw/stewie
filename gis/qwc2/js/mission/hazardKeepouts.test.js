// node:test for hazardKeepouts.js -- the pure council #52 client bridge (DERIVE KEEP-OUTS FROM HAZARD). The
// REAL fixture below is the VERBATIM response from GET /api/world/keepouts-from-hazard?site=shackleton_rim
// (the real Shackleton-rim LOLA work-area crop, 2026-07-09) -- not synthetic; captured from
// stewie.server.gis_layers.hazard_keepouts_geojson. One real hazard region (a crater-rim drop-off), 1 feature.
//   Run: node --test gis/qwc2/js/mission/hazardKeepouts.test.js
const test = require("node:test");
const assert = require("node:assert");
const HK = require("./hazardKeepouts.js");

// VERBATIM real response (shackleton_rim): a single negative-obstacle hazard region, 8-vertex closed ring.
const REAL = {
  type: "FeatureCollection",
  properties: {
    site: "shackleton_rim", crs: "OGC:CRS84", n_features: 1, n_specks_dropped: 6, nogo_cells: 11,
    grid_cells: 16384, nogo_fraction: 0.000671,
    hazard_gate: ["slope", "sinkage", "tip_risk", "negative_obstacle"],
    per_layer_block: { slope: 1, sinkage: 0, tip_risk: 0, negative_obstacle: 11 },
    thresholds: { max_slope_deg: 25.0, min_area_m2: 100.0 },
    grid: { rows: 128, cols: 128, cell_m: 5.0 }, truncated: false
  },
  features: [{
    type: "Feature", properties: { kind: "hazard_keepout", area_m2: 106.36, holes: 0 },
    geometry: {
      type: "Polygon", coordinates: [[
        [129.072871, -89.729108], [129.023794, -89.729084], [129.001836, -89.728955],
        [129.055996, -89.728748], [129.080505, -89.72876], [129.102484, -89.728888],
        [129.09995, -89.729004], [129.072871, -89.729108]
      ]]
    }
  }]
};

// A deterministic stub reproject: IAU_2015:30100 lon/lat -> a fake metric map frame (scale by 1000). Finite
// everywhere, so every real vertex survives -- exactly the shape CoordinatesUtils.reproject returns.
function stubReproject(pt /*, srcCrs, dstCrs */) { return [pt[0] * 1000, pt[1] * 1000]; }

test("url encodes the site into the public route", () => {
  assert.strictEqual(HK.url("shackleton_rim"), "/api/world/keepouts-from-hazard?site=shackleton_rim");
  assert.strictEqual(HK.url("a b"), "/api/world/keepouts-from-hazard?site=a%20b");
});

test("openRing drops the closing duplicate (GeoJSON ring is closed)", () => {
  const closed = REAL.features[0].geometry.coordinates[0];   // 8 verts, first === last
  const open = HK.openRing(closed);
  assert.strictEqual(open.length, closed.length - 1);        // 7 open verts
  assert.notDeepStrictEqual(open[0], open[open.length - 1]); // no longer closed
  // an already-open ring is returned unchanged (by value)
  const already = [[0, 0], [1, 0], [1, 1]];
  assert.deepStrictEqual(HK.openRing(already), already);
});

test("exteriorRings extracts the open exterior ring; skips non-polygons + degenerate rings", () => {
  const regions = HK.exteriorRings(REAL);
  assert.strictEqual(regions.length, 1);
  assert.strictEqual(regions[0].ring.length, 7);             // opened exterior ring
  assert.strictEqual(regions[0].area_m2, 106.36);
  // a mixed FC: a LineString + a degenerate 2-vertex polygon are both skipped; only the real polygon survives
  const mixed = {
    features: [
      { geometry: { type: "LineString", coordinates: [[0, 0], [1, 1]] } },
      { geometry: { type: "Polygon", coordinates: [[[0, 0], [1, 0]]] } },   // < 3 verts -> skipped
      REAL.features[0]
    ]
  };
  assert.strictEqual(HK.exteriorRings(mixed).length, 1);
});

test("toMapRings reprojects each exterior ring to the map frame via the injected reproject", () => {
  const res = HK.toMapRings(REAL, stubReproject);
  assert.strictEqual(res.total, 1);
  assert.strictEqual(res.rings.length, 1);
  assert.strictEqual(res.skipped, 0);
  // every map vertex is the stub-reprojected lon/lat (scale 1000), and finite
  assert.deepStrictEqual(res.rings[0][0], [129072.871, -89729.108]);
  res.rings[0].forEach((p) => { assert.ok(Number.isFinite(p[0]) && Number.isFinite(p[1])); });
});

test("toMapRings drops a vertex that reprojects non-finite, and skips a sub-3-vertex ring", () => {
  // a reproject that fails on all but two vertices -> the ring falls below 3 finite verts -> skipped (counted)
  let n = 0;
  const flaky = (pt) => { n += 1; return n <= 2 ? [pt[0], pt[1]] : [NaN, NaN]; };
  const res = HK.toMapRings(REAL, flaky);
  assert.strictEqual(res.rings.length, 0);
  assert.strictEqual(res.skipped, 1);
});

test("toMapRings skips a ring over the vertex cap (counted)", () => {
  const res = HK.toMapRings(REAL, stubReproject, { maxVerts: 3 });   // the real ring has 7 verts > 3
  assert.strictEqual(res.rings.length, 0);
  assert.strictEqual(res.skipped, 1);
  assert.strictEqual(res.total, 1);
});

test("addToMission adds each region through the controller keep-out path, serially", async () => {
  const calls = [];
  const ctrl = { addKeepoutPolygon: (ring) => { calls.push(ring); return Promise.resolve({ ok: true }); } };
  const out = await HK.addToMission(REAL, ctrl, stubReproject);
  assert.deepStrictEqual(out, { added: 1, skipped: 0, total: 1 });
  assert.strictEqual(calls.length, 1);
  assert.strictEqual(calls[0].length, 7);   // the map-frame open ring was handed to the existing keep-out path
});

test("addToMission is a no-op when the controller lacks the keep-out path", async () => {
  const out = await HK.addToMission(REAL, {}, stubReproject);
  assert.deepStrictEqual(out, { added: 0, skipped: 0, total: 1 });
});
