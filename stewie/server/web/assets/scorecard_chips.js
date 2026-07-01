// FS-24: pure trainer-scorecard KPI chip strips (TR-01). boardChips() = the full Metrics-pane A-board;
// quickChips() = the shorter strip under the session-start output. Both are payload -> HTML string (no
// DOM); the innerHTML writes stay in cockpit.js. De-duplicates the two inline copies. Sets
// window.STEWIE_SCORECARD_CHIPS.
(function (root) {
  "use strict";

  // one KPI chip; warn=true draws a red border (a truth-divergence / over-budget flag).
  function chip(k, v, warn) {
    return '<span style="border:1px solid ' + (warn ? "#c0392b" : "var(--line)")
      + ';border-radius:6px;padding:3px 8px;margin:2px;display:inline-block;font-size:11px">'
      + '<span style="color:var(--muted)">' + k + "</span> "
      + '<b style="font-variant-numeric:tabular-nums">' + v + "</b></span>";
  }

  // full A-board chip strip from a persisted scorecard m (makespan/opt over 1.15 flags red).
  function boardChips(m) {
    return chip("objectives", (m.completed ? "✓" : "✗") + " " + m.objectives_total)
      + chip("legs delivered", m.legs_delivered + "/" + m.legs_total)
      + chip("comm delivered", (m.comm_delivered_frac * 100).toFixed(0) + "%")
      + chip("makespan", m.makespan_s + " s")
      + chip("optimal", m.optimal_s + " s")
      + chip("makespan/opt", (m.makespan_ratio || 1).toFixed(2) + "×", (m.makespan_ratio || 1) > 1.15)
      + chip("recharges", m.recharges) + chip("replans", m.replans)
      + chip("stranded pkts", m.stranded_packets) + chip("dropped pkts", m.dropped_packets)
      + chip("energy", m.energy_MJ + " MJ")
      + (m.energy_divergence_J !== undefined
          ? chip("⚠ believed↔actual (truth)", m.energy_divergence_J + " J", true) : "");
  }

  // shorter quick chip strip shown inline under the session-start output.
  function quickChips(b) {
    return chip("objectives", (b.completed ? "✓" : "✗") + " " + b.objectives_total)
      + chip("legs delivered", b.legs_delivered + "/" + b.legs_total)
      + chip("comm delivered", (b.comm_delivered_frac * 100).toFixed(0) + "%")
      + chip("makespan/opt", (b.makespan_ratio || 1).toFixed(2) + "×")
      + chip("recharges", b.recharges) + chip("replans", b.replans)
      + chip("stranded", b.stranded_packets) + chip("energy", b.energy_MJ + " MJ")
      + (b.energy_divergence_J !== undefined ? chip("⚠ divergence (truth)", b.energy_divergence_J + " J") : "");
  }

  var API = { chip: chip, boardChips: boardChips, quickChips: quickChips };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_SCORECARD_CHIPS = API;                                 // browser (window)
})(typeof window !== "undefined" ? window : null);
