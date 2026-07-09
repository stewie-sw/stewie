// GW-02: the shared workspace-context store — one canonical site/body/mission the whole IDE reads,
// URL-hydratable, pub/sub so a site pick in one plugin propagates to every consumer. Replaces the
// per-module `|| "haworth"` literals scattered across catalogLayers/evidenceReport/selectionInspect/planAuthor.
const assert = require("node:assert");
const { test } = require("node:test");
const W = require("./workspace.js");

test("default workspace exposes ONE canonical site + body", () => {
  W.reset();
  assert.strictEqual(W.site(), "haworth");
  assert.strictEqual(W.get().body, "moon");
});

test("set() mutates + returns a copy (no external aliasing of internal state)", () => {
  W.reset();
  const a = W.set({ site: "shackleton_rim" });
  assert.strictEqual(W.site(), "shackleton_rim");
  a.site = "tampered";
  assert.strictEqual(W.site(), "shackleton_rim");   // the returned copy is not the live state
});

test("subscribe() fires on change, only on real change, and unsubscribes", () => {
  W.reset();
  let calls = 0, last = null;
  const unsub = W.subscribe((s) => { calls += 1; last = s.site; });
  W.set({ site: "nobile_rim" });
  assert.strictEqual(last, "nobile_rim");
  assert.strictEqual(calls, 1);
  W.set({ site: "nobile_rim" });                    // no-op: same value -> no notify
  assert.strictEqual(calls, 1);
  unsub();
  W.set({ site: "malapert_massif" });
  assert.strictEqual(calls, 1);                     // unsubscribed -> not called again
});

test("hydrateFromQuery() restores site/body/mission from a URL query string", () => {
  W.reset();
  W.hydrateFromQuery("?site=nobile_rim&body=moon&mission=demo-001");
  assert.strictEqual(W.site(), "nobile_rim");
  assert.strictEqual(W.get().mission, "demo-001");
});

test("toQuery() emits only NON-default keys so a clean URL stays clean", () => {
  W.reset();
  assert.strictEqual(W.toQuery(), "");
  W.set({ site: "malapert_massif" });
  assert.strictEqual(W.toQuery(), "site=malapert_massif");
});

test("GW-02 integration: catalogLayers builders read the SHARED workspace site (no baked-in literal)", () => {
  W.reset();
  const C = require("./catalogLayers.js");   // same singleton: catalogLayers require()s ./workspace.js
  W.set({ site: "shackleton_rim" });
  assert.strictEqual(C.trafficUrl(), "/api/world/traffic-layer?site=shackleton_rim");
  assert.match(C.sunQS({}), /site=shackleton_rim/);
  W.set({ site: "nobile_rim" });             // a second pick propagates without passing the site through
  assert.strictEqual(C.layerManifestUrl(), "/api/world/layer-manifest?site=nobile_rim");
  W.reset();                                 // restore the default so other tests see haworth
});

// task #77: the plot-event channel (3D terrain Shift+click -> Mission Plan order queue) is a SEPARATE
// pub/sub from set()/subscribe() -- it must never touch the whitelisted (site/body/mission/profile/source)
// state store.
test("emitPlot() delivers the point to onPlot() subscribers", () => {
  const seen = [];
  const unsub = W.onPlot((pt) => seen.push(pt));
  const point = { e_m: 12.5, n_m: -3.2, elev_m: 1840.1, lat: -89.1, lon: 42.0 };
  W.emitPlot(point);
  assert.strictEqual(seen.length, 1);
  assert.deepStrictEqual(seen[0], point);
  unsub();
});

test("onPlot() unsubscribe function stops further delivery", () => {
  let calls = 0;
  const unsub = W.onPlot(() => { calls += 1; });
  W.emitPlot({ e_m: 1, n_m: 1, elev_m: 1, lat: 1, lon: 1 });
  assert.strictEqual(calls, 1);
  unsub();
  W.emitPlot({ e_m: 2, n_m: 2, elev_m: 2, lat: 2, lon: 2 });
  assert.strictEqual(calls, 1);              // unsubscribed -> not called again
});

test("a throwing onPlot() subscriber does not break emitPlot() delivery to others", () => {
  let goodCalls = 0;
  const unsubBad = W.onPlot(() => { throw new Error("boom"); });
  const unsubGood = W.onPlot(() => { goodCalls += 1; });
  assert.doesNotThrow(() => W.emitPlot({ e_m: 0, n_m: 0, elev_m: 0, lat: 0, lon: 0 }));
  assert.strictEqual(goodCalls, 1);
  unsubBad(); unsubGood();
});

test("task #56: requestFloat() delivers the plugin id to onFloatRequest() subscribers", () => {
  const seen = [];
  const unsub = W.onFloatRequest((id) => seen.push(id));
  W.requestFloat("MissionTerrain3D");
  assert.deepStrictEqual(seen, ["MissionTerrain3D"]);
  unsub();
  W.requestFloat("MissionTerrain3D");
  assert.strictEqual(seen.length, 1, "unsubscribe stops further delivery");
});

test("task #56: a throwing onFloatRequest() subscriber does not break delivery to others", () => {
  let good = 0;
  const bad = W.onFloatRequest(() => { throw new Error("boom"); });
  const ok = W.onFloatRequest(() => { good += 1; });
  assert.doesNotThrow(() => W.requestFloat("MissionPlan"));
  assert.strictEqual(good, 1);
  bad(); ok();
});

// task #80: the route-event channel (the 3D measure tool's waypoints -> Mission Plan's Traverse authoring)
// is a SEPARATE pub/sub, same shape as emitPlot/onPlot and requestFloat/onFloatRequest.
test("task #80: emitRoute() delivers the points array to onRoute() subscribers", () => {
  const seen = [];
  const unsub = W.onRoute((pts) => seen.push(pts));
  const points = [
    {lx: 1, ly: 2, elev_m: 1840.1, lat: -89.1, lon: 42.0},
    {lx: 3, ly: 4, elev_m: 1841.7, lat: -89.2, lon: 42.3}
  ];
  W.emitRoute(points);
  assert.strictEqual(seen.length, 1);
  assert.deepStrictEqual(seen[0], points);
  unsub();
});

test("task #80: onRoute() unsubscribe function stops further delivery", () => {
  let calls = 0;
  const unsub = W.onRoute(() => { calls += 1; });
  W.emitRoute([{lx: 0, ly: 0, elev_m: 0, lat: 0, lon: 0}]);
  assert.strictEqual(calls, 1);
  unsub();
  W.emitRoute([{lx: 1, ly: 1, elev_m: 1, lat: 1, lon: 1}]);
  assert.strictEqual(calls, 1);              // unsubscribed -> not called again
});

test("task #80: a throwing onRoute() subscriber does not break emitRoute() delivery to others", () => {
  let goodCalls = 0;
  const unsubBad = W.onRoute(() => { throw new Error("boom"); });
  const unsubGood = W.onRoute(() => { goodCalls += 1; });
  assert.doesNotThrow(() => W.emitRoute([{lx: 0, ly: 0, elev_m: 0, lat: 0, lon: 0}]));
  assert.strictEqual(goodCalls, 1);
  unsubBad(); unsubGood();
});
