// FS-24 (node:test): the release-evidence HTML builders are pure (payload -> innerHTML string) and so
// unit-testable without a browser. The DOM write stays in cockpit.js; behaviour is preserved.
// Run: node --test stewie/server/web/assets/evidence_html.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const E = require("./evidence_html.js");
const esc = require("./htmlesc.js").esc;

test("evidenceHTML: renders the three sections in order with the system columns", () => {
  const d = {
    capability_matrix: { "Navigation": { scope: "global", motion: "articulated" } },
    accuracy_precision: { "Navigation": { accuracy_m: 1.2, precision_m: 0.3, frame: "DEM", source: "this work" }, _note: "regimes differ" },
    modality_sigma: { range_m: 10, articulation_parallax_sigma_m: 0.05, stereo_sigma_m: 0.2, articulation_advantage_x: 4 },
  };
  const h = E.evidenceHTML(d, esc);
  assert.ok(h.indexOf("GENERALIZATION — capability matrix") < h.indexOf("COMPARISON"));
  assert.ok(h.indexOf("COMPARISON") < h.indexOf("PHOTOMETRIC + DEPTH"));
  assert.ok(h.includes("Navigation"));
  assert.ok(h.includes("regimes differ"));            // the _note
  assert.ok(h.includes("4×"));                         // articulation advantage
});

test("evidenceHTML: missing values render as the em-dash placeholder, no crash on empty payload", () => {
  const h = E.evidenceHTML({}, esc);
  assert.ok(h.includes("—"));
  assert.ok(h.includes("range precision @ — m"));
});

test("evidenceHTML: escapes a hostile source string (SEC-04)", () => {
  const d = { accuracy_precision: { "Navigation": { source: "<img onerror=x>" } } };
  const h = E.evidenceHTML(d, esc);
  assert.ok(!h.includes("<img onerror=x>"));
  assert.ok(h.includes("&lt;img"));
});

test("gateEvidenceHTML: G1/G2 + frozen byte-identical + next gate", () => {
  const j = { g1: "PASS ✓", g2: "PASS ✓", byte_identical_to_frozen: true, latest_artifact: "run_42",
    evidence: { evidence_mode: "real", g1_contract_checks_pass: 8, g1_contract_checks_total: 8,
      g1_ate_m: 3.35, g1_eval_track_m: 92.48, g1_baseline_raw_m: 12, g1_baseline_aligned_m: 9,
      g2_sigma_px: 0.6, g2_coverage_3sigma: 0.997, g2_median_depth_m: 4.1, g2_sigma_depth_m: 0.03,
      g2_evidence_scope: "held-out", next_gate: "G3" } };
  const h = E.gateEvidenceHTML(j);
  assert.ok(h.includes("3.35 m"));
  assert.ok(h.includes("byte-identical ✓"));
  assert.ok(h.includes("run_42"));
  assert.ok(h.includes("G3"));
});

test("gateEvidenceHTML: diverged frozen baseline shows the failure span", () => {
  const j = { g1: "x", g2: "y", byte_identical_to_frozen: false, latest_artifact: "r", evidence: {} };
  const h = E.gateEvidenceHTML(j);
  assert.ok(h.includes("DIVERGED ✗"));
});

test("gateEvidenceHTML: null numerics fall back to the em-dash", () => {
  const j = { g1: "x", g2: "y", byte_identical_to_frozen: true, latest_artifact: "r",
    evidence: { g1_ate_m: null, g2_sigma_px: null } };
  const h = E.gateEvidenceHTML(j);
  assert.ok(h.includes("—"));
});
