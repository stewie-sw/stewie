// FS-24 (node:test): the trainer-scorecard chip strips are pure (scorecard -> HTML string), so unit-
// testable without a browser. De-duplicates the former two inline copies. Behavior preserved.
// Run: node --test stewie/server/web/assets/scorecard_chips.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const S = require("./scorecard_chips.js");

const SC = {
  completed: true, objectives_total: 3, legs_delivered: 10, legs_total: 10, comm_delivered_frac: 0.9,
  makespan_s: 1200, optimal_s: 1000, makespan_ratio: 1.2, recharges: 1, replans: 0,
  stranded_packets: 0, dropped_packets: 0, energy_MJ: 4.3, energy_divergence_J: 500,
};

test("boardChips: renders the full A-board KPIs", () => {
  const h = S.boardChips(SC);
  assert.ok(h.includes("objectives") && h.includes("✓ 3"));
  assert.ok(h.includes("legs delivered") && h.includes("10/10"));
  assert.ok(h.includes("comm delivered") && h.includes("90%"));
  assert.ok(h.includes("makespan") && h.includes("1200 s") && h.includes("optimal") && h.includes("1000 s"));
  assert.ok(h.includes("dropped pkts"));                  // board has dropped pkts (quick strip does not)
  assert.ok(h.includes("4.3 MJ"));
});

test("boardChips: makespan/opt over 1.15 draws the red warn border; divergence too", () => {
  const h = S.boardChips(SC);                              // ratio 1.2 > 1.15
  assert.ok(h.includes("#c0392b"));                       // red border present (warn)
  assert.ok(h.includes("believed↔actual (truth)") && h.includes("500 J"));
});

test("boardChips: no divergence chip when energy_divergence_J is absent", () => {
  const noDiv = { ...SC, energy_divergence_J: undefined };
  assert.ok(!S.boardChips(noDiv).includes("believed↔actual"));
});

test("quickChips: shorter strip, no dropped-pkts, no red makespan border", () => {
  const h = S.quickChips(SC);
  assert.ok(h.includes("objectives") && h.includes("legs delivered") && h.includes("makespan/opt"));
  assert.ok(!h.includes("dropped pkts"));                 // quick strip omits dropped/makespan/optimal rows
  assert.ok(!h.includes("#c0392b"));                      // quick makespan/opt is not warn-bordered
  assert.ok(h.includes("⚠ divergence (truth)") && h.includes("500 J"));
});

test("chip: escapes nothing itself but warn toggles the border color", () => {
  assert.ok(S.chip("k", "v", true).includes("#c0392b"));
  assert.ok(S.chip("k", "v", false).includes("var(--line)"));
});
