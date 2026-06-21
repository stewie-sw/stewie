// FS-03 Construction work area: PURE renderers for the Construction pane (badge FORGE, operator+). No DOM
// lookups, no network, no module globals -- the cockpit's thin wrapper fetches /construction + reads the
// last-plan `validation` (+ `ordered_acceptance`) and passes them in, mirroring fleet_render.js. Builders:
//   constructionCatalogHTML(con, esc)     -> the real structure-template build catalog (always present)
//   constructionAcceptanceHTML(con, validation, esc)
//        -> the acceptance-criteria DEFINITION (what validate_plan measures + default tolerances) AND the
//           live AS-BUILT acceptance RESULT from the LAST plan (validation: flatness/berm/repose/bearing
//           pass-fail on the real terrain); honest empty state for the result when no plan has been run.
// node:test'able (esc is injected). The cockpit gates the whole pane on operator+ (AG-01).
(function (root) {
  "use strict";

  function _cm(m) { return (Number(m || 0) * 100).toFixed(1); }

  // the structure-template BUILD CATALOG from the real /construction payload (leap/structures.py).
  function constructionCatalogHTML(con, esc) {
    if (!con || !Array.isArray(con.templates) || !con.templates.length) {
      return '<div class="empty">No structure catalog served. /construction returned no templates.</div>';
    }
    var rows = con.templates.map(function (t) {
      var kinds = (t.orders || []).map(function (o) {
        var c = o.kind === "cut" ? "#e07b39" : "#4caf72";
        return '<span style="color:' + c + '">' + esc(o.kind) + "</span> "
          + esc(o.action) + " (" + Number(o.footprint_m2 || 0).toFixed(1) + " m² × "
          + _cm(o.depth_m) + " cm)";
      }).join("<br>");
      var bal = t.balanced
        ? '<span style="color:#4caf72">cut↔fill balanced</span>'
        : '<span style="opacity:.7">cut-only (source/grade)</span>';
      return "<tr>"
        + '<td style="font-weight:600;vertical-align:top">' + esc(t.id) + "</td>"
        + '<td style="font-size:10px;opacity:.85;vertical-align:top">' + esc(t.doc || "") + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums;vertical-align:top">' + esc(t.n_orders) + "</td>"
        + '<td style="vertical-align:top">' + bal + "</td>"
        + '<td style="font-size:10px;opacity:.85;vertical-align:top">' + kinds + "</td>"
        + "</tr>";
    }).join("");
    return '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>structure</th><th>what</th><th style='text-align:right'>orders</th>"
      + "<th>balance</th><th>primitive cut/fill (default size)</th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table>"
      + '<div style="font-size:10px;opacity:.6;margin-top:6px">'
      + esc(con.count || 0) + " templates · " + esc(con.balanced_count || 0)
      + " volume-balanced · catalog from specs (leap/structures.py)</div>";
  }

  // the acceptance-criteria DEFINITION (always) + the LIVE as-built RESULT from the last /plan validation.
  function constructionAcceptanceHTML(con, validation, esc) {
    var acc = (con && con.acceptance) || {};
    var checks = Array.isArray(acc.checks) ? acc.checks : [];
    var critRows = checks.map(function (c) {
      var tol = "";
      if (typeof c.tol_m === "number") tol = _cm(c.tol_m) + " cm";
      else if (typeof c.max_slope_deg === "number") tol = "≤ " + c.max_slope_deg + "°";
      else if (typeof c.factor_of_safety === "number") tol = "FS " + c.factor_of_safety;
      return "<tr>"
        + '<td style="font-weight:600">' + esc(c.id) + "</td>"
        + '<td style="font-size:10px;opacity:.85">' + esc(c.what || "") + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + esc(tol || "—") + "</td>"
        + "</tr>";
    }).join("");
    var defers = (acc.defers_to_totals || []).map(esc).join(", ");
    var critHTML = '<table style="width:100%;border-collapse:collapse;font-size:11px;margin-bottom:8px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>check</th><th>what it measures</th><th style='text-align:right'>tolerance</th></tr></thead>"
      + "<tbody>" + critRows + "</tbody></table>"
      + (defers ? '<div style="font-size:10px;opacity:.6;margin-bottom:10px">defers to plan totals: '
          + defers + "</div>" : "");

    // the LIVE as-built acceptance RESULT from the last plan's validate_plan output.
    var resultHTML;
    var v = validation || {};
    if (!v || typeof v.feasible === "undefined") {
      resultHTML = '<div class="empty">No as-built acceptance yet. Plan a mission (Plan tab); the '
        + "flatness, berm-profile, repose, and bearing pass/fail on the real terrain from that plan "
        + "appear here.</div>";
    } else {
      var verdict = function (ok) {
        return ok
          ? '<span style="color:#4caf72;font-weight:600">✓ pass</span>'
          : '<span style="color:#e8273f;font-weight:600">✗ fail</span>';
      };
      var items = [
        ["feasible (material/siting)", v.feasible, ""],
        ["mass conserved", v.mass_conserved,
          typeof v.mass_drift_kg === "number" ? "drift " + Number(v.mass_drift_kg).toFixed(2) + " kg" : ""],
        ["as-built flatness", v.as_built_pass,
          v.as_built_on_real_dem
            ? "RMSE " + _cm(v.as_built_flatness_rmse_m) + " cm (tol " + _cm(v.as_built_tol_m) + " cm)"
            : "measured on flat mantle (no real DEM)"],
        ["berm crest-profile", v.berm_profile_pass,
          Array.isArray(v.berm_profile) ? v.berm_profile.length + " fill order(s)" : ""],
        ["repose stability", v.repose_pass,
          typeof v.repose_limit_deg === "number" ? "limit " + v.repose_limit_deg + "° (φ)" : ""],
        ["bearing capacity", v.bearing_pass,
          Array.isArray(v.bearing) ? v.bearing.length + " pad(s)" : ""],
      ].filter(function (it) { return typeof it[1] !== "undefined"; });
      var resRows = items.map(function (it) {
        return "<tr>"
          + '<td style="font-weight:600">' + esc(it[0]) + "</td>"
          + "<td>" + verdict(it[1]) + "</td>"
          + '<td style="font-size:10px;opacity:.85">' + esc(it[2] || "") + "</td>"
          + "</tr>";
      }).join("");
      resultHTML = '<table style="width:100%;border-collapse:collapse;font-size:11px">'
        + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
        + "<th>acceptance</th><th>verdict</th><th>detail</th></tr></thead>"
        + "<tbody>" + resRows + "</tbody></table>";
    }
    return '<div style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em;'
      + 'color:var(--muted);margin-bottom:6px">CRITERIA — validate_plan (conserved authority)</div>'
      + critHTML
      + '<div style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em;'
      + 'color:var(--muted);margin:10px 0 6px">AS-BUILT — last plan</div>'
      + resultHTML;
  }

  var API = {
    constructionCatalogHTML: constructionCatalogHTML,
    constructionAcceptanceHTML: constructionAcceptanceHTML,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_CONSTRUCTION_RENDER = API;                             // browser (window)
})(typeof window !== "undefined" ? window : null);
