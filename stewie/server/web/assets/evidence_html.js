// FS-24: the RELEASE-EVIDENCE HTML builders -- pure functions that turn a server payload into the
// innerHTML string for the evidence/gate panels. No DOM, no globals: the cockpit's renderEvidence /
// renderGateEvidence wrappers fetch the payload, call these, and write the result into $("evbox") /
// $("gateevidence"), per the existing window.STEWIE_* module pattern. Extracted verbatim from
// cockpit.js (PRD FS-24); behaviour is preserved exactly. esc() is injected so the same SEC-04
// HTML-escaping (htmlesc.js) hardens the same sinks; node:test'able.
(function (root) {
  "use strict";

  // the cross-system EVIDENCE matrix (generalization + accuracy/precision + photometric depth). `d` is
  // the /evidence payload; `escFn` is the SEC-04 escaper (htmlesc.esc). Returns the inner HTML string.
  function evidenceHTML(d, escFn) {
    const e = (typeof escFn === "function") ? escFn : (s) => String(s);
    const fmt = (v) => Array.isArray(v) ? v.join("–") : (v === true ? "✓" : v === false ? "—"
                      : (v == null ? "—" : e(String(v))));
    const SYS = ["Stanford NAV Lab (LAC)", "ShadowNav (JPL)", "Navigation"];
    const th = (t) => `<th style="text-align:left;padding:2px 8px">${e(t)}</th>`;
    const td = (v, muted) => `<td style="padding:2px 8px${muted ? ';color:var(--muted)' : ''}">${fmt(v)}</td>`;
    const h3 = (t) => `<h3 style="font-size:11px;letter-spacing:.1em;margin:12px 0 4px">${t}</h3>`;
    // 1) GENERALIZATION -- the capability matrix (systems x attribute)
    const cm = d.capability_matrix || {};
    const rows = ["scope", "needs_orbital_prior", "builds_map_online", "motion", "heading_source",
                  "shadow_role", "active_reconfiguration"];
    let html = h3("GENERALIZATION — capability matrix")
      + `<table style="font-size:11px;border-collapse:collapse;width:100%"><tr>${th("")}${SYS.map(th).join("")}</tr>`
      + rows.map((k) => `<tr><td style="color:var(--muted);padding:2px 8px">${k}</td>`
          + SYS.map((s) => td((cm[s] || {})[k])).join("") + `</tr>`).join("") + `</table>`;
    // 2) COMPARISON -- accuracy / precision per system (each in its reported regime)
    const ap = d.accuracy_precision || {};
    html += h3("COMPARISON — accuracy / precision (each system's reported regime)")
      + `<table style="font-size:11px;border-collapse:collapse;width:100%"><tr>`
      + ["system", "accuracy (m)", "precision (m)", "frame", "source"].map(th).join("") + `</tr>`
      + SYS.map((s) => { const r = ap[s] || {};
          return `<tr>${td(s)}${td(r.accuracy_m)}${td(r.precision_m)}${td(r.frame)}${td(r.source, true)}</tr>`;
        }).join("") + `</table>`;
    if (ap._note) html += `<div style="font-size:10px;color:var(--muted);margin-top:4px">${e(ap._note)}</div>`;
    // 3) PHOTOMETRIC + DEPTH -- modality range precision
    const ms = d.modality_sigma || {};
    html += h3(`PHOTOMETRIC + DEPTH — range precision @ ${fmt(ms.range_m)} m`)
      + `<div style="font-size:11px;line-height:1.8">articulation parallax σ <b>${fmt(ms.articulation_parallax_sigma_m)} m</b>`
      + ` vs physical stereo σ <b>${fmt(ms.stereo_sigma_m)} m</b> → articulation advantage `
      + `<b>${fmt(ms.articulation_advantage_x)}×</b> (the pose-change baseline exceeds the rig baseline)</div>`;
    return html;
  }

  // the RELEASE-GATES evidence card (G1/G2 + frozen-baseline + next gate). `j` = the /admin/gates
  // /validate payload. Returns the inner HTML string for $("gateevidence").
  function gateEvidenceHTML(j) {
    const e = j.evidence || {};
    const f = (x, u, d) => (x == null ? "—" : (+x).toFixed(d == null ? 2 : d) + (u || ""));
    const ok = (s) => `<span style="color:#7CE0A6">${s}</span>`;
    return `<div style="border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:8px;font-size:11px;line-height:1.7;font-variant-numeric:tabular-nums">
       <div style="font-family:Orbitron,system-ui;letter-spacing:.08em;font-size:10px;color:var(--accent);margin-bottom:6px">RELEASE GATES — EVIDENCE <small style="color:var(--muted)">(${e.evidence_mode || "?"})</small></div>
       <div><b>G1</b> ${ok(j.g1)} · contracts ${e.g1_contract_checks_pass}/${e.g1_contract_checks_total} PASS · real Katwijk dead-reckon ATE <b>${f(e.g1_ate_m, " m")}</b> over ${f(e.g1_eval_track_m, " m", 1)} · sim baseline ${f(e.g1_baseline_raw_m, " m")} raw / ${f(e.g1_baseline_aligned_m, " m")} aligned</div>
       <div><b>G2</b> ${ok(j.g2)} · stereo covariance σ <b>${f(e.g2_sigma_px, " px")}</b> · held-out 3σ coverage <b>${f(e.g2_coverage_3sigma, "", 3)}</b> · depth ${f(e.g2_median_depth_m, " m")} ± ${f(e.g2_sigma_depth_m, " m", 3)}</div>
       <div style="color:var(--muted);margin-top:4px">${e.g2_evidence_scope || ""}</div>
       <div style="margin-top:4px">frozen baseline ${j.byte_identical_to_frozen ? ok("byte-identical ✓") : '<span style="color:#e0556a">DIVERGED ✗</span>'} · artifact <code>${j.latest_artifact}</code></div>
       <div style="color:var(--muted);margin-top:4px"><b>next gate:</b> ${e.next_gate || ""}</div>
       <div style="margin-top:6px;color:var(--muted)">Full evidence (head-to-head, cross-dataset generalization, photometric depth pass, the executed notebooks): <a href="https://stewie-sw.github.io/stewie/" target="_blank" rel="noopener">documentation ↗</a></div>
     </div>`;
  }

  var API = { evidenceHTML: evidenceHTML, gateEvidenceHTML: gateEvidenceHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_EVIDENCE_HTML = API;                                   // browser (window)
})(typeof window !== "undefined" ? window : null);
