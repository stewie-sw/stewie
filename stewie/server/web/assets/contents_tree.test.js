// GIS S-2 (node:test): the Contents tree is a PURE render module -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/contents_tree.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const T = require("./contents_tree.js");

// keepout labeller mirrors keepout_geom.koLabel's shape (disc/box/poly).
function koLabel(k) {
  if (Array.isArray(k.vertices)) return "polygon (" + k.vertices.length + " pts)";
  if (k.x0 !== undefined) return "box";
  return "circle @ " + k.x + "," + k.y + " · r " + k.r + " m";
}

function baseState(overrides) {
  return Object.assign({
    layerOn: { imagery: true, dem: true, slope: false, hazard: true, excavation: true, lander: true,
               illumination: false, psr: false },
    orders: [],
    keepouts: [],
    selectedOrder: -1,
    markers: { lander: { present: true, x: 0, y: 0 }, charger: { present: true, x: 0, y: 0 } },
    koLabel,
  }, overrides || {});
}

// ---- buildTree: structure ----
test("buildTree: groups come back in canonical order, empty groups dropped", () => {
  const tree = T.buildTree(baseState());
  const ids = tree.map((g) => g.id);
  // Basemap/Terrain/Operations have rows; Sun is empty (illumination/psr off but PRESENT in layerOn -> rows
  // are PRESENT regardless of on/off, only dropped if the layer id is absent). Confirm canonical ordering.
  assert.deepStrictEqual(ids, ["basemap", "terrain", "sun", "safety", "operations"]);
});

test("buildTree: only layers the cockpit serves become rows (absent ids skipped)", () => {
  const st = baseState({ layerOn: { imagery: true, dem: true } });   // no sun/hazard/excavation ids
  const tree = T.buildTree(st);
  const ids = tree.map((g) => g.id);
  assert.ok(ids.includes("basemap"));
  assert.ok(ids.includes("terrain"));
  assert.ok(!ids.includes("sun"), "Sun group dropped when no sun layer ids present");
  // operations still has markers (lander present in markers, but lander LAYER id absent -> marker row uses
  // visible=lander flag which is absent -> visible=false, still a row)
});

// ---- buildTree: orders as a feature layer ----
test("buildTree: each queued order becomes a selectable Operations feature row with zoom+remove+shape", () => {
  const st = baseState({
    orders: [
      { kind: "cut", action: "Level pad", x: 10, y: 5, footprint_m2: 36, depth_m: 0.04,
        shape: { kind: "rectangle", w: 15, h: 2, theta_deg: 30 } },
      { kind: "goto", action: "Traverse", x: 20, y: 0 },
    ],
    selectedOrder: 0,
  });
  const tree = T.buildTree(st);
  const ops = tree.find((g) => g.id === "operations");
  const orderRows = ops.rows.filter((r) => r.kind === "order");
  assert.strictEqual(orderRows.length, 2, "two order feature rows");
  assert.strictEqual(orderRows[0].ref, 0);
  assert.ok(orderRows[0].label.includes("Level pad"), "order label carries its action");
  assert.ok(orderRows[0].label.includes("10"), "order label carries its x");
  assert.strictEqual(orderRows[0].badge, "rect 15×2 @30°", "order badge is the typed shape");
  assert.strictEqual(orderRows[0].canZoom, true);
  assert.strictEqual(orderRows[0].canRemove, true);
  assert.strictEqual(orderRows[0].selected, true, "selectedOrder=0 highlights row 0");
  assert.strictEqual(orderRows[1].selected, false);
  assert.strictEqual(orderRows[1].badge, "goto");
});

test("buildTree: order rows track LAYER_ON.excavation for visibility", () => {
  const on = T.buildTree(baseState({ orders: [{ kind: "cut", action: "A", x: 0, y: 0 }] }));
  assert.strictEqual(on.find((g) => g.id === "operations").rows.find((r) => r.kind === "order").visible, true);
  const off = T.buildTree(baseState({
    layerOn: { imagery: true, excavation: false, lander: true, hazard: true },
    orders: [{ kind: "cut", action: "A", x: 0, y: 0 }],
  }));
  assert.strictEqual(off.find((g) => g.id === "operations").rows.find((r) => r.kind === "order").visible, false);
});

// ---- buildTree: keep-outs as Safety feature rows ----
test("buildTree: each keep-out is a removable Safety feature row labelled via koLabel", () => {
  const st = baseState({
    keepouts: [{ x: 25, y: 0, r: 8 }, { vertices: [[0, 0], [1, 0], [1, 1]] }],
  });
  const tree = T.buildTree(st);
  const safety = tree.find((g) => g.id === "safety");
  const koRows = safety.rows.filter((r) => r.kind === "keepout");
  assert.strictEqual(koRows.length, 2);
  assert.ok(koRows[0].label.includes("circle @ 25,0 · r 8 m"));
  assert.ok(koRows[1].label.includes("polygon (3 pts)"));
  assert.strictEqual(koRows[0].canRemove, true);
  assert.strictEqual(koRows[0].ref, 0);
  // the hazard raster row precedes the keep-out features in the Safety group
  assert.strictEqual(safety.rows[0].kind, "layer");
  assert.strictEqual(safety.rows[0].ref, "hazard");
});

// ---- buildTree: markers ----
test("buildTree: lander + charger markers are Operations rows; charger has no visibility toggle", () => {
  const tree = T.buildTree(baseState());
  const ops = tree.find((g) => g.id === "operations");
  const lander = ops.rows.find((r) => r.id === "marker:lander");
  const charger = ops.rows.find((r) => r.id === "marker:charger");
  assert.ok(lander, "lander marker row present");
  assert.strictEqual(lander.visible, true, "lander visibility tracks LAYER_ON.lander");
  assert.ok(charger, "charger marker row present");
  assert.strictEqual(charger.visible, null, "charger row has no visibility toggle");
});

// ---- stepper coherence ----
test("buildTree: groups carry the stepper section (Site=1 terrain/sun/basemap, Orders=5 safety/operations)", () => {
  const tree = T.buildTree(baseState({ keepouts: [{ x: 1, y: 1, r: 2 }], orders: [{ kind: "cut", action: "A", x: 0, y: 0 }] }));
  const sec = {};
  tree.forEach((g) => { sec[g.id] = g.section; });
  assert.strictEqual(sec.basemap, "1");
  assert.strictEqual(sec.terrain, "1");
  assert.strictEqual(sec.sun, "1");
  assert.strictEqual(sec.safety, "5");
  assert.strictEqual(sec.operations, "5");
});

// ---- renderTree: DOM (jsdom-free minimal document stub) ----
function fakeDoc() {
  function mk(tag) {
    const node = {
      tag, children: [], attrs: {}, style: { cssText: "" }, className: "",
      checked: false, title: "", type: "", onclick: null, onchange: null, firstChild: null,
      appendChild(c) { this.children.push(c); this.firstChild = this.children[0]; return c; },
      removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1);
        this.firstChild = this.children[0] || null; return c; },
      setAttribute(k, v) { this.attrs[k] = v; },
      get textContent() { return this.children.map((c) => c._text != null ? c._text : (c.textContent || "")).join(""); },
    };
    return node;
  }
  return {
    createElement: (t) => mk(t),
    createTextNode: (s) => ({ _text: String(s), textContent: String(s) }),
  };
}

test("renderTree: builds a details per group and a row per feature; checkbox + zoom + remove wired", () => {
  const doc = fakeDoc();
  const container = doc.createElement("div");
  const st = baseState({
    orders: [{ kind: "cut", action: "Level pad", x: 10, y: 5, shape: { kind: "rectangle", w: 15, h: 2 } }],
    keepouts: [{ x: 25, y: 0, r: 8 }],
  });
  const tree = T.buildTree(st);
  const events = [];
  const n = T.renderTree(container, tree, doc, {
    onToggle: (row, checked) => events.push(["toggle", row.id, checked]),
    onZoom: (row) => events.push(["zoom", row.id]),
    onRemove: (row) => events.push(["remove", row.id]),
    onSelect: (row) => events.push(["select", row.id]),
  });
  assert.ok(n > 0, "rows rendered");
  // one <details> per non-empty group
  const groups = container.children.filter((c) => c.tag === "details");
  assert.strictEqual(groups.length, tree.length);

  // find the order row across all groups; exercise its checkbox/zoom/remove/select
  let orderRow = null;
  groups.forEach((g) => g.children.forEach((c) => { if (c.attrs && c.attrs["data-row"] === "order:0") orderRow = c; }));
  assert.ok(orderRow, "order:0 row in DOM");
  const cb = orderRow.children.find((c) => c.tag === "input");
  assert.ok(cb && cb.type === "checkbox", "order row has a visibility checkbox");
  cb.checked = false; cb.onchange();
  const lab = orderRow.children.find((c) => c.className === "ct-label");
  lab.onclick();
  const zoom = orderRow.children.find((c) => c.className === "ct-zoom");
  zoom.onclick();
  const rm = orderRow.children.find((c) => c.className === "ct-remove");
  rm.onclick();

  assert.deepStrictEqual(events, [
    ["toggle", "order:0", false],
    ["select", "order:0"],
    ["zoom", "order:0"],
    ["remove", "order:0"],
  ]);
});

test("renderTree: charger marker row renders a spacer (no checkbox) since visible=null", () => {
  const doc = fakeDoc();
  const container = doc.createElement("div");
  const tree = T.buildTree(baseState());
  T.renderTree(container, tree, doc, {});
  let chargerRow = null;
  container.children.forEach((g) => g.children.forEach((c) => {
    if (c.attrs && c.attrs["data-row"] === "marker:charger") chargerRow = c; }));
  assert.ok(chargerRow, "charger row present");
  const cb = chargerRow.children.find((c) => c.tag === "input");
  assert.ok(!cb, "charger row has NO checkbox (visible=null)");
});

test("renderTree: empty tree shows an honest empty state", () => {
  const doc = fakeDoc();
  const container = doc.createElement("div");
  const n = T.renderTree(container, [], doc, {});
  assert.strictEqual(n, 0);
  assert.ok(container.children.some((c) => c.className === "empty"), "empty-state node present");
});
