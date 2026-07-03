// [REQ:FR-13] Pure render of a RegolithVolumeEstimate (from POST /siteplan/volume): the moved mass with its
// uncertainty band, confidence class, acceptance status, and the conservation + drum cross-checks. CSP-safe
// (no inline handlers), no fabricated data -- every number is straight from the estimate contract.
(function (root) {
  "use strict";

  function _kg(x) { return (x === null || x === undefined) ? "—" : Number(x).toFixed(1) + " kg"; }

  function volumeEvidenceHTML(ev, esc) {
    esc = esc || function (s) { return String(s); };
    if (!ev || ev.observed_mass_kg === null || ev.observed_mass_kg === undefined) {
      return '<div class="empty">No volume evidence yet — analyze a plan.</div>';
    }
    var accepted = ev.acceptance === "accepted";
    var ufPct = (Number(ev.uncertainty_frac || 0) * 100).toFixed(1);
    var rows = [
      ["Moved mass", _kg(ev.observed_mass_kg) + " ± " + _kg(ev.uncertainty_kg) + " (" + ufPct + "%)"],
      ["Band", _kg(ev.lower_kg) + " … " + _kg(ev.upper_kg)],
      ["Confidence", String(ev.confidence_class || "—")],
      ["Conservation", ev.agreement_conserved === null || ev.agreement_conserved === undefined ? "—"
        : (ev.agreement_conserved ? "agrees" : "MISMATCH") + " (err " + _kg(ev.conserved_err_kg) + ")"],
      ["Drum cross-check", ev.agreement_drum === null || ev.agreement_drum === undefined ? "not run"
        : (ev.agreement_drum ? "agrees" : "MISMATCH")],
      ["Transaction", String(ev.transaction_id || "—")],
    ];
    var h = '<div class="volev">';
    h += '<div class="volev-accept ' + (accepted ? "ok" : "review") + '">' + (accepted ? "ACCEPTED" : "REVIEW") + "</div>";
    h += '<table class="volev-tbl">';
    for (var i = 0; i < rows.length; i++) {
      h += "<tr><td class=\"volev-k\">" + esc(rows[i][0]) + "</td><td>" + esc(rows[i][1]) + "</td></tr>";
    }
    h += "</table></div>";
    return h;
  }

  root.STEWIE_VOLUME_EVIDENCE = { volumeEvidenceHTML: volumeEvidenceHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = root.STEWIE_VOLUME_EVIDENCE;
})(typeof window !== "undefined" ? window : globalThis);
