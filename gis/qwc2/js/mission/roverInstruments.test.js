// [REQ:AS-03] node:test for the rover INSTRUMENT pure view-model (roverInstruments.js).
//
// FIXTURE = REAL /joint_states + /stewie/imu frames captured verbatim from the live STEWIE Gazebo sim
// (gz-sim8 Harmonic, world stewie_lunar = real LOLA Haworth, model ipex) on 2026-07-07, serialized with
// the SAME rosidl_runtime_py.message_to_ordereddict transform deploy/ros2/rosbridge_feeder.py applies ->
// the frames are byte-faithful to what the rosbridge collector broadcasts and the browser receives. See
// fixtures/joint_states_imu_sample.json for full provenance. NO synthetic telemetry: the sim on flat
// ground genuinely reports a level (identity) attitude, so the IMU attitude asserts are against the real
// identity orientation; the quaternion->euler formula is additionally checked on canonical rotations,
// LABELED as pure-math (not sim telemetry), to prove it for non-zero angles the flat spawn never produced.
//
// Run: node --test gis/qwc2/js/mission/roverInstruments.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const RI = require("./roverInstruments.js");
const FIX = require("./fixtures/joint_states_imu_sample.json");

function approx(actual, expected, tol, label) {
  assert.ok(actual !== null && actual !== undefined && !Number.isNaN(actual),
    `${label}: expected a number, got ${actual}`);
  assert.ok(Math.abs(actual - expected) <= tol,
    `${label}: ${actual} not within ${tol} of ${expected}`);
}
const byName = (rows) => { const m = {}; rows.forEach((r) => { m[r.name] = r; }); return m; };

// --- the fixture is real captured sim data -----------------------------------------------------------
test("fixture is REAL captured sim telemetry (8 IPEx joints, message_to_ordereddict transform)", () => {
  assert.match(FIX._provenance, /message_to_ordereddict/);
  assert.match(FIX._provenance, /NO synthetic data/);
  assert.strictEqual(FIX.straight.joint_states.name.length, 8);
  assert.strictEqual(FIX.turning.joint_states.name.length, 8);
});

// --- 8 joints -> 4 wheels + 2 arms + 2 drums ---------------------------------------------------------
test("parseJointStates maps the 8 real joints into 4 wheels + 2 arms + 2 drums", () => {
  const j = RI.parseJointStates(FIX.straight.joint_states);
  assert.strictEqual(j.count, 8);
  assert.strictEqual(j.wheels.length, 4);
  assert.strictEqual(j.arms.length, 2);
  assert.strictEqual(j.drums.length, 2);
  assert.strictEqual(j.other.length, 0);
  // wheels are ordered + labeled FL, FR, RL, RR
  assert.deepStrictEqual(j.wheels.map((w) => w.label), ["FL", "FR", "RL", "RR"]);
  // every wheel got a real position + velocity
  j.wheels.forEach((w) => {
    assert.strictEqual(typeof w.positionRad, "number");
    assert.strictEqual(typeof w.velocityRadS, "number");
  });
});

// --- wheel RPM: sign + magnitude from real velocities ------------------------------------------------
test("straight drive: all 4 wheels report forward (+RPM) from the real velocities", () => {
  const w = byName(RI.parseJointStates(FIX.straight.joint_states).wheels);
  // real captured wheel velocity was 1.63934 rad/s forward on all four -> +15.65 RPM
  ["front_left_wheel_joint", "front_right_wheel_joint", "rear_left_wheel_joint", "rear_right_wheel_joint"].forEach((n) => {
    assert.ok(w[n].rpm > 0, `${n} should be +RPM (forward), got ${w[n].rpm}`);
    approx(w[n].rpm, 15.654, 0.02, `${n} rpm`);
    approx(w[n].rpm, w[n].velocityRadS * 60 / (2 * Math.PI), 1e-9, `${n} rpm == vel*60/2pi`);
  });
});

test("turning: LEFT wheels -RPM, RIGHT wheels +RPM (real skid-steer sign contrast)", () => {
  const w = byName(RI.parseJointStates(FIX.turning.joint_states).wheels);
  // real captured turn: left wheels -0.717 rad/s, right wheels +0.717 rad/s
  assert.ok(w["front_left_wheel_joint"].rpm < 0, "front-left should be -RPM in a left turn");
  assert.ok(w["rear_left_wheel_joint"].rpm < 0, "rear-left should be -RPM in a left turn");
  assert.ok(w["front_right_wheel_joint"].rpm > 0, "front-right should be +RPM in a left turn");
  assert.ok(w["rear_right_wheel_joint"].rpm > 0, "rear-right should be +RPM in a left turn");
  // left and right are equal-and-opposite (skid steer)
  approx(w["front_left_wheel_joint"].rpm, -w["front_right_wheel_joint"].rpm, 1e-6, "left == -right rpm");
});

// --- arm + drum hinge angles in degrees --------------------------------------------------------------
test("arm hinges map real settled positions (rad) to degrees (+/-24.4 deg under lunar gravity)", () => {
  const a = byName(RI.parseJointStates(FIX.straight.joint_states).arms);
  // real captured arm positions were front -0.42554 rad, rear +0.42554 rad
  approx(a["front_drum_arm_joint"].positionDeg, -24.38, 0.05, "front arm deg");
  approx(a["rear_drum_arm_joint"].positionDeg, 24.38, 0.05, "rear arm deg");
  // positionDeg == positionRad * 180/pi
  approx(a["front_drum_arm_joint"].positionDeg,
    a["front_drum_arm_joint"].positionRad * 180 / Math.PI, 1e-9, "arm deg == rad*180/pi");
});

test("drum spins map real free-spin velocity to RPM + wrap the accumulated position to (-180,180]", () => {
  const d = byName(RI.parseJointStates(FIX.straight.joint_states).drums);
  // drums free-spin during the drive (real ~1.144 rad/s) and their position accumulates unbounded ->
  // the wrapped display angle stays in (-180, 180]
  ["front_drum_spin_joint", "rear_drum_spin_joint"].forEach((n) => {
    approx(d[n].rpm, d[n].velocityRadS * 60 / (2 * Math.PI), 1e-9, `${n} rpm`);
    assert.ok(d[n].positionWrappedDeg > -180 && d[n].positionWrappedDeg <= 180,
      `${n} wrapped deg in (-180,180], got ${d[n].positionWrappedDeg}`);
  });
});

// --- IMU: real lunar gravity + level attitude --------------------------------------------------------
test("parseImu: real lunar gravity magnitude ~1.62 m/s^2 from linear_acceleration; level attitude", () => {
  const im = RI.parseImu(FIX.straight.imu);
  // the real captured linear_acceleration was ~[0,0,1.62] -> |g| ~ 1.62 (lunar), not 9.81
  approx(im.gravityMag, 1.62, 1e-3, "gravity magnitude");
  approx(im.linearAccel.z, 1.62, 1e-3, "linear_accel.z");
  // flat spawn -> real identity orientation -> level (roll/pitch/yaw ~ 0)
  approx(im.rollDeg, 0, 1e-6, "roll");
  approx(im.pitchDeg, 0, 1e-6, "pitch");
  approx(im.yawDeg, 0, 1e-6, "yaw");
  // angular velocity ~ 0 (body at rest attitude-wise)
  approx(im.angularVel.z, 0, 1e-6, "yaw rate");
  assert.strictEqual(im.frameId, "ipex/base_link/imu");
});

// --- quaternion -> euler PURE-MATH correctness (canonical rotations, NOT sim telemetry) ---------------
// These inputs are exact unit quaternions for named rotations, used ONLY to verify the conversion math
// for non-zero angles the flat-ground sim never produced. They are labeled math, not captured telemetry.
test("quatToEuler is correct on canonical rotations (labeled pure-math, not sim data)", () => {
  const S = Math.SQRT1_2;                                 // sin/cos of 45 deg = 1/sqrt(2)
  assert.deepStrictEqual(RI.quatToEuler({ x: 0, y: 0, z: 0, w: 1 }),
    { rollDeg: 0, pitchDeg: 0, yawDeg: 0 });              // identity
  approx(RI.quatToEuler({ x: 0, y: 0, z: S, w: S }).yawDeg, 90, 1e-9, "+90 yaw");
  approx(RI.quatToEuler({ x: 0, y: 0, z: -S, w: S }).yawDeg, -90, 1e-9, "-90 yaw");
  approx(RI.quatToEuler({ x: S, y: 0, z: 0, w: S }).rollDeg, 90, 1e-9, "+90 roll");
  approx(RI.quatToEuler({ x: 0, y: S, z: 0, w: S }).pitchDeg, 90, 1e-9, "+90 pitch");
});

// --- robustness: classify BOTH vehicle naming schemes ------------------------------------------------
test("classifyJoint resolves BOTH the live IPEx `*_joint` and the EZ-RASSOR `*_hinge` names", () => {
  const ipex = {
    front_left_wheel_joint: "wheel", rear_right_wheel_joint: "wheel",
    front_drum_arm_joint: "arm", rear_drum_arm_joint: "arm",
    front_drum_spin_joint: "drum", rear_drum_spin_joint: "drum"
  };
  Object.keys(ipex).forEach((n) => assert.strictEqual(RI.classifyJoint(n).kind, ipex[n], n));
  const ez = {
    left_wheel_front_hinge: "wheel", right_wheel_back_hinge: "wheel",
    arm_front_hinge: "arm", arm_back_hinge: "arm",
    drum_front_hinge: "drum", drum_back_hinge: "drum"
  };
  Object.keys(ez).forEach((n) => assert.strictEqual(RI.classifyJoint(n).kind, ez[n], n));
  // sides + ends resolve for a wheel
  const c = RI.classifyJoint("front_left_wheel_joint");
  assert.strictEqual(c.side, "left");
  assert.strictEqual(c.end, "front");
});

// --- EVIDENCE-ONLY: no command surface ---------------------------------------------------------------
test("EVIDENCE-ONLY: the module exports NO command/publish/advertise surface", () => {
  Object.keys(RI).map((k) => k.toLowerCase()).forEach((k) => {
    assert.ok(!/publish|advertise|command|cmd|send|nav_goal|safe|actuat/.test(k),
      `roverInstruments must expose no command surface, found: ${k}`);
  });
});
