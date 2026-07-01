// FS-24: pure Validation/Navigation-pane stat lines. driveStatsHTML() = the /nav/run drive outcome;
// slamStatsHTML() + leaveOneOutHTML() = the /slam estimator ATE + leave-one-out; errLine() = the shared
// red error span. Payload -> HTML string (no DOM); the fetch + innerHTML wiring + canvas plots stay in
// cockpit.js. Sets window.STEWIE_NAV_STATS_HTML.
(function (root) {
  "use strict";

  function errLine(msg, esc) { return '<span style="color:#e8273f">' + esc(String(msg)) + "</span>"; }

  // b = POST /nav/run result. arrived/reason + routed/ticks/recoveries + cross-track + stages.
  function driveStatsHTML(b, esc) {
    const dev = b.deviation || {};
    const arr = b.arrived
      ? '<b style="color:var(--accent)">arrived</b>'
      : '<b style="color:#e8273f">' + esc(b.reason) + "</b>";
    return arr + " · routed <b>" + b.routed_m + " m</b> · <b>" + b.n_ticks + "</b> control ticks · "
      + "<b>" + b.n_recoveries + "</b> recoveries · cross-track mean <b>" + (dev.mean_m || 0).toFixed(2)
      + " m</b> / max <b>" + (dev.max_m || 0).toFixed(2) + " m</b>"
      + '<br><span style="opacity:.7">Stages: ' + esc((b.stages || []).join(" → "))
      + ". Real Haworth DEM; route_leg corridor then plan_local/track_plan/recovery drive.</span>";
  }

  // b = POST /slam result. Fused ATE vs baseline, with the reduction factor.
  function slamStatsHTML(b) {
    return "fused ATE <b>" + b.ate_aligned_m + " m</b> · abs drift <b>" + b.abs_max_err_m + " m</b>"
      + " vs baseline <b>" + b.baseline_abs_max_err_m + ' m</b> · <b style="color:var(--accent)">'
      + b.reduction_x + "× tighter</b>";
  }

  // the leave-one-out drift-contribution line (which fix, removed, costs how much drift).
  function leaveOneOutHTML(b) {
    return "leave-one-out (drift increase when removed): "
      + Object.entries(b.leave_one_out).map(function (e) {
          return e[0] + " <b>+" + e[1].contribution_m + " m</b>";
        }).join(" · ");
  }

  var API = { errLine: errLine, driveStatsHTML: driveStatsHTML,
              slamStatsHTML: slamStatsHTML, leaveOneOutHTML: leaveOneOutHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_NAV_STATS_HTML = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
