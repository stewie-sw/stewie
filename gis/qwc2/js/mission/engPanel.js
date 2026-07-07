// [REQ:RT-04] The RViz/Foxglove ENGINEERING PANEL pure view-model (PRD §7.B RT-04).
//
// EVIDENCE-ONLY BY CONSTRUCTION (acceptance D3): this module only DERIVES a read-only view model from
// the read-only rosbridge telemetry -- topic freshness, the TF frame tree, the /odom pose + covariance,
// the /rover/state telemetry, and the diagnostics roster. It exports NO publish / advertise / command
// surface, so nothing here can act on the rover. It is pure (no DOM, no ROSLIB, no React), so it
// unit-tests in bare node exactly like catalogLayers.js / gantt_downsample.js. The thin browser shell
// engPanelClient.js subscribes the live topics and feeds each rosbridge publish frame into ingest();
// the MissionEngPanel.jsx plugin renders the derived model. Source of truth for the derivations lives
// HERE (one place, tested); the plugin is a dumb renderer.
(function (root) {
  "use strict";

  // The RT-04 acceptance names topic freshness / TF / robot-model / path / costmap / perception /
  // covariance / diagnostics / SAFE. `live:true` = relayed over the read-only browser WS (the RT-04
  // feeder subscribes exactly /tf, /odom, /rover/state, /rover/leg). `live:false` = named by the
  // acceptance but NOT relayed to the browser -- surfaced honestly as "absent", never fabricated.
  //   * /diagnostics       -- not published by the sim graph.
  //   * /stewie/costmap    -- exists only via the auth-gated POST /ros/export/costmap (AS-11); not on the WS.
  //   * /robot_description -- URDF for the 3-D robot-model render (RViz parity), a deferred increment.
  var EXPECTED_TOPICS = [
    { topic: "/tf",              label: "TF frames",         type: "tf2_msgs/TFMessage",              live: true,  section: "tf" },
    { topic: "/odom",           label: "Odometry + covariance", type: "nav_msgs/Odometry",          live: true,  section: "pose" },
    { topic: "/rover/state",    label: "Rover state",       type: "std_msgs/String",                 live: true,  section: "telemetry" },
    { topic: "/rover/leg",      label: "Rover leg",         type: "std_msgs/String",                 live: true,  section: "telemetry" },
    { topic: "/diagnostics",    label: "Diagnostics",       type: "diagnostic_msgs/DiagnosticArray", live: false, section: "diagnostics" },
    { topic: "/stewie/costmap", label: "Costmap (occupancy)", type: "nav_msgs/OccupancyGrid",        live: false, section: "costmap" },
    { topic: "/robot_description", label: "Robot model (URDF)", type: "std_msgs/String",              live: false, section: "model" }
  ];

  var FRESH_MS = 2500;   // <=2.5 s since the last message = fresh (green); older = stale (amber)

  function freshModel() {
    return {
      topics: {},        // topic -> { lastMs, count, hz, _stamps:[] }  (client-clock liveness)
      frames: {},        // child_frame_id -> { parent, translation, rotation, stampMs }
      odom: null,        // { x, y, z, headingDeg, speed, covariance:[36] }
      state: null,       // parsed /rover/state JSON
      diagnostics: []    // parsed diagnostic_msgs/DiagnosticArray statuses (empty until /diagnostics arrives)
    };
  }

  function _bump(model, topic, nowMs) {
    var t = model.topics[topic] || (model.topics[topic] = { lastMs: null, count: 0, hz: null, _stamps: [] });
    t.lastMs = nowMs; t.count += 1;
    t._stamps.push(nowMs);
    if (t._stamps.length > 8) { t._stamps.shift(); }
    if (t._stamps.length > 1) {
      var span = (t._stamps[t._stamps.length - 1] - t._stamps[0]) / 1000;
      if (span > 0) { t.hz = (t._stamps.length - 1) / span; }
    }
    return t;
  }

  function _yawDeg(q) {
    if (!q) { return null; }
    var yaw = Math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));
    return ((yaw * 180 / Math.PI) % 360 + 360) % 360;   // 0..360
  }

  function _stampMs(header) {
    if (header && header.stamp) { return header.stamp.sec * 1000 + header.stamp.nanosec / 1e6; }
    return null;
  }

  // Fold ONE rosbridge publish frame {topic, msg} into the model. nowMs = client clock (Date.now()).
  // Read-only: it only records/derives; there is no path from here to a publisher.
  function ingest(model, frame, nowMs) {
    if (!frame || !frame.topic) { return model; }
    _bump(model, frame.topic, nowMs);
    var msg = frame.msg;
    if (frame.topic === "/tf" && msg && msg.transforms) {
      msg.transforms.forEach(function (tr) {
        model.frames[tr.child_frame_id] = {
          parent: tr.header ? tr.header.frame_id : null,
          translation: tr.transform ? tr.transform.translation : null,
          rotation: tr.transform ? tr.transform.rotation : null,
          stampMs: _stampMs(tr.header)
        };
      });
    } else if (frame.topic === "/odom" && msg && msg.pose && msg.pose.pose) {
      var p = msg.pose.pose.position, o = msg.pose.pose.orientation;
      model.odom = {
        x: p ? p.x : null, y: p ? p.y : null, z: p ? p.z : null,
        headingDeg: _yawDeg(o),
        speed: (msg.twist && msg.twist.twist) ? msg.twist.twist.linear.x : null,
        covariance: msg.pose.covariance || null
      };
    } else if (frame.topic === "/rover/state" && msg && typeof msg.data === "string") {
      try {
        var d = JSON.parse(msg.data);
        model.state = {
          slip: d.slip, sinkage: d.sinkage_m,
          slopeDeg: (d.slope_rad != null) ? d.slope_rad * 180 / Math.PI : null,
          soc: (d.soc == null) ? null : d.soc,
          legId: d.leg_id, row: d.row, col: d.col,
          entrapped: !!d.entrapped,
          vAchieved: d.v_achieved_mps
        };
      } catch (e) { /* keep last-known on a malformed frame */ }
    } else if (frame.topic === "/diagnostics" && msg && msg.status) {
      model.diagnostics = msg.status.map(function (s) {
        return { level: s.level, name: s.name, message: s.message, hardware_id: s.hardware_id };
      });
    }
    return model;
  }

  // The TF tree: roots (frames that are never a child) then their descendants, children sorted for a
  // stable render. Each row: { frame, parent, translation, stampMs, depth }.
  function tfTree(model) {
    var childOf = model.frames;                 // child_frame_id -> info
    var byParent = {};                          // parent -> [child, ...]
    Object.keys(childOf).forEach(function (c) {
      var par = childOf[c].parent || "(unrooted)";
      (byParent[par] = byParent[par] || []).push(c);
    });
    var roots = Object.keys(byParent).filter(function (p) { return !childOf[p]; }).sort();
    var out = [];
    function emit(frame, depth) {
      var info = childOf[frame];                // undefined for a pure-root parent (e.g. "map")
      out.push({
        frame: frame, depth: depth,
        parent: info ? (info.parent || null) : null,
        translation: info ? (info.translation || null) : null,
        stampMs: info ? (info.stampMs || null) : null
      });
      (byParent[frame] || []).slice().sort().forEach(function (c) { emit(c, depth + 1); });
    }
    roots.forEach(function (r) { emit(r, 0); });
    return out;
  }

  // Per-topic freshness rows for the whole acceptance roster. status: "fresh" | "stale" | "absent".
  // A live-expected topic that never arrived is "absent" too -- honest, not a fabricated liveness.
  function topicRows(model, nowMs) {
    return EXPECTED_TOPICS.map(function (spec) {
      var t = model.topics[spec.topic];
      var status = "absent", ageMs = null, hz = null, count = 0;
      if (t && t.lastMs != null) {
        ageMs = nowMs - t.lastMs; hz = t.hz; count = t.count;
        status = (ageMs <= FRESH_MS) ? "fresh" : "stale";
      }
      return { topic: spec.topic, label: spec.label, type: spec.type, expectedLive: spec.live,
               section: spec.section, status: status, ageMs: ageMs, hz: hz, count: count };
    });
  }

  // Pose + covariance from /odom. nav_msgs/Odometry pose.covariance is a row-major 6x6 over
  // [x, y, z, roll, pitch, yaw]; sigma is the sqrt of the diagonal. Null until /odom arrives.
  function poseCovariance(model) {
    if (!model.odom) { return null; }
    var c = model.odom.covariance, sigma = null;
    if (c && c.length === 36) {
      sigma = { sx: Math.sqrt(Math.max(0, c[0])), sy: Math.sqrt(Math.max(0, c[7])),
                sz: Math.sqrt(Math.max(0, c[14])), syaw: Math.sqrt(Math.max(0, c[35])) };
    }
    return { x: model.odom.x, y: model.odom.y, z: model.odom.z,
             headingDeg: model.odom.headingDeg, speed: model.odom.speed, sigma: sigma };
  }

  function diagnosticsRows(model) { return model.diagnostics.slice(); }

  var API = {
    EXPECTED_TOPICS: EXPECTED_TOPICS, FRESH_MS: FRESH_MS,
    freshModel: freshModel, ingest: ingest, tfTree: tfTree,
    topicRows: topicRows, poseCovariance: poseCovariance, diagnosticsRows: diagnosticsRows
  };
  if (typeof module !== "undefined" && module.exports) { module.exports = API; }   // node:test + `import X from`
  if (root) { root.STEWIE_ENG_PANEL = API; }                                        // browser (window)
})(typeof window !== "undefined" ? window : null);
