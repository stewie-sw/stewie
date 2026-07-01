// FS-24 (node:test): the Report-pane world-state + terrain-provenance HTML builders are pure (payload +
// esc -> string | null), so unit-testable without a browser. The fetch + DOM write stay in cockpit.js.
// Run: node --test stewie/server/web/assets/world_state_html.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const W = require("./world_state_html.js");
const esc = require("./htmlesc.js").esc;

const LATEST = {
  committed: true, count: 5,
  transaction: { authority_sha: "c5110549cc9cabcdef", twin_version: 0, plan_id: "loop demo",
                 world_sha: "fb13bf97fbef0011", seq: 4 },
};
const TXNS = [
  { seq: 0, provenance: "SIM run: released plan loop demo" },
  { seq: 1, provenance: "SIM leg: sim leg 0: continue [ok]" },
  { seq: 3, provenance: "SIM as-built: loop demo" },
];

test("worldStateHTML: renders authority/plan/seq + the execution timeline in order", () => {
  const h = W.worldStateHTML(LATEST, TXNS, esc);
  assert.ok(h.includes("LINKED WORLD STATE — DT-01"));
  assert.ok(h.indexOf("LINKED WORLD STATE") < h.indexOf("EXECUTION TIMELINE"));
  assert.ok(h.includes("c5110549cc9c…"));                 // short authority sha
  assert.ok(h.includes("loop demo") && h.includes("5 transaction(s)"));
  assert.ok(h.includes("#0") && h.includes("SIM as-built: loop demo"));
  assert.ok(h.includes("var(--accent)"));                 // the [ok] leg is accent-colored
});

test("worldStateHTML: returns null when nothing is committed (no fabricated state)", () => {
  assert.strictEqual(W.worldStateHTML({ committed: false }, [], esc), null);
  assert.strictEqual(W.worldStateHTML(null, [], esc), null);
});

test("worldStateHTML: empty timeline shows the honest no-transitions line", () => {
  const h = W.worldStateHTML(LATEST, [], esc);
  assert.ok(h.includes("No transitions recorded yet."));
});

test("worldStateHTML: escapes a hostile provenance string (SEC)", () => {
  const h = W.worldStateHTML(LATEST, [{ seq: 9, provenance: "<img src=x onerror=alert(1)>" }], esc);
  assert.ok(!h.includes("<img src=x"));
  assert.ok(h.includes("&lt;img src=x"));
});

test("terrainProvenanceHTML: renders the three provenance classes + the raster img", () => {
  const tv = { ok: true, provenance: {
    rows: 2000, cols: 2000, cells: { observed: 0, as_built: 4, pristine: 3999996 },
    as_built_version: 1, twin_version: 0, observed_fraction: 0.0 } };
  const h = W.terrainProvenanceHTML(tv, esc, "/world/terrain_view.png?max_px=360&_=123");
  assert.ok(h.includes("observed (measured) 0"));
  assert.ok(h.includes("as-built (remembered) 4"));
  assert.ok(h.includes("pristine (modeled) 3999996"));
  assert.ok(h.includes('src="/world/terrain_view.png?max_px=360&_=123"'));
  assert.ok(h.includes("as-built v1"));
});

test("terrainProvenanceHTML: returns null when the view is absent (site DEM missing)", () => {
  assert.strictEqual(W.terrainProvenanceHTML({ ok: false }, esc, "x"), null);
  assert.strictEqual(W.terrainProvenanceHTML(null, esc, "x"), null);
});
