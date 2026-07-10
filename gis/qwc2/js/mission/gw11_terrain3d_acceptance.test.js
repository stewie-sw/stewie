// [REQ:GW-11] (node:test) — the acceptance binder for the /ide 3D terrain panel synced to the GIS map.
// GW-11's acceptance is compound; this test asserts the three PURE serializer contracts that make it true,
// with real values (not just shapes). The two RENDER clauses are Playwright-verified on the deployed /ide
// (real GPU): (a) the Three.js panel renders the site's REAL DEM window (via /dem/heightfield) in the
// site-local frame with the 1-5x vertical-exaggeration control, and (b) it ports the cockpit three3d.js
// capabilities (orbit/fly, sun shadows, layer-texture drape). The live e2e is frontend/_ide_features_e2e.mjs
// (opens Terrain 3D, authors 24 keep-outs on the 2D map, asserts they render in 3D). Component tests:
// terrain3d.test.js (formatHover), missionFeatures3d.test.js (the 30135->order transform), workspace.test.js
// (the features channel). This file binds them to the acceptance sub-clauses (c)/(d)/(e).
const assert = require("node:assert");
const { test } = require("node:test");
const T = require("./terrain3d.js");             // (c) hover coordinate-readout formatting
const MF = require("./missionFeatures3d.js");    // (d) 2D-authored 30135 feature -> viz3d order-frame spec
const WS = require("./workspace.js");            // (d)/(e) the shared workspace store: features + plot channels
// workspace.js exports a SINGLETON; node --test isolates each file in its own process, so it is fresh here.
// Each channel test emits before it reads and unsubscribes its own subscriber, so there is no cross-test bleed.

// The DEM window's 30135 anchor (x0=min X, y1=max Y) the /ide plugin fetches from /dem/site_meta; identical
// shape to missionFeatures3d.test.js so the transform is exercised against the same fixture the unit test uses.
const FRAME = { x0: -20000, y1: -10000, window_m: 10000 };

// ---- (c) Click/hover-3D returns the exact map coordinate into the IDE coordinate display ------------------
// viz3d _hoverPick / _plotAt raycast the relief, recover order-local e_m/n_m (UV-derived) + absolute elev,
// and resolve selenographic lat/lon via the shared /dem/site_lonlat transform. The IDE coordinate display is
// terrain3d.formatHover(payload). Assert it reports order metres E/N + elevation + selenographic lon/lat.
test("(c) the IDE coordinate display shows order metres E/N + elev + selenographic lon/lat", () => {
  const payload = { e_m: 5234.5, n_m: 6120.2, elev_m: -812.3, lat: -87.34521, lon: 25.11987 };
  const f = T.formatHover(payload);
  assert.strictEqual(f.en, "E 5234.5 m N 6120.2 m");   // order-frame metres (the DEM-window-local frame)
  assert.strictEqual(f.elev, "elev -812.3 m");
  assert.strictEqual(f.lonlat, "lat -87.34521° lon 25.11987°");   // selenographic, 5 dp
});

test("(c) an unresolved coordinate (lon/lat lookup pending) reads a dash, never a fabricated value", () => {
  const f = T.formatHover({ e_m: 100, n_m: 200, elev_m: -800, lat: null, lon: null });
  assert.strictEqual(f.en, "E 100.0 m N 200.0 m");   // metres are known immediately from the raycast
  assert.strictEqual(f.lonlat, "lat — lon —");        // selenographic only after /dem/site_lonlat resolves
});

// ---- (d) a mission feature authored on the 2D map appears in 3D from the same backend state, one refresh --
// The GW-08 edit-session holds features in IAU_2015:30135 metres. planAuthor emits them on WS.emitFeatures
// after every load/create/modify/delete/undo; the 3D panel reads WS.getFeatures() and converts through
// missionFeatures3d.featuresToSpecs(state, frame) into the viz3d order-frame it renders. Assert the transform
// value AND that the WS features channel HOLDS the last set (so a panel opened later still sees it) and
// notifies a subscriber synchronously (the "within one refresh" guarantee).
test("(d) a 30135-authored keep-out converts to the viz3d order-frame the 3D view renders", () => {
  const state = { features: [{ fid: "ko1", kind: "circle", cx: -15000, cy: -16000, r: 500 }], markers: [] };
  const specs = MF.featuresToSpecs(state, FRAME);
  assert.strictEqual(specs.keepouts.length, 1);
  // centre order = (cx-x0, y1-cy) = (5000, 6000); the t=0 ring vertex = (cx+r-x0, y1-cy) = (5500, 6000)
  const ring0 = specs.keepouts[0].ring[0];
  assert.ok(Math.abs(ring0[0] - 5500) < 1e-6 && Math.abs(ring0[1] - 6000) < 1e-6);
});

test("(d) the WS features channel HOLDS the authored set and notifies within one refresh", () => {
  let seen = null, calls = 0;
  const unsub = WS.onFeatures((s) => { seen = s; calls++; });   // the 3D panel's subscription
  const authored = {
    features: [{ fid: "ko1", kind: "polygon", ring: [[-18000, -18000], [-16000, -18000], [-16000, -16000]] }],
    markers: [{ fid: "m1", kind: "marker", x: -15000, y: -16000, otype: "beacon", label: "A" }]
  };
  WS.emitFeatures(authored);                                    // planAuthor emits after _adoptEditState
  assert.strictEqual(calls, 1, "subscriber notified synchronously (within one refresh)");
  // A panel opened AFTER authoring still reads the current set (HELD value, unlike a transient event channel).
  const held = WS.getFeatures();
  assert.strictEqual(held.features.length, 1);
  assert.strictEqual(held.markers.length, 1);
  assert.strictEqual(held.markers[0].fid, "m1");
  // And the held set converts to a renderable order-frame spec (the same chain the plugin runs on notify).
  const specs = MF.featuresToSpecs(held, FRAME);
  assert.strictEqual(specs.keepouts.length, 1);
  assert.strictEqual(specs.markers.length, 1);
  assert.deepStrictEqual(specs.markers[0].fid, "m1");
  unsub();
  WS.emitFeatures({ features: [], markers: [] });
  assert.strictEqual(calls, 1, "unsubscribed panel receives no further notifications");
});

// ---- (e) a 3D waypoint pick lands in the SAME order-frame serializer the 2D path uses --------------------
// viz3d _plotAt raycasts the relief and emits { e_m, n_m, elev_m, lat, lon } (order-frame metres +
// selenographic) via onPlot; the plugin wires VIZ.onPlot((pt) => WS.emitPlot(pt)). WS.emitPlot is the exact
// channel the 2D map's singleclick fills, so a 3D pick and a 2D click reach one queue. Assert a 3D-picked
// point (the shape viz3d emits) is delivered verbatim to a MissionPlan-style onPlot subscriber.
test("(e) a 3D pick reaches the shared order-frame plot channel the 2D singleclick uses", () => {
  const received = [];
  const unsub = WS.onPlot((pt) => received.push(pt));   // MissionPlan subscribes to the SAME channel for 2D clicks
  const pick3d = { e_m: 4210.5, n_m: 7788.0, elev_m: -805.2, lat: -87.301, lon: 24.55 };   // viz3d _plotAt payload
  WS.emitPlot(pick3d);                                   // plugin: VIZ.onPlot((pt) => WS.emitPlot(pt))
  assert.strictEqual(received.length, 1);
  assert.deepStrictEqual(received[0], pick3d, "the order-frame point is passed through unchanged");
  // A 2D singleclick fills the identical channel with the same order-frame shape -> both feed one order queue.
  WS.emitPlot({ e_m: 100, n_m: 200, elev_m: -800, lat: -87.0, lon: 20.0 });
  assert.strictEqual(received.length, 2);
  unsub();
});
