// TOOL PALETTE authoring logic (node:test): the pure serialization the Mission-Plan tool palette uses --
// traverse-waypoint orders, the traverse polyline, the return-to-lander anchor, the order-frame entry shared
// with /api/plan, and the place-object marker body. Pure (no DOM, no OpenLayers, no React), so it unit-tests
// in bare node -- NO external deps (the CI browser-JS tier runs `node --test` with no npm install; ci.yml:87).
//
// REAL DATA PROVENANCE: coordinates are the committed Artemis III LOLA-5m Site01 footprint center --
// selenographic [lon, lat] = [-137.489553, -89.463163] (IAU_2015:30100) paired with its map-CRS center
// [x, y] = [-11000, -12000] (IAU_2015:30135), the SAME real pair siteZoom.test.js uses (from gis/build_project
// .py -> data/gis/vectors/artemis_sites.geojson, PGDA Product 78). Nothing here is fabricated.
//
// Run: node --test gis/qwc2/js/mission/planTools.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const PT = require("./planTools.js");

// A real map-CRS coord + its selenographic lon/lat (the Site01 pair) and two nearby work points.
const C0 = [-11000, -12000], LL0 = [-137.489553, -89.463163];
const C1 = [-10940, -11970], LL1 = [-137.470000, -89.462000];
const C2 = [-11060, -12040], LL2 = [-137.510000, -89.464500];

test("TRAVERSE_KIND is the backend goto order kind (lode _ORDER_KINDS)", () => {
    assert.strictEqual(PT.TRAVERSE_KIND, "goto");
});

test("OBJECT_TYPES matches the server ALLOWED_MARKER_TYPES vocabulary (drift guard)", () => {
    assert.deepStrictEqual(PT.OBJECT_TYPES, ["beacon", "cache", "instrument", "sample", "antenna"]);
});

test("traverseOrder builds a goto order the pydantic Order schema accepts", () => {
    const o = PT.traverseOrder(C1, LL1);
    assert.strictEqual(o.kind, "goto");                 // -> the backend auto-chains consecutive gotos into a path
    assert.ok(o.footprint_m2 > 0);                      // schemas.Order footprint_m2 gt=0 (the backend zeroes it for a goto)
    assert.strictEqual(o.depth_m, 0);
    assert.deepStrictEqual(o.coord, C1);
    assert.deepStrictEqual(o.lonlat, LL1);
    assert.strictEqual(o.waypoint, true);
});

test("traversePath is the ordered polyline of ONLY the goto waypoints (authorship order)", () => {
    const orders = [
        PT.traverseOrder(C0, LL0),
        { kind: "cut", coord: [1, 2], lonlat: [0, 0] },   // a non-traverse order is skipped
        PT.traverseOrder(C1, LL1),
        PT.traverseOrder(C2, LL2)
    ];
    assert.deepStrictEqual(PT.traversePath(orders), [C0, C1, C2]);
    assert.deepStrictEqual(PT.traversePath([]), []);
});

test("centroidLonLat = the mean selenographic lon/lat anchor (the return-to-lander base)", () => {
    const orders = [
        { kind: "cut", lonlat: LL0 }, { kind: "fill", lonlat: LL1 }, PT.traverseOrder(C2, LL2)
    ];
    const c = PT.centroidLonLat(orders);
    assert.ok(Math.abs(c[0] - (LL0[0] + LL1[0] + LL2[0]) / 3) < 1e-9);
    assert.ok(Math.abs(c[1] - (LL0[1] + LL1[1] + LL2[1]) / 3) < 1e-9);
    assert.strictEqual(PT.centroidLonLat([]), null);     // no orders -> no lander anchor
});

test("orderFrameEntry: a goto serializes to the anchor-relative order frame (y-flipped, raster-down)", () => {
    const wc = [-11000, -12000];                         // the anchor in map coords
    const o = PT.traverseOrder([-10950, -11980], [0, 0]); // 50 m East, 20 m North of the anchor
    const e = PT.orderFrameEntry(o, 0, wc);
    assert.strictEqual(e.kind, "goto");
    assert.strictEqual(e.action, "goto 1");
    assert.strictEqual(e.x, 50);                         // East offset = X - anchorX
    assert.strictEqual(e.y, -20);                        // North offset y-flipped: anchorY - Y = -12000 - -11980 = -20
    assert.ok(e.footprint_m2 > 0);                       // stays pydantic-valid; the backend zeroes it for a goto
});

test("orderFrameEntry: a cut order matches the legacy _anchorAndOrders formula (regression)", () => {
    const wc = [-11000, -12000];
    const cut = { kind: "cut", coord: [-10940, -12030], footprint_m2: 60, depth_m: 0.4 };
    const e = PT.orderFrameEntry(cut, 2, wc);
    // 60 m East, 30 m SOUTH of the anchor -> raster-down order frame: x=+60, y=+30 (anchorY - Y = -12000 - -12030).
    assert.deepStrictEqual(e, { action: "cut 3", kind: "cut", x: 60, y: 30, footprint_m2: 60, depth_m: 0.4 });
});

test("markerBody builds a valid place-object feature for the edit-session route", () => {
    const b = PT.markerBody(C1, "beacon", "Nav B1");
    assert.strictEqual(b.kind, undefined);   // MarkerIn is extra="forbid" with NO kind; sending it 400'd every POST. The store re-adds kind:"marker" on normalize.
    assert.strictEqual(b.x, C1[0]);
    assert.strictEqual(b.y, C1[1]);
    assert.strictEqual(b.otype, "beacon");
    assert.strictEqual(b.label, "Nav B1");
    // an omitted label is left off (the server defaults it from the type)
    assert.strictEqual(PT.markerBody(C0, "cache").label, undefined);
});

test("markerBody rejects an object type outside the vocabulary", () => {
    assert.throws(() => PT.markerBody(C0, "death-ray"), /unknown object type/);
});

// --- PLAN ANYWHERE (map-click pick): clickToLonLat + isPlannableLatLon -------------------------------
// The pure logic behind the Mission-Plan "Plan here (click the map)" mode: a workbench-map click coord
// (IAU_2015:30135) reprojects to selenographic [lon, lat] (IAU_2015:30100), validated against the SAME
// domain the backend request-time crop serves (stewie/terrain/adhoc_dem._MAX_ABS_LAT = 89.9).

test("MAX_ABS_LAT is in lockstep with the backend crop domain (adhoc_dem._MAX_ABS_LAT drift guard)", () => {
    assert.strictEqual(PT.MAX_ABS_LAT, 89.9);
});

test("clickToLonLat reprojects a map-CRS click to selenographic [lon, lat] via the injected transform", () => {
    // Stub reproject: assert it is called map-CRS -> geo-CRS with the click coord, and return the known pair
    // (the real CoordinatesUtils.reproject does the polar-stereographic -> longlat transform in the browser).
    const calls = [];
    const reproject = (coord, src, dst) => { calls.push([coord.slice(), src, dst]); return LL0.slice(); };
    const ll = PT.clickToLonLat(C0, reproject, "IAU_2015:30135", "IAU_2015:30100");
    assert.deepStrictEqual(ll, LL0);
    assert.strictEqual(calls.length, 1);
    assert.deepStrictEqual(calls[0][0], C0);                 // reprojected the clicked coord
    assert.strictEqual(calls[0][1], "IAU_2015:30135");       // FROM the workbench map CRS
    assert.strictEqual(calls[0][2], "IAU_2015:30100");       // TO selenographic lon/lat
});

test("clickToLonLat returns null on a throwing or non-finite reproject (no NaN pick)", () => {
    assert.strictEqual(PT.clickToLonLat(C0, () => { throw new Error("off-projection"); }, "a", "b"), null);
    assert.strictEqual(PT.clickToLonLat(C0, () => [NaN, -85], "a", "b"), null);
    assert.strictEqual(PT.clickToLonLat(C0, () => [10, Infinity], "a", "b"), null);
    assert.strictEqual(PT.clickToLonLat(null, () => LL0.slice(), "a", "b"), null);
    assert.strictEqual(PT.clickToLonLat(C0, null, "a", "b"), null);
});

test("isPlannableLatLon accepts an off-site pick but refuses the exact pole (curated tiles serve there)", () => {
    assert.ok(PT.isPlannableLatLon(-86.0, -30.0));           // a real off-site south-polar pick
    assert.ok(PT.isPlannableLatLon(0.0, 137.0));             // equatorial far-side is plannable too
    assert.ok(PT.isPlannableLatLon(89.9, 10.0));             // the domain boundary is inclusive
    assert.ok(!PT.isPlannableLatLon(89.95, 10.0));           // past the boundary -> the curated polar tile serves
    assert.ok(!PT.isPlannableLatLon(-90.0, 0.0));            // the pole itself
    assert.ok(!PT.isPlannableLatLon(NaN, 0.0));              // non-finite -> not plannable
    assert.ok(!PT.isPlannableLatLon(-85.0, NaN));
});

test("materialBalance sums cut/fill bank volumes + flags surplus/deficit", () => {
    const orders = [
        { kind: "cut", footprint_m2: 60, depth_m: 0.4 },    // 24 m3
        { kind: "cut", footprint_m2: 40, depth_m: 0.5 },    // 20 m3
        { kind: "fill", footprint_m2: 30, depth_m: 0.3 },   // 9 m3
        { kind: "goto", footprint_m2: 0, depth_m: 0 }        // ignored (zero-mass visit)
    ];
    const b = PT.materialBalance(orders);   // cut 44 m3 bank, fill 9 m3 bank
    assert.strictEqual(b.cut_m3, 44);
    assert.strictEqual(b.fill_m3, 9);
    assert.strictEqual(b.loose_spoil_m3, 65);          // 44 * 1920/1300 = +~48% swell
    assert.strictEqual(b.cut_mass_kg, 84480);          // 44 * 1920
    assert.strictEqual(b.fill_mass_kg, 11700);         // 9 * 1300
    assert.strictEqual(b.balance_kg, 72780);           // mass surplus (the conserved quantity)
    assert.strictEqual(b.status, "surplus");
    assert.strictEqual(b.cut_count, 2);
    // equal BANK volumes are a mass SURPLUS, not balance -- cut@1920 supplies more mass than loose fill@1300 needs:
    const eq = PT.materialBalance([{ kind: "cut", footprint_m2: 100, depth_m: 1 }, { kind: "fill", footprint_m2: 100, depth_m: 1 }]);
    assert.strictEqual(eq.cut_m3, eq.fill_m3);
    assert.ok(eq.balance_kg > 0 && eq.status === "surplus");
    assert.strictEqual(PT.materialBalance([]).balance_kg, 0);            // empty -> 0 balance
});

// [REQ:SD-02] the net direction the acceptance names: cut-only => net SPOIL (surplus), fill-only => net
// BORROW (deficit), with the RHO_DEEP(1920 bank)->RHO_SPOIL(1300 loose) bulking + mass conserved. Densities
// are moon-hardcoded (constants.py RHO_DEEP/RHO_SPOIL); body-aware densities are deferred (task #62).
test("[REQ:SD-02] materialBalance: cut-only => net spoil (surplus), fill-only => net borrow (deficit)", () => {
    const cutOnly = PT.materialBalance([{ kind: "cut", footprint_m2: 50, depth_m: 1 }]);   // 50 m3 bank
    assert.strictEqual(cutOnly.fill_m3, 0);
    assert.strictEqual(cutOnly.cut_mass_kg, 96000);          // 50 * 1920 (RHO_DEEP bank)
    assert.strictEqual(cutOnly.loose_spoil_m3, 73.8);        // 50 * 1920/1300 loose bulking (+~48%)
    assert.ok(cutOnly.balance_kg > 0 && cutOnly.status === "surplus", "cut-only is a net spoil surplus");
    const fillOnly = PT.materialBalance([{ kind: "fill", footprint_m2: 50, depth_m: 1 }]);  // 50 m3 bank
    assert.strictEqual(fillOnly.cut_m3, 0);
    assert.strictEqual(fillOnly.fill_mass_kg, 65000);        // 50 * 1300 (RHO_SPOIL loose fill)
    assert.ok(fillOnly.balance_kg < 0 && fillOnly.status === "deficit", "fill-only is a net borrow deficit");
});

// --- F17 / F32: a minimal fake PlanAuthor controller for the pure dispatch/adopt helpers -----------------
// Mirrors the REAL controller contract the helpers touch: the three mutually-exclusive placing modes
// (activeKind/structKind/objectType), setTool()'s TOGGLE + clear-siblings semantics (planAuthor.js
// setTool/setStructure/setObjectTool), placeAt()'s "queue a goto only while traverse is active" rule
// (planAuthor.js:1149), and reproject() as an identity stub (the 30100->30135 affine is Playwright-checked).
function fakeCtrl(initialTool) {
    return {
        activeKind: initialTool || null,
        structKind: null,
        objectType: null,
        orders: [],
        structCalls: [],
        objectCalls: [],
        placeAtCalls: [],
        hints: [],
        // identity reproject: [lon,lat] in -> the same pair back (the helpers pass it straight to place*).
        reproject(coord) { return [coord[0], coord[1]]; },
        // setTool TOGGLES activeKind and clears the sibling placing modes, exactly like planAuthor.setTool.
        setTool(kind) {
            this.structKind = null; this.objectType = null;
            this.activeKind = (this.activeKind === kind) ? null : kind;
        },
        // placeAt queues a goto ONLY while traverse is the active tool (planAuthor.js:1149); otherwise a
        // cut/fill order. A call with no active tool is a no-op (matches placeAt's `if (!this.activeKind) return`).
        placeAt(coord) {
            this.placeAtCalls.push(coord);
            if (this.activeKind === "traverse") { this.orders.push({ kind: "goto", coord: coord }); }
            else if (this.activeKind) { this.orders.push({ kind: this.activeKind, coord: coord }); }
        },
        placeStructure(coord) { this.structCalls.push(coord); },
        placeObject(coord) { this.objectCalls.push(coord); },
        _setHint(msg, isErr) { this.hints.push({ msg: msg, isErr: !!isErr }); }
    };
}
function lastHint(c) { return c.hints.length ? c.hints[c.hints.length - 1] : null; }

// F17: _adoptRoute forced Traverse active to place the 3D-measured route and NEVER restored the prior tool,
// leaving the 2D map stuck in Traverse placing mode (the operator's next click dropped a stray waypoint).
test("adoptRoute: queues the goto waypoints AND restores the prior 'cut' tool (F17)", () => {
    const c = fakeCtrl("cut");
    const placed = PT.adoptRoute(c, [LL1, LL2].map((ll) => ({ lon: ll[0], lat: ll[1] })),
        "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(placed, 2, "both waypoints placed");
    assert.strictEqual(c.orders.filter((o) => o.kind === "goto").length, 2, "two goto waypoints queued");
    assert.strictEqual(c.activeKind, "cut", "prior 'cut' tool restored — NOT left in traverse (F17)");
});

test("adoptRoute: no prior tool -> restores to null (next map click is inert, not a stray waypoint)", () => {
    const c = fakeCtrl(null);
    const placed = PT.adoptRoute(c, [{ lon: 1, lat: 2 }, { lon: 3, lat: 4 }], "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(placed, 2);
    assert.strictEqual(c.orders.filter((o) => o.kind === "goto").length, 2);
    assert.strictEqual(c.activeKind, null, "restored to no-tool (no stray-waypoint mode left behind)");
});

test("adoptRoute: prior tool already 'traverse' -> stays traverse, no double-toggle no-op", () => {
    const c = fakeCtrl("traverse");
    const placed = PT.adoptRoute(c, [{ lon: 1, lat: 2 }, { lon: 3, lat: 4 }], "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(placed, 2, "guard skips the re-toggle so placeAt still queues both gotos");
    assert.strictEqual(c.orders.filter((o) => o.kind === "goto").length, 2);
    assert.strictEqual(c.activeKind, "traverse");
});

test("adoptRoute: fewer than 2 waypoints is refused (no tool mutation, error hint)", () => {
    const c = fakeCtrl("cut");
    const placed = PT.adoptRoute(c, [{ lon: 1, lat: 2 }], "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(placed, 0);
    assert.strictEqual(c.orders.length, 0);
    assert.strictEqual(c.activeKind, "cut", "a refused route never touches the tool");
    assert.ok(lastHint(c) && lastHint(c).isErr, "surfaces an error hint");
});

// F32: the 3D 'plot the active tool' onPlot channel only fired for cut/fill/traverse (activeKind); a
// structure template (structKind) or place-object (objectType) tool could not be plotted and only nagged.
test("plotDispatch: structure tool active -> placeStructure (F32)", () => {
    const c = fakeCtrl(null); c.structKind = "landing_pad";
    const mode = PT.plotDispatch(c, { lon: LL0[0], lat: LL0[1] }, "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(mode, "structure");
    assert.strictEqual(c.structCalls.length, 1, "the structure was placed at the plotted point");
    assert.strictEqual(c.objectCalls.length, 0);
    assert.strictEqual(c.placeAtCalls.length, 0);
});

test("plotDispatch: place-object tool active -> placeObject (F32)", () => {
    const c = fakeCtrl(null); c.objectType = "beacon";
    const mode = PT.plotDispatch(c, { lon: LL0[0], lat: LL0[1] }, "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(mode, "object");
    assert.strictEqual(c.objectCalls.length, 1, "the marker was placed at the plotted point");
    assert.strictEqual(c.structCalls.length, 0);
});

test("plotDispatch: cut/fill/traverse tool -> placeAt (the unchanged earthworks path)", () => {
    const c = fakeCtrl("cut");
    const mode = PT.plotDispatch(c, { lon: LL0[0], lat: LL0[1] }, "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(mode, "place");
    assert.strictEqual(c.placeAtCalls.length, 1);
    assert.strictEqual(c.orders.filter((o) => o.kind === "cut").length, 1);
});

test("plotDispatch: no tool active -> hint, no placement", () => {
    const c = fakeCtrl(null);
    const mode = PT.plotDispatch(c, { lon: 1, lat: 2 }, "IAU_2015:30100", "IAU_2015:30135");
    assert.strictEqual(mode, null);
    assert.strictEqual(c.placeAtCalls.length + c.structCalls.length + c.objectCalls.length, 0);
    assert.ok(lastHint(c) && !lastHint(c).isErr, "hints the operator to pick a tool");
});

test("plotDispatch: null point payload is ignored (no throw, no placement)", () => {
    const c = fakeCtrl("cut");
    assert.strictEqual(PT.plotDispatch(c, null, "IAU_2015:30100", "IAU_2015:30135"), null);
    assert.strictEqual(PT.plotDispatch(c, { lon: null, lat: null }, "IAU_2015:30100", "IAU_2015:30135"), null);
    assert.strictEqual(c.placeAtCalls.length, 0);
});
