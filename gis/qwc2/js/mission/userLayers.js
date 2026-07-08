/**
 * userLayers — the PURE logic behind the IDE's user-layers subsystem (#44, the unbuilt LY-01 clause):
 * parse a pasted/imported GeoJSON and CRS-VALIDATE it against the lunar frame BEFORE it can touch the map or
 * planning. STEWIE is lunar (IAU_2015:30135 south-polar metric / 30100 selenographic lon/lat); a layer that
 * declares an EARTH CRS (EPSG:4326/3857/2056/WGS84/CRS84 -- the #40 Earth-CRS trap) would misplace every
 * feature, so it is rejected with a legible reason. No DOM/OpenLayers -> node-testable.
 */
(function (root) {
  "use strict";

  function parseUserLayer(text) {
    var gj;
    try { gj = JSON.parse(text); } catch (e) { return { ok: false, error: "not valid JSON: " + e.message }; }
    if (!gj || (gj.type !== "FeatureCollection" && gj.type !== "Feature")) {
      return { ok: false, error: "not GeoJSON — need a Feature or FeatureCollection" };
    }
    var features = gj.type === "FeatureCollection" ? (gj.features || []) : [gj];
    return { ok: true, geojson: gj, featureCount: features.length };
  }

  // The GeoJSON crs member (RFC 7946 deprecated it in favour of mandatory WGS84, but many exporters still
  // emit it; its absence therefore *implies* Earth WGS84 -- which in a lunar tool we treat as "assume lunar").
  function _crsName(geojson) {
    if (geojson && geojson.crs && geojson.crs.properties && geojson.crs.properties.name) {
      return String(geojson.crs.properties.name);
    }
    return null;
  }

  function validateLayerCrs(geojson) {
    var name = _crsName(geojson);
    if (name === null) {
      return { ok: true, crs: null, isLunar: false, isEarth: false,
               warning: "No CRS declared — assuming lunar selenographic lon/lat (IAU_2015:30100). Add a crs member to be explicit." };
    }
    var upper = name.toUpperCase();
    if (upper.indexOf("IAU") >= 0 || upper.indexOf("MOON") >= 0 || upper.indexOf("30135") >= 0 || upper.indexOf("30100") >= 0) {
      return { ok: true, crs: name, isLunar: true, isEarth: false, warning: null };
    }
    if (upper.indexOf("WGS") >= 0 || upper.indexOf("4326") >= 0 || upper.indexOf("3857") >= 0 ||
        upper.indexOf("CRS84") >= 0 || upper.indexOf("2056") >= 0 || upper.indexOf("EPSG") >= 0) {
      return { ok: false, crs: name, isLunar: false, isEarth: true,
               warning: "This layer declares an EARTH CRS (" + name + "). STEWIE is lunar (IAU_2015) — importing it would misplace every feature. Re-project to IAU_2015:30100 (lon/lat) or 30135 (metric) first." };
    }
    return { ok: false, crs: name, isLunar: false, isEarth: false,
             warning: "Unknown CRS '" + name + "'. Declare IAU_2015:30100 (selenographic lon/lat) or 30135 (south-polar metric)." };
  }

  var API = { parseUserLayer: parseUserLayer, validateLayerCrs: validateLayerCrs };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_USER_LAYERS = API; }                                     // browser (window)
})(typeof window !== "undefined" ? window : null);
