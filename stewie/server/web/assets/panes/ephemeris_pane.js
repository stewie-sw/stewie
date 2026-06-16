// Phase 2 / FS-15: the Solar/Ephemeris PANE component. PURE render: a view STATE (produced by
// STEWIE_ADAPTERS.toViewState from the /ephemeris contract) -> an HTML string. Handles loading/ok/
// empty/error. No fetch, no DOM mutation here -- the cockpit mounts the returned HTML. The azimuth
// convention is shown verbatim (FS-06/§25.3). node:test'able + browser-previewable.
(function (root) {
  "use strict";
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function renderEphemerisPane(vs) {
    if (!vs || vs.state === "loading")
      return '<div class="eph-pane" data-state="loading"><div class="muted">Resolving sun geometry…</div></div>';
    if (vs.state === "error")
      return '<div class="eph-pane" data-state="error"><div class="bad">Ephemeris error: ' +
        esc(vs.error || "unknown") + "</div></div>";
    if (vs.state === "empty")
      return '<div class="eph-pane" data-state="empty"><div class="muted">No ephemeris for this site/time.</div></div>';
    var d = vs.data;
    var badge = d.lit ? '<span class="badge lit">SUNLIT</span>'
                      : '<span class="badge dark">SHADOWED</span>';
    return '<div class="eph-pane" data-state="ok">' +
      '<div class="row head"><b>SUN</b> ' + badge + "</div>" +
      '<div class="row">azimuth <b>' + d.sun.azDeg.toFixed(1) + "&deg;</b> " +
        '<span class="conv">(' + esc(d.sun.convention) + ")</span></div>" +
      '<div class="row">elevation <b>' + d.sun.elDeg.toFixed(1) + "&deg;</b></div>" +
      '<div class="row muted">' + esc(d.site.frame) + " &middot; src " + esc(d.source) + "</div>" +
      "</div>";
  }

  var API = { renderEphemerisPane: renderEphemerisPane };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  if (root) root.STEWIE_PANE_EPHEMERIS = API;
})(typeof window !== "undefined" ? window : null);
