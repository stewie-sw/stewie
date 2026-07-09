// viz.stewie.space: pure generation of the metric km grid for the 3D terrain surface. Straight lines in the
// order-LOCAL metre frame [0, win]^2 (x East, y North) at a round-number spacing; the curved lon/lat graticule
// is the server's /dem/graticule (mirrors graticule.js). No THREE / DOM here -> node-testable. UMD (browser
// <script> sets window.STEWIE_VIZGRID + node --test require).
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIE_VIZGRID = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // A round-number step (1/2/5 x 10^k) that fits ~target lines across a span -- so grid labels read cleanly.
  function niceStep(span, target) {
    if (!(span > 0) || !(target > 0)) { return 1; }
    var raw = span / target;
    var k = Math.floor(Math.log10(raw));
    var base = raw / Math.pow(10, k);
    var mult = base < 1.5 ? 1 : (base < 3.5 ? 2 : 5);
    return mult * Math.pow(10, k);
  }

  // Label a distance in metres: km past 1000 m (trimmed), else metres. e.g. 500 -> "500 m", 2000 -> "2 km".
  function label(m) {
    if (Math.abs(m) >= 1000) { return (Math.round(m / 100) / 10) + " km"; }
    return Math.round(m) + " m";
  }

  // Grid lines over [0, win]^2 at `stepM` (auto if omitted). Each line is a straight order-frame segment the
  // caller drapes onto the surface (sampling height along it). axis 'x' = constant-x meridian-of-metres line
  // (runs in +y/North); axis 'y' = constant-y line (runs in +x/East). Includes both borders (0 and win).
  function metricGrid(win, stepM, opts) {
    opts = opts || {};
    win = +win;
    if (!(win > 0)) { return []; }
    var step = (stepM && stepM > 0) ? +stepM : niceStep(win, opts.target || 8);
    var out = [], v, eps = 1e-6;
    for (v = 0; v <= win + eps; v += step) {
      var x = Math.min(v, win);
      out.push({ coords: [[x, 0], [x, win]], value: x, label: label(x), axis: "x" });
    }
    for (v = 0; v <= win + eps; v += step) {
      var y = Math.min(v, win);
      out.push({ coords: [[0, y], [win, y]], value: y, label: label(y), axis: "y" });
    }
    return { step: step, lines: out };
  }

  return { metricGrid: metricGrid, niceStep: niceStep, label: label };
});
