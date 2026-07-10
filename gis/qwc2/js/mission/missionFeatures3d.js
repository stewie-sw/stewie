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

    function _circleRing(cx, cy, r, x0, y0) {
        var ring = [];
        for (var i = 0; i <= CIRCLE_SEGS; i++) {
            var t = (i / CIRCLE_SEGS) * Math.PI * 2;
            ring.push([cx + r * Math.cos(t) - x0, cy + r * Math.sin(t) - y0]);
        }
        return ring;   // closed by construction (i=CIRCLE_SEGS repeats i=0)
    }

    // featuresToSpecs(state, meta) -> { keepouts:[{fid,kind,ring:[[lx,ly],...]}], markers:[{fid,lx,ly,otype,label}] }
    //   state = { features:[...], markers:[...] } from GET /edit/session/{sid}
    //   meta  = { x0, y0, window_m } from the viz3d heightfield_full headers (STEWIE_VIZ.meta)
    // A feature wholly outside the rendered window [0,window_m]^2 is dropped (nothing to draw on this tile).
    function featuresToSpecs(state, meta) {
        var out = { keepouts: [], markers: [] };
        if (!state || !meta) { return out; }
        var x0 = +meta.x0 || 0, y0 = +meta.y0 || 0, W = +meta.window_m;
        var inWin = function (lx, ly) {
            return !(W > 0) || (lx >= -1e-6 && lx <= W + 1e-6 && ly >= -1e-6 && ly <= W + 1e-6);
        };
        (state.features || []).forEach(function (f) {
            if (!f) { return; }
            var ring = null;
            if (f.kind === "circle" && isFinite(f.cx) && isFinite(f.cy) && +f.r > 0) {
                ring = _circleRing(+f.cx, +f.cy, +f.r, x0, y0);
            } else if (f.kind === "polygon" && Array.isArray(f.ring) && f.ring.length >= 3) {
                ring = f.ring.map(function (p) { return [+p[0] - x0, +p[1] - y0]; });
                ring.push(ring[0].slice());   // close the open ring the store holds
            }
            if (!ring) { return; }
            if (!ring.some(function (p) { return inWin(p[0], p[1]); })) { return; }   // wholly off-tile
            out.keepouts.push({ fid: f.fid, kind: f.kind, ring: ring });
        });
        (state.markers || []).forEach(function (m) {
            if (!m || !isFinite(+m.x) || !isFinite(+m.y)) { return; }
            var lx = +m.x - x0, ly = +m.y - y0;
            if (!inWin(lx, ly)) { return; }
            out.markers.push({ fid: m.fid, lx: lx, ly: ly, otype: m.otype || "marker", label: (m.label != null ? m.label : null) });
        });
        return out;
    }

    return { featuresToSpecs: featuresToSpecs, CIRCLE_SEGS: CIRCLE_SEGS };
});
