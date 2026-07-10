// [GW-11 clause 4] node tests for the edit-session-features -> viz3d order-frame conversion.
const assert = require("node:assert");
const { test } = require("node:test");
const MF = require("./missionFeatures3d.js");

// window covers 30135 [-20000,-10000] x [-20000,-10000] (order-frame [0,10000]^2)
const META = { x0: -20000, y0: -20000, window_m: 10000 };

test("circle keep-out -> closed order-frame ring, centered by the inverse hover convention", () => {
    const s = { features: [{ fid: "ko1", kind: "circle", cx: -15000, cy: -16000, r: 500 }], markers: [] };
    const o = MF.featuresToSpecs(s, META);
    assert.equal(o.keepouts.length, 1);
    assert.equal(o.keepouts[0].kind, "circle");
    const ring = o.keepouts[0].ring;
    assert.equal(ring.length, MF.CIRCLE_SEGS + 1);
    // center order-frame = (cx-x0, cy-y0) = (5000, 4000); t=0 point = (cx+r-x0, cy-y0) = (5500, 4000)
    assert.ok(Math.abs(ring[0][0] - 5500) < 1e-6 && Math.abs(ring[0][1] - 4000) < 1e-6);
    assert.deepEqual(ring[0], ring[ring.length - 1]);   // closed
});

test("polygon keep-out -> order-frame ring, closed (store holds an OPEN ring)", () => {
    const s = { features: [{ fid: "ko2", kind: "polygon", ring: [[-18000, -18000], [-16000, -18000], [-16000, -16000]] }], markers: [] };
    const o = MF.featuresToSpecs(s, META);
    assert.equal(o.keepouts.length, 1);
    assert.deepEqual(o.keepouts[0].ring[0], [2000, 2000]);
    assert.equal(o.keepouts[0].ring.length, 4);   // 3 verts + close
    assert.deepEqual(o.keepouts[0].ring[0], o.keepouts[0].ring[3]);
});

test("marker -> order-frame point with otype/label", () => {
    const s = { features: [], markers: [{ fid: "m1", kind: "marker", x: -15000, y: -15000, otype: "beacon", label: "A" }] };
    const o = MF.featuresToSpecs(s, META);
    assert.deepEqual(o.markers, [{ fid: "m1", lx: 5000, ly: 5000, otype: "beacon", label: "A" }]);
});

test("features wholly outside the tile window are dropped", () => {
    const s = {
        features: [{ fid: "ko3", kind: "circle", cx: 50000, cy: 50000, r: 100 }],
        markers: [{ fid: "m2", kind: "marker", x: 99999, y: 99999, otype: "cache" }]
    };
    const o = MF.featuresToSpecs(s, META);
    assert.equal(o.keepouts.length, 0);
    assert.equal(o.markers.length, 0);
});

test("a circle straddling the tile edge is KEPT (partially visible)", () => {
    // center just outside at order-frame (-100, 5000) but r=500 crosses into the window
    const s = { features: [{ fid: "ko4", kind: "circle", cx: -20100, cy: -15000, r: 500 }], markers: [] };
    assert.equal(MF.featuresToSpecs(s, META).keepouts.length, 1);
});

test("null / empty inputs are safe", () => {
    assert.deepEqual(MF.featuresToSpecs(null, META), { keepouts: [], markers: [] });
    assert.deepEqual(MF.featuresToSpecs({ features: [], markers: [] }, META), { keepouts: [], markers: [] });
    assert.deepEqual(MF.featuresToSpecs({ features: [{ fid: "x", kind: "bogus" }], markers: [] }, META).keepouts, []);
});
