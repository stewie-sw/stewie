// [REQ:EV-01] (node:test): the QWC2 Evidence/Report bridge is pure data/logic (no DOM, no React) so its
// URL builder + axis/section derivations unit-test in bare node. Asserts the REAL outputs of the actual
// module logic in evidenceReport.js against a representative /api/evidence/bundle payload: the public read
// URL, the 5-axis reproduced summary, the plan/layer/profile/world/audit row projections, and -- the
// honesty invariant -- that host-gated captures render as "not captured" with a reason and NEVER a
// fabricated path.
// (JS-only citation: the python req_trace + gen scanners scan python test_*.py, so this does NOT trigger a
// gen regen; the [REQ:EV-01] backend citation is stewie/server/test_ev01_evidence_bundle.py.)
// Run: node --test gis/qwc2/js/mission/evidenceReport.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const E = require("./evidenceReport.js");

// A representative bundle mirroring the real backend shape (one SIM run persisted).
const BUNDLE = {
  ok: true, site: "haworth", mission: "cockpit-run", bundle_sha: "a".repeat(64),
  plan_inputs: {
    n_plans: 1, n_reports: 2,
    plan_transactions: [{ seq: 1, plan_id: "deadbeefcafef00d1234", mission: "cockpit-run",
      provenance: "SIM run: released plan cockpit-run" }],
    reports: [{ stem: "report-abc", pdf: "/reports/report-abc.pdf", md: "/reports/report-abc.md",
      size_bytes: 58000, mtime: 1782735694 }]
  },
  selected_layers: {
    catalog_count: 66, n_planning_layers: 2,
    planning_layers: [
      { id: "terrain.slope", domain: "terrain", type: "raster", source_class: "derived",
        confidence: { cls: "derived", tier: "medium" }, release_execute_eligible: true },
      { id: "hazard.costmap", domain: "hazard", type: "raster", source_class: "observed/prior",
        confidence: { cls: "measured", tier: "high" }, release_execute_eligible: false }
    ],
    freshness: { observed: true, observed_fraction: 0.42, provenance_class: "observed",
      dem_source: "haworth_10km_5m", twin_version: 3, as_built_version: 1, mutated: true }
  },
  runtime_profile: {
    active_profile_id: "desktop_sil", count: 7,
    active_profile: { id: "desktop_sil", evidence_class: "forecast", can_execute: false },
    registry: [
      { id: "desktop_sil", kind: "software_in_loop", command_capability: "none",
        evidence_class: "forecast", can_release: false, can_execute: false },
      { id: "live_rover", kind: "live", command_capability: "full", evidence_class: "live",
        can_release: true, can_execute: true }
    ]
  },
  world_transactions: {
    count: 3, verified: true, returned: 2,
    transactions: [
      { seq: 1, world_sha: "1111111111112222", plan_id: "deadbeefcafef00d1234", mission: "cockpit-run",
        provenance: "SIM run: released plan cockpit-run" },
      { seq: 2, world_sha: "3333333333334444", plan_id: null, mission: "cockpit-run",
        provenance: "SIM leg: leg [nominal]" }
    ]
  },
  audit: {
    executive: { verified: true, count: 1, returned: 1,
      records: [{ actor: "director", action: "executive.run", timestamp: "2026-07-07T12:00:00+00:00",
        location: "cockpit-run@haworth", mode: "sim", reason: "SIM run abc",
        before_state: "released", after_state: "completed", evidence: "run_id=abc;legs=4" }] }
  },
  artifacts: {
    ros_gazebo_rviz: { lifecycle_nodes: [{ name: "safing" }], gazebo_worlds: ["haworth.sdf"] },
    captures: [
      { kind: "ros_bag", what: "rosbag2 MCAP", captured: false, reason: "host-gated: requires a live ROS2 run" },
      { kind: "gazebo_recording", what: "Gazebo recording", captured: false, reason: "host-gated: needs Gazebo" },
      { kind: "rviz_capture", what: "RViz screengrab", captured: false, reason: "host-gated: needs RViz" },
      { kind: "godot_frames", what: "Godot PNGs", captured: false, reason: "host-gated: needs a GPU render" }
    ],
    host_gated_kinds: ["ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"]
  },
  reproduced: ["plan_inputs", "selected_layers", "runtime_profile", "world_transactions", "audit"],
  host_gated: ["ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"]
};

test("AXES: the five reproduced axes in display order", () => {
  assert.deepStrictEqual(E.AXES.map((a) => a.key),
    ["plan_inputs", "selected_layers", "runtime_profile", "world_transactions", "audit"]);
});

test("bundleUrl targets the PUBLIC /api/evidence/bundle read with filters", () => {
  assert.strictEqual(E.bundleUrl(), "/api/evidence/bundle?site=haworth");
  assert.strictEqual(E.bundleUrl({ site: "nobile", mission: "m1", session: "s9", limit: 20 }),
    "/api/evidence/bundle?site=nobile&mission=m1&session=s9&limit=20");
});

test("axes(): reproduced flags come from the backend's own list; summaries carry real counts", () => {
  const ax = E.axes(BUNDLE);
  assert.strictEqual(ax.length, 5);
  assert.ok(ax.every((a) => a.reproduced === true));
  const byKey = Object.fromEntries(ax.map((a) => [a.key, a]));
  assert.match(byKey.plan_inputs.summary, /1 plan tx · 2 reports/);
  assert.match(byKey.world_transactions.summary, /3 tx · chain verified/);
  assert.match(byKey.audit.summary, /1 records · chain verified/);
  assert.match(byKey.runtime_profile.summary, /desktop_sil · 7 profiles/);
});

test("an axis NOT in the backend's reproduced list is honestly marked not-reproduced", () => {
  const partial = Object.assign({}, BUNDLE, { reproduced: ["plan_inputs", "runtime_profile"] });
  const byKey = Object.fromEntries(E.axes(partial).map((a) => [a.key, a]));
  assert.strictEqual(byKey.plan_inputs.reproduced, true);
  assert.strictEqual(byKey.audit.reproduced, false);        // not asserted -> honest false
});

test("section rows: plan / layer / profile / world / audit project the real fields", () => {
  assert.strictEqual(E.planTxnRows(BUNDLE)[0].planId, "deadbeefcafe");   // short sha
  assert.strictEqual(E.reportRows(BUNDLE)[0].size, "57 KB");
  const ly = E.layerRows(BUNDLE);
  assert.deepStrictEqual(ly.map((l) => l.id), ["terrain.slope", "hazard.costmap"]);
  assert.strictEqual(ly[1].confidence, "measured");
  const prof = E.profileRows(BUNDLE);
  assert.strictEqual(prof.find((p) => p.id === "desktop_sil").active, true);
  assert.strictEqual(prof.find((p) => p.id === "live_rover").canExecute, true);
  assert.strictEqual(E.worldTxnRows(BUNDLE)[0].worldSha, "111111111111");
  assert.strictEqual(E.auditRows(BUNDLE)[0].action, "executive.run");
});

test("captureRows: host-gated captures are 'not captured' WITH a reason, never a fabricated path", () => {
  const caps = E.captureRows(BUNDLE);
  assert.deepStrictEqual(caps.map((c) => c.kind),
    ["ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"]);
  for (const c of caps) {
    assert.strictEqual(c.captured, false);
    assert.ok(c.reason.includes("host-gated"));
    assert.deepStrictEqual(c.paths, []);                     // no fabricated artifact paths
  }
});

test("buildModel: the full normalized view model an EV-01 report renders", () => {
  const m = E.buildModel(BUNDLE);
  assert.strictEqual(m.ok, true);
  assert.strictEqual(m.site, "haworth");
  assert.strictEqual(m.bundleSha, "a".repeat(64));
  assert.strictEqual(m.axes.length, 5);
  assert.strictEqual(m.planTxns.length, 1);
  assert.strictEqual(m.layers.length, 2);
  assert.strictEqual(m.captures.length, 4);
  assert.strictEqual(m.freshness.provenance_class, "observed");   // DT-05 per-site freshness carried through
  assert.strictEqual(m.freshness.dem_source, "haworth_10km_5m");
  assert.deepStrictEqual(m.hostGated, ["ros_bag", "gazebo_recording", "rviz_capture", "godot_frames"]);
  assert.ok(m.rosEvidence && m.rosEvidence.gazebo_worlds.length === 1);
});

test("degrades honestly on an empty/absent bundle (no throw, honest empties)", () => {
  const m = E.buildModel({ ok: false });
  assert.strictEqual(m.ok, false);
  assert.deepStrictEqual(m.planTxns, []);
  assert.deepStrictEqual(m.layers, []);
  assert.deepStrictEqual(m.captures, []);
  assert.ok(E.axes({}).every((a) => a.reproduced === false));   // nothing reproduced -> all honest false
});
