/**
 * planTools — the pure authoring logic behind the STEWIE Mission-Plan TOOL PALETTE (artemis.stewie.space/ide/).
 *
 * The palette adds three tools on top of the existing Cut / Fill / Structure authoring:
 *   • TRAVERSE (waypoints) — drop ordered path waypoints; each is a backend ``goto`` order (lode
 *     planner_model._ORDER_KINDS = cut|fill|sinter|goto), a ZERO-MASS visit the planner auto-chains into a
 *     path (consecutive gotos -> auto precedence). No new order kind is needed: goto is already first-class.
 *   • RETURN TO LANDER — append a goto at the lander/charger anchor so the traverse ends back at base. The
 *     lander anchor = the order centroid in selenographic lon/lat (the SAME anchor /api/plan uses).
 *   • PLACE OBJECT — drop a mission object (beacon/cache/instrument/sample/antenna) as a POINT marker that
 *     persists through the backend edit-session (versioned audit + undo), kept SEPARATE from the keep-out set
 *     so it never routes the planner around it (a marker annotates; it is not a hazard).
 *
 * Pure (no DOM, no OpenLayers, no React) -> node:test-able in bare node, exactly like siteZoom.js /
 * gantt_downsample.js. planAuthor.js (the OpenLayers controller) imports this; MissionPlan.jsx wires the panel.
 * The interactive proof (a real click drops a waypoint / object) is planAuthor + MissionPlan driven by Playwright.
 *   Run: node --test gis/qwc2/js/mission/planTools.test.js
 */
(function (root) {
    "use strict";

    // The backend order kind for a traverse waypoint: a zero-mass, sequenced path visit (lode
    // planner_model._ORDER_KINDS). Consecutive gotos auto-chain into a path (mission_from_dict auto_prec).
    var TRAVERSE_KIND = "goto";
    // The placeable mission-object types. MUST match the server ALLOWED_MARKER_TYPES
    // (stewie/server/edit_session.py) -- a bad type is a 400 there and is caught client-side here too.
    var OBJECT_TYPES = ["beacon", "cache", "instrument", "sample", "antenna"];
    // A positive placeholder footprint so the goto order passes the pydantic Order schema (footprint_m2 gt=0,
    // stewie/server/schemas.py); mission_from_dict FORCES footprint/depth to 0 for a goto, so this is ignored.
    var GOTO_FOOTPRINT_M2 = 1;
    // PLAN ANYWHERE (map-click pick): the max |lat| a request-time crop can serve, MATCHING the backend
    // resolver (stewie/terrain/adhoc_dem.py _MAX_ABS_LAT) -- a local equirectangular crop degenerates at the
    // pole itself, where the curated polar-stereographic tiles serve instead. Kept in lockstep here so a
    // map-click pick is refused with the same reason the backend would give, BEFORE the network round-trip.
    var MAX_ABS_LAT = 89.9;

    function round1(n) { return Math.round(n * 10) / 10; }

    // PLAN ANYWHERE: is a selenographic (lat, lon) plannable via a request-time global-LDEM crop? True when
    // both are finite and |lat| <= MAX_ABS_LAT (the backend's own domain). The pole itself (|lat| > 89.9) is
    // served by the curated polar tiles, not an ad-hoc crop -- so a click there is refused, not faked.
    function isPlannableLatLon(lat, lon) {
        return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= MAX_ABS_LAT;
    }

    // PLAN ANYWHERE: turn a MAP-CLICK coord (in the workbench CRS, IAU_2015:30135 polar-stereographic) into
    // selenographic [lon, lat] (IAU_2015:30100) via the injected reproject(coord, srcCrs, dstCrs) -> [x, y]
    // (CoordinatesUtils.reproject) -- the SAME reproject the order-placement path already uses (planAuthor
    // placeAt/placeStructure). Returns [lon, lat] on a clean finite reproject, else null (a reproject that
    // throws or yields a non-finite coord -> no pick, so the controller hints instead of planning a NaN spot).
    // Pure: the reproject is injected, so this unit-tests in bare node with a stub transform.
    function clickToLonLat(coord, reproject, mapCrs, geoCrs) {
        if (!coord || typeof reproject !== "function") { return null; }
        var ll;
        try { ll = reproject([coord[0], coord[1]], mapCrs, geoCrs); }
        catch (e) { return null; }
        if (!ll || !Number.isFinite(ll[0]) || !Number.isFinite(ll[1])) { return null; }
        return [ll[0], ll[1]];
    }

    // A traverse waypoint as a client ORDER object -- the SAME shape as the cut/fill orders, so the existing
    // order queue, the pre-plan markers, and _anchorAndOrders serialize it with no special-casing.
    function traverseOrder(coord, lonlat) {
        return {
            kind: TRAVERSE_KIND, footprint_m2: GOTO_FOOTPRINT_M2, depth_m: 0,
            coord: [coord[0], coord[1]], lonlat: [lonlat[0], lonlat[1]], waypoint: true
        };
    }

    function isTraverse(order) { return !!order && order.kind === TRAVERSE_KIND; }

    // The ordered polyline of traverse-waypoint MAP coords (authorship order) -- the path the palette draws.
    // Non-traverse orders (cut/fill) are skipped: the path is only the sequenced drive.
    function traversePath(orders) {
        var out = [];
        for (var i = 0; i < (orders || []).length; i++) {
            if (isTraverse(orders[i]) && orders[i].coord) {
                out.push([orders[i].coord[0], orders[i].coord[1]]);
            }
        }
        return out;
    }

    // The lander / charger anchor = the centroid of the current orders in selenographic lon/lat. This is the
    // SAME anchor /api/plan uses (planAuthor._anchorAndOrders: mean lon/lat -> reproject -> order-frame origin
    // = the charger). Return-to-lander appends a goto here so the traverse ends at the base. Returns
    // [meanLon, meanLat] (the controller reprojects it to map coords), or null when there are no orders yet.
    function centroidLonLat(orders) {
        var os = [];
        for (var i = 0; i < (orders || []).length; i++) {
            if (orders[i] && orders[i].lonlat) { os.push(orders[i].lonlat); }
        }
        if (!os.length) { return null; }
        var sLon = 0, sLat = 0;
        for (var j = 0; j < os.length; j++) { sLon += os[j][0]; sLat += os[j][1]; }
        return [sLon / os.length, sLat / os.length];
    }

    // The per-order ORDER-FRAME entry POSTed to /api/plan: anchor-relative x/y in metres, y-flipped to the
    // raster-down order frame (ox = X30135 - anchorX ; oy = anchorY - Y30135). This is the ONE serializer
    // cut / fill / goto share, so a traverse waypoint rides the exact same /plan path as a cut order. `wc` is
    // the anchor in map coords (IAU_2015:30135).
    function orderFrameEntry(order, index, wc) {
        return {
            action: order.kind + " " + (index + 1), kind: order.kind,
            x: round1(order.coord[0] - wc[0]), y: round1(wc[1] - order.coord[1]),
            footprint_m2: order.footprint_m2, depth_m: order.depth_m
        };
    }

    // A place-object marker create BODY for the edit-session route (POST /api/edit/session/{sid}/marker), in
    // the map frame (IAU_2015:30135, metres) -- the same frame the keep-outs are stored in. Validates the type
    // against OBJECT_TYPES (mirrors the server) so a bad type is caught before the round-trip. An omitted label
    // is left off (the server defaults it from the type).
    function markerBody(coord, otype, label) {
        if (OBJECT_TYPES.indexOf(otype) < 0) {
            throw new Error("unknown object type " + otype + " (want one of " + OBJECT_TYPES.join("/") + ")");
        }
        var body = { kind: "marker", x: coord[0], y: coord[1], otype: otype };
        if (label) { body.label = String(label); }
        return body;
    }

    // Cut/fill MATERIAL BALANCE (civil earthwork economy). Cut is excavated at BANK density (RHO_DEEP=1920)
    // and the placed spoil BULKS to LOOSE density (RHO_SPOIL=1300 -> +~48% volume). So the honest balance is the
    // MASS the backend conserves (cut_bank*1920 vs fill_bank*1300), NOT bank-volume minus bank-volume -- the
    // latter ignores the swell and disagrees with the backend's mass-balanced certification (fill_vol ~= 1.48*
    // cut_vol). We also surface the loose spoil volume (what actually drives drum loads + haul cycles).
    function materialBalance(orders, opts) {
        opts = opts || {};
        var rhoBank = opts.rhoBank || 1920, rhoLoose = opts.rhoLoose || 1300;   // constants.py RHO_DEEP / RHO_SPOIL
        var cutBank = 0, fillBank = 0, nCut = 0, nFill = 0;
        (orders || []).forEach(function (o) {
            var v = (Number(o.footprint_m2) || 0) * (Number(o.depth_m) || 0);
            if (o.kind === "cut") { cutBank += v; nCut += 1; }
            else if (o.kind === "fill") { fillBank += v; nFill += 1; }
        });
        var looseSpoil = cutBank * (rhoBank / rhoLoose);
        var cutMassKg = cutBank * rhoBank, fillMassKg = fillBank * rhoLoose;
        var balanceKg = cutMassKg - fillMassKg;
        return {
            cut_m3: round1(cutBank), fill_m3: round1(fillBank), loose_spoil_m3: round1(looseSpoil),
            cut_mass_kg: round1(cutMassKg), fill_mass_kg: round1(fillMassKg), balance_kg: round1(balanceKg),
            status: balanceKg >= 0 ? "surplus" : "deficit", cut_count: nCut, fill_count: nFill
        };
    }

    var API = {
        TRAVERSE_KIND: TRAVERSE_KIND,
        OBJECT_TYPES: OBJECT_TYPES,
        GOTO_FOOTPRINT_M2: GOTO_FOOTPRINT_M2,
        MAX_ABS_LAT: MAX_ABS_LAT,
        round1: round1,
        traverseOrder: traverseOrder,
        isTraverse: isTraverse,
        traversePath: traversePath,
        centroidLonLat: centroidLonLat,
        orderFrameEntry: orderFrameEntry,
        markerBody: markerBody,
        isPlannableLatLon: isPlannableLatLon,
        clickToLonLat: clickToLonLat,
        materialBalance: materialBalance
    };
    if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
    if (root) { root.STEWIE_PLAN_TOOLS = API; }                                       // browser (window)
})(typeof window !== "undefined" ? window : null);
