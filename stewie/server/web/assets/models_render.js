// FS-03 Models work area: PURE renderers for the Models pane (engineer/dev surface, operator+). No DOM
// lookups, no network, no module globals -- the cockpit's thin wrapper fetches /models, normalizes it
// through the FS-15 adapter (adapters.normalizeModelsRegistry), and passes the VIEW MODEL in (never the
// raw /models JSON), mirroring fleet_render.js. Builders:
//   modelsProfilesHTML(m, esc)   -> the deployable SYSTEM-PROFILE registry (sha256 + VERIFIED status)
//   modelsRegistriesHTML(m, esc) -> the vehicle + body registries with provenance
//   modelsGovernanceHTML(m, esc) -> the ML-01 deployment-ready gate + §25.3 no-command-path status
// node:test'able (esc is injected). The cockpit gates the whole pane on operator+.
(function (root) {
  "use strict";

  function _short(s) { return String(s || "").slice(0, 12); }

  // the deployable SYSTEM-PROFILE registry (specs/profiles.py): exact-bytes sha256 + VERIFIED status.
  function modelsProfilesHTML(m, esc) {
    if (!m || !Array.isArray(m.profiles) || !m.profiles.length) {
      return '<div class="empty">No profiles served. /models returned no system profiles.</div>';
    }
    var rows = m.profiles.map(function (p) {
      var ready = p.deploymentReady
        ? '<span style="color:#4caf72;font-weight:600">✓ ' + esc(p.status) + "</span>"
        : '<span style="color:#e07b39;font-weight:600">' + esc(p.status) + "</span>";
      return "<tr>"
        + '<td style="font-weight:600">' + esc(p.id) + "</td>"
        + "<td>" + ready + "</td>"
        + "<td>" + esc(p.substrate) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + esc(p.nCameras) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">'
          + (p.dryMassKg != null ? Number(p.dryMassKg).toFixed(1) : "—") + "</td>"
        + '<td style="font-family:monospace;font-size:10px;opacity:.75">' + esc(_short(p.sha256)) + "…</td>"
        + "</tr>";
    }).join("");
    return '<table style="width:100%;border-collapse:collapse;font-size:11px">'
      + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
      + "<th>profile</th><th>deploy status</th><th>substrate</th><th style='text-align:right'>cams</th>"
      + "<th style='text-align:right'>dry kg</th><th>sha256</th></tr></thead>"
      + "<tbody>" + rows + "</tbody></table>"
      + '<div style="font-size:10px;opacity:.6;margin-top:6px">'
      + esc(m.profileCount || 0) + " profiles · " + esc(m.profilesDeployable || 0)
      + " VERIFIED (deployable) · default " + esc(m.defaultProfile || "") + "</div>";
  }

  // the vehicle + body registries (specs/vehicles.py, specs/bodies.py) with provenance.
  function modelsRegistriesHTML(m, esc) {
    var veh = (m && Array.isArray(m.vehicles)) ? m.vehicles : [];
    var bod = (m && Array.isArray(m.bodies)) ? m.bodies : [];
    if (!veh.length && !bod.length) {
      return '<div class="empty">No registries served. /models returned no vehicles or bodies.</div>';
    }
    var vrows = veh.map(function (v) {
      return "<tr>"
        + '<td style="font-weight:600">' + esc(v.id) + "</td>"
        + "<td>" + esc(v.label) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + Number(v.dryMassKg || 0).toFixed(1) + "</td>"
        + '<td style="font-size:9px;opacity:.7">' + esc(v.provenance || "") + "</td>"
        + "</tr>";
    }).join("");
    var brows = bod.map(function (b) {
      return "<tr>"
        + '<td style="font-weight:600">' + esc(b.id) + "</td>"
        + "<td>" + esc(b.bekkerRegime) + "</td>"
        + '<td style="text-align:right;font-variant-numeric:tabular-nums">' + Number(b.gMS2 || 0).toFixed(2) + "</td>"
        + '<td style="font-size:9px;opacity:.7">' + esc(b.confidence || "") + "</td>"
        + "</tr>";
    }).join("");
    var html = "";
    if (veh.length) {
      html += '<div style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em;'
        + 'color:var(--muted);margin-bottom:6px">VEHICLE REGISTRY — specs/vehicles.py ('
        + esc(m.vehicleCount || veh.length) + ", default " + esc(m.defaultVehicle || "") + ")</div>"
        + '<table style="width:100%;border-collapse:collapse;font-size:11px;margin-bottom:10px">'
        + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
        + "<th>id</th><th>platform</th><th style='text-align:right'>dry kg</th><th>provenance</th></tr></thead>"
        + "<tbody>" + vrows + "</tbody></table>";
    }
    if (bod.length) {
      html += '<div style="font-family:Orbitron,system-ui;font-size:10px;letter-spacing:.08em;'
        + 'color:var(--muted);margin:4px 0 6px">BODY / SOIL REGISTRY — specs/bodies.py ('
        + esc(m.bodyCount || bod.length) + ", default " + esc(m.defaultBody || "") + ")</div>"
        + '<table style="width:100%;border-collapse:collapse;font-size:11px">'
        + '<thead><tr style="text-align:left;color:var(--muted);border-bottom:1px solid var(--line)">'
        + "<th>id</th><th>regime</th><th style='text-align:right'>g m/s²</th><th>confidence</th></tr></thead>"
        + "<tbody>" + brows + "</tbody></table>";
    }
    return html;
  }

  // the ML-01 model-deployment governance: deployment-ready gate criteria + §25.3 no-command-path status.
  function modelsGovernanceHTML(m, esc) {
    var g = (m && m.governance) || {};
    var crit = (g.deploymentReadyCriteria || []).map(function (c) {
      return '<li style="font-size:11px;opacity:.9">' + esc(c) + "</li>";
    }).join("");
    var deployed = Array.isArray(g.deployedModels) ? g.deployedModels : [];
    var enforced = g.commandPathEnforced
      ? '<span style="color:#4caf72;font-weight:600">✓ enforced</span>'
      : '<span style="color:#e8273f;font-weight:600">✗ not enforced</span>';
    return '<div style="font-size:11px;line-height:1.6">'
      + '<div><b>' + esc(g.contract || "ModelArtifact") + "</b> · schema "
      + esc(g.schemaEndpoint || "/contracts/schema") + "</div>"
      + '<div style="margin-top:6px"><b>ML-01 deployment-ready gate</b> (all required):</div>'
      + '<ul style="margin:4px 0 6px 18px;padding:0">' + crit + "</ul>"
      + '<div>§25.3 command-path invariant: ' + enforced
      + ' — <span style="opacity:.85">' + esc(g.commandPathInvariant || "") + "</span></div>"
      + '<div style="margin-top:6px"><b>deployed models:</b> '
      + (deployed.length
          ? esc(deployed.length) + " on command path"
          : '<span style="color:#4caf72">none on the command path</span>')
      + "</div>"
      + '<div style="font-size:10px;opacity:.7;margin-top:6px">' + esc(g.status || "") + "</div>"
      + "</div>";
  }

  var API = {
    modelsProfilesHTML: modelsProfilesHTML,
    modelsRegistriesHTML: modelsRegistriesHTML,
    modelsGovernanceHTML: modelsGovernanceHTML,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_MODELS_RENDER = API;                                   // browser (window)
})(typeof window !== "undefined" ? window : null);
