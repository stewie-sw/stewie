// FS-24: keep-out GEOMETRY classification + measurement. Pure functions over a keep-out object {k}
// in the site/local frame: which shape is it (polygon / rect / disc), what is its axis-aligned
// bounding box, and a human-readable summary. No DOM, no canvas, no globals -- the cockpit's
// fillKeepout() wires the 2D-canvas drawing on top of these, and renderKeepouts() / _planExtent()
// consume koLabel/koBounds. Extracted from cockpit.js (PRD FS-24) verbatim so the shape math is
// unit-testable without a browser; behaviour is preserved exactly (matches the Python
// keepout_is_poly / keepout_is_rect predicates). node:test'able.
(function (root) {
  "use strict";

  // #178: polygon keep-out -- a points array with at least 3 vertices (matches keepout_is_poly).
  function koIsPoly(k) { return !!(k && Array.isArray(k.points) && k.points.length >= 3); }

  // #178: rect keep-out -- no radius but has a corner (matches keepout_is_rect).
  function koIsRect(k) { return k && k.r == null && k.x0 != null; }

  // #178: a keep-out's local-frame axis-aligned bounding box, any shape.
  function koBounds(k) {
    if (koIsPoly(k)) {
      const xs = k.points.map((p) => p[0]), ys = k.points.map((p) => p[1]);
      return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
    }
    return koIsRect(k)
      ? { x0: Math.min(k.x0, k.x1), y0: Math.min(k.y0, k.y1), x1: Math.max(k.x0, k.x1), y1: Math.max(k.y0, k.y1) }
      : { x0: k.x - k.r, y0: k.y - k.r, x1: k.x + k.r, y1: k.y + k.r };
  }

  // #178: a human-readable keep-out summary (polygon vertex count / box corners / circle centre+radius).
  function koLabel(k) {
    if (koIsPoly(k)) return `polygon (${k.points.length} pts)`;
    return koIsRect(k) ? `box [${Math.round(k.x0)},${Math.round(k.y0)}]–[${Math.round(k.x1)},${Math.round(k.y1)}] m`
                       : `circle @ ${k.x},${k.y} · r ${k.r} m`;
  }

  var API = { koIsPoly: koIsPoly, koIsRect: koIsRect, koBounds: koBounds, koLabel: koLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_KEEPOUT_GEOM = API;                                     // browser (window)
})(typeof window !== "undefined" ? window : null);
