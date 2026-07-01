// FS-03 Fleet work area: PURE renderers for the Fleet pane. No DOM lookups, no network, no module
// globals -- the cockpit's thin wrapper fetches /fleet, normalizes it through the FS-15 adapter
// (adapters.normalizeFleetRoster), reads the last-plan `totals`, and passes them in, mirroring the
// existing window.STEWIE_* module pattern (rover_hud.js / plan_geom.js). Two builders:
//   fleetRosterHTML(vm, esc)     -> the roster table from the NORMALIZED roster view model (FS-15:
//                                    this module consumes the view model, never the raw /fleet JSON)
//   fleetPlanHTML(totals, esc)   -> the live per-vehicle ALLOCATION + makespan + space-time conflicts
//                                    from the LAST plan (totals.vehicles_detail + makespan_s + *_conflicts);
//                                    honest empty state when no multi-vehicle plan has been run yet.
// node:test'able (esc is injected). The cockpit gates the whole pane on operator+ (AG-01).
(function (root) {
  "use strict";

  function _hours(s) { return (Number(s || 0) / 3600).toFixed(2); }
  function _mj(j) { return (Number(j || 0) / 1e6).toFixed(2); }
  function _km(m) { return (Number(m || 0) / 1000).toFixed(2); }

  // the static fleet ROSTER from the NORMALIZED /fleet view model (adapters.normalizeFleetRoster).
  function fleetRosterHTML(vm, esc) {
    if (!vm || !Array.isArray(vm.vehicles) || !vm.vehicles.length) {
      return '<div class="empty">No vehicle registry served. /fleet returned no vehicles.</div>';
    }
    var rows = vm.vehicles.map(function (v) {
      var caps = (v.capabilities || []).map(esc).join(", ");
      var pwr = (v.onboardPower || []).map(function (p) {
        return esc(p.label) + " (" + Number(p.capacityMJ || 0).toFixed(2) + " MJ)";
      }).join(", ") || "—";
      var vis = v.uiVisible ? "" : ' <span style="opacity:.55;font-size:9px">(data only)</span>';
      return "<tr>"
        + '<td style="font-weight:600">' + esc(v.id) + vis + "</td>"
        + "<td>" + esc(v.label) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + Number(v.dryMassKg || 0).toFixed(1) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + Number(v.drumCapacityKg || 0).toFixed(1) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + Number(v.drivePowerW || 0).toFixed(1) + "</td>"
        + "<td>" + (v.canDig ? "✓" : "—") + "</td>"
        + '<td style="font-size:10px;opacity:.85">' + caps + "</td>"
        + '<td style="font-size:10px;opacity:.85">' + pwr + "</td>"
        + "</tr>";
    }).join("");
    return '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>id</th><th>platform</th><th style='text-align:right'>dry kg</th>"
      + "<th style='text-align:right'>drum kg</th><th style='text-align:right'>drive W</th>"
      + "<th>digs</th><th>capabilities</th><th>onboard power</th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table>"
      + '<div style="font-size:10px;opacity:.6;margin-top:6px">'
      + esc(vm.count || 0) + " registered · " + esc(vm.uiVisibleCount || 0)
      + " UI-visible · default " + esc(vm.defaultVehicle || "") + "</div>";
  }

  // the LIVE per-vehicle allocation + makespan + conflicts from the last /plan `totals` (real plan data).
  function fleetPlanHTML(totals, esc) {
    var t = totals || {};
    var detail = Array.isArray(t.vehicles_detail) ? t.vehicles_detail : [];
    if (!detail.length) {
      return '<div class="empty">No fleet allocation yet. Plan a mission with <b>≥1 rover</b> '
        + "(Plan tab → fleet size); the per-vehicle allocation, makespan, and space-time conflicts "
        + "from that plan appear here.</div>";
    }
    var rows = detail.map(function (d) {
      var h = (d.health && d.health.health) || "nominal";
      var hcolor = h === "stranded" ? "#e8273f" : (h === "low_margin" ? "#e07b39" : "#4caf72");
      var waits = [];
      if (d.charger_wait_s) waits.push("chg " + _hours(d.charger_wait_s) + "h");
      if (d.crowd_wait_s) waits.push("crowd " + _hours(d.crowd_wait_s) + "h");
      if (d.precedence_wait_s) waits.push("prec " + _hours(d.precedence_wait_s) + "h");
      if (d.resource_wait_s) waits.push("res " + _hours(d.resource_wait_s) + "h");
      var minb = d.health && typeof d.health.min_batt_frac === "number"
        ? (d.health.min_batt_frac * 100).toFixed(0) + "%" : "—";
      return "<tr>"
        + '<td style="font-weight:600">' + esc(d.vehicle) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + esc(d.n_trips) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _hours(d.time_s) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _mj(d.energy_J) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + _km(d.distance_m) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + esc(d.charges) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + minb + "</td>"
        + '<td style="font-size:10px;opacity:.85">' + (waits.join(" · ") || "—") + "</td>"
        + '<td><span style="color:' + hcolor + ';font-weight:600">' + esc(h) + "</span></td>"
        + "</tr>";
    }).join("");
    var conflicts = [
      ["space-time", t.vehicle_conflicts],
      ["temporal (crowding)", t.temporal_conflicts],
      ["haul-path", t.haul_path_conflicts],
      ["charger", t.charger_conflicts],
    ].filter(function (c) { return typeof c[1] === "number"; });
    var anyConflict = conflicts.some(function (c) { return c[1] > 0; });
    var conflictHTML = conflicts.map(function (c) {
      var bad = c[1] > 0;
      return '<span style="padding:2px 8px;border-radius:8px;border:1px solid '
        + (bad ? "#e8273f" : "var(--line)") + ";color:" + (bad ? "#e8273f" : "var(--muted)")
        + '">' + esc(c[0]) + ": " + esc(c[1]) + "</span>";
    }).join(" ");
    var replan = t.fleet_needs_replan
      ? ' <span style="color:#e8273f;font-weight:600">⚠ fleet needs replan (a rover is stranded)</span>' : "";
    var head = '<div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin-bottom:8px;font-size:12px">'
      + "<b>" + esc(t.vehicles || detail.length) + " rovers</b>"
      + '<span>makespan <b>' + _hours(t.makespan_s) + " h</b></span>"
      + '<span style="opacity:.7">parallel ' + _hours(t.makespan_parallel_s) + " h</span>"
      + (anyConflict ? "" : '<span style="color:#4caf72">fully deconflicted</span>')
      + replan + "</div>"
      + '<div style="display:flex;gap:6px;flex-wrap:wrap;font-size:10px;margin-bottom:8px">' + conflictHTML + "</div>";
    return head
      + '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>vehicle</th><th style='text-align:right'>trips</th><th style='text-align:right'>time h</th>"
      + "<th style='text-align:right'>energy MJ</th><th style='text-align:right'>dist km</th>"
      + "<th style='text-align:right'>charges</th><th style='text-align:right'>min SoC</th>"
      + "<th>waits</th><th>health</th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table>";
  }

  var API = { fleetRosterHTML: fleetRosterHTML, fleetPlanHTML: fleetPlanHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_FLEET_RENDER = API;                                    // browser (window)
})(typeof window !== "undefined" ? window : null);
