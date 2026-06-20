// FS-24: site-frame GEOMETRY + COORDINATE FORMATTING helpers. Pure functions the cockpit's "where are we"
// locator (#174) uses to render distance + compass bearing from the rover to the lander/landmarks and to
// print selenographic coordinates next to order-frame metres. No DOM, no network, no globals here -- the
// cockpit (updateLocator) wires fetch + DOM on top. Extracted from cockpit.js (PRD FS-24) so the angle math
// is unit-testable without a browser; behaviour is preserved verbatim. node:test'able.
(function (root) {
  "use strict";

  // East/North deltas (site frame: +x = East, +y = North) -> "DEG° DIR" compass string.
  // 0 deg = North, 90 deg = East; the 16-point rose is rounded to the nearest 22.5 deg sector.
  function bearingFrom(dE, dN) {
    var b = Math.atan2(dE, dN) * 180 / Math.PI;            // 0 deg = North, 90 deg = East
    if (b < 0) b += 360;
    var dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
    return b.toFixed(0) + "° " + dirs[Math.round(b / 22.5) % 16];
  }

  // a {lat, lon} (degrees) -> "LAT°, LON°" at 4 decimals, or the em-dash placeholder when absent.
  function fmtLL(ll) {
    return ll ? (ll.lat.toFixed(4) + "°, " + ll.lon.toFixed(4) + "°") : "—";
  }

  var API = { bearingFrom: bearingFrom, fmtLL: fmtLL };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_GEOFMT = API;                                          // browser (window)
})(typeof window !== "undefined" ? window : null);
