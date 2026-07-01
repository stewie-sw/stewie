// FS-24 (node:test): the Terrain Memory readout is pure (payload -> HTML string), so unit-testable
// without a browser. The fetch + DOM write stay in cockpit.js. Behavior preserved.
// Run: node --test stewie/server/web/assets/terrain_memory_html.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const T = require("./terrain_memory_html.js");
const esc = require("./htmlesc.js").esc;

test("terrainMemoryHTML: renders the recorded change summary", () => {
  const t = { recorded: true, version: 2, chain_valid: true, cells_changed: 1234,
              net_volume_m3: 5.678, max_cut_m: 0.31, max_fill_m: 0.12, missions: ["pad-1", "berm-2"] };
  const h = T.terrainMemoryHTML(t, "haworth", esc);
  assert.ok(h.includes("haworth") && h.includes("v2") && h.includes("chain ✓"));
  assert.ok(h.includes("cells changed <b>1,234</b>"));
  assert.ok(h.includes("5.68 m³"));
  assert.ok(h.includes("31.0 cm") && h.includes("12.0 cm"));
  assert.ok(h.includes("pad-1, berm-2"));
});

test("terrainMemoryHTML: invalid chain shows the red chain-broken marker", () => {
  const h = T.terrainMemoryHTML({ recorded: true, version: 1, chain_valid: false, missions: [] }, "haworth", esc);
  assert.ok(h.includes("chain ✗") && h.includes("#e8273f"));
  assert.ok(h.includes("missions: —"));                    // no missions -> em-dash
});

test("terrainMemoryHTML: not-recorded shows the record prompt", () => {
  const h = T.terrainMemoryHTML({ recorded: false }, "nobile", esc);
  assert.ok(h.includes("No terrain changes recorded for <b>nobile</b>"));
});

test("unavailableHTML: renders the shared error line and escapes the detail", () => {
  assert.ok(T.unavailableHTML("HTTP 500", esc).includes("Terrain memory unavailable (HTTP 500)."));
  assert.ok(T.unavailableHTML("<x>", esc).includes("&lt;x&gt;"));
});

test("terrainMemoryHTML: escapes a hostile site name (SEC)", () => {
  const h = T.terrainMemoryHTML({ recorded: false }, "<img onerror=1>", esc);
  assert.ok(!h.includes("<img onerror") && h.includes("&lt;img"));
});
