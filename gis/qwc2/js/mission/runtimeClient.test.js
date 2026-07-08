// Runtime Context rail: the client normalizes the PUBLIC /runtime/profiles registry. Fixture = a real curl
// of the live backend (artemis.stewie.space/api/runtime/profiles, 2026-07-08) -- not synthetic.
const assert = require("node:assert");
const { test } = require("node:test");
const R = require("./runtimeClient.js");

const REAL = {   // verbatim shape/values from GET /api/runtime/profiles
  ok: true, count: 7, profiles: [
    { id: "desktop_sil", kind: "sil", command_capability: "none", evidence_class: "sil", can_release: false, can_execute: false, description: "software-in-the-loop" },
    { id: "gazebo_sim", kind: "sim", command_capability: "bounded", evidence_class: "sim", can_release: false, can_execute: false, description: "gazebo sim, truth-isolated" },
    { id: "hil", kind: "hil", command_capability: "bounded", evidence_class: "hil", can_release: true, can_execute: true, description: "hardware in the loop" },
    { id: "live_rover", kind: "live", command_capability: "full", evidence_class: "live", can_release: true, can_execute: true, description: "the real rover" }
  ]
};

test("profilesUrl is the public runtime registry endpoint", () => {
  assert.strictEqual(R.profilesUrl(), "/api/runtime/profiles");
});

test("buildProfilesModel normalizes profiles + derives the command authority", () => {
  const m = R.buildProfilesModel(REAL);
  assert.strictEqual(m.ok, true);
  assert.strictEqual(m.count, 4);
  const sil = m.profiles.find((p) => p.id === "desktop_sil");
  assert.strictEqual(sil.authority, "evidence only");     // cmd none, no release/execute
  assert.strictEqual(sil.release, false);
  const gz = m.profiles.find((p) => p.id === "gazebo_sim");
  assert.strictEqual(gz.authority, "bounded (sim)");       // bounded cmd but cannot release/execute
  const live = m.profiles.find((p) => p.id === "live_rover");
  assert.strictEqual(live.authority, "live command");      // can execute on real hardware
  assert.strictEqual(live.command, "full");
});

test("buildProfilesModel surfaces an error honestly", () => {
  assert.strictEqual(R.buildProfilesModel({ ok: false }).ok, false);
  assert.strictEqual(R.buildProfilesModel(null).ok, false);
});
