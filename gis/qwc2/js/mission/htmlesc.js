// VERBATIM LIFT of stewie/server/web/assets/htmlesc.js (STEWIE FS-24 pure string helper). The cockpit
// /program page loads it via <script src="/assets/htmlesc.js"> before program_board.js; the QWC2 IDE
// bundles it the same way (webpack) so programBoard.js's renderers get the identical esc(). No DOM, no
// globals. Source of truth stays stewie/server/web/assets/htmlesc.js; do not edit the escaping logic here.
(function (root) {
  "use strict";

  var _ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  // null/undefined -> "", then replace the five HTML-significant characters with their entities.
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return _ESC[c]; }); }

  var API = { esc: esc };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_HTMLESC = API;                                          // browser (window)
})(typeof window !== "undefined" ? window : null);
