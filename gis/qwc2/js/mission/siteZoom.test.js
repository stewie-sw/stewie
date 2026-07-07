// CLICK-A-SITE-TO-ZOOM (node:test): the main-map site-click hit-test + framing-box math are pure (no DOM, no
// OpenLayers, no React), so they unit-test in bare node -- NO external deps (the CI browser-JS tier runs
// `node --test` with no npm install; ci.yml:87). This asserts the REAL outputs of siteZoom.js against REAL
// Artemis III LOLA-5m site data.
//
// REAL DATA PROVENANCE: the site centers below are the committed Artemis III LOLA-5m footprints produced by
// gis/build_project.py -> data/gis/vectors/artemis_sites.geojson (derived from the PGDA Product 78 DEM COG
// extents). Each row's selenographic center [lon, lat] (IAU_2015:30100) is paired with its map-CRS center
// [x, y] (IAU_2015:30135) = the midpoint of that footprint's real `extent_m`. The lon/lat -> x/y pairs were
// cross-checked against a live proj4 reprojection (`+proj=stere +lat_0=-90 +R=1737400` vs `+proj=longlat
// +R=1737400`) and matched the real extents to <= 0.01 m. Nothing here is fabricated: these are real DEM
// extents, and the injected reproject is a lookup of those real proj4 results (so pickSiteAt is exercised on
// real values without depending on proj4 being installed in the CI node tier).
//
// Run: node --test gis/qwc2/js/mission/siteZoom.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const SZ = require("./siteZoom.js");

// REAL rows shaped like a /api/sites payload row ({name, label, lon, lat}) + the real map-CRS center the
// caller's reproject yields. site key/label are the build's real Artemis-candidate names.
const REAL = [
    { name: "Site01", lon: -137.489553, lat: -89.463163, xy: [-11000, -12000] },
    { name: "Site04", lon: -171.869898, lat: -89.766811, xy: [-1000, -7000] },
    { name: "Site06", lon: 37.366669, lat: -85.4381, xy: [84000, 110000] },
    { name: "Site07", lon: 123.690068, lat: -88.811008, xy: [30000, -20000] },
    { name: "Site11", lon: -67.9321, lat: -88.683418, xy: [-37000, 15000] },
    { name: "Site20", lon: 31.742761, lat: -85.426577, xy: [73000, 118000] },
    { name: "Site23", lon: -0.235784, lat: -85.994785, xy: [-500, 121500] },
    { name: "Site42", lon: -116.322016, lat: -85.829551, xy: [-113400, -56100] }
];
const SITES = REAL.map((r) => ({ name: r.name, label: r.name, lon: r.lon, lat: r.lat }));
const ENTRIES = REAL.map((r) => ({ site: { name: r.name, label: r.name }, center: r.xy.slice() }));
// A reproject lookup over the REAL lon/lat -> x/y pairs (the exact proj4 result), so pickSiteAt runs the real
// reproject-then-hit-test path with no external dependency. Signature matches CoordinatesUtils.reproject.
const MAP_CRS = "IAU_2015:30135";
function lookupReproject(coord, src, dst) {
    assert.strictEqual(src, SZ.GEO_CRS);   // the plugin reprojects FROM selenographic lon/lat...
    assert.strictEqual(dst, MAP_CRS);      // ...TO the workbench map CRS
    for (const r of REAL) {
        if (Math.abs(coord[0] - r.lon) < 1e-9 && Math.abs(coord[1] - r.lat) < 1e-9) { return r.xy.slice(); }
    }
    throw new Error("no real reprojection for " + coord);
}

test("constants are in LOCKSTEP with WholeMoon.jsx (same dive box + CRS)", () => {
    assert.strictEqual(SZ.HALF_M, 30000, "must equal WholeMoon.jsx DIVE_HALF_M");
    assert.strictEqual(SZ.GEO_CRS, "IAU_2015:30100", "must equal WholeMoon.jsx GEO_CRS");
});

test("zoomBox is the WholeMoon dive box around a center", () => {
    assert.deepStrictEqual(SZ.zoomBox([100, 200], 30000), [-29900, -29800, 30100, 30200]);
    // default half-width == HALF_M (so main-map dive == Whole Moon dive)
    assert.deepStrictEqual(SZ.zoomBox([0, 0]), [-30000, -30000, 30000, 30000]);
});

test("siteLonLat guards non-numeric coords exactly like WholeMoon.dive", () => {
    assert.deepStrictEqual(SZ.siteLonLat({ lon: 1.5, lat: -85 }), [1.5, -85]);
    assert.strictEqual(SZ.siteLonLat({ lon: null, lat: -85 }), null);
    assert.strictEqual(SZ.siteLonLat({ lat: -85 }), null);
    assert.strictEqual(SZ.siteLonLat(null), null);
});

test("a click ON each real site center hits that site and returns its dive box", () => {
    for (const r of REAL) {
        const hit = SZ.pickCenterAt(r.xy, ENTRIES, SZ.HALF_M);
        assert.ok(hit, "click on " + r.name + " center should hit");
        assert.strictEqual(hit.site.name, r.name);
        assert.deepStrictEqual(hit.extent, SZ.zoomBox(r.xy, SZ.HALF_M));   // zoom target == the WholeMoon box
    }
});

test("a click INSIDE a real footprint (not the exact center) still hits it", () => {
    // 20 km NE of Site06's center is inside its 60 km box.
    const hit = SZ.pickCenterAt([84000 + 20000, 110000 + 20000], ENTRIES, SZ.HALF_M);
    assert.ok(hit);
    assert.strictEqual(hit.site.name, "Site06");
});

test("a click far from every site returns null (default map behavior stands)", () => {
    // 500 km from all real centers -> no box contains it.
    assert.strictEqual(SZ.pickCenterAt([500000, 500000], ENTRIES, SZ.HALF_M), null);
    assert.strictEqual(SZ.pickCenterAt([-500000, -500000], ENTRIES, SZ.HALF_M), null);
});

test("overlapping boxes: the NEAREST real site wins", () => {
    // Site04 (-1000,-7000) and Site07 (30000,-20000) are 33.6 km apart -> their 60 km boxes overlap.
    // A click at (5000,-8000) sits in BOTH; it is nearer Site04 (6.1 km) than Site07 (27.7 km).
    const hit = SZ.pickCenterAt([5000, -8000], ENTRIES, SZ.HALF_M);
    assert.ok(hit);
    assert.strictEqual(hit.site.name, "Site04");
    // A click nearer Site07 in the same overlap band resolves to Site07.
    const hit2 = SZ.pickCenterAt([25000, -15000], ENTRIES, SZ.HALF_M);
    assert.ok(hit2);
    assert.strictEqual(hit2.site.name, "Site07");
});

test("pickSiteAt: reproject-then-hit-test on real /api/sites-shaped rows", () => {
    // Click on Site06's real map-CRS center -> the real reproject places the site there -> Site06 is hit,
    // and the extent is the same WholeMoon dive box.
    const hit = SZ.pickSiteAt([84000, 110000], SITES, lookupReproject, MAP_CRS, SZ.HALF_M);
    assert.ok(hit);
    assert.strictEqual(hit.site.name, "Site06");
    assert.deepStrictEqual(hit.center, [84000, 110000]);
    assert.deepStrictEqual(hit.extent, SZ.zoomBox([84000, 110000], SZ.HALF_M));
    // A far click still returns null through the full path.
    assert.strictEqual(SZ.pickSiteAt([600000, 600000], SITES, lookupReproject, MAP_CRS, SZ.HALF_M), null);
});

test("pickSiteAt degrades safely on bad input (no throw, honest null)", () => {
    // rows with non-numeric coords are skipped, not fabricated.
    const rows = [{ name: "bad", lon: null, lat: -85 }, { name: "nope" }];
    assert.strictEqual(SZ.pickSiteAt([0, 0], rows, lookupReproject, MAP_CRS, SZ.HALF_M), null);
    assert.strictEqual(SZ.pickSiteAt([0, 0], [], lookupReproject, MAP_CRS, SZ.HALF_M), null);
    assert.strictEqual(SZ.pickSiteAt(null, SITES, lookupReproject, MAP_CRS, SZ.HALF_M), null);
    assert.strictEqual(SZ.pickSiteAt([0, 0], SITES, null, MAP_CRS, SZ.HALF_M), null);
});
