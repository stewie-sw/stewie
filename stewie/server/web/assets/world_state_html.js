// FS-24: pure Report-pane world-state + terrain-provenance HTML builders. No DOM, no fetch, no globals --
// take the /world/transaction(+/world/transactions) and /world/terrain_view payloads + an esc(), and return
// an HTML string (or null when there is nothing to show, so the caller hides the block). The fetch +
// innerHTML + style wiring stays in cockpit.js. Sets window.STEWIE_WORLD_STATE_HTML.
(function (root) {
  "use strict";

  function _sh(s, esc) { return esc(String(s || "").slice(0, 12)) + "…"; }   // short sha + ellipsis

  // latest = GET /world/transaction ({committed, count, transaction}); txns = the /world/transactions list.
  // Returns null when nothing is committed yet (no fabricated state -- the caller hides the block).
  function worldStateHTML(latest, txns, esc) {
    if (!latest || !latest.committed) return null;
    const t = latest.transaction;
    const rows = txns || [];
    let html =
      '<div class="cap"><span>LINKED WORLD STATE — DT-01</span></div>'
      + '<div style="font-size:11px;font-variant-numeric:tabular-nums;line-height:1.7;color:var(--muted)">'
      + "authority <code>" + _sh(t.authority_sha, esc) + "</code> · twin v" + esc(String(t.twin_version))
      + " · plan <code>" + esc(String(t.plan_id)) + "</code><br>"
      + "world_sha <code>" + _sh(t.world_sha, esc) + "</code> · seq " + esc(String(t.seq))
      + " · " + esc(String(latest.count)) + " transaction(s)</div>";
    html += '<div class="cap" style="margin-top:8px"><span>EXECUTION TIMELINE</span></div>'
      + '<div style="font-size:11px;line-height:1.6;max-height:200px;overflow:auto">'
      + (rows.length
          ? rows.map(function (x) {
              const m = /\[(\w+)\]/.exec(x.provenance || "");
              const tag = m ? m[1] : "";
              const color = tag === "ok" ? "var(--accent)"
                : (tag === "safed" || tag === "blocked") ? "#e0a000" : "var(--muted)";
              return '<div><span style="color:var(--muted)">#' + esc(String(x.seq)) + "</span> "
                + '<span style="color:' + color + '">' + esc(x.provenance) + "</span></div>";
            }).join("")
          : '<div class="empty">No transitions recorded yet.</div>')
      + "</div>";
    return html;
  }

  // tv = GET /world/terrain_view ({ok, provenance}); imgSrc = the (cache-busted) raster URL the caller builds.
  // Returns null when the view is absent (site DEM missing) -- the caller hides the block.
  function terrainProvenanceHTML(tv, esc, imgSrc) {
    if (!tv || !tv.ok) return null;
    const pv = tv.provenance;
    const tot = (pv.rows * pv.cols) || 1;
    const pct = function (n) { return (100 * n / tot).toFixed(3); };
    return '<div class="cap"><span>TERRAIN PROVENANCE — measured vs remembered vs modeled</span></div>'
      + '<div style="font-size:11px;line-height:1.7;color:var(--muted)">'
      + '<span style="color:#28be5a">■</span> observed (measured) ' + esc(String(pv.cells.observed))
      + " (" + pct(pv.cells.observed) + "%) · "
      + '<span style="color:#2e6edc">■</span> as-built (remembered) ' + esc(String(pv.cells.as_built))
      + " (" + pct(pv.cells.as_built) + "%) · "
      + '<span style="color:#5a5a5a">■</span> pristine (modeled) ' + esc(String(pv.cells.pristine)) + "<br>"
      + "as-built v" + esc(String(pv.as_built_version)) + " · twin v" + esc(String(pv.twin_version))
      + " · observed fraction " + (pv.observed_fraction * 100).toFixed(3) + "%</div>"
      + '<img src="' + imgSrc + '" alt="terrain provenance source map" '
      + 'style="margin-top:8px;max-width:360px;border:1px solid var(--line);border-radius:6px;image-rendering:pixelated" />';
  }

  var API = { worldStateHTML: worldStateHTML, terrainProvenanceHTML: terrainProvenanceHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_WORLD_STATE_HTML = API;                                // browser (window)
})(typeof window !== "undefined" ? window : null);
