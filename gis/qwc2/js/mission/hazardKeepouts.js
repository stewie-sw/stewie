/**
 * hazardKeepouts — the PURE bridge for council #52 DERIVE KEEP-OUTS FROM HAZARD in the lunar IDE's
 * Mission-Plan panel. The backend's GET /api/world/keepouts-from-hazard is a PUBLIC, non-destructive map-data
 * read: for a site it auto-derives keep-out POLYGONS from the real terrain-hazard NOGO mask over the framed
 * work-area crop (the SAME FORGE costmap layers the planner routes on, scoped to physical barriers -- slope /
 * sinkage / tip-over / negative-obstacle -- with PSR shadow + operator keepout + reservation EXCLUDED), as a
 * GeoJSON FeatureCollection of Polygons in selenographic lon/lat (IAU_2015:30100).
 *
 * This module (a) builds the URL + fetches, (b) extracts each region's EXTERIOR ring (the avoid-region; a
 * single-ring planner keep-out cannot express a passable hole, so the exterior ring is the SAFE over-
 * approximation -- it never routes through a real hazard), and (c) ADDS them to the current mission through the
 * EXISTING keep-out path: it reprojects each lon/lat vertex to the map frame (IAU_2015:30135) via the injected
 * reproject (CoordinatesUtils.reproject, the SAME one planTools/graticule use) and calls the controller's
 * ``addKeepoutPolygon`` -- so a derived keep-out routes the planner around it AND renders exactly like a drawn
 * one. No DOM/React/OpenLayers here -> node-testable, exactly like siteSuitability.js / planTools.js.
 *   Run: node --test gis/qwc2/js/mission/hazardKeepouts.test.js
 */
(function (root) {
  "use strict";
  var API_BASE = "/api";                         // same-origin mission API (nginx proxies /api/). Overridable for tests.
  var GEO_CRS = "IAU_2015:30100";                // selenographic lon/lat (the GeoJSON's frame)
  var MAP_CRS = "IAU_2015:30135";                // the polar-stereographic workbench/map frame the keep-outs store in
  var MAX_RING_VERTS = 256;                      // MUST match server MAX_KEEPOUT_VERTS (edit_session.py) / planner cap
  function base() { return API_BASE; }
  function setApiBase(b) { API_BASE = b; }

  // The PUBLIC derive-keep-outs-from-hazard endpoint (per-site work-area hazard vector product).
  function url(site) { return API_BASE + "/world/keepouts-from-hazard?site=" + encodeURIComponent(site); }

  function fetchKeepouts(site) {
    return fetch(url(site)).then(function (r) {
      if (!r.ok) {
        // 404 = the site has no imported DEM bundle; surface the backend reason if present.
        return r.json().then(function (b) {
          throw new Error((b && b.error) || ("keepouts-from-hazard HTTP " + r.status));
        }, function () { throw new Error("keepouts-from-hazard HTTP " + r.status); });
      }
      return r.json();
    });
  }

  // Drop a ring's closing duplicate vertex (GeoJSON rings are closed: first === last) -> the OPEN ring the
  // backend keep-out schema wants (edit_session.py: "open ring, 3..MAX verts"). A ring already open is returned
  // as-is. Compares with a tiny epsilon so a rounded-coordinate close still de-duplicates.
  function openRing(ring) {
    if (!Array.isArray(ring) || ring.length < 2) { return ring || []; }
    var a = ring[0], b = ring[ring.length - 1];
    var closed = a && b && Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
    return closed ? ring.slice(0, -1) : ring.slice();
  }

  // Each derived region's EXTERIOR lon/lat ring (open), with its provenance. A polygon with holes keeps only
  // the exterior ring: an additive keep-out cannot re-allow a passable island, so covering it is the safe
  // (never-route-through-hazard) choice -- stated, not silent. Skips a feature whose exterior ring is degenerate.
  function exteriorRings(fc) {
    var out = [];
    var feats = (fc && fc.features) || [];
    for (var i = 0; i < feats.length; i++) {
      var f = feats[i];
      var g = f && f.geometry;
      if (!g || g.type !== "Polygon" || !Array.isArray(g.coordinates) || !g.coordinates.length) { continue; }
      var ring = openRing(g.coordinates[0]);
      if (ring.length < 3) { continue; }
      var props = f.properties || {};
      out.push({ ring: ring, area_m2: props.area_m2, holes: props.holes || 0 });
    }
    return out;
  }

  // Reproject each region's exterior lon/lat ring to a MAP-FRAME (IAU_2015:30135) open ring [[x, y], ...] via
  // the injected reproject([lon, lat], srcCrs, dstCrs) -> [x, y] (CoordinatesUtils.reproject). A vertex that
  // reprojects to a non-finite coord is dropped; a ring left with < 3 finite verts, or one over the vertex cap,
  // is skipped (counted) so an invalid polygon is never handed to the keep-out path. Pure: reproject injected.
  function toMapRings(fc, reproject, opts) {
    opts = opts || {};
    var geo = opts.geoCrs || GEO_CRS, map = opts.mapCrs || MAP_CRS;
    var cap = opts.maxVerts || MAX_RING_VERTS;
    var rings = [], skipped = 0;
    var regions = exteriorRings(fc);
    for (var i = 0; i < regions.length; i++) {
      var lonlat = regions[i].ring;
      if (lonlat.length > cap) { skipped++; continue; }     // too complex for a single keep-out -> skip, counted
      var mapRing = [];
      for (var j = 0; j < lonlat.length; j++) {
        var p = null;
        try { p = reproject([lonlat[j][0], lonlat[j][1]], geo, map); } catch (e) { p = null; }
        if (p && Number.isFinite(p[0]) && Number.isFinite(p[1])) { mapRing.push([p[0], p[1]]); }
      }
      if (mapRing.length >= 3) { rings.push(mapRing); } else { skipped++; }
    }
    return { rings: rings, skipped: skipped, total: regions.length };
  }

  // ADD the derived hazard regions to the current mission's keep-outs through the EXISTING keep-out path:
  // ctrl.addKeepoutPolygon(mapRing) for each region, SERIALLY (deterministic audit order, mirroring
  // clearKeepouts). Returns a Promise resolving to {added, skipped, total}. The controller writes each through
  // the backend edit-session (or the local fallback), so /api/plan then routes the mission around them.
  function addToMission(fc, ctrl, reproject, opts) {
    var res = toMapRings(fc, reproject, opts);
    if (!ctrl || typeof ctrl.addKeepoutPolygon !== "function") {
      return Promise.resolve({ added: 0, skipped: res.skipped, total: res.total });
    }
    var added = 0;
    var chain = res.rings.reduce(function (p, ring) {
      return p.then(function () {
        return Promise.resolve(ctrl.addKeepoutPolygon(ring)).then(function () { added += 1; });
      });
    }, Promise.resolve());
    return chain.then(function () { return { added: added, skipped: res.skipped, total: res.total }; });
  }

  var API = {
    base: base, setApiBase: setApiBase, url: url, fetchKeepouts: fetchKeepouts,
    openRing: openRing, exteriorRings: exteriorRings, toMapRings: toMapRings, addToMission: addToMission,
    GEO_CRS: GEO_CRS, MAP_CRS: MAP_CRS, MAX_RING_VERTS: MAX_RING_VERTS
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_HAZARD_KEEPOUTS = API; }                                 // browser (window)
})(typeof window !== "undefined" ? window : null);
