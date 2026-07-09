// PO-04 (node:test): the QWC2 mission LAYER-CATALOG bridge is pure data/logic (no DOM, no OL, no React) so
// its derivations serialize + unit-test in bare node. This asserts the REAL outputs of the actual module
// logic in catalogLayers.js: the SERVABLE/LEGEND_KEY/GROUPS tables, the provenance + confidence derivations
// (kept in parity with stewie/server/routers/world.py), the ordered/grouped catalog tree, the sun/URL
// builders, the QWC2 `image`-layer serializer, and the [REQ:GW-06] manifest-freshness projection.
// Run: node --test gis/qwc2/js/mission/catalogLayers.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const C = require("./catalogLayers.js");

// --- constant tables -------------------------------------------------------------------------------
test("SERVABLE: 19 globe-kind mappings grounded in the backend _GLOBE_KINDS allow-list", () => {
  assert.strictEqual(Object.keys(C.SERVABLE).length, 19);
  assert.strictEqual(C.SERVABLE["base.dem"], "dem");
  assert.strictEqual(C.SERVABLE["traffic.cost_global"], "cost");
  assert.strictEqual(C.SERVABLE["traffic.traversability"], "blocking");
  assert.strictEqual(C.SERVABLE["physics.excavation_resistance"], "excavation_resistance");
  assert.strictEqual(C.SERVABLE["traffic.compaction"], "traffic");
  // LY-05 DEM-derivative drapes: aspect + curvature + roughness are servable globe kinds
  assert.strictEqual(C.SERVABLE["terrain.aspect"], "aspect");
  assert.strictEqual(C.SERVABLE["terrain.curvature"], "curvature");
  assert.strictEqual(C.SERVABLE["terrain.roughness"], "roughness");
  // physics.compaction is DELIBERATELY absent (it re-labels the same TrafficMemory Dr family)
  assert.strictEqual(Object.prototype.hasOwnProperty.call(C.SERVABLE, "physics.compaction"), false);
});

test("GROUPS: 12 ordered display groups, site-context first, evidence/runtime last", () => {
  assert.strictEqual(C.GROUPS.length, 12);
  assert.deepStrictEqual(C.GROUPS.map((g) => g.id),
    ["base", "terrain", "hazard", "physics", "traffic", "regolith",
     "mission", "design", "map", "robot", "runtime", "evidence"]);
  assert.strictEqual(C.GROUPS[0].name, "Base");
  assert.strictEqual(C.GROUPS[0].section, "1");
  assert.strictEqual(C.GROUPS[3].name, "Physics (TM)");
});

test("LEGEND_KEY: grid has no legend entry; each servable kind maps to its legend key", () => {
  assert.strictEqual(C.LEGEND_KEY.dem, "dem");
  assert.strictEqual(C.LEGEND_KEY.slip_risk, "slip_risk");
  assert.strictEqual(C.LEGEND_KEY.traffic, "traffic");
  assert.strictEqual(C.LEGEND_KEY.aspect, "aspect");
  assert.strictEqual(C.LEGEND_KEY.curvature, "curvature");
  assert.strictEqual(C.LEGEND_KEY.roughness, "roughness");
  assert.strictEqual(Object.prototype.hasOwnProperty.call(C.LEGEND_KEY, "grid"), false);
});

test("LUNAR_GEOG_CRS is the selenographic authoring CRS the ImageStatic is declared in", () => {
  assert.strictEqual(C.LUNAR_GEOG_CRS, "IAU_2015:30100");
});

// --- provClass: strongest evidence token wins ------------------------------------------------------
test("provClass: strongest (lowest-rank) token wins across a source_class string", () => {
  assert.strictEqual(C.provClass("prior/observed"), "observed");   // observed(3) beats prior(13)
  assert.strictEqual(C.provClass("forecast/belief"), "belief");    // belief(10) beats forecast(11)
  assert.strictEqual(C.provClass("live/prior"), "live");           // live(0) is strongest
});

test("provClass: empty/nullish -> prior; an unknown token passes through as-is", () => {
  assert.strictEqual(C.provClass(""), "prior");
  assert.strictEqual(C.provClass(null), "prior");
  assert.strictEqual(C.provClass("foo"), "foo");
});

// --- shortName -------------------------------------------------------------------------------------
test("shortName: takes the id tail and de-underscores it", () => {
  assert.strictEqual(C.shortName("physics.slip_risk"), "slip risk");
  assert.strictEqual(C.shortName("base.dem"), "dem");
  assert.strictEqual(C.shortName("dem"), "dem");   // no dot -> whole id
});

// --- confidenceFromSourceClass (parity with world.py layer_confidence) -----------------------------
test("confidenceFromSourceClass: an observed layer is measured/high, not conditional", () => {
  assert.deepStrictEqual(C.confidenceFromSourceClass("observed"),
    { cls: "measured", tier: "high", basis: "observed", conditional: false });
});

test("confidenceFromSourceClass: a measurement token OVER a baseline token is conditional", () => {
  assert.deepStrictEqual(C.confidenceFromSourceClass("prior/observed"),
    { cls: "measured", tier: "high", basis: "prior/observed", conditional: true });
  assert.deepStrictEqual(C.confidenceFromSourceClass("live/prior"),
    { cls: "measured", tier: "high", basis: "live/prior", conditional: true });
});

test("confidenceFromSourceClass: forecast/derived/user/released classes", () => {
  assert.deepStrictEqual(C.confidenceFromSourceClass("forecast"),
    { cls: "predicted", tier: "low", basis: "forecast", conditional: false });
  assert.deepStrictEqual(C.confidenceFromSourceClass("derived"),
    { cls: "derived", tier: "medium", basis: "derived", conditional: false });
  assert.deepStrictEqual(C.confidenceFromSourceClass("user"),
    { cls: "authored", tier: "n/a", basis: "user", conditional: false });
  assert.deepStrictEqual(C.confidenceFromSourceClass("released"),
    { cls: "approved", tier: "high", basis: "released", conditional: false });
});

test("confidenceFromSourceClass: empty -> unknown (basis emptied); unknown token -> unknown (basis kept)", () => {
  assert.deepStrictEqual(C.confidenceFromSourceClass(""),
    { cls: "unknown", tier: "n/a", basis: "", conditional: false });
  assert.deepStrictEqual(C.confidenceFromSourceClass("foo"),
    { cls: "unknown", tier: "n/a", basis: "foo", conditional: false });
});

// --- confidenceBaseline: strip the live measurement, classify the remaining baseline ----------------
test("confidenceBaseline: prior/observed falls back to prior/reference; forecast/observed to forecast/predicted", () => {
  assert.deepStrictEqual(C.confidenceBaseline("prior/observed"),
    { cls: "reference", tier: "medium", basis: "prior", conditional: false });
  assert.deepStrictEqual(C.confidenceBaseline("forecast/observed"),
    { cls: "predicted", tier: "low", basis: "forecast", conditional: false });
});

test("confidenceBaseline: an observed-only layer has no baseline left -> unknown", () => {
  assert.deepStrictEqual(C.confidenceBaseline("observed"),
    { cls: "unknown", tier: "n/a", basis: "", conditional: false });
});

// --- groupCatalog: the ordered, grouped, row-shaped tree -------------------------------------------
const CATALOG = { layers: [
  { id: "base.dem", domain: "base", type: "raster", purpose: "elevation",
    source_class: "prior/observed", planning_eligible: true, release_execute_eligible: false },
  { id: "terrain.slope", domain: "terrain", type: "raster", purpose: "slope",
    source_class: "derived", planning_eligible: true, release_execute_eligible: true },
  { id: "physics.compaction", domain: "physics", type: "raster", purpose: "support",
    source_class: "observed" },
  { id: "runtime.foo", domain: "runtime", source_class: "live" },
  { id: "evidence.bar", domain: "evidence", source_class: "replay" },
  { id: "weird.thing", domain: "weird", source_class: "user" }
]};

test("groupCatalog: emits groups in GROUPS order, drops empty groups", () => {
  const tree = C.groupCatalog(CATALOG);
  assert.strictEqual(tree.length, 5);
  assert.deepStrictEqual(tree.map((g) => g.id), ["base", "terrain", "physics", "runtime", "weird"]);
  assert.strictEqual(tree[0].name, "Base");
  assert.strictEqual(tree[0].section, "1");
});

test("groupCatalog: a servable row carries kind/legendKey/provClass/confidence + eligibility", () => {
  const row = C.groupCatalog(CATALOG)[0].rows[0];
  assert.deepStrictEqual(row, {
    id: "base.dem", domain: "base", type: "raster", purpose: "elevation",
    sourceClass: "prior/observed", provClass: "observed",
    planningEligible: true, releaseEligible: false,
    confidence: { cls: "measured", tier: "high", basis: "prior/observed", conditional: true },
    servable: true, kind: "dem", legendKey: "dem", label: "dem"
  });
});

test("groupCatalog: a non-servable row (physics.compaction) is shown but carries no map layer", () => {
  const row = C.groupCatalog(CATALOG)[2].rows[0];
  assert.strictEqual(row.servable, false);
  assert.strictEqual(row.kind, null);
  assert.strictEqual(row.legendKey, null);
  assert.strictEqual(row.label, "compaction");
});

test("groupCatalog: runtime + evidence domains fold into one 'Evidence/Runtime' display group", () => {
  const tree = C.groupCatalog(CATALOG);
  const ev = tree[3];
  assert.strictEqual(ev.name, "Evidence/Runtime");
  assert.strictEqual(ev.section, "6");
  assert.deepStrictEqual(ev.rows.map((r) => r.id), ["runtime.foo", "evidence.bar"]);
});

test("groupCatalog: a domain with no GROUPS entry is appended as its own trailing group, never dropped", () => {
  const weird = C.groupCatalog(CATALOG)[4];
  assert.strictEqual(weird.id, "weird");
  assert.strictEqual(weird.name, "weird");
  assert.strictEqual(weird.section, "");
  assert.deepStrictEqual(weird.rows.map((r) => r.id), ["weird.thing"]);
});

test("groupCatalog: accepts a bare array identically to a {layers:[...]} payload", () => {
  assert.strictEqual(C.groupCatalog(CATALOG.layers).length, C.groupCatalog(CATALOG).length);
});

test("groupCatalog: null / empty payload -> empty tree (no fabricated rows)", () => {
  assert.strictEqual(C.groupCatalog(null).length, 0);
  assert.strictEqual(C.groupCatalog({}).length, 0);
});

test("groupCatalog: a backend-served `confidence` is preferred over the local derivation", () => {
  const tree = C.groupCatalog({ layers: [
    { id: "base.dem", domain: "base", source_class: "prior/observed",
      confidence: { cls: "served", tier: "x" } }
  ]});
  assert.strictEqual(tree[0].rows[0].confidence.cls, "served");
});

test("servableSummary: counts servable vs total across the grouped tree", () => {
  const tree = C.groupCatalog(CATALOG);
  assert.deepStrictEqual(C.servableSummary(tree), { total: 6, servable: 2, nonServable: 4 });
});

// --- sunQS: sun-parameterized drape query string ---------------------------------------------------
test("sunQS: explicit el/az/site/bust are threaded verbatim", () => {
  assert.strictEqual(C.sunQS({ sunEl: 20, sunAz: 120, site: "nobile", bust: 5 }),
    "sun_el=20&sun_az=120&site=nobile&b=5");
});

test("sunQS: a zero sun elevation is honoured (!= null, not falsy-defaulted)", () => {
  assert.strictEqual(C.sunQS({ sunEl: 0, bust: 1 }), "sun_el=0&sun_az=90&site=haworth&b=1");
});

test("sunQS: defaults el=15/az=90/site=haworth and URL-encodes the site", () => {
  assert.strictEqual(C.sunQS({ site: "a b", bust: 1 }), "sun_el=15&sun_az=90&site=a%20b&b=1");
});

// --- endpoint URL builders (pure) ------------------------------------------------------------------
test("URL builders: same-origin /api endpoints for catalog/legend/terramech", () => {
  assert.strictEqual(C.base(), "/api");
  assert.strictEqual(C.catalogUrl(), "/api/world/layer-catalog");
  assert.strictEqual(C.legendUrl(), "/api/layers/legend");
  assert.strictEqual(C.terramechUrl(), "/api/world/terramechanics-layers");
});

test("URL builders: site-scoped traffic + [REQ:GW-06] layer-manifest default to haworth and encode the site", () => {
  assert.strictEqual(C.trafficUrl(), "/api/world/traffic-layer?site=haworth");
  assert.strictEqual(C.trafficUrl("a b"), "/api/world/traffic-layer?site=a%20b");
  assert.strictEqual(C.layerManifestUrl("nobile"), "/api/world/layer-manifest?site=nobile");
});

test("URL builders: globe png + bbox carry the sun query string", () => {
  assert.strictEqual(C.globePngUrl("dem", { bust: 7 }),
    "/api/layers/globe/dem.png?sun_el=15&sun_az=90&site=haworth&b=7");
  assert.strictEqual(C.globeBboxUrl("slope", { bust: 2 }),
    "/api/layers/globe/slope/bbox?sun_el=15&sun_az=90&site=haworth&b=2");
});

test("setApiBase re-bases every endpoint URL (restored to /api after)", () => {
  try {
    C.setApiBase("https://h/api");
    assert.strictEqual(C.base(), "https://h/api");
    assert.strictEqual(C.catalogUrl(), "https://h/api/world/layer-catalog");
  } finally {
    C.setApiBase("/api");
  }
  assert.strictEqual(C.base(), "/api");
});

// --- imageLayerFor: the QWC2 `image` (ImageStatic) layer object ------------------------------------
test("imageLayerFor: a servable row + bbox -> a stable, reprojectable QWC2 image layer", () => {
  const row = C.groupCatalog(CATALOG)[0].rows[0];   // base.dem
  const layer = C.imageLayerFor(row, { west: -10, south: -20, east: 10, north: 20 }, { bust: 7 });
  assert.deepStrictEqual(layer, {
    id: "stewie-mission:base.dem",
    type: "image",
    name: "stewie:base.dem",
    title: "Base · Dem",
    url: "/api/layers/globe/dem.png?sun_el=15&sun_az=90&site=haworth&b=7",
    projection: "IAU_2015:30100",
    imageExtent: [-10, -20, 10, 20],
    stewie: {
      catalogId: "base.dem", domain: "base", kind: "dem",
      sourceClass: "prior/observed", provClass: "observed",
      planningEligible: true, releaseEligible: false, legendKey: "dem"
    }
  });
});

test("imageLayerFor: null for a non-servable row or a missing bbox (never fabricated)", () => {
  const servableRow = C.groupCatalog(CATALOG)[0].rows[0];
  const nonServableRow = C.groupCatalog(CATALOG)[2].rows[0];   // physics.compaction
  assert.strictEqual(C.imageLayerFor(nonServableRow, { west: 0, south: 0, east: 1, north: 1 }, {}), null);
  assert.strictEqual(C.imageLayerFor(servableRow, null, {}), null);
  assert.strictEqual(C.imageLayerFor(null, { west: 0, south: 0, east: 1, north: 1 }, {}), null);
});

test("imageLayerFor: a row whose domain isn't in GROUPS titles from the raw domain", () => {
  const row = { id: "x.y", domain: "nogroup", servable: true, kind: "dem", label: "y",
    sourceClass: "prior", provClass: "prior", planningEligible: false, releaseEligible: false,
    legendKey: "dem" };
  const layer = C.imageLayerFor(row, { west: 0, south: 0, east: 1, north: 1 }, { bust: 3 });
  assert.strictEqual(layer.id, "stewie-mission:x.y");
  assert.strictEqual(layer.title, "nogroup · Y");
});

// --- legendFor -------------------------------------------------------------------------------------
test("legendFor: returns the legend entry for a servable row's key, else null", () => {
  const row = C.groupCatalog(CATALOG)[0].rows[0];   // base.dem -> legendKey "dem"
  assert.deepStrictEqual(C.legendFor(row, { dem: { min: 0, max: 100 } }), { min: 0, max: 100 });
  assert.strictEqual(C.legendFor(row, {}), null);                                  // key absent
  assert.strictEqual(C.legendFor(C.groupCatalog(CATALOG)[2].rows[0], { dem: {} }), null);  // no legendKey
});

// --- freshnessFromManifest ([REQ:GW-06]) -----------------------------------------------------------
test("freshnessFromManifest: full manifest -> the projected freshness/provenance readout", () => {
  const f = C.freshnessFromManifest({ freshness: {
    observed: true, observed_fraction: 0.42, provenance_class: "observed",
    dem_source: "LOLA", twin_version: 3, as_built_version: 2, mutated: true } });
  assert.deepStrictEqual(f, {
    observed: true, observedFraction: 0.42, observedPct: 42, provClass: "observed",
    demSource: "LOLA", twinVersion: 3, asBuiltVersion: 2, mutated: true });
});

test("freshnessFromManifest: a sparse manifest fills honest defaults (null pct, prior class, zero versions)", () => {
  const f = C.freshnessFromManifest({ freshness: { observed: false } });
  assert.deepStrictEqual(f, {
    observed: false, observedFraction: null, observedPct: null, provClass: "prior",
    demSource: null, twinVersion: 0, asBuiltVersion: 0, mutated: false });
});

test("freshnessFromManifest: a positive fraction with no class implies 'observed' and rounds the pct", () => {
  const f = C.freshnessFromManifest({ freshness: { observed_fraction: 0.7 } });
  assert.strictEqual(f.provClass, "observed");
  assert.strictEqual(f.observedPct, 70);
  assert.strictEqual(C.freshnessFromManifest({ freshness: { observed_fraction: 0.126 } }).observedPct, 13);
});

test("freshnessFromManifest: absent manifest/freshness -> null (no claim, not fabricated)", () => {
  assert.strictEqual(C.freshnessFromManifest(null), null);
  assert.strictEqual(C.freshnessFromManifest({}), null);
});
