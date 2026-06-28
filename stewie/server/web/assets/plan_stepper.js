// PLAN-STEPPER: the pure step -> sidebar-section map for the mission pipeline spine
// (Site -> Fleet -> Orders -> Solve -> Review -> Execute). The DOM glue (focusStep) lives in
// cockpit.js; this module is the single source of truth for WHICH numbered Plan-sidebar sections
// each step reveals. Pure + side-effect-free so it is unit-testable without a DOM.
//
// The sidebar's numbered sections (built by collapseSidebar from the <h3> "N · ..." headings):
//   1 Site · 2 Contents · 3 Rovers · 4 Plan
// (sidebar 7->4 reorg, docs/cockpit_reorg_plan_2026-06-23.md: the old standalone 4 Feasibility / 5 Plan /
//  6 Catalog / 7 Telemetry sections were FOLDED INTO section 4 "Plan -- the mission, in order" as its
//  sub-steps A..F + Files/Catalog/Telemetry. Sections 5/6/7 NO LONGER EXIST in the DOM, so any step that
//  still mapped to them revealed nothing -- that was the navigation regression this map now fixes.)
//
// Intent (each step shows ONLY its sections; the rest collapse):
//   site    -> 1 Site picker + 2 Contents/layers/locator
//   fleet   -> 3 Rovers (vehicle/rovers/soil/charger)
//   orders  -> 4 Plan (Feasibility + build queue + order authoring + keep-outs)
//   solve   -> 4 Plan (D Constraints + E Solve)
//   review  -> 4 Plan (F Review: plan summary, Plan IR / report export)
//   execute -> 4 Plan (Execute + watch, Training session)
// orders/solve/review/execute all live INSIDE section 4 now; stepScrollTo (cockpit.js) scrolls to the
// right sub-step within it, and the Plan VIEW also switches to report/metrics for review/execute.
//
// GIS S-2 Contents tree (contents_tree.js, mounted IN section 2): its groups stay coherent with this map.
// Each tree group carries the numbered section its features ALSO live in, so the tree never claims a feature
// belongs to a step that does not reveal it:
//   Basemap / Terrain / Sun  -> section "1" (the Site step reveals 1+2)
//   Safety (keep-outs) / Operations (build orders) -> section "4" (the Orders step reveals 4)
// plan_stepper.test.js asserts these group sections are revealed by the Site / Orders steps respectively.
//
// Review/Execute keep the existing plan-gating contract (the cockpit gates them on a solved plan and
// switches to the report/metrics VIEWS when a plan exists); this map only governs sidebar focus when
// the Plan view is showing.
(function (root) {
  "use strict";

  var STEP_SECTIONS = {
    site: ["1", "2"],
    fleet: ["3"],
    orders: ["4"],
    solve: ["4"],
    review: ["4"],
    execute: ["4"],
  };

  // The numbered sections a step reveals (the rest collapse). Returns a fresh array; [] for an
  // unknown step (the caller leaves the sidebar untouched). Pure.
  function sectionsForStep(step) {
    var want = STEP_SECTIONS[step];
    return want ? want.slice() : [];
  }

  // True iff this numbered section should be OPEN for the given step. Pure.
  function sectionVisible(step, sectionNumber) {
    return sectionsForStep(step).indexOf(String(sectionNumber)) !== -1;
  }

  var API = {
    STEP_SECTIONS: STEP_SECTIONS,
    sectionsForStep: sectionsForStep,
    sectionVisible: sectionVisible,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_PLAN_STEPPER = API;
})(typeof window !== "undefined" ? window : null);
