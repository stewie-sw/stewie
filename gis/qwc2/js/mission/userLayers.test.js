// User-layers #44: the CRS gate. A lunar-frame layer is accepted; an Earth-CRS import (the #40 trap) is
// rejected with a reason. Fixtures are real GeoJSON shapes (RFC 7946 + the legacy crs member).
// [REQ:LY-03] user-created/imported layers with an Earth-CRS reject gate (extends LY-01): an imported GeoJSON
// declaring an Earth CRS (EPSG:4326/3857/CRS84/WGS84) is rejected with a legible reason BEFORE it touches the
// map or is promoted planning-eligible; a valid lunar-frame (IAU_2015:30135/30100) layer is accepted. These
// node tests prove the validateLayerCrs runtime behavior; the static wiring gate — that MissionUserLayer.jsx
// blocks on !v.ok before map.addLayer — is stewie/server/test_ly03_user_layer_crs_gate.py, the python
// [REQ:LY-03] citation req_trace.py counts (it scans python test_*.py, not the JS tier).
const assert = require("node:assert");
const { test } = require("node:test");
const UL = require("./userLayers.js");

test("parseUserLayer accepts a FeatureCollection + rejects non-GeoJSON", () => {
  const fc = UL.parseUserLayer('{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[0,-88]},"properties":{}}]}');
  assert.strictEqual(fc.ok, true);
  assert.strictEqual(fc.featureCount, 1);
  assert.strictEqual(UL.parseUserLayer("not json").ok, false);
  assert.strictEqual(UL.parseUserLayer('{"type":"Polygon"}').ok, false);   // a bare geometry is not importable
});

test("validateLayerCrs ACCEPTS a lunar IAU frame", () => {
  const r = UL.validateLayerCrs({ type: "FeatureCollection", crs: { properties: { name: "IAU_2015:30100" } }, features: [] });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.isLunar, true);
  assert.strictEqual(r.warning, null);
});

test("validateLayerCrs REJECTS an Earth CRS (the trap)", () => {
  const r = UL.validateLayerCrs({ type: "FeatureCollection", crs: { properties: { name: "urn:ogc:def:crs:EPSG::4326" } }, features: [] });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.isEarth, true);
  assert.match(r.warning, /EARTH CRS/i);
  assert.strictEqual(UL.validateLayerCrs({ crs: { properties: { name: "EPSG:3857" } } }).isEarth, true);
});

test("validateLayerCrs soft-notes a no-crs GeoJSON (assume lunar selenographic, still ok)", () => {
  const r = UL.validateLayerCrs({ type: "FeatureCollection", features: [] });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.isEarth, false);
  assert.match(r.warning, /assuming lunar|No CRS/i);
});
