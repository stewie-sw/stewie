// #40 graticule — pure generation of a lunar graticule's meridian / parallel / km-grid polylines. Given an
// injected reproject(lon,lat)->[x,y] (proj4 IAU_2015:30100 -> 30135 in the app), it returns the polyline
// coordinate arrays + labels the OL vector layer draws. Selenographic lines are sampled densely then
// reprojected so they curve correctly in the polar-stereographic view; the km grid is straight in the metric
// frame. No OL / DOM here -> node-testable. UMD (browser <script> + node --test).
(function (root, factory) {
  if (typeof module === "object" && module.exports) { module.exports = factory(); }
  else { root.STEWIEGraticule = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  function _range(a, b, step) { var out = [], v = a; for (; v <= b + 1e-9; v += step) { out.push(Math.round(v * 1e6) / 1e6); } return out; }

  // Selenographic meridians (constant-lon), sampled in lat then reprojected to the map frame.
  function meridians(reproject, opts) {
    opts = opts || {};
    var lonStep = opts.lonStep || 30,
        latMin = opts.latMin != null ? opts.latMin : -89,
        latMax = opts.latMax != null ? opts.latMax : -55,
        latSample = opts.latSample || 0.5, out = [];
    for (var lon = 0; lon < 360; lon += lonStep) {
      var pts = _range(latMin, latMax, latSample).map(function (lat) { return reproject(lon, lat); });
      out.push({ coords: pts, label: lon + "°", lon: lon, kind: "meridian" });
    }
    return out;
  }

  // Selenographic parallels (constant-lat circles), sampled in lon then reprojected.
  function parallels(reproject, opts) {
    opts = opts || {};
    var latStep = opts.latStep || 5,
        latMin = opts.latMin != null ? opts.latMin : -85,
        latMax = opts.latMax != null ? opts.latMax : -55,
        lonSample = opts.lonSample || 2, out = [];
    _range(latMin, latMax, latStep).forEach(function (lat) {
      var pts = _range(0, 360, lonSample).map(function (lon) { return reproject(lon, lat); });
      out.push({ coords: pts, label: lat + "°", lat: lat, kind: "parallel" });
    });
    return out;
  }

  // Polar METRIC km grid: straight lines every stepKm in the 30135 metric frame over [-halfKm, halfKm].
  function kmGrid(opts) {
    opts = opts || {};
    var stepKm = opts.stepKm || 50, halfKm = opts.halfKm || 400, stepM = stepKm * 1000, halfM = halfKm * 1000, out = [];
    _range(-halfM, halfM, stepM).forEach(function (x) { out.push({ coords: [[x, -halfM], [x, halfM]], label: (x / 1000) + " km", axis: "x", kind: "km" }); });
    _range(-halfM, halfM, stepM).forEach(function (y) { out.push({ coords: [[-halfM, y], [halfM, y]], label: (y / 1000) + " km", axis: "y", kind: "km" }); });
    return out;
  }

  function selenographic(reproject, opts) { return meridians(reproject, opts).concat(parallels(reproject, opts)); }

  return { meridians: meridians, parallels: parallels, kmGrid: kmGrid, selenographic: selenographic };
});
