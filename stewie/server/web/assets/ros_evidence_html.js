// [REQ:FS-27] the ROS/Gazebo/RViz EVIDENCE surface render (Validate/System/Report panes): turns the
// /ros/evidence payload into the innerHTML that proves a run matches its runnable profile -- the lifecycle
// nodes, the clock/tf/joint + gz-bridged topics, the RViz displays, and the Gazebo worlds. Pure function,
// no DOM/fetch/globals; node:test'able; esc() injected so the same SEC-04 HTML-escaping hardens the sink.
(function (root) {
  "use strict";

  function _ok(b) {
    return b
      ? '<span style="color:var(--accent)">✓</span>'
      : '<span style="color:var(--muted)">✗</span>';
  }

  function rosEvidenceHTML(e, esc) {
    e = e || {};
    var roles = (e.lifecycle_nodes || []).map(function (n) { return esc(n.role); }).join(" · ");
    var displays = (e.rviz_displays || []).filter(function (d) { return d && d.name; })
      .map(function (d) { return esc(d.name); }).slice(0, 16).join(" · ");
    var worlds = (e.gazebo_worlds || []).map(esc).join(", ");
    var nBridged = (e.gz_bridged_topics || []).length;
    return '<div class="ros-evidence">'
      + '<div><b>ROS lifecycle nodes (' + (e.n_nodes || 0) + ')</b> — ' + roles + "</div>"
      + '<div style="margin-top:4px">clock ' + _ok(e.clock_present) + " · tf " + _ok(e.tf_present)
      + " · joint_states " + _ok(e.joint_states_present) + " · gz-bridged topics " + nBridged + "</div>"
      + '<div style="margin-top:4px"><b>RViz displays (' + (e.n_rviz_displays || 0) + ")</b> — "
      + displays + "</div>"
      + '<div style="margin-top:4px"><b>Gazebo worlds</b> — ' + (worlds || "—") + "</div>"
      + '<div style="margin-top:4px"><b>Container tiers</b> — '
      + ((e.container_tiers || []).map(esc).join(" · ") || "—") + "</div>"
      + "</div>";
  }

  var API = { rosEvidenceHTML: rosEvidenceHTML };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ROS_EVIDENCE = API;                                    // browser (window)
})(typeof window !== "undefined" ? window : null);
