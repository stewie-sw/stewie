// [REQ:AS-03] Rover INSTRUMENT view-model (PRD §7.B RT-04) -- the faithful EZ-RASSOR/IPEx proprioception
// readout for the MissionHUD panel. Pure mapping of the two URDF-declared telemetry sources into display
// fields:
//   * /joint_states (sensor_msgs/JointState) -> the 8 actuated joints: 4 skid-steer wheels (position +
//     velocity, velocity shown as RPM), 2 drum-arm hinges + 2 drum spins (position shown in degrees).
//   * /stewie/imu   (sensor_msgs/Imu)        -> attitude (orientation quaternion -> roll/pitch/yaw),
//     angular velocity, and linear acceleration (whose magnitude is the sensed gravity, ~1.62 m/s^2 on
//     the Moon).
//
// EVIDENCE-ONLY BY CONSTRUCTION: this module only DERIVES a read-only view model; it exports NO publish /
// advertise / command surface, so nothing here can act on the rover. It is pure (no DOM, no ROSLIB, no
// React) and unit-tests in bare node exactly like engPanel.js / gantt_downsample.js -- the source of truth
// for these derivations lives HERE (one place, tested); rt04Client feeds it live frames and the MissionHUD
// plugin renders the derived model.
//
// JOINT NAMING: the sim's gz JointStatePublisher emits the joints by their URDF name, alphabetically. Two
// naming schemes exist across STEWIE vehicle models, so joints are classified by NAME (not index), which
// makes the readout robust to a model swap:
//   * IPEx (ros2_control, the live model of record): front_left_wheel_joint / front_right_wheel_joint /
//     rear_left_wheel_joint / rear_right_wheel_joint / front_drum_arm_joint / rear_drum_arm_joint /
//     front_drum_spin_joint / rear_drum_spin_joint.
//   * EZ-RASSOR (upstream): left_wheel_front_hinge / right_wheel_front_hinge / left_wheel_back_hinge /
//     right_wheel_back_hinge / arm_front_hinge / arm_back_hinge / drum_front_hinge / drum_back_hinge.
(function (root) {
  "use strict";

  var RAD2DEG = 180 / Math.PI;
  var RADPS_TO_RPM = 60 / (2 * Math.PI);

  function num(v) {
    return (v === undefined || v === null || Number.isNaN(Number(v))) ? null : Number(v);
  }
  function radToDeg(r) { var n = num(r); return n === null ? null : n * RAD2DEG; }
  function radPerSecToRpm(v) { var n = num(v); return n === null ? null : n * RADPS_TO_RPM; }

  // normalize an angle in degrees to (-180, 180] (continuous-joint positions accumulate unbounded)
  function wrapDeg180(deg) {
    var n = num(deg);
    if (n === null) return null;
    var d = ((n % 360) + 360) % 360;   // [0, 360)
    return d > 180 ? d - 360 : d;
  }

  // classify a joint by its NAME so both the IPEx `*_joint` and EZ-RASSOR `*_hinge` schemes resolve.
  function classifyJoint(name) {
    var n = String(name === undefined || name === null ? "" : name).toLowerCase();
    var side = /(^|[^a-z])left([^a-z]|$)/.test(n) ? "left"
             : (/(^|[^a-z])right([^a-z]|$)/.test(n) ? "right" : null);
    var end = /front/.test(n) ? "front"
            : ((/rear/.test(n) || /back/.test(n)) ? "rear" : null);
    var kind;
    if (n.indexOf("wheel") >= 0) kind = "wheel";
    else if (n.indexOf("arm") >= 0) kind = "arm";                              // ipex *_drum_arm_joint + ez arm_*_hinge
    else if (n.indexOf("drum") >= 0 || n.indexOf("spin") >= 0) kind = "drum";  // ipex *_drum_spin_joint + ez drum_*_hinge
    else kind = "other";
    return { kind: kind, side: side, end: end };
  }

  function wheelLabel(c) {
    var e = c.end === "front" ? "F" : (c.end === "rear" ? "R" : "?");
    var s = c.side === "left" ? "L" : (c.side === "right" ? "R" : "?");
    return e + s;                                                              // FL / FR / RL / RR
  }
  var END_RANK = { front: 0, rear: 1 };
  var SIDE_RANK = { left: 0, right: 1 };
  function byEndSide(a, b) {
    var e = (END_RANK[a.end] === undefined ? 9 : END_RANK[a.end]) - (END_RANK[b.end] === undefined ? 9 : END_RANK[b.end]);
    if (e !== 0) return e;
    return (SIDE_RANK[a.side] === undefined ? 9 : SIDE_RANK[a.side]) - (SIDE_RANK[b.side] === undefined ? 9 : SIDE_RANK[b.side]);
  }
  function byEnd(a, b) {
    return (END_RANK[a.end] === undefined ? 9 : END_RANK[a.end]) - (END_RANK[b.end] === undefined ? 9 : END_RANK[b.end]);
  }

  // /joint_states (sensor_msgs/JointState) -> classified wheels / arms / drums with display fields.
  function parseJointStates(msg) {
    if (!msg || !Array.isArray(msg.name)) return null;
    var names = msg.name;
    var pos = Array.isArray(msg.position) ? msg.position : [];
    var vel = Array.isArray(msg.velocity) ? msg.velocity : [];
    var eff = Array.isArray(msg.effort) ? msg.effort : [];
    var wheels = [], arms = [], drums = [], other = [];
    for (var i = 0; i < names.length; i++) {
      var c = classifyJoint(names[i]);
      var p = i < pos.length ? pos[i] : null;
      var v = i < vel.length ? vel[i] : null;
      var row = {
        name: names[i], kind: c.kind, side: c.side, end: c.end,
        positionRad: num(p), positionDeg: radToDeg(p), positionWrappedDeg: wrapDeg180(radToDeg(p)),
        velocityRadS: num(v), rpm: radPerSecToRpm(v),
        effort: i < eff.length ? num(eff[i]) : null
      };
      if (c.kind === "wheel") { row.label = wheelLabel(c); wheels.push(row); }
      else if (c.kind === "arm") { row.label = (c.end ? c.end.toUpperCase() : "?") + " ARM"; arms.push(row); }
      else if (c.kind === "drum") { row.label = (c.end ? c.end.toUpperCase() : "?") + " DRUM"; drums.push(row); }
      else { row.label = String(names[i]); other.push(row); }
    }
    wheels.sort(byEndSide); arms.sort(byEnd); drums.sort(byEnd);
    var st = msg.header && msg.header.stamp ? msg.header.stamp : null;
    return {
      names: names, count: names.length,
      wheels: wheels, arms: arms, drums: drums, other: other,
      stampSec: st ? num(st.sec) + (num(st.nanosec) || 0) * 1e-9 : null
    };
  }

  // sensor_msgs/Imu orientation quaternion -> roll/pitch/yaw (deg), REP-103 body frame (x-fwd, y-left,
  // z-up), aerospace ZYX. The yaw formula is the SAME atan2 rt04Client uses for the /odom heading.
  function quatToEuler(q) {
    var x = num(q && q.x), y = num(q && q.y), z = num(q && q.z), w = num(q && q.w);
    if (x === null || y === null || z === null || w === null) {
      return { rollDeg: null, pitchDeg: null, yawDeg: null };
    }
    var roll = Math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y));
    var sp = 2 * (w * y - z * x);
    sp = sp > 1 ? 1 : (sp < -1 ? -1 : sp);              // clamp for asin domain
    var pitch = Math.asin(sp);
    var yaw = Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
    return { rollDeg: roll * RAD2DEG, pitchDeg: pitch * RAD2DEG, yawDeg: yaw * RAD2DEG };
  }

  // /stewie/imu (sensor_msgs/Imu) -> attitude + rates + specific force. gravityMag = |linear_acceleration|
  // (the sensed gravity; ~1.62 m/s^2 lunar when the rover is at rest and level).
  function parseImu(msg) {
    if (!msg) return null;
    var o = msg.orientation || {}, a = msg.angular_velocity || {}, l = msg.linear_acceleration || {};
    var e = quatToEuler(o);
    var lx = num(l.x), ly = num(l.y), lz = num(l.z);
    var gravityMag = (lx === null || ly === null || lz === null)
      ? null : Math.sqrt(lx * lx + ly * ly + lz * lz);
    return {
      quat: { x: num(o.x), y: num(o.y), z: num(o.z), w: num(o.w) },
      rollDeg: e.rollDeg, pitchDeg: e.pitchDeg, yawDeg: e.yawDeg,
      angularVel: { x: num(a.x), y: num(a.y), z: num(a.z) },
      linearAccel: { x: lx, y: ly, z: lz },
      gravityMag: gravityMag,
      frameId: msg.header ? msg.header.frame_id : null
    };
  }

  var API = {
    RAD2DEG: RAD2DEG, RADPS_TO_RPM: RADPS_TO_RPM,
    radToDeg: radToDeg, radPerSecToRpm: radPerSecToRpm, wrapDeg180: wrapDeg180,
    classifyJoint: classifyJoint, parseJointStates: parseJointStates,
    quatToEuler: quatToEuler, parseImu: parseImu
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ROVER_INSTRUMENTS = API;                               // browser (window)
})(typeof window !== "undefined" ? window : null);
