// [REQ:RT-04] node:test for the RViz/Foxglove ENGINEERING PANEL pure view-model (engPanel.js).
//
// The panel is EVIDENCE-ONLY (PRD §7.B RT-04, acceptance D3): it derives a READ-ONLY view model
// (topic freshness / TF tree / pose+covariance / diagnostics roster) from the read-only rosbridge
// telemetry and holds NO command authority. engPanel.js is pure (no DOM, no ROSLIB, no React), so
// its derivations unit-test in bare node exactly like catalogLayers.test.js / gantt_downsample.test.js.
//
// FIXTURES are REAL rosbridge messages captured verbatim from the live /rosbridge relay on this host
// (stewie-rosbridge collector, 2026-07-07): the sim publishes /tf = map->base_link, /odom with a
// zeroed pose.covariance (the open-loop sim reports zero uncertainty -- honest, not fabricated), and
// /rover/state as a JSON String. No synthetic telemetry: where the tree-recursion path needs a second
// frame, it is built from the SAME real /tf message schema and labeled as such.
//
// Run: node --test gis/qwc2/js/mission/engPanel.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const E = require("./engPanel.js");

// --- REAL captured fixtures (verbatim from the live /rosbridge relay) ------------------------------
const TF_REAL = { transforms: [ {
  header: { stamp: { sec: 1783436472, nanosec: 241494702 }, frame_id: "map" },
  child_frame_id: "base_link",
  transform: { translation: { x: 280.0, y: -235.0, z: 2826.582763671875 },
               rotation: { x: 0.0, y: 0.0, z: -0.0, w: 1.0 } }
} ] };
const ODOM_REAL = {
  header: { stamp: { sec: 1783436472, nanosec: 241494702 }, frame_id: "map" },
  child_frame_id: "base_link",
  pose: { pose: { position: { x: 280.0, y: -235.0, z: 2826.582763671875 },
                  orientation: { x: 0.0, y: 0.0, z: -0.0, w: 1.0 } },
          covariance: new Array(36).fill(0.0) },
  twist: { twist: { linear: { x: 0.0, y: 0.0, z: 0.0 }, angular: { x: 0.0, y: 0.0, z: 0.0 } } }
};
const STATE_REAL = { data: JSON.stringify({
  leg_id: -1, row: 47.0, col: 56.0, yaw_rad: 0.0, v_achieved_mps: 0.0,
  slip: 0.0, sinkage_m: 0.0, slope_rad: 0.0, soc: 1.0, entrapped: false, met: 0.0
}) };

// --- the acceptance topic roster -------------------------------------------------------------------
test("EXPECTED_TOPICS roster: live read-only topics vs acceptance topics not relayed to the browser", () => {
  const by = {};
  E.EXPECTED_TOPICS.forEach((s) => { by[s.topic] = s; });
  // relayed over the read-only browser WS (the feeder subscribes exactly these)
  assert.strictEqual(by["/tf"].live, true);
  assert.strictEqual(by["/odom"].live, true);
  assert.strictEqual(by["/rover/state"].live, true);
  // named by the RT-04 acceptance but NOT relayed to the browser -> shown honestly as absent
  assert.strictEqual(by["/diagnostics"].live, false);
  assert.strictEqual(by["/stewie/costmap"].live, false);
  assert.ok(Object.prototype.hasOwnProperty.call(by, "/robot_description")); // URDF/robot-model (deferred)
});

test("EVIDENCE-ONLY (D3): the module exports NO command/publish/advertise surface", () => {
  const keys = Object.keys(E).map((k) => k.toLowerCase());
  keys.forEach((k) => {
    assert.ok(!/publish|advertise|command|cmd|send|nav_goal|safe|actuat/.test(k),
      `engPanel must expose no command surface, found: ${k}`);
  });
});

// --- TF tree ---------------------------------------------------------------------------------------
test("ingest /tf builds the real map->base_link tree with the captured translation", () => {
  const m = E.freshModel();
  E.ingest(m, { topic: "/tf", msg: TF_REAL }, 1000);
  const tree = E.tfTree(m);
  assert.deepStrictEqual(tree.map((r) => r.frame), ["map", "base_link"]);
  assert.strictEqual(tree[0].depth, 0);          // map is the root (never a child)
  assert.strictEqual(tree[0].parent, null);
  assert.strictEqual(tree[1].depth, 1);
  assert.strictEqual(tree[1].parent, "map");
  assert.strictEqual(tree[1].translation.x, 280.0);
  assert.strictEqual(tree[1].translation.z, 2826.582763671875);
});

test("tfTree recursion+ordering: a second child of base_link (real /tf schema) nests + sorts", () => {
  // exercises the multi-level/multi-child path using the REAL /tf message schema; the live sim
  // currently publishes only map->base_link, so this second frame is constructed, not captured.
  const m = E.freshModel();
  E.ingest(m, { topic: "/tf", msg: TF_REAL }, 1000);
  E.ingest(m, { topic: "/tf", msg: { transforms: [
    { header: { stamp: { sec: 1783436473, nanosec: 0 }, frame_id: "base_link" },
      child_frame_id: "lidar_link",
      transform: { translation: { x: 0.1, y: 0.0, z: 0.4 }, rotation: { x: 0, y: 0, z: 0, w: 1 } } },
    { header: { stamp: { sec: 1783436473, nanosec: 0 }, frame_id: "base_link" },
      child_frame_id: "imu_link",
      transform: { translation: { x: 0.0, y: 0.0, z: 0.2 }, rotation: { x: 0, y: 0, z: 0, w: 1 } } }
  ] } }, 2000);
  const tree = E.tfTree(m);
  // map -> base_link -> {imu_link, lidar_link} (children sorted); depths 0,1,2,2
  assert.deepStrictEqual(tree.map((r) => r.frame), ["map", "base_link", "imu_link", "lidar_link"]);
  assert.deepStrictEqual(tree.map((r) => r.depth), [0, 1, 2, 2]);
});

// --- pose + covariance -----------------------------------------------------------------------------
test("ingest /odom yields pose + covariance sigma (zero-covariance sim -> sigma 0, honest)", () => {
  const m = E.freshModel();
  E.ingest(m, { topic: "/odom", msg: ODOM_REAL }, 1000);
  const pc = E.poseCovariance(m);
  assert.strictEqual(pc.x, 280.0);
  assert.strictEqual(pc.y, -235.0);
  assert.strictEqual(pc.headingDeg, 0);          // identity quaternion -> 0 deg
  assert.strictEqual(pc.speed, 0.0);
  assert.ok(pc.sigma, "a 36-element covariance yields a sigma readout");
  assert.strictEqual(pc.sigma.sx, 0.0);          // the open-loop sim publishes zero pose covariance
  assert.strictEqual(pc.sigma.syaw, 0.0);
});

test("poseCovariance is null until /odom arrives", () => {
  assert.strictEqual(E.poseCovariance(E.freshModel()), null);
});

// --- /rover/state telemetry ------------------------------------------------------------------------
test("ingest /rover/state parses the real JSON telemetry (slip/sinkage/soc/entrapped)", () => {
  const m = E.freshModel();
  E.ingest(m, { topic: "/rover/state", msg: STATE_REAL }, 1000);
  assert.strictEqual(m.state.slip, 0.0);
  assert.strictEqual(m.state.sinkage, 0.0);
  assert.strictEqual(m.state.soc, 1.0);
  assert.strictEqual(m.state.entrapped, false);
  assert.strictEqual(m.state.legId, -1);
});

// --- topic freshness -------------------------------------------------------------------------------
test("topicRows: live topics go fresh->stale by age; unpublished acceptance topics stay absent", () => {
  const m = E.freshModel();
  E.ingest(m, { topic: "/tf", msg: TF_REAL }, 1000);
  E.ingest(m, { topic: "/odom", msg: ODOM_REAL }, 1000);
  E.ingest(m, { topic: "/rover/state", msg: STATE_REAL }, 1000);
  const fresh = {};
  E.topicRows(m, 1200).forEach((r) => { fresh[r.topic] = r; });   // 200 ms later
  assert.strictEqual(fresh["/tf"].status, "fresh");
  assert.strictEqual(fresh["/odom"].status, "fresh");
  assert.strictEqual(fresh["/tf"].ageMs, 200);
  // never-published acceptance topics are honestly absent (no fabricated liveness)
  assert.strictEqual(fresh["/diagnostics"].status, "absent");
  assert.strictEqual(fresh["/stewie/costmap"].status, "absent");
  assert.strictEqual(fresh["/diagnostics"].ageMs, null);
  // the same /tf row goes stale once older than the freshness window
  const stale = {};
  E.topicRows(m, 1000 + E.FRESH_MS + 1).forEach((r) => { stale[r.topic] = r; });
  assert.strictEqual(stale["/tf"].status, "stale");
});

test("diagnosticsRows is empty when /diagnostics never arrives (honest 'no data')", () => {
  const m = E.freshModel();
  E.ingest(m, { topic: "/odom", msg: ODOM_REAL }, 1000);
  assert.deepStrictEqual(E.diagnosticsRows(m), []);
});
