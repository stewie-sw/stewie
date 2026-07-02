// PIPELINE-GATES: PURE per-stage readiness predicates for the mission pipeline spine
// (Site -> Fleet -> Orders -> Solve -> Rehearse -> Validate -> Release -> Execute -> Report).
// Planning-workflow audit (docs/frontend_audit_2026-07-01.md): solve/review/execute used to share ONE
// predicate (a solved timeline exists), so the wizard read "Mission ready" straight after a solve with
// no rehearse, no validation run, and no signed release. Each stage now keys on its REAL prerequisite:
//   site     -> a site is chosen                 fleet    -> at least one rover
//   orders   -> a build order or keep-out        solve    -> a solved plan timeline
//   rehearse -> the last /resync/compare succeeded (forward-compare futures cached)
//   validate -> a Validate-tab run completed (drive preview / estimator / relocalize)
//   release  -> /executive/release-plan returned a signed revision
//   execute  -> a RELEASED plan (execute's prerequisite is the sign-off, not the solve)
//   review   -> the solved plan's report (generated at solve)
// No DOM lookups, no network, no module globals: the cockpit passes a state snapshot in, mirroring the
// window.STEWIE_* pure-module pattern (plan_stepper.js / rehearse_render.js). node:test'able.
(function (root) {
  "use strict";

  var STEP_ORDER = ["site", "fleet", "orders", "solve", "rehearse", "validate", "release", "execute", "review"];

  // s = { hasSite, fleetCount, orderCount, keepoutCount, planned, rehearsed, validated, released }
  // -> { ok } or { ok:false, msg } where msg names the real next action.
  function validateStep(step, s) {
    s = s || {};
    if (step === "site") return s.hasSite ? { ok: true } : { ok: false, msg: "choose a site first (1·Site)" };
    if (step === "fleet") return (Number(s.fleetCount) >= 1) ? { ok: true } : { ok: false, msg: "set at least one rover (3·Fleet)" };
    if (step === "orders") return (Number(s.orderCount) > 0 || Number(s.keepoutCount) > 0)
      ? { ok: true } : { ok: false, msg: "add at least one build order or keep-out" };
    if (step === "solve") return s.planned ? { ok: true } : { ok: false, msg: "press “Plan mission → open report” to solve" };
    if (step === "rehearse") return s.rehearsed ? { ok: true } : { ok: false, msg: "run the forward-compare (Rehearse tab)" };
    if (step === "validate") return s.validated ? { ok: true } : { ok: false, msg: "run a drive preview or estimator check (Validate tab)" };
    if (step === "release") return s.released ? { ok: true } : { ok: false, msg: "sign the release (Release tab, director)" };
    if (step === "execute") return s.released ? { ok: true } : { ok: false, msg: "release the plan before executing" };
    if (step === "review") return s.planned ? { ok: true } : { ok: false, msg: "solve a plan to generate the report" };
    return { ok: true };
  }

  // The first stage whose real prerequisite is unmet, or null when the whole ladder is satisfied.
  // "Mission ready" is EARNED only once release is signed (execute/review then follow from it).
  function firstUnmet(s) {
    for (var i = 0; i < STEP_ORDER.length; i++) {
      if (!validateStep(STEP_ORDER[i], s).ok) return STEP_ORDER[i];
    }
    return null;
  }

  // Sequential strip states: steps before the first unmet are "done", it is "current", the rest are
  // "locked" (the same sequential walk renderStepper used, extracted so it is unit-tested).
  function stepStates(s) {
    var states = {}, current = null;
    for (var i = 0; i < STEP_ORDER.length; i++) {
      var st = STEP_ORDER[i];
      if (!current && validateStep(st, s).ok) states[st] = "done";
      else if (!current) { states[st] = "current"; current = st; }
      else states[st] = "locked";
    }
    return { states: states, current: current, allDone: current === null };
  }

  var API = { STEP_ORDER: STEP_ORDER, validateStep: validateStep, firstUnmet: firstUnmet, stepStates: stepStates };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_PIPELINE_GATES = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
