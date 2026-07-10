// [GW-11 clause 4] node tests for the edit-session-features (IAU_2015:30135 metres) -> viz3d order-frame.
// The order frame is a Y-FLIPPED affine of the 30135 raster: order_x = X - frame.x0 ; order_y = frame.y1 - Y,
// anchored at the DEM window's top-left corner (x0 = min X, y1 = max Y from /dem/site_meta bounds_m).
const assert = require("node:assert");
const { test } = require("node:test");
const MF = require("./missionFeatures3d.js");

// window covers 30135 X in [-20000,-10000], Y in [-20000,-10000] -> order-frame [0,10000]^2
const FRAME = { x0: -20000, y1: -10000, window_m: 10000 };

test("circle keep-out -> closed order-frame ring; centre + y-flip correct", () => {
    const s = { features: [{ fid: "ko1", kind: "circle", cx: -15000, cy: -16000, r: 500 }], markers: [] };
    const o = MF.featuresToSpecs(s, FRAME);
    assert.equal(o.keepouts.length, 1);
    const ring = o.keepouts[0].ring;
    assert.equal(ring.length, MF.CIRCLE_SEGS + 1);
    // centre order = (cx-x0, y1-cy) = (5000, 6000); t=0 point = (cx+r-x0, y1-cy) = (5500, 6000)
    assert.ok(Math.abs(ring[0][0] - 5500) < 1e-6 && Math.abs(ring[0][1] - 6000) < 1e-6);
    assert.deepEqual(ring[0], ring[ring.length - 1]);   // closed
});

test("polygon keep-out -> order-frame ring, closed, y-flipped", () => {
    const s = { features: [{ fid: "ko2", kind: "polygon", ring: [[-18000, -18000], [-16000, -18000], [-16000, -16000]] }], markers: [] };
    const o = MF.featuresToSpecs(s, FRAME);
    assert.equal(o.keepouts.length, 1);
    assert.deepEqual(o.keepouts[0].ring[0], [2000, 8000]);   // (-18000-(-20000), -10000-(-18000))
    assert.equal(o.keepouts[0].ring.length, 4);              // 3 verts + close
    assert.deepEqual(o.keepouts[0].ring[0], o.keepouts[0].ring[3]);
});

test("marker -> order-frame point (y-flipped) with otype/label", () => {
    const s = { features: [], markers: [{ fid: "m1", kind: "marker", x: -15000, y: -16000, otype: "beacon", label: "A" }] };
    const o = MF.featuresToSpecs(s, FRAME);
    assert.deepEqual(o.markers, [{ fid: "m1", lx: 5000, ly: 6000, otype: "beacon", label: "A" }]);
});

test("features wholly outside the tile window are dropped", () => {
    const s = {
        features: [{ fid: "ko3", kind: "circle", cx: 50000, cy: 50000, r: 100 }],
        markers: [{ fid: "m2", kind: "marker", x: 99999, y: 99999, otype: "cache" }]
    };
    const o = MF.featuresToSpecs(s, FRAME);
    assert.equal(o.keepouts.length, 0);
    assert.equal(o.markers.length, 0);
});

test("a circle straddling the tile edge is KEPT (partially visible)", () => {
    // order centre (-100, 5000): X = -100 + x0 = -20100 ; Y = y1 - 5000 = -15000 ; r=500 crosses the left edge
    const s = { features: [{ fid: "ko4", kind: "circle", cx: -20100, cy: -15000, r: 500 }], markers: [] };
    assert.equal(MF.featuresToSpecs(s, FRAME).keepouts.length, 1);
});

test("null / empty / bad frame inputs are safe", () => {
    assert.deepEqual(MF.featuresToSpecs(null, FRAME), { keepouts: [], markers: [] });
    assert.deepEqual(MF.featuresToSpecs({ features: [], markers: [] }, FRAME), { keepouts: [], markers: [] });
    assert.deepEqual(MF.featuresToSpecs({ features: [{ fid: "x", kind: "bogus" }], markers: [] }, FRAME).keepouts, []);
    assert.deepEqual(MF.featuresToSpecs({ features: [{ fid: "x", kind: "circle", cx: 0, cy: 0, r: 1 }] }, { window_m: 10 }), { keepouts: [], markers: [] });  // no x0/y1
});
