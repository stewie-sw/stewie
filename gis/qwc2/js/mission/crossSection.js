// #45 resource cross-section: pure geometry for the transect profile. Densifies a drawn transect polyline to
// uniform along-arc samples for POST /world/transect, and derives the chart series / PSR shading bands from the
// response. No OL/DOM/React here -> node-testable. UMD (browser <script> + node --test).
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIECrossSection = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Densify a transect polyline (order-frame [x,y] metre vertices) to N points EVENLY spaced by ARC LENGTH, so
  // the /world/transect samples are uniform along the line regardless of vertex spacing. Clamped to [2,512].
  function densify(vertices, targetN) {
    if (!vertices || vertices.length < 2) { return vertices ? vertices.map(function (p) { return p.slice(); }) : []; }
    var n = Math.max(2, Math.min(512, Math.floor(targetN) || 2));
    var segLen = [], total = 0, i;
    for (i = 1; i < vertices.length; i++) {
      var l = Math.hypot(vertices[i][0] - vertices[i - 1][0], vertices[i][1] - vertices[i - 1][1]);
      segLen.push(l); total += l;
    }
    if (!(total > 0)) { return [vertices[0].slice(), vertices[0].slice()]; }   // degenerate: a point
    var out = [];
    for (var k = 0; k < n; k++) {
      var target = total * k / (n - 1), acc = 0, seg = 0;
      while (seg < segLen.length - 1 && acc + segLen[seg] < target) { acc += segLen[seg]; seg++; }
      var t = segLen[seg] > 0 ? (target - acc) / segLen[seg] : 0;
      var a = vertices[seg], b = vertices[seg + 1];
      out.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
    }
    return out;
  }

  // Extract a {dist, value} series for one numeric field from a /world/transect samples[], dropping null /
  // out-of-bounds (never invent a value for a missing cell).
  function series(samples, key) {
    var out = [];
    (samples || []).forEach(function (s) {
      if (s && typeof s[key] === "number" && isFinite(s[key])) { out.push({ dist: s.dist_m, value: s[key] }); }
    });
    return out;
  }

  // [min, max] of a series' values for chart scaling; [0,1] if empty, and widened if flat.
  function extent(pts) {
    if (!pts || !pts.length) { return [0, 1]; }
    var lo = pts[0].value, hi = pts[0].value;
    pts.forEach(function (p) { if (p.value < lo) { lo = p.value; } if (p.value > hi) { hi = p.value; } });
    if (lo === hi) { hi = lo + 1; }
    return [lo, hi];
  }

  // Along-distance ranges [d0,d1] where psr === true (a run of permanently-shadowed samples), for the PSR
  // shading band under the profile. Only TRUE contributes; null/false break a run.
  function psrBands(samples) {
    var bands = [], start = null, lastTrue = null;
    (samples || []).forEach(function (s) {
      if (s && s.psr === true) {
        if (start === null) { start = s.dist_m; }
        lastTrue = s.dist_m;
      } else if (start !== null) {
        bands.push([start, lastTrue]); start = null; lastTrue = null;
      }
    });
    if (start !== null) { bands.push([start, lastTrue]); }
    return bands;
  }

  return { densify: densify, series: series, extent: extent, psrBands: psrBands };
});
