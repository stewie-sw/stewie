// FS-21 (node:test): the NAMED-layout collection logic is PURE -> unit-testable without a browser. The DOM
// capture/apply glue + dropdown UI live in cockpit.js; this covers save / list / get / load-snapshot /
// rename / delete / setDefault and the view-only invariant (a layout carries order + collapsed only).
// Run: node --test stewie/server/web/assets/layouts.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const N = require("./layouts.js");

const SNAP = { order: ["site", "fleet", "plan"], collapsed: { site: false, fleet: true, plan: false } };
const EMPTY = { layouts: [], defaultName: null };

test("save adds a named layout; list returns its name; get restores the snapshot", () => {
  const { store, error } = N.save(EMPTY, "Survey", SNAP);
  assert.strictEqual(error, null);
  assert.deepStrictEqual(N.list(store), ["Survey"]);
  assert.deepStrictEqual(N.get(store, "Survey"), { name: "Survey", order: SNAP.order, collapsed: SNAP.collapsed });
});

test("save rejects a blank name", () => {
  const { store, error } = N.save(EMPTY, "   ", SNAP);
  assert.match(error, /needs a name/i);
  assert.deepStrictEqual(N.list(store), []);
});

test("save with an existing name (case-insensitive) OVERWRITES in place, keeps the slot + canonical name", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.save(s, "Plan A", SNAP).store;
  const snap2 = { order: ["fleet", "site", "plan"], collapsed: { fleet: false } };
  const r = N.save(s, "survey", snap2);                 // different case, same layout
  assert.strictEqual(r.error, null);
  assert.deepStrictEqual(N.list(r.store), ["Survey", "Plan A"]);   // no dupe, order preserved
  assert.deepStrictEqual(N.get(r.store, "Survey").order, snap2.order);
  assert.strictEqual(N.get(r.store, "Survey").name, "Survey");     // canonical name kept
});

test("get returns null for an unknown layout; get returns a COPY (mutating it does not corrupt the store)", () => {
  const s = N.save(EMPTY, "Survey", SNAP).store;
  assert.strictEqual(N.get(s, "nope"), null);
  const g = N.get(s, "Survey");
  g.order.push("hacked"); g.collapsed.site = true;
  assert.deepStrictEqual(N.get(s, "Survey").order, SNAP.order);     // store untouched
});

test("rename changes the name; old name gone, new name resolves the same snapshot", () => {
  const s = N.save(EMPTY, "Survey", SNAP).store;
  const { store, error } = N.rename(s, "Survey", "Recon");
  assert.strictEqual(error, null);
  assert.deepStrictEqual(N.list(store), ["Recon"]);
  assert.deepStrictEqual(N.get(store, "Recon").order, SNAP.order);
  assert.strictEqual(N.get(store, "Survey"), null);
});

test("rename rejects a collision with a different existing layout", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.save(s, "Recon", SNAP).store;
  const { store, error } = N.rename(s, "Survey", "Recon");
  assert.match(error, /already exists/i);
  assert.deepStrictEqual(N.list(store), ["Survey", "Recon"]);       // unchanged
});

test("rename to the SAME name (case change) is allowed", () => {
  const s = N.save(EMPTY, "Survey", SNAP).store;
  const { store, error } = N.rename(s, "Survey", "SURVEY");
  assert.strictEqual(error, null);
  assert.deepStrictEqual(N.list(store), ["SURVEY"]);
});

test("delete removes the layout", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.save(s, "Recon", SNAP).store;
  const { store, error } = N.remove(s, "survey");                   // case-insensitive
  assert.strictEqual(error, null);
  assert.deepStrictEqual(N.list(store), ["Recon"]);
});

test("delete of an unknown layout errors and leaves the store unchanged", () => {
  const s = N.save(EMPTY, "Survey", SNAP).store;
  const { store, error } = N.remove(s, "nope");
  assert.match(error, /no such layout/i);
  assert.deepStrictEqual(N.list(store), ["Survey"]);
});

test("setDefault marks a layout default; defaultName reports it", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.save(s, "Recon", SNAP).store;
  const { store, error } = N.setDefault(s, "Recon");
  assert.strictEqual(error, null);
  assert.strictEqual(N.defaultName(store), "Recon");
});

test("setDefault(null) clears the default", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.setDefault(s, "Survey").store;
  assert.strictEqual(N.defaultName(s), "Survey");
  const cleared = N.setDefault(s, null).store;
  assert.strictEqual(N.defaultName(cleared), null);
});

test("setDefault on an unknown layout errors and does not change the default", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.setDefault(s, "Survey").store;
  const { store, error } = N.setDefault(s, "ghost");
  assert.match(error, /no such layout/i);
  assert.strictEqual(N.defaultName(store), "Survey");
});

test("rename carries the default flag along with the renamed layout", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.setDefault(s, "Survey").store;
  const { store } = N.rename(s, "Survey", "Recon");
  assert.strictEqual(N.defaultName(store), "Recon");
});

test("deleting the default layout clears the default flag", () => {
  let s = N.save(EMPTY, "Survey", SNAP).store;
  s = N.setDefault(s, "Survey").store;
  const { store } = N.remove(s, "Survey");
  assert.strictEqual(N.defaultName(store), null);
});

test("normalize repairs a corrupt / legacy store into the empty store (boot never breaks)", () => {
  assert.deepStrictEqual(N.normalize(null), EMPTY);
  assert.deepStrictEqual(N.normalize("garbage"), EMPTY);
  assert.deepStrictEqual(N.normalize({ layouts: "nope" }), EMPTY);
  // a defaultName pointing at a missing layout is dropped
  assert.strictEqual(N.normalize({ layouts: [], defaultName: "ghost" }).defaultName, null);
});

test("normalize drops blank-named + case-insensitive duplicate entries", () => {
  const dirty = { layouts: [
    { name: "Survey", order: ["site"], collapsed: {} },
    { name: "survey", order: ["fleet"], collapsed: {} },   // dupe (case-insensitive) -> dropped
    { name: "  ", order: ["x"], collapsed: {} }             // blank -> dropped
  ], defaultName: null };
  assert.deepStrictEqual(N.list(N.normalize(dirty)), ["Survey"]);
});

test("VIEW-ONLY invariant: a saved layout carries ONLY order + collapsed (no role/contract/auth fields)", () => {
  // even if a caller smuggles extra keys into the snapshot, only order + collapsed survive into the store
  const sneaky = { order: ["site"], collapsed: { site: true }, role: "director", apiKey: "secret", auth: 1 };
  const s = N.save(EMPTY, "X", sneaky).store;
  const got = N.get(s, "X");
  assert.deepStrictEqual(Object.keys(got).sort(), ["collapsed", "name", "order"]);
  assert.strictEqual("role" in got, false);
  assert.strictEqual("apiKey" in got, false);
  assert.strictEqual("auth" in got, false);
});

test("collapsed values are coerced to booleans (a layout stores open/closed, nothing richer)", () => {
  const snap = { order: ["site"], collapsed: { site: 1, fleet: "" } };
  const s = N.save(EMPTY, "X", snap).store;
  assert.deepStrictEqual(N.get(s, "X").collapsed, { site: true, fleet: false });
});

test("all mutations are pure: they never mutate the input store", () => {
  const base = N.save(EMPTY, "Survey", SNAP).store;
  const frozen = JSON.parse(JSON.stringify(base));
  N.save(base, "Recon", SNAP);
  N.rename(base, "Survey", "Z");
  N.remove(base, "Survey");
  N.setDefault(base, "Survey");
  assert.deepStrictEqual(base, frozen);
});

test("KEY is the stable localStorage key the glue persists the collection under", () => {
  assert.strictEqual(N.KEY, "stewie_named_layouts");
});
