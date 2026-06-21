// FS-24: HTML-entity escaping. The single pure string helper the cockpit uses when it must put
// server-derived text into a template-literal-built HTML fragment (the few innerHTML paths that
// remain alongside the S-02 el() builder). Escapes the five HTML-significant characters so an
// `<img onerror>`-style value renders inert. No DOM, no globals -- extracted from cockpit.js
// (PRD FS-24) verbatim so it is unit-testable without a browser; behaviour is preserved exactly.
// node:test'able.
(function (root) {
  "use strict";

  var _ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

  // null/undefined -> "", then replace the five HTML-significant characters with their entities.
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return _ESC[c]; }); }

  var API = { esc: esc };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_HTMLESC = API;                                          // browser (window)
})(typeof window !== "undefined" ? window : null);
