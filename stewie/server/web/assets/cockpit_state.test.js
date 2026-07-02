// Phase 2 / FS-16 (node:test): the cockpit state model is pure -> unit-testable without a browser.
// Run: node --test stewie/server/web/assets/cockpit_state.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const S = require("./cockpit_state.js");

test("defaultState carries the routeable keys", () => {
  const s = S.defaultState();
  ["mission", "site", "vehicle", "body", "timeS", "mode", "role", "workArea", "selectedEntity", "source"]
    .forEach((k) => assert.ok(k in s, k));
  assert.strictEqual(s.workArea, "plan");
  assert.strictEqual(s.source, "sim");
});

test("setState applies a patch and enforces enums", () => {
  const s = S.setState(S.defaultState(), { workArea: "fleet", source: "live", mode: "sandbox" });
  assert.strictEqual(s.workArea, "fleet");
  assert.strictEqual(s.source, "live");
  assert.throws(() => S.setState(s, { workArea: "nope" }));   // unknown work area rejected
  assert.throws(() => S.setState(s, { source: "fake" }));     // unknown source rejected
});

test("toHash/fromHash round-trip the routeable state (a link restores the view)", () => {
  const s = S.setState(S.defaultState(), { workArea: "navigation", site: "haworth", source: "eval" });
  const back = S.fromHash("#" + S.toHash(s));
  assert.strictEqual(back.workArea, "navigation");
  assert.strictEqual(back.site, "haworth");
  assert.strictEqual(back.source, "eval");
});

test("fromHash ignores junk and keeps defaults", () => {
  const s = S.fromHash("#garbage&workArea=report&=bad");
  assert.strictEqual(s.workArea, "report");
  assert.strictEqual(s.body, "moon");        // default preserved
});

test("PO-10: the state model enumerates the four provenance classes, distinctly", () => {
  assert.strictEqual(S.PROVENANCE.length, 4, "not a four-way provenance distinction");
  const kinds = S.provenanceKinds();
  const labels = S.PROVENANCE.map((p) => p.label);
  assert.deepStrictEqual([...new Set(kinds)].sort(), ["belief", "forecast", "live", "truth"]);
  assert.strictEqual(new Set(labels).size, 4, "provenance human labels are not distinct");
  // forecast / sim-truth / estimator-belief / live-telemetry are all named
  ["forecast", "sim-truth", "estimator-belief", "live-telemetry"].forEach((l) =>
    assert.ok(labels.includes(l), l));
});
