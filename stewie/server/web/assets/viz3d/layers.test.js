// node --test for the viz3d layer stack model (pure, no browser). Covers: add/remove/reorder determinism,
// opacity clamp, zOrder stable sort, visibleOrdered filtering, toJSON/fromJSON round-trip, and that every
// catalog kind with available:true has a real sourceUrl matching the backend route shape (available:false
// kinds carry no fabricated source). A "fake" layer object is a legitimate unit-test boundary here.
// Run: node --test stewie/server/web/assets/viz3d/layers.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const L = require("./layers.js");

// ---- helpers -----------------------------------------------------------------------------------------
function drape(id, z) {
  return { id: id, kind: id, label: id.toUpperCase(), opacity: 1, zOrder: z,
    sourceUrl: "/dem/heightfield_full/layer.png?site=haworth&window_m=-1&x0=0&y0=0&kind=" + id };
}

// ---- add / remove ------------------------------------------------------------------------------------
test("add: requires an id and a kind", () => {
  const s = L.makeLayerStack();
  assert.throws(() => s.add({ kind: "slope" }), /requires an id/);
  assert.throws(() => s.add({ id: "x" }), /requires a kind/);
});

test("add: rejects a duplicate id", () => {
  const s = L.makeLayerStack();
  s.add(drape("slope", 0));
  assert.throws(() => s.add(drape("slope", 1)), /duplicate layer id/);
  assert.strictEqual(s.size(), 1);
});

test("add: auto-assigns a contiguous zOrder when omitted (0,1,2,...)", () => {
  const s = L.makeLayerStack();
  const a = s.add({ id: "a", kind: "a" });
  const b = s.add({ id: "b", kind: "b" });
  const c = s.add({ id: "c", kind: "c" });
  assert.deepStrictEqual([a.zOrder, b.zOrder, c.zOrder], [0, 1, 2]);
});

test("remove: drops by id, returns false for an unknown id", () => {
  const s = L.makeLayerStack([drape("a", 0), drape("b", 1)]);
  assert.strictEqual(s.remove("a"), true);
  assert.strictEqual(s.size(), 1);
  assert.strictEqual(s.remove("nope"), false);
  assert.strictEqual(s.get("a"), null);
  assert.strictEqual(s.get("b").id, "b");
});

// ---- opacity clamp -----------------------------------------------------------------------------------
test("setOpacity: clamps to [0,1]", () => {
  const s = L.makeLayerStack([drape("a", 0)]);
  s.setOpacity("a", 2.5); assert.strictEqual(s.get("a").opacity, 1);
  s.setOpacity("a", -3); assert.strictEqual(s.get("a").opacity, 0);
  s.setOpacity("a", 0.42); assert.strictEqual(s.get("a").opacity, 0.42);
});

test("setOpacity: rejects a non-finite value (leaves the prior value)", () => {
  const s = L.makeLayerStack([drape("a", 0)]);
  s.setOpacity("a", 0.5);
  assert.strictEqual(s.setOpacity("a", NaN), false);
  assert.strictEqual(s.setOpacity("a", Infinity), false);
  assert.strictEqual(s.get("a").opacity, 0.5);         // unchanged
  assert.strictEqual(s.setOpacity("missing", 0.5), false);
});

test("add: opacity is clamped on construction too", () => {
  const s = L.makeLayerStack();
  assert.strictEqual(s.add({ id: "a", kind: "a", opacity: 5 }).opacity, 1);
  assert.strictEqual(s.add({ id: "b", kind: "b", opacity: -1 }).opacity, 0);
  assert.strictEqual(s.add({ id: "c", kind: "c", opacity: NaN }).opacity, 1);   // NaN -> default 1
});

test("clampOpacity: exported pure helper", () => {
  assert.strictEqual(L.clampOpacity(1.7), 1);
  assert.strictEqual(L.clampOpacity(-0.2), 0);
  assert.strictEqual(L.clampOpacity(0.3), 0.3);
  assert.strictEqual(L.clampOpacity(NaN), null);
});

// ---- zOrder sort + stability -------------------------------------------------------------------------
test("ordered: sorts ascending by zOrder", () => {
  const s = L.makeLayerStack([drape("hi", 5), drape("lo", 1), drape("mid", 3)]);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["lo", "mid", "hi"]);
});

test("ordered: stable on equal zOrder (insertion order breaks ties)", () => {
  const s = L.makeLayerStack();
  s.add(drape("first", 2));
  s.add(drape("second", 2));
  s.add(drape("third", 2));
  s.add(drape("under", 0));
  // all three z=2 keep insertion order behind the z=0 layer
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["under", "first", "second", "third"]);
});

test("setZOrder: re-sorts; rejects non-finite / unknown", () => {
  const s = L.makeLayerStack([drape("a", 0), drape("b", 1)]);
  assert.strictEqual(s.setZOrder("a", 10), true);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["b", "a"]);
  assert.strictEqual(s.setZOrder("a", NaN), false);
  assert.strictEqual(s.setZOrder("ghost", 1), false);
});

// ---- move --------------------------------------------------------------------------------------------
test("move: up/down swaps neighbours and renumbers to 0..n-1", () => {
  const s = L.makeLayerStack([drape("a", 0), drape("b", 1), drape("c", 2)]);
  assert.strictEqual(s.move("b", "up"), true);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["a", "c", "b"]);
  assert.deepStrictEqual(s.ordered().map((l) => l.zOrder), [0, 1, 2]);
  assert.strictEqual(s.move("b", "down"), true);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["a", "b", "c"]);
});

test("move: boundary is a no-op (returns false), order unchanged", () => {
  const s = L.makeLayerStack([drape("a", 0), drape("b", 1), drape("c", 2)]);
  assert.strictEqual(s.move("a", "down"), false);
  assert.strictEqual(s.move("c", "up"), false);
  assert.strictEqual(s.move("ghost", "up"), false);
  assert.strictEqual(s.move("a", "sideways"), false);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["a", "b", "c"]);
});

test("move: deterministic even when zOrders collide (renumber resolves it)", () => {
  const s = L.makeLayerStack();
  s.add(drape("a", 4));
  s.add(drape("b", 4));
  s.add(drape("c", 4));                 // all equal -> ordered() = insertion order a,b,c
  assert.strictEqual(s.move("a", "up"), true);
  assert.deepStrictEqual(s.ordered().map((l) => l.id), ["b", "a", "c"]);
  assert.deepStrictEqual(s.ordered().map((l) => l.zOrder), [0, 1, 2]);
});

// ---- visibleOrdered ----------------------------------------------------------------------------------
test("visibleOrdered: filters hidden, keeps draw order", () => {
  const s = L.makeLayerStack([drape("a", 0), drape("b", 1), drape("c", 2)]);
  s.setVisible("b", false);
  assert.deepStrictEqual(s.visibleOrdered().map((l) => l.id), ["a", "c"]);
  assert.strictEqual(s.setVisible("ghost", true), false);
  s.setVisible("b", true);
  assert.deepStrictEqual(s.visibleOrdered().map((l) => l.id), ["a", "b", "c"]);
});

// ---- toJSON / fromJSON round-trip --------------------------------------------------------------------
test("toJSON/fromJSON: round-trips exactly (ordering + legend + fields)", () => {
  const s1 = L.makeLayerStack();
  s1.add(L.layerFromCatalog("elevation", { site: "haworth", window_m: -1, x0: 0, y0: 0 }));
  s1.add(L.layerFromCatalog("slope", { site: "haworth", window_m: 640, x0: 100, y0: 200 }));
  s1.add(L.layerFromCatalog("illumination", { site: "haworth" }));
  s1.setOpacity("slope", 0.6);
  s1.setVisible("illumination", false);
  s1.move("slope", "up");
  const snap = s1.toJSON();
  const s2 = L.makeLayerStack().fromJSON(snap);
  assert.deepStrictEqual(s2.toJSON(), snap);
  assert.deepStrictEqual(s2.ordered().map((l) => l.id), s1.ordered().map((l) => l.id));
});

test("toJSON: is a deep copy (mutating the snapshot's legend does not touch the stack)", () => {
  const s = L.makeLayerStack();
  s.add(L.layerFromCatalog("slope", { site: "haworth" }));
  const snap = s.toJSON();
  snap[0].legend.max = 999;
  snap[0].opacity = 0;
  assert.strictEqual(s.get("slope").legend.max, 30);   // untouched
  assert.strictEqual(s.get("slope").opacity, 1);
});

test("fromJSON: accepts { layers: [...] } as well as a bare array", () => {
  const s1 = L.makeLayerStack([drape("a", 0), drape("b", 1)]);
  const s2 = L.makeLayerStack().fromJSON({ layers: s1.toJSON() });
  assert.deepStrictEqual(s2.ordered().map((l) => l.id), ["a", "b"]);
});

// ---- catalog: available:true kinds have a real sourceUrl matching the backend route shape -------------
test("catalog: includes the design section 7-C kinds", () => {
  const kinds = L.LAYER_CATALOG.map((e) => e.kind);
  for (const k of ["elevation", "hillshade", "slope", "aspect", "roughness", "cost", "illumination"]) {
    assert.ok(kinds.includes(k), "catalog missing kind " + k);
  }
});

test("catalog: every available:true entry builds a REAL sourceUrl of the right route shape", () => {
  for (const e of L.LAYER_CATALOG) {
    if (!e.available) { continue; }
    assert.strictEqual(typeof e.sourceUrl, "function", e.kind + " should have a sourceUrl builder");
    const url = e.sourceUrl("haworth", 640, 100, 200);
    if (e.render === "base") {
      // elevation: the native heightfield binary, NOT a layer.png drape
      assert.ok(url.startsWith("/dem/heightfield_full?"), e.kind + " base url: " + url);
      assert.ok(!url.includes("layer.png"), e.kind + " must not be a layer.png drape");
      assert.ok(!url.includes("kind="), e.kind + " base url carries no kind");
    } else {
      assert.ok(url.startsWith("/dem/heightfield_full/layer.png?"), e.kind + " drape url: " + url);
      assert.ok(url.includes("kind=" + e.kind), e.kind + " drape url must carry its kind");
    }
    // the window params the backend route requires are all present
    assert.ok(url.includes("site=haworth"), e.kind + " url missing site");
    assert.ok(url.includes("window_m=640"), e.kind + " url missing window_m");
    assert.ok(url.includes("x0=100") && url.includes("y0=200"), e.kind + " url missing x0/y0");
  }
});

test("catalog: available:false entries carry NO fabricated source", () => {
  const unavailable = L.LAYER_CATALOG.filter((e) => !e.available);
  assert.ok(unavailable.length >= 1, "expected at least one available:false kind (traffic)");
  for (const e of unavailable) {
    assert.strictEqual(e.sourceUrl, null, e.kind + " unavailable -> sourceUrl must be null");
    assert.ok(typeof e.note === "string" && e.note.length > 0, e.kind + " unavailable needs a why-note");
  }
});

test("catalog: legends carry only backend-defined ranges (slope 0..30, aspect 0..360; others null)", () => {
  assert.deepStrictEqual([L.catalogEntry("slope").legend.min, L.catalogEntry("slope").legend.max], [0, 30]);
  assert.deepStrictEqual([L.catalogEntry("aspect").legend.min, L.catalogEntry("aspect").legend.max], [0, 360]);
  // percentile-stretched / binary / per-tile kinds have no fabricated fixed range
  for (const k of ["roughness", "cost", "illumination", "hillshade", "elevation"]) {
    assert.strictEqual(L.catalogEntry(k).legend.min, null, k + " min must be null (no fabricated range)");
    assert.strictEqual(L.catalogEntry(k).legend.max, null, k + " max must be null (no fabricated range)");
  }
});

// ---- layerFromCatalog --------------------------------------------------------------------------------
test("layerFromCatalog: builds a LayerModel; returns null for unknown or unavailable kinds", () => {
  const slope = L.layerFromCatalog("slope", { site: "haworth", window_m: 640, x0: 1, y0: 2 });
  assert.strictEqual(slope.id, "slope");
  assert.strictEqual(slope.render, "drape");
  assert.ok(slope.sourceUrl.includes("kind=slope"));
  const elev = L.layerFromCatalog("elevation", {});
  assert.strictEqual(elev.render, "base");
  assert.ok(elev.sunDependent === false);
  assert.strictEqual(L.layerFromCatalog("traffic", {}), null);   // available:false
  assert.strictEqual(L.layerFromCatalog("bogus", {}), null);     // unknown
});

test("layerFromCatalog: sun-dependent flag matches the backend (hillshade/illumination/cost true; slope false)", () => {
  assert.strictEqual(L.layerFromCatalog("hillshade", {}).sunDependent, true);
  assert.strictEqual(L.layerFromCatalog("illumination", {}).sunDependent, true);
  assert.strictEqual(L.layerFromCatalog("cost", {}).sunDependent, true);
  assert.strictEqual(L.layerFromCatalog("slope", {}).sunDependent, false);
  assert.strictEqual(L.layerFromCatalog("aspect", {}).sunDependent, false);
});
