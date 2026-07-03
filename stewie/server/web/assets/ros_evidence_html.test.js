// [REQ:FS-27] the ROS/Gazebo/RViz evidence surface render shows the lifecycle nodes, clock/tf/joint status,
// the RViz displays, and the Gazebo worlds -- the evidence a run's runnable-profile match rests on.
const test = require("node:test");
const assert = require("node:assert");
const { rosEvidenceHTML } = require("./ros_evidence_html.js");

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

test("rosEvidenceHTML: surfaces lifecycle nodes + clock/tf/joint + rviz displays + gazebo worlds", () => {
  const e = { n_nodes: 9, lifecycle_nodes: [{ role: "perception" }, { role: "mapping" }],
    clock_present: true, tf_present: true, joint_states_present: true,
    gz_bridged_topics: ["/a", "/b"], n_rviz_displays: 3,
    rviz_displays: [{ name: "Rock Graph", topic: "/x" }, { name: "Relocalization Factors", topic: "/y" }],
    gazebo_worlds: ["haworth_heightfield.sdf", "stewie_lunar.sdf"] };
  const h = rosEvidenceHTML(e, esc);
  assert.ok(h.includes("ROS lifecycle nodes (9)"), "node count");
  assert.ok(h.includes("perception") && h.includes("mapping"), "node roles");
  assert.ok(h.includes("clock") && h.includes("✓"), "clock/tf/joint status");
  assert.ok(h.includes("Relocalization Factors"), "rviz displays surfaced");
  assert.ok(h.includes("haworth_heightfield.sdf"), "gazebo worlds surfaced");
});

test("rosEvidenceHTML: absent evidence renders safely (✗, no crash)", () => {
  const h = rosEvidenceHTML({ clock_present: false }, esc);
  assert.ok(h.includes("✗") && h.includes("Gazebo worlds"));
});

test("rosEvidenceHTML: escapes a hostile display name (SEC-04)", () => {
  const h = rosEvidenceHTML({ rviz_displays: [{ name: "<img onerror=x>", topic: "/z" }] }, esc);
  assert.ok(!h.includes("<img onerror=x") && h.includes("&lt;img"));
});
