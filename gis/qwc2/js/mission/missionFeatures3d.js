// [GW-11 clause 4] mission-features-in-3D: convert the GW-08 edit-session's authored features (keep-outs +
// place-object markers, held in IAU_2015:30135 map metres) into viz3d ORDER-FRAME render specs. The 3D panel
// fetches GET /edit/session/{sid} (the SAME backend state the 2D map renders) and hands its {features,markers}
// here; viz3d.renderMissionFeatures(specs) then draws keep-outs as draped rings + markers as 3D points, so a
// feature authored on the 2D map appears in the 3D view (the GW-11 acceptance's "within one refresh" clause).
//
// COORD FRAME: order-local lx/ly = (30135 metre) - (window origin x0/y0). This is the EXACT inverse of viz3d's
// already-verified hover convention (x = x0 + lx, y = y0 + ly -> /dem/site_lonlat), so there is NO y-flip:
// a feature at 30135 (cx,cy) renders at the order-frame point the hover would report there.
//
// PURE + node-tested (no THREE / DOM / fetch), UMD like reqGuard.js / terrain3d.js.
(function (root, factory) {
    if (typeof module === "object" && module.exports) { module.exports = factory(); }
    else { root.STEWIEMissionFeatures3D = factory(); }
})(typeof self !== "undefined" ? self : this, function () {
    "use strict";

    var CIRCLE_SEGS = 48;   // segments approximating a circle keep-out as a draped closed ring

    // 30135 map metres -> viz3d order-frame. The order frame is a Y-FLIPPED affine of the 30135 raster
    // (planAuthor.js: order_x = X30135 - x0 ; order_y = y1 - Y30135, raster-down), anchored at the DEM window's
    // top-left corner (x0 = min X, y1 = max Y). NOT the heightfield header x0/y0 (those are the order origin = 0).
    function _toOrder(X, Y, x0, y1) { return [X - x0, y1 - Y]; }

    // featuresToSpecs(state, frame) -> { keepouts:[{fid,kind,ring:[[lx,ly],...]}], markers:[{fid,lx,ly,otype,label}] }
    //   state = { features:[...], markers:[...] } from GET /edit/session/{sid} (geometry in IAU_2015:30135 metres)
    //   frame = { x0, y1, window_m } -- the DEM window's 30135 bounds (x0=min X, y1=max Y) from GET /dem/site_meta.
    // A feature wholly outside the rendered window [0,window_m]^2 is dropped (nothing to draw on this tile).
    function featuresToSpecs(state, frame) {
        var out = { keepouts: [], markers: [] };
        if (!state || !frame) { return out; }
        var x0 = +frame.x0, y1 = +frame.y1, W = +frame.window_m;
        if (!isFinite(x0) || !isFinite(y1)) { return out; }
        var inWin = function (lx, ly) {
            return !(W > 0) || (lx >= -1e-6 && lx <= W + 1e-6 && ly >= -1e-6 && ly <= W + 1e-6);
        };
        (state.features || []).forEach(function (f) {
            if (!f) { return; }
            var ring = null;
            if (f.kind === "circle" && isFinite(f.cx) && isFinite(f.cy) && +f.r > 0) {
                ring = [];
                for (var i = 0; i <= CIRCLE_SEGS; i++) {
                    var t = (i / CIRCLE_SEGS) * Math.PI * 2;
                    ring.push(_toOrder(+f.cx + +f.r * Math.cos(t), +f.cy + +f.r * Math.sin(t), x0, y1));
                }
            } else if (f.kind === "polygon" && Array.isArray(f.ring) && f.ring.length >= 3) {
                ring = f.ring.map(function (p) { return _toOrder(+p[0], +p[1], x0, y1); });
                ring.push(ring[0].slice());   // close the open ring the store holds
            }
            if (!ring) { return; }
            if (!ring.some(function (p) { return inWin(p[0], p[1]); })) { return; }   // wholly off-tile
            out.keepouts.push({ fid: f.fid, kind: f.kind, ring: ring });
        });
        (state.markers || []).forEach(function (m) {
            if (!m || !isFinite(+m.x) || !isFinite(+m.y)) { return; }
            var o = _toOrder(+m.x, +m.y, x0, y1);
            if (!inWin(o[0], o[1])) { return; }
            out.markers.push({ fid: m.fid, lx: o[0], ly: o[1], otype: m.otype || "marker", label: (m.label != null ? m.label : null) });
        });
        return out;
    }

    return { featuresToSpecs: featuresToSpecs, CIRCLE_SEGS: CIRCLE_SEGS };
});
