/**
 * siteZoom — pure hit-test + framing-box logic for CLICK-A-SITE-TO-ZOOM on the STEWIE lunar IDE main map
 * (artemis.stewie.space/ide/). The complaint was "can't click on locations to zoom in": the Whole Moon
 * overlay already dives on a site click (js/mission/wholeMoonGlobe.js + js/plugins/WholeMoon.jsx), but the
 * SOUTH-POLAR workbench map's Artemis site markers were static. This module is the framework-agnostic core
 * the SiteZoom plugin (js/plugins/SiteZoom.jsx) uses to turn a main-map singleclick into the SAME dive.
 *
 * REUSE, not reinvent: the framing box + CRS are IDENTICAL to WholeMoon.dive (WholeMoon.jsx), so a click on
 * the main map flies to EXACTLY the box the Whole Moon overlay dives to. The site registry is the same real
 * /api/sites payload the overlay's markers come from ({name, label, lat, lon, imported, ...} — stewie/specs/
 * sites.py site_rows()). Site centers arrive in selenographic lon/lat (GEO_CRS); the caller reprojects them to
 * the map's polar-stereographic CRS (state.map.projection = IAU_2015:30135) with CoordinatesUtils.reproject
 * before the hit-test, so both the hit region and the zoom target live in map coordinates.
 *
 * Pure (no DOM, no OpenLayers, no React) -> node:test-able in bare node. The interactive proof (a real click
 * flies the workbench) is the SiteZoom plugin driven by Playwright.
 *   Run: node --test gis/qwc2/js/mission/siteZoom.test.js
 */
(function (root) {
    "use strict";

    // Selenographic lon/lat CRS the /api/sites site centers arrive in. IDENTICAL to WholeMoon.jsx GEO_CRS.
    var GEO_CRS = "IAU_2015:30100";
    // Half-width (metres, in the map's polar-stereographic CRS) of the framing box a site click flies to.
    // IDENTICAL to WholeMoon.jsx DIVE_HALF_M (a ~60 km box). Kept in LOCKSTEP so the main-map dive is the same
    // dive as the Whole Moon overlay; siteZoom.test.js guards these two constants against drift.
    var HALF_M = 30000;

    // The axis-aligned framing box [xmin, ymin, xmax, ymax] around a site center [x, y] (map-CRS metres) —
    // exactly WholeMoon.dive's box (c[0]-H, c[1]-H, c[0]+H, c[1]+H).
    function zoomBox(center, halfM) {
        var h = (typeof halfM === "number") ? halfM : HALF_M;
        return [center[0] - h, center[1] - h, center[0] + h, center[1] + h];
    }

    // [lon, lat] of a /api/sites row, or null if it lacks numeric coords (the SAME guard as WholeMoon.dive:
    // `typeof site.lon !== 'number' || typeof site.lat !== 'number'`).
    function siteLonLat(site) {
        if (!site || typeof site.lon !== "number" || typeof site.lat !== "number") { return null; }
        return [site.lon, site.lat];
    }

    function inBox(coord, box) {
        return coord[0] >= box[0] && coord[0] <= box[2] && coord[1] >= box[1] && coord[1] <= box[3];
    }

    // Hit-test a map-CRS click against site centers ALREADY in map coordinates. `entries` is
    // [{..payload, center: [x, y]}, ...]; returns the entry whose framing box contains the click, choosing the
    // NEAREST center when overlapping boxes both contain it, else null (-> the caller does nothing, so the
    // default map behavior — pan / scroll+double-click zoom / Identify — stands). The returned entry carries
    // the `extent` the caller passes straight to zoomToExtent.
    function pickCenterAt(coord, entries, halfM) {
        if (!coord || !Array.isArray(entries)) { return null; }
        var h = (typeof halfM === "number") ? halfM : HALF_M;
        var best = null, bestD = Infinity;
        for (var i = 0; i < entries.length; i++) {
            var e = entries[i];
            var c = e && e.center;
            if (!c || !isFinite(c[0]) || !isFinite(c[1])) { continue; }
            var box = zoomBox(c, h);
            if (!inBox(coord, box)) { continue; }
            var dx = coord[0] - c[0], dy = coord[1] - c[1], d = dx * dx + dy * dy;
            if (d < bestD) { bestD = d; best = { site: e.site, center: c, extent: box }; }
        }
        return best;
    }

    // The plugin's entry point: reproject each /api/sites row's center (GEO_CRS -> mapCrs) with the injected
    // `reproject(coord, srcCrs, dstCrs) -> [x, y]` (CoordinatesUtils.reproject), then hit-test the click.
    // Rows without numeric coords, or that fail to reproject, are skipped honestly (no fabricated position).
    // Returns {site, center, extent} | null; `extent` == zoomBox(reproject(center)) — the WholeMoon dive box.
    function pickSiteAt(coord, sites, reproject, mapCrs, halfM) {
        if (!coord || !Array.isArray(sites) || typeof reproject !== "function") { return null; }
        var entries = [];
        for (var i = 0; i < sites.length; i++) {
            var ll = siteLonLat(sites[i]);
            if (!ll) { continue; }
            var c;
            try { c = reproject(ll, GEO_CRS, mapCrs); } catch (e) { continue; }
            if (!c || !isFinite(c[0]) || !isFinite(c[1])) { continue; }
            entries.push({ site: sites[i], center: c });
        }
        return pickCenterAt(coord, entries, halfM);
    }

    var API = {
        GEO_CRS: GEO_CRS,
        HALF_M: HALF_M,
        zoomBox: zoomBox,
        siteLonLat: siteLonLat,
        pickCenterAt: pickCenterAt,
        pickSiteAt: pickSiteAt
    };
    if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
    if (root) { root.STEWIE_SITE_ZOOM = API; }                                       // browser (window)
})(typeof window !== "undefined" ? window : null);
