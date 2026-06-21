// PLAN-STEPPER: the pure step -> sidebar-section map for the mission pipeline spine
// (Site -> Fleet -> Orders -> Solve -> Review -> Execute). The DOM glue (focusStep) lives in
// cockpit.js; this module is the single source of truth for WHICH numbered Plan-sidebar sections
// each step reveals. Pure + side-effect-free so it is unit-testable without a DOM.
//
// The sidebar's numbered sections (built by collapseSidebar from the <h3> "N · ..." headings):
//   1 Site · 2 Contents · 3 Fleet · 4 Feasibility · 5 Plan (orders/keep-outs/solve/review/exec)
//   6 Catalog (saved missions & structures) · 7 Telemetry (channels & drum sensing; exec feed)
//
// Intent (each step shows ONLY its sections; the rest collapse):
//   site    -> 1 Site picker + 2 Contents/layers/locator
//   fleet   -> 3 Fleet (vehicle/rovers/soil/charger) + 4 Feasibility
//   orders  -> 5 Plan (build queue + order authoring + keep-outs)
//
// GIS S-2 Contents tree (contents_tree.js, mounted IN section 2): its groups stay coherent with this map.
// Each tree group carries the numbered section its features ALSO live in, so the tree never claims a feature
// belongs to a step that does not reveal it:
//   Basemap / Terrain / Sun  -> section "1" (the Site step reveals 1+2)
//   Safety (keep-outs) / Operations (build orders) -> section "5" (the Orders step reveals 5)
// plan_stepper.test.js asserts these group sections are revealed by the Site / Orders steps respectively.
//   solve   -> 4 Feasibility + 5 Plan (constraints + algorithm + Plan button)
//   review  -> 5 Plan (plan summary, Plan IR/report export) + 6 Catalog (saved missions/report)
//   execute -> 5 Plan (Execute+watch, Training session) + 7 Telemetry (channels/drum/exec feed)
//
// Review/Execute keep the existing plan-gating contract (the cockpit gates them on a solved plan and
// switches to the report/metrics VIEWS when a plan exists); this map only governs sidebar focus when
// the Plan view is showing.
(function (root) {
  "use strict";

  var STEP_SECTIONS = {
    site: ["1", "2"],
    fleet: ["3", "4"],
    orders: ["5"],
    solve: ["4", "5"],
    review: ["5", "6"],
    execute: ["5", "7"],
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
