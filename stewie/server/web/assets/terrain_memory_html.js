// FS-24: pure Construction-pane Terrain Memory readout (W3). terrainMemoryHTML() renders the site's
// authoritative world-state summary (GET /twin/terrain/{site}) or the "nothing recorded yet" prompt;
// unavailableHTML() is the shared error line. Payload -> HTML string (no DOM); the fetch + innerHTML
// wiring stays in cockpit.js. Sets window.STEWIE_TERRAIN_MEMORY_HTML.
(function (root) {
  "use strict";

  function unavailableHTML(detail, esc) {
    return '<div class="empty">Terrain memory unavailable (' + (esc ? esc(String(detail)) : detail) + ").</div>";
  }

  // t = GET /twin/terrain/{site}. Recorded -> the change summary; not recorded -> the record prompt.
  function terrainMemoryHTML(t, site, esc) {
    if (!t || !t.recorded) {
      return '<div class="empty">No terrain changes recorded for <b>' + esc(site) + "</b> yet — "
        + "record a plan below and the site starts remembering what was built.</div>";
    }
    const miss = (t.missions || []).map(esc).join(", ") || "—";
    return "<b>" + esc(site) + "</b> · v" + t.version + " · "
      + (t.chain_valid ? "chain ✓" : "<span style='color:#e8273f'>chain ✗</span>") + "<br>"
      + "cells changed <b>" + (t.cells_changed || 0).toLocaleString() + "</b> · net volume <b>"
      + (t.net_volume_m3 || 0).toFixed(2) + " m³</b><br>"
      + "deepest cut <b>" + ((t.max_cut_m || 0) * 100).toFixed(1) + " cm</b> · highest build <b>"
      + ((t.max_fill_m || 0) * 100).toFixed(1) + " cm</b><br>missions: " + miss;
  }

  var API = { unavailableHTML: unavailableHTML, terrainMemoryHTML: terrainMemoryHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_TERRAIN_MEMORY_HTML = API;                             // browser (window)
})(typeof window !== "undefined" ? window : null);
