// PIPELINE-GATES (node:test): the per-stage readiness predicates for the mission pipeline spine are
// PURE -> unit-testable without a browser. Planning-workflow audit (docs/frontend_audit_2026-07-01.md):
// solve/review/execute used to share ONE predicate (a solved timeline), so the wizard asserted
// "Mission ready" with no rehearse, no validation run, and no signed release. These tests pin the
// honest ladder. Run: node --test stewie/server/web/assets/pipeline_gates.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const G = require("./pipeline_gates.js");

// a state snapshot the cockpit would pass in (all stages met).
function met() {
  return { hasSite: true, fleetCount: 1, orderCount: 2, keepoutCount: 0,
           planned: true, rehearsed: true, validated: true, released: true };
}

test("STEP_ORDER: one spine, tab vocabulary, release before execute, report last", () => {
  assert.deepStrictEqual(G.STEP_ORDER,
    ["site", "fleet", "orders", "solve", "rehearse", "validate", "release", "execute", "review"]);
});

test("validateStep: each stage keys on its OWN real prerequisite", () => {
  const s = met();
  assert.ok(G.validateStep("site", s).ok);
  assert.ok(!G.validateStep("site", { ...s, hasSite: false }).ok);
  assert.ok(!G.validateStep("fleet", { ...s, fleetCount: 0 }).ok);
  assert.ok(!G.validateStep("orders", { ...s, orderCount: 0, keepoutCount: 0 }).ok);
  assert.ok(G.validateStep("orders", { ...s, orderCount: 0, keepoutCount: 1 }).ok, "a keep-out alone authors");
  assert.ok(!G.validateStep("solve", { ...s, planned: false }).ok);
  assert.ok(!G.validateStep("rehearse", { ...s, rehearsed: false }).ok, "a solve does NOT satisfy rehearse");
  assert.ok(!G.validateStep("validate", { ...s, validated: false }).ok, "a solve does NOT satisfy validate");
  assert.ok(!G.validateStep("release", { ...s, released: false }).ok, "a solve does NOT satisfy release");
  assert.ok(!G.validateStep("execute", { ...s, released: false }).ok, "execute's prerequisite is the sign-off");
  assert.ok(!G.validateStep("review", { ...s, planned: false }).ok);
  // every unmet stage carries an actionable message
  assert.ok(G.validateStep("rehearse", { ...s, rehearsed: false }).msg.length > 0);
});

test("firstUnmet: the wizard walks the honest ladder solve -> rehearse -> validate -> release", () => {
  const s = { hasSite: true, fleetCount: 1, orderCount: 1, keepoutCount: 0,
              planned: false, rehearsed: false, validated: false, released: false };
  assert.strictEqual(G.firstUnmet(s), "solve");
  s.planned = true;
  assert.strictEqual(G.firstUnmet(s), "rehearse", "post-solve the next stage is REHEARSE, not ready");
  s.rehearsed = true;
  assert.strictEqual(G.firstUnmet(s), "validate");
  s.validated = true;
  assert.strictEqual(G.firstUnmet(s), "release");
  s.released = true;
  assert.strictEqual(G.firstUnmet(s), null, "the full ladder met -> mission ready");
});

test("stepStates: 'Mission ready' (allDone) ONLY once release is signed", () => {
  const plannedOnly = { hasSite: true, fleetCount: 1, orderCount: 1, keepoutCount: 0,
                        planned: true, rehearsed: true, validated: true, released: false };
  const st = G.stepStates(plannedOnly);
  assert.strictEqual(st.allDone, false, "planned+rehearsed+validated but unsigned is NOT mission-ready");
  assert.strictEqual(st.current, "release");
  assert.strictEqual(st.states.solve, "done");
  assert.strictEqual(st.states.release, "current");
  assert.strictEqual(st.states.execute, "locked");
  const all = G.stepStates(met());
  assert.strictEqual(all.allDone, true);
  assert.strictEqual(all.current, null);
  assert.strictEqual(all.states.review, "done");
});

test("stepStates: fresh boot -> site is current, everything downstream locked", () => {
  const st = G.stepStates({ hasSite: false, fleetCount: 0, orderCount: 0, keepoutCount: 0,
                            planned: false, rehearsed: false, validated: false, released: false });
  assert.strictEqual(st.current, "site");
  assert.strictEqual(st.states.rehearse, "locked");
});
