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
