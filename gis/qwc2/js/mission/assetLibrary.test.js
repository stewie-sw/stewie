// [REQ:GW-04] (node:test): the QWC2 Asset-Library bridge is pure data/logic (no DOM, no React) so its
// browse/search/group/format derivations unit-test in bare node. Asserts the REAL outputs of the actual
// module logic in assetLibrary.js: the type tables, the URL builders (public /api/library reads), the
// size/date formatters, the client-side search match, and the ordered group-by-type projection.
// (JS-only citation: the python req_trace + gen scanners scan python test_*.py, so this does NOT trigger a
// gen regen; the [REQ:GW-04] backend citation is stewie/server/test_gw04_asset_library.py.)
// Run: node --test gis/qwc2/js/mission/assetLibrary.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const A = require("./assetLibrary.js");

test("TYPES: the six durable asset types in display order", () => {
  assert.deepStrictEqual(A.TYPES.map((t) => t.id),
    ["mission", "structure", "report", "site", "twin", "dem"]);
  assert.strictEqual(A.TYPE_LABEL.mission, "Missions");
  assert.strictEqual(A.TYPE_LABEL.dem, "DEM Bundles");
});

test("URL builders target the PUBLIC /api/library read + inspect/export", () => {
  assert.strictEqual(A.libraryUrl(), "/api/library");
  assert.strictEqual(A.libraryUrl({ q: "berm", type: "structure" }),
    "/api/library?q=berm&type=structure");
  assert.strictEqual(A.libraryUrl({ includeTrash: true }), "/api/library?include_trash=1");
  assert.strictEqual(A.inspectUrl("mission", "landing-pad-a"), "/api/library/mission/landing-pad-a");
  assert.strictEqual(A.exportUrl("dem", "haworth_10km_5m"),
    "/api/library/dem/haworth_10km_5m/export");
});

test("humanSize / humanTime: pure formatters", () => {
  assert.strictEqual(A.humanSize(0), "0 B");
  assert.strictEqual(A.humanSize(512), "512 B");
  assert.strictEqual(A.humanSize(2048), "2.0 KB");
  assert.strictEqual(A.humanSize(68315384), "65 MB");
  assert.strictEqual(A.humanSize(-1), "");
  assert.strictEqual(A.humanTime(0), "");
  assert.strictEqual(A.humanTime(1782735694).length, 10);   // YYYY-MM-DD
});

test("matchAsset / filterAssets: case-insensitive substring over type/id/title/provenance", () => {
  const assets = [
    { type: "mission", id: "landing-pad-a", title: "Landing Pad A", provenance: "authored by alice (live)" },
    { type: "report", id: "haworth_plan", title: "haworth plan", provenance: "mission-control report" },
    { type: "dem", id: "haworth_10km_5m", title: "haworth 10km 5m", provenance: "real LOLA DEM ingest" }
  ];
  assert.strictEqual(A.matchAsset(assets[0], ""), true);           // empty query matches all
  assert.strictEqual(A.matchAsset(assets[0], "ALICE"), true);      // provenance, case-insensitive
  assert.strictEqual(A.matchAsset(assets[1], "dem"), false);
  const haworth = A.filterAssets(assets, "haworth");
  assert.strictEqual(haworth.length, 2);
  assert.deepStrictEqual(haworth.map((a) => a.type).sort(), ["dem", "report"]);
});

test("groupByType: ordered sections, empty types dropped, unknown type appended", () => {
  const assets = [
    { type: "report", id: "r1" }, { type: "mission", id: "m1" }, { type: "mission", id: "m2" },
    { type: "gadget", id: "g1" }
  ];
  const tree = A.groupByType(assets);
  assert.deepStrictEqual(tree.map((g) => g.id), ["mission", "report", "gadget"]);  // TYPES order, unknown last
  assert.strictEqual(tree[0].rows.length, 2);       // both missions grouped
  assert.strictEqual(tree[0].label, "Missions");
  assert.strictEqual(tree[2].label, "gadget");      // unknown type keeps its raw id as label
});

test("counts: per-type tally for the browse header", () => {
  const c = A.counts([{ type: "mission" }, { type: "mission" }, { type: "dem" }]);
  assert.deepStrictEqual(c, { mission: 2, dem: 1 });
});

test("setApiBase rebinds the URL builders (test hook)", () => {
  A.setApiBase("http://127.0.0.1:8799");
  assert.strictEqual(A.libraryUrl(), "http://127.0.0.1:8799/library");
  A.setApiBase("/api");                              // restore
  assert.strictEqual(A.libraryUrl(), "/api/library");
});
