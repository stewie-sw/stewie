// FS-24: pure Validation/Navigation-pane stat lines. driveStatsHTML() = the /nav/run drive outcome;
// errLine() = the shared red error span. Payload -> HTML string (no DOM); the fetch + innerHTML wiring + canvas plots stay in
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

  var API = { errLine: errLine, driveStatsHTML: driveStatsHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_NAV_STATS_HTML = API;                                  // browser (window)
})(typeof window !== "undefined" ? window : null);
