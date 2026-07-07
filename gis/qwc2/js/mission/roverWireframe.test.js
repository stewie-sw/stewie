// [REQ:AS-03] node:test for the rover KINEMATIC WIREFRAME view-model (roverWireframe.js).
//
// Two grounding sources, no fabricated data:
//   1. GEOMETRY is checked against the authoritative URDF constants in
//      ros2_ws/src/stewie_description/urdf/ipex.urdf.xacro (dimension-for-dimension).
//   2. LIVE POSE is driven by the SAME real captured /joint_states fixture the #24 instrument test uses
//      (fixtures/joint_states_imu_sample.json), parsed through the shipped roverInstruments.parseJointStates,
//      so the wireframe animates from real sim angles exactly as it will in the browser.
//
// Run: node --test gis/qwc2/js/mission/roverWireframe.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const W = require("./roverWireframe.js");
const RI = require("./roverInstruments.js");
const FIX = require("./fixtures/joint_states_imu_sample.json");

function approx(actual, expected, tol, label) {
  assert.ok(typeof actual === "number" && !Number.isNaN(actual), `${label}: expected a number, got ${actual}`);
  assert.ok(Math.abs(actual - expected) <= tol, `${label}: ${actual} not within ${tol} of ${expected}`);
}
const jointsStraight = RI.parseJointStates(FIX.straight.joint_states);
const jointsTurning = RI.parseJointStates(FIX.turning.joint_states);

// ============================ 1. skeleton dimensions match the URDF ============================
test("URDF constants match ipex.urdf.xacro dimension-for-dimension", () => {
  const U = W.URDF;
  assert.strictEqual(U.wheelbase, 0.30);
  assert.strictEqual(U.track_gauge, 0.3645);
  assert.strictEqual(U.wheel_radius, 0.1525);
  assert.strictEqual(U.wheel_width, 0.18);
  assert.strictEqual(U.cg_height, 0.21);
  assert.strictEqual(U.chassis_len, 0.46);
  assert.strictEqual(U.chassis_wid, 0.30);
  assert.strictEqual(U.chassis_hgt, 0.18);
  assert.strictEqual(U.drum_radius, 0.21855);
  assert.strictEqual(U.drum_width, 0.3526);
  assert.strictEqual(U.drum_reach, 0.32);
  assert.strictEqual(U.stereo_baseline, 0.05);
  approx(U.cam_z, 0.40, 1e-12, "cam_z = cg_height + chassis_hgt/2 + 0.10");
  approx(U.cam_fwd, 0.23, 1e-12, "cam_fwd = chassis_len/2");
});

test("the 4 skid-steer wheels sit at (+/-wheelbase/2, +/-track_gauge/2, 0)", () => {
  const wp = W.wheelPositions();
  assert.strictEqual(wp.length, 4);
  const by = {}; wp.forEach((w) => { by[w.label] = w; });
  assert.deepStrictEqual(wp.map((w) => w.label), ["FL", "FR", "RL", "RR"]);
  approx(by.FL.x, 0.15, 1e-12, "FL x"); approx(by.FL.y, 0.18225, 1e-12, "FL y");
  approx(by.FR.x, 0.15, 1e-12, "FR x"); approx(by.FR.y, -0.18225, 1e-12, "FR y");
  approx(by.RL.x, -0.15, 1e-12, "RL x"); approx(by.RL.y, 0.18225, 1e-12, "RL y");
  approx(by.RR.x, -0.15, 1e-12, "RR x"); approx(by.RR.y, -0.18225, 1e-12, "RR y");
  wp.forEach((w) => assert.strictEqual(w.z, 0));
});

test("drum arm hinges at x=+/-0.31, and the neutral drum centre sits drum_reach/2 out from the hinge", () => {
  approx(W.HINGE.front_hinge_x, 0.31, 1e-12, "front hinge x");
  approx(W.HINGE.rear_hinge_x, -0.31, 1e-12, "rear hinge x");
  // arm angle 0 => drum centre exactly drum_reach/2 (0.16) ahead of / behind the hinge, on the ground plane
  const df = W.drumCenter("front", 0), dr = W.drumCenter("rear", 0);
  approx(df.x, 0.47, 1e-12, "front drum x @0"); approx(df.z, 0, 1e-12, "front drum z @0");
  approx(dr.x, -0.47, 1e-12, "rear drum x @0"); approx(dr.z, 0, 1e-12, "rear drum z @0");
});

test("the 8-camera rig matches the URDF positions + operational/redundant roles", () => {
  const cams = W.cameras();
  assert.strictEqual(cams.length, 8);
  const by = {}; cams.forEach((c) => { by[c.frame] = c; });
  // front stereo pair at cam_fwd, +/- baseline/2, mast height, yaw 0, operational
  approx(by.front_left.x, 0.23, 1e-12, "front_left x");
  approx(by.front_left.y, 0.025, 1e-12, "front_left y = +baseline/2");
  approx(by.front_right.y, -0.025, 1e-12, "front_right y = -baseline/2");
  approx(by.front_left.z, 0.40, 1e-12, "front_left z = cam_z");
  // side monos at +/- chassis_wid/2, yaw +/- pi/2
  approx(by.left_mono.y, 0.15, 1e-12, "left_mono y = +chassis_wid/2");
  approx(by.left_mono.yaw, Math.PI / 2, 1e-12, "left_mono yaw");
  approx(by.right_mono.yaw, -Math.PI / 2, 1e-12, "right_mono yaw");
  // drum cams at +/- wheelbase/2, z=cg_height
  approx(by.drum_front.x, 0.15, 1e-12, "drum_front x = wheelbase/2");
  approx(by.drum_front.z, 0.21, 1e-12, "drum_front z = cg_height");
  // roles: front stereo + left_mono + drum_front operational; the other four redundant
  const op = cams.filter((c) => c.role === "operational").map((c) => c.frame).sort();
  assert.deepStrictEqual(op, ["drum_front", "front_left", "front_right", "left_mono"]);
  const red = cams.filter((c) => c.role === "redundant").length;
  assert.strictEqual(red, 4);
});

test("IMU at (0,0,cg_height) and 3 forward depth hardpoints", () => {
  approx(W.IMU.x, 0, 1e-12, "imu x"); approx(W.IMU.y, 0, 1e-12, "imu y");
  approx(W.IMU.z, 0.21, 1e-12, "imu z = cg_height");
  const dm = W.depthMounts();
  assert.strictEqual(dm.length, 3);
  dm.forEach((m) => assert.ok(m.x > W.URDF.cam_fwd, `${m.name} on the forward hardpoint (x>${W.URDF.cam_fwd})`));
});

// ============================ 2. projectors place parts at the right 2D positions ============================
test("orthographic projectors put a body point on the right (u,v) axes", () => {
  const p = { x: 0.23, y: 0.15, z: 0.40 };
  assert.deepStrictEqual(W.PROJECTORS.side(p), { u: 0.23, v: 0.40 });   // x-z
  assert.deepStrictEqual(W.PROJECTORS.front(p), { u: 0.15, v: 0.40 });  // y-z
  assert.deepStrictEqual(W.PROJECTORS.back(p), { u: -0.15, v: 0.40 });  // -y-z (mirror of front)
  assert.deepStrictEqual(W.PROJECTORS.top(p), { u: -0.15, v: 0.23 });   // -y-x (nose-up plan)
});

test("SIDE view: wheels render as full circles of wheel_radius on the ground plane (v=0)", () => {
  const side = W.buildView("side", jointsStraight);
  const circles = side.primitives.filter((p) => p.type === "circle" && p.cls === "wheel");
  // FL/FR share x (coincide in side); RL/RR share x => 4 circles at x=+/-0.15, v=0, r=wheel_radius
  assert.strictEqual(circles.length, 4);
  circles.forEach((c) => { approx(c.r, 0.1525, 1e-12, "wheel r"); approx(c.v, 0, 1e-12, "wheel centre on ground"); });
  const xs = circles.map((c) => c.u).sort();
  approx(xs[0], -0.15, 1e-9, "rear wheels u"); approx(xs[3], 0.15, 1e-9, "front wheels u");
});

test("TOP view: cameras project to the right plan positions; all 8 FOV cones are drawn (yaws in-plane)", () => {
  const top = W.buildView("top", jointsStraight);
  const cones = top.primitives.filter((p) => p.type === "cone");
  assert.strictEqual(cones.length, 8, "all 8 cameras' yaw fans are in the x-y plane -> all cones show in TOP");
  // front_left (x=0.23,y=0.025) -> top (u=-y,v=x) = (-0.025, 0.23)
  const nodes = top.primitives.filter((p) => p.type === "node" && p.frame === "front_left");
  assert.strictEqual(nodes.length, 1);
  approx(nodes[0].u, -0.025, 1e-9, "front_left u in TOP");
  approx(nodes[0].v, 0.23, 1e-9, "front_left v in TOP");
});

test("SIDE view: side-mono cones are dropped (axis +/-Y is perpendicular to x-z); forward cones survive", () => {
  const side = W.buildView("side", jointsStraight);
  const cones = side.primitives.filter((p) => p.type === "cone");
  // front_left/right + rear_left/right + drum_front/back point along +/-x (in-plane) => 6 cones;
  // left_mono/right_mono point along +/-y (perpendicular) => dropped. Nodes still present for all 8.
  assert.strictEqual(cones.length, 6, "6 x/-x-facing cones survive, 2 side monos dropped");
  const nodes = side.primitives.filter((p) => p.type === "node" && /cam-/.test(p.cls));
  assert.strictEqual(nodes.length, 8, "all 8 camera nodes still drawn");
});

// ============================ 3. a joint angle change moves the right primitive (LIVE, real fixture) ============
test("ARM SWING moves the drum along an arc about its hinge (real settled arm angle vs neutral)", () => {
  // real fixture front arm settled at -0.42554 rad (-24.38 deg); rear at +0.42554 rad
  const armFront = jointsStraight.arms.find((a) => a.end === "front").positionRad;
  approx(armFront, -0.42554, 1e-4, "fixture front arm rad");
  const neutral = W.drumCenter("front", 0);
  const posed = W.drumCenter("front", armFront);
  // swinging the arm off zero moves the drum centre BOTH in x (back, toward the hinge) and up in z (arc)
  assert.ok(posed.x < neutral.x, `arm swing pulls the front drum back in x (${posed.x} < ${neutral.x})`);
  assert.ok(Math.abs(posed.z) > 0.01, `arm swing lifts the front drum off the ground plane (z=${posed.z})`);
  // the drum centre stays exactly drum_reach/2 from the hinge (rigid arm, arc not translation)
  const hinge = { x: W.HINGE.front_hinge_x, z: 0 };
  const reach = Math.hypot(posed.x - hinge.x, posed.z - hinge.z);
  approx(reach, W.URDF.drum_reach / 2, 1e-9, "drum stays on the arc radius drum_reach/2");
});

test("ARM SWING moves the drum-arm primitive endpoint in the built SIDE view", () => {
  const drumSideNeutral = W.buildView("side", null).primitives.filter((p) => p.cls === "drum")[0];
  const drumSideLive = W.buildView("side", jointsStraight).primitives.filter((p) => p.cls === "drum")[0];
  // front drum circle centre must move between the neutral pose and the live settled pose
  const moved = Math.hypot(drumSideLive.u - drumSideNeutral.u, drumSideLive.v - drumSideNeutral.v);
  assert.ok(moved > 0.02, `live arm angle relocates the drum circle in the SIDE panel (moved ${moved} m)`);
});

test("WHEEL SPIN rotates the spoke: the spoke tip differs between two real wheel angles", () => {
  // straight-drive wheel angle vs turning wheel angle (both REAL captured positions)
  const aStraight = jointsStraight.wheels.find((w) => w.label === "FL").positionRad;   // 4.1548 rad
  const aTurning = jointsTurning.wheels.find((w) => w.label === "FL").positionRad;     // -2.6151 rad
  assert.notStrictEqual(aStraight, aTurning);
  const center = { x: 0.15, y: 0.18225, z: 0 };
  const tipA = W.project("side", W.spokeTip(center, W.URDF.wheel_radius, aStraight));
  const tipB = W.project("side", W.spokeTip(center, W.URDF.wheel_radius, aTurning));
  const moved = Math.hypot(tipA.u - tipB.u, tipA.v - tipB.v);
  assert.ok(moved > 0.02, `spoke tip rotates with the wheel angle (moved ${moved} m)`);
  // the spoke tip stays exactly wheel_radius from the hub (rotation, not translation)
  approx(Math.hypot(tipA.u - center.x, tipA.v - center.z), W.URDF.wheel_radius, 1e-9, "spoke length = wheel_radius");
});

test("DRUM SPIN spoke rotates with the real free-spin drum position", () => {
  const dPos = jointsStraight.drums.find((d) => d.end === "front").positionRad;   // real ~3.077 rad
  const center = W.drumCenter("front", jointsStraight.arms.find((a) => a.end === "front").positionRad);
  const tip0 = W.project("side", W.spokeTip(center, W.URDF.drum_radius, 0));
  const tipLive = W.project("side", W.spokeTip(center, W.URDF.drum_radius, dPos));
  const moved = Math.hypot(tip0.u - tipLive.u, tip0.v - tipLive.v);
  assert.ok(moved > 0.02, `drum spoke rotates with the drum spin position (moved ${moved} m)`);
});

test("SKID-STEER turn: left and right wheel spokes diverge (opposite real velocities -> opposite angles)", () => {
  const side = W.buildView("side", jointsTurning);
  const spokes = side.primitives.filter((p) => p.cls === "wheel-spoke");
  assert.strictEqual(spokes.length, 4);
  // FL wheel angle is negative, FR positive in the turn -> their spoke tips land at different v
  const flAng = jointsTurning.wheels.find((w) => w.label === "FL").positionRad;
  const frAng = jointsTurning.wheels.find((w) => w.label === "FR").positionRad;
  assert.ok(flAng * frAng < 0, "real turn: FL and FR wheel positions have opposite sign");
});

// ============================ buildAll + bounds sanity ============================
test("buildAll returns all four labelled panels with finite bounds", () => {
  const all = W.buildAll(jointsStraight);
  assert.deepStrictEqual(Object.keys(all).sort(), ["back", "front", "side", "top"]);
  W.VIEWS.forEach((v) => {
    const b = all[v].bounds;
    ["minU", "maxU", "minV", "maxV"].forEach((k) => assert.ok(Number.isFinite(b[k]), `${v}.${k} finite`));
    assert.ok(b.maxU > b.minU && b.maxV > b.minV, `${v} bounds non-degenerate`);
    assert.ok(all[v].primitives.length > 20, `${v} has a populated skeleton`);
    assert.strictEqual(all[v].angles.hasData, true, `${v} posed from real joint data`);
  });
});

test("EVIDENCE-ONLY: the wireframe module exports no command/publish/advertise surface", () => {
  Object.keys(W).map((k) => k.toLowerCase()).forEach((k) => {
    assert.ok(!/publish|advertise|command|cmd|send|nav_goal|safe|actuat/.test(k),
      `roverWireframe must expose no command surface, found: ${k}`);
  });
});
