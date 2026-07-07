// [REQ:AS-03] Rover KINEMATIC WIREFRAME view-model (PRD §7.B RT-04) -- the URDF-faithful IPEx skeleton
// projected to orthographic SIDE / FRONT / BACK / TOP panels, with the articulated joints posed LIVE from
// the /joint_states already flowing into the MissionHUD (via rt04Client -> roverInstruments.parseJointStates).
//
// GROUND TRUTH: every dimension below is transcribed from ros2_ws/src/stewie_description/urdf/ipex.urdf.xacro
// (REP-103 body frame: x-forward, y-left, z-up; metres). Nothing here is fabricated: the geometry is the URDF,
// and the pose comes from the real parsed joint POSITION angles. When no telemetry has arrived the pose falls
// back to a neutral zero pose (arms straight out) so the panel never implies data it does not have.
//
// PURE + node-testable exactly like roverInstruments.js: no DOM, no React, no ROSLIB. It returns 2D line/
// circle/poly/node/cone primitives (in world metres, u=screen-right, v=screen-up) + a bounds box per view;
// the MissionHUD plugin fits those into an SVG viewBox and redraws them on every telemetry frame.
//
// EVIDENCE-ONLY BY CONSTRUCTION: it only DERIVES a read-only picture; it exports no publish/advertise/command
// surface, so nothing here can act on the rover.
(function (root) {
  "use strict";

  // ============================ authoritative URDF dimensions (ipex.urdf.xacro) ============================
  // <xacro:property> values, verbatim. cam_z / cam_fwd are the xacro-derived expressions evaluated.
  var U = {
    wheelbase:      0.30,      // front<->rear wheel separation (x)
    track_gauge:    0.3645,    // left<->right wheel separation (y)
    wheel_radius:   0.1525,
    wheel_width:    0.18,
    cg_height:      0.21,      // chassis box + IMU z
    chassis_len:    0.46,      // x
    chassis_wid:    0.30,      // y
    chassis_hgt:    0.18,      // z
    drum_radius:    0.21855,
    drum_width:     0.3526,
    drum_reach:     0.32,      // arm reach; drum sits drum_reach/2 out from the hinge
    stereo_baseline: 0.05,     // TRL5-final front stereo baseline
    // derived (xacro): cam_z = cg_height + chassis_hgt/2 + 0.10 ; cam_fwd = chassis_len/2
    cam_z:          0.21 + 0.18 / 2 + 0.10,   // 0.40
    cam_fwd:        0.46 / 2                   // 0.23
  };

  var HALF = {
    // hinge x for the two drum arms: wheelbase/2 + drum_reach/2 (front), negated (rear)
    front_hinge_x:  U.wheelbase / 2 + U.drum_reach / 2,   // 0.31
    rear_hinge_x: -(U.wheelbase / 2 + U.drum_reach / 2),  // -0.31
    drum_offset:    U.drum_reach / 2                       // 0.16, drum out from hinge along the arm
  };

  // ------- the 4 skid-steer wheels: (x=+/-wheelbase/2, y=+/-track_gauge/2, z=0), spin about +Y -------
  function wheelPositions() {
    var hx = U.wheelbase / 2, hy = U.track_gauge / 2;
    return [
      { name: "front_left_wheel",  label: "FL", x:  hx, y:  hy, z: 0 },
      { name: "front_right_wheel", label: "FR", x:  hx, y: -hy, z: 0 },
      { name: "rear_left_wheel",   label: "RL", x: -hx, y:  hy, z: 0 },
      { name: "rear_right_wheel",  label: "RR", x: -hx, y: -hy, z: 0 }
    ];
  }

  // ------- the 8-camera rig (mast z=cam_z=0.40 except the two drum cams at cg_height). role from the
  //         URDF comments: front stereo + left_mono + drum_front are OPERATIONAL; the rest REDUNDANT. -------
  function cameras() {
    var b2 = U.stereo_baseline / 2, w2 = U.chassis_wid / 2, hb = U.wheelbase / 2;
    return [
      { frame: "front_left",  label: "FL", x:  U.cam_fwd, y:  b2, z: U.cam_z,     yaw: 0,             role: "operational" },
      { frame: "front_right", label: "FR", x:  U.cam_fwd, y: -b2, z: U.cam_z,     yaw: 0,             role: "operational" },
      { frame: "rear_left",   label: "RL", x: -U.cam_fwd, y: -b2, z: U.cam_z,     yaw: Math.PI,       role: "redundant" },
      { frame: "rear_right",  label: "RR", x: -U.cam_fwd, y:  b2, z: U.cam_z,     yaw: Math.PI,       role: "redundant" },
      { frame: "left_mono",   label: "LM", x: 0,          y:  w2, z: U.cam_z,     yaw:  Math.PI / 2,  role: "operational" },
      { frame: "right_mono",  label: "RM", x: 0,          y: -w2, z: U.cam_z,     yaw: -Math.PI / 2,  role: "redundant" },
      { frame: "drum_front",  label: "DF", x:  hb,        y: 0,   z: U.cg_height, yaw: 0,             role: "operational" },
      { frame: "drum_back",   label: "DB", x: -hb,        y: 0,   z: U.cg_height, yaw: Math.PI,       role: "redundant" }
    ];
  }

  // ------- swappable depth-source hardpoints on the forward mast (stereo/LiDAR/RGB-D share these mounts) -----
  function depthMounts() {
    var f = U.cam_fwd;
    return [
      { name: "depth_sensor_mount", label: "DEPTH", x: f + 0.02, y: 0, z: U.cam_z + 0.04 },
      { name: "lidar_front_mount",  label: "LIDAR", x: f + 0.03, y: 0, z: U.cam_z + 0.07 },
      { name: "rgbd_front_mount",   label: "RGBD",  x: f + 0.03, y: 0, z: U.cam_z + 0.04 }
    ];
  }

  var IMU = { name: "imu_link", label: "IMU", x: 0, y: 0, z: U.cg_height };

  // ============================ kinematics ============================
  // rotate a body-frame point about +Y (the wheel / arm / drum spin axis) by theta.
  //   R_y(t): x' = x cos t + z sin t ;  z' = -x sin t + z cos t ;  y unchanged
  function rotateY(p, theta) {
    var c = Math.cos(theta), s = Math.sin(theta);
    return { x: p.x * c + p.z * s, y: p.y, z: -p.x * s + p.z * c };
  }

  // the arm swings the drum about its hinge: drum centre = hinge + R_y(armAngle) * (drum_offset along arm-x).
  // front offset is +drum_offset, rear is -drum_offset (the arm reaches ahead / behind respectively).
  function drumCenter(end, armAngleRad) {
    var hingeX = end === "rear" ? HALF.rear_hinge_x : HALF.front_hinge_x;
    var off = { x: (end === "rear" ? -HALF.drum_offset : HALF.drum_offset), y: 0, z: 0 };
    var r = rotateY(off, armAngleRad || 0);
    return { x: hingeX + r.x, y: 0, z: r.z };
  }

  // a spin mark (spoke) on a +Y spinner (wheel or drum): tip = centre + R_y(angle)*(radius along +x).
  function spokeTip(center, radius, angleRad) {
    var r = rotateY({ x: radius, y: 0, z: 0 }, angleRad || 0);
    return { x: center.x + r.x, y: center.y + r.y, z: center.z + r.z };
  }

  // pull the live joint angles (radians) out of the parsed roverInstruments model; default 0 (neutral pose).
  function anglesFromJoints(joints) {
    var w = { FL: 0, FR: 0, RL: 0, RR: 0 }, a = { front: 0, rear: 0 }, d = { front: 0, rear: 0 };
    var has = false;
    function set(bag, key, val) { if (key != null && bag.hasOwnProperty(key) && val != null && !Number.isNaN(val)) { bag[key] = val; has = true; } }
    if (joints) {
      (joints.wheels || []).forEach(function (x) { set(w, x.label, x.positionRad); });
      (joints.arms   || []).forEach(function (x) { set(a, x.end, x.positionRad); });
      (joints.drums  || []).forEach(function (x) { set(d, x.end, x.positionRad); });
    }
    return { wheels: w, arms: a, drums: d, hasData: has };
  }

  // ============================ orthographic projectors ============================
  // Each returns {u, v} in world metres, u = screen-right, v = screen-up. Derivations (right = up x toward-viewer):
  //   SIDE  looking along -Y (rover faces screen-right): u = x, v = z
  //   FRONT looking along -X (viewer in front): u = y, v = z      (true front view: rover-left at screen-right)
  //   BACK  looking along +X (viewer behind):   u = -y, v = z     (mirror of front)
  //   TOP   looking along -Z (plan, nose-up):   u = -y, v = x      (forward up, rover-left at screen-left)
  var PROJECTORS = {
    side:  function (p) { return { u: p.x,  v: p.z }; },
    front: function (p) { return { u: p.y,  v: p.z }; },
    back:  function (p) { return { u: -p.y, v: p.z }; },
    top:   function (p) { return { u: -p.y, v: p.x }; }
  };
  function project(view, p) { return (PROJECTORS[view] || PROJECTORS.side)(p); }

  // project the 8 corners of an axis-aligned box (centre +/- half per axis) and return the (u,v) bbox rectangle.
  // Correct for an axis-aligned box under an axis-aligned orthographic projection (wheels/drums seen edge-on,
  // chassis in every view).
  function boxRect(view, center, half, cls) {
    var minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
    for (var sx = -1; sx <= 1; sx += 2) {
      for (var sy = -1; sy <= 1; sy += 2) {
        for (var sz = -1; sz <= 1; sz += 2) {
          var q = project(view, { x: center.x + sx * half.x, y: center.y + sy * half.y, z: center.z + sz * half.z });
          if (q.u < minU) minU = q.u; if (q.u > maxU) maxU = q.u;
          if (q.v < minV) minV = q.v; if (q.v > maxV) maxV = q.v;
        }
      }
    }
    return {
      type: "poly", cls: cls, closed: true,
      pts: [{ u: minU, v: minV }, { u: maxU, v: minV }, { u: maxU, v: maxV }, { u: minU, v: maxV }]
    };
  }

  // ============================ FOV cone ============================
  // schematic pointing wedge (the DIRECTION is the URDF yaw; the +/-30 deg spread + 0.18 m length are a
  // schematic indicator, NOT a measured intrinsic -- the URDF carries no FOV). The optical axis is horizontal
  // (yaw only): axis = (cos yaw, sin yaw, 0). We project that axis into the panel and draw a 2D wedge around
  // the projected direction, so a cone shows in every view where the axis has in-plane extent and is dropped
  // where the axis is perpendicular to the view plane (e.g. a forward cam in FRONT view, a side mono in SIDE).
  var FOV_HALF = 30 * Math.PI / 180, FOV_LEN = 0.18;
  function fovCone(view, cam, cls) {
    var apex = project(view, cam);
    var tip = project(view, { x: cam.x + Math.cos(cam.yaw), y: cam.y + Math.sin(cam.yaw), z: cam.z });
    var du = tip.u - apex.u, dv = tip.v - apex.v;
    if (Math.hypot(du, dv) < 1e-6) return null;   // optical axis ~perpendicular to this view plane -> no cone
    var ang = Math.atan2(dv, du);
    function edge(sign) {
      var a = ang + sign * FOV_HALF;
      return { u: apex.u + FOV_LEN * Math.cos(a), v: apex.v + FOV_LEN * Math.sin(a) };
    }
    return { type: "cone", cls: cls, pts: [apex, edge(+1), edge(-1)] };
  }

  // ============================ per-view assembly ============================
  function pushBounds(b, u, v) {
    if (u < b.minU) b.minU = u; if (u > b.maxU) b.maxU = u;
    if (v < b.minV) b.minV = v; if (v > b.maxV) b.maxV = v;
  }
  function accumulateBounds(prims) {
    var b = { minU: Infinity, maxU: -Infinity, minV: Infinity, maxV: -Infinity };
    prims.forEach(function (p) {
      if (p.type === "circle") { pushBounds(b, p.u - p.r, p.v - p.r); pushBounds(b, p.u + p.r, p.v + p.r); }
      else if (p.type === "line") { pushBounds(b, p.u1, p.v1); pushBounds(b, p.u2, p.v2); }
      else if (p.type === "node" || p.type === "label") { pushBounds(b, p.u, p.v); }
      else if (p.pts) { p.pts.forEach(function (q) { pushBounds(b, q.u, q.v); }); }
    });
    return b;
  }

  // Build one orthographic panel of primitives for `view`, posed from `joints` (parsed roverInstruments model
  // or null). Returns { view, primitives, bounds, angles }.
  function buildView(view, joints) {
    if (!PROJECTORS[view]) view = "side";
    var ang = anglesFromJoints(joints);
    var prims = [];
    var isPlan = view === "top";

    // --- chassis box (centre 0,0,cg_height ; dims chassis_len x wid x hgt) ---
    prims.push(boxRect(view, { x: 0, y: 0, z: U.cg_height },
      { x: U.chassis_len / 2, y: U.chassis_wid / 2, z: U.chassis_hgt / 2 }, "chassis"));

    // --- ground datum line at z=0 (side/front/back only; the wheel-contact plane) ---
    if (!isPlan) {
      var span = view === "side" ? 0.85 : 0.45;
      prims.push({ type: "line", cls: "ground", u1: -span, v1: 0, u2: span, v2: 0 });
    }

    // --- camera mast stub (chassis top z=0.30 -> mast z=cam_z=0.40) at centre ---
    if (!isPlan) {
      var mtop = project(view, { x: 0, y: 0, z: U.cam_z });
      var mbot = project(view, { x: 0, y: 0, z: U.cg_height + U.chassis_hgt / 2 });
      prims.push({ type: "line", cls: "mast", u1: mbot.u, v1: mbot.v, u2: mtop.u, v2: mtop.v });
    }

    // --- 4 wheels: side => circle + live spin spoke ; other views => edge-on/footprint rectangle ---
    wheelPositions().forEach(function (wp) {
      var center = { x: wp.x, y: wp.y, z: 0 };
      var spin = ang.wheels[wp.label] || 0;
      if (view === "side") {
        var c = project(view, center);
        prims.push({ type: "circle", cls: "wheel", u: c.u, v: c.v, r: U.wheel_radius });
        var tip = project(view, spokeTip(center, U.wheel_radius, spin));
        prims.push({ type: "line", cls: "wheel-spoke", u1: c.u, v1: c.v, u2: tip.u, v2: tip.v });
      } else {
        prims.push(boxRect(view, center,
          { x: U.wheel_radius, y: U.wheel_width / 2, z: U.wheel_radius }, "wheel"));
      }
    });

    // --- 2 drum arms + drums: arm line hinge->drum centre ; drum side => circle + spin spoke, else rectangle ---
    ["front", "rear"].forEach(function (end) {
      var hingeX = end === "rear" ? HALF.rear_hinge_x : HALF.front_hinge_x;
      var hinge = { x: hingeX, y: 0, z: 0 };
      var center = drumCenter(end, ang.arms[end]);
      var hp = project(view, hinge), cp = project(view, center);
      prims.push({ type: "line", cls: "arm", u1: hp.u, v1: hp.v, u2: cp.u, v2: cp.v });
      if (view === "side") {
        prims.push({ type: "circle", cls: "drum", u: cp.u, v: cp.v, r: U.drum_radius });
        var dtip = project(view, spokeTip(center, U.drum_radius, ang.drums[end] || 0));
        prims.push({ type: "line", cls: "drum-spoke", u1: cp.u, v1: cp.v, u2: dtip.u, v2: dtip.v });
      } else {
        prims.push(boxRect(view, center,
          { x: U.drum_radius, y: U.drum_width / 2, z: U.drum_radius }, "drum"));
      }
    });

    // --- 8 cameras: node + role-coloured FOV cone + label ---
    cameras().forEach(function (cam) {
      var p = project(view, cam);
      var op = cam.role === "operational";
      var cone = fovCone(view, cam, op ? "fov-op" : "fov-red");
      if (cone) prims.push(cone);
      prims.push({ type: "node", cls: op ? "cam-op" : "cam-red", u: p.u, v: p.v, shape: "square", frame: cam.frame });
      prims.push({ type: "label", cls: op ? "label-op" : "label-red", u: p.u, v: p.v, text: cam.label });
    });

    // --- depth / LiDAR / RGB-D hardpoints (forward mast) ---
    depthMounts().forEach(function (m) {
      var p = project(view, m);
      prims.push({ type: "node", cls: "depth", u: p.u, v: p.v, shape: "diamond", frame: m.name });
    });
    // one shared DEPTH label at the primary depth mount to avoid clutter
    var dp = project(view, depthMounts()[0]);
    prims.push({ type: "label", cls: "label-dim", u: dp.u, v: dp.v, text: "DEPTH" });

    // --- IMU ---
    var ip = project(view, IMU);
    prims.push({ type: "node", cls: "imu", u: ip.u, v: ip.v, shape: "cross", frame: "imu_link" });
    prims.push({ type: "label", cls: "label-dim", u: ip.u, v: ip.v, text: "IMU" });

    return { view: view, primitives: prims, bounds: accumulateBounds(prims), angles: ang };
  }

  var VIEWS = ["side", "front", "back", "top"];
  function buildAll(joints) {
    var out = {};
    VIEWS.forEach(function (v) { out[v] = buildView(v, joints); });
    return out;
  }

  var API = {
    URDF: U, HINGE: HALF, VIEWS: VIEWS,
    wheelPositions: wheelPositions, cameras: cameras, depthMounts: depthMounts, IMU: IMU,
    rotateY: rotateY, drumCenter: drumCenter, spokeTip: spokeTip, anglesFromJoints: anglesFromJoints,
    PROJECTORS: PROJECTORS, project: project, boxRect: boxRect, fovCone: fovCone,
    buildView: buildView, buildAll: buildAll
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ROVER_WIREFRAME = API;                                 // browser (window)
})(typeof window !== "undefined" ? window : null);
