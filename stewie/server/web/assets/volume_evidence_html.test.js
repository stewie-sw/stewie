// [REQ:FR-13] node test for the pure volume-evidence render module.
// Run: node --test stewie/server/web/assets/volume_evidence_html.test.js
const test = require("node:test");
const assert = require("node:assert");
const V = require("./volume_evidence_html.js");

const EV = {
  observed_mass_kg: 24.9, fill_mass_kg: 0.0, uncertainty_kg: 2.5, uncertainty_frac: 0.1,
  lower_kg: 22.4, upper_kg: 27.4, conserved_err_kg: 0.0, agreement_conserved: true,
  drum_inferred_kg: 24.9, agreement_drum: true, confidence_class: "medium",
  acceptance: "accepted", transaction_id: "plan:abc123",
};

test("renders the mass, uncertainty band, confidence, acceptance, cross-checks", () => {  // [REQ:FR-13]
  const h = V.volumeEvidenceHTML(EV, (s) => String(s));
  assert.ok(/24\.9 kg/.test(h), "moved mass");
  assert.ok(/± 2\.5 kg/.test(h) && /10\.0%/.test(h), "uncertainty magnitude");
  assert.ok(/22\.4 kg … 27\.4 kg/.test(h), "lower..upper band");
  assert.ok(/ACCEPTED/.test(h), "acceptance status");
  assert.ok(/medium/.test(h), "confidence class");
  assert.ok(/agrees/.test(h), "conservation + drum cross-checks");
  assert.ok(/plan:abc123/.test(h), "linked transaction");
});

test("REVIEW state when a cross-check disagrees", () => {  // [REQ:FR-13]
  const h = V.volumeEvidenceHTML(Object.assign({}, EV, { acceptance: "review", agreement_drum: false }), (s) => String(s));
  assert.ok(/REVIEW/.test(h) && /MISMATCH/.test(h));
});

test("empty state with no estimate", () => {  // [REQ:FR-13]
  assert.ok(/No volume evidence yet/.test(V.volumeEvidenceHTML(null, (s) => String(s))));
});

test("escapes values (SEC-04)", () => {  // [REQ:FR-13]
  let escd = false;
  V.volumeEvidenceHTML(Object.assign({}, EV, { transaction_id: "<x>" }),
    (s) => { escd = true; return String(s).replace(/</g, "&lt;"); });
  assert.ok(escd, "esc applied to the rendered values");
});
