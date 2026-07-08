// Analyze▸Terramechanics: the client normalizes the PUBLIC /world/terramechanics-layers spine for display.
// The fixture is a real curl of the live backend (artemis.stewie.space/api, haworth) -- not synthetic.
const assert = require("node:assert");
const { test } = require("node:test");
const T = require("./terramechClient.js");

const REAL = {   // verbatim shape from GET /api/world/terramechanics-layers?site=haworth (2026-07-08)
  ok: true, backend: "tier2_numpy", derived_layers: [
    { layer: "terrain.slope", from_terms: ["slope"], backend: "tier2_numpy", computed_terms: [] },
    { layer: "terrain.roughness", from_terms: ["roughness"], backend: "tier2_numpy", computed_terms: [] },
    { layer: "physics.bearing", from_terms: ["contact_pressure"], backend: "tier2_numpy", computed_terms: ["contact_pressure"] },
    { layer: "physics.sinkage", from_terms: ["sinkage"], backend: "tier2_numpy", computed_terms: ["sinkage"] }
  ]
};

test("spineUrl encodes the site", () => {
  assert.strictEqual(T.spineUrl("shackleton_rim"), "/api/world/terramechanics-layers?site=shackleton_rim");
});

test("buildSpineModel normalizes derived_layers into group/name/terms/computed/backend", () => {
  const m = T.buildSpineModel(REAL);
  assert.strictEqual(m.ok, true);
  assert.strictEqual(m.backend, "tier2_numpy");
  assert.strictEqual(m.count, 4);
  const bearing = m.layers.find((l) => l.layer === "physics.bearing");
  assert.strictEqual(bearing.group, "physics");
  assert.strictEqual(bearing.name, "bearing");
  assert.deepStrictEqual(bearing.terms, ["contact_pressure"]);
  assert.deepStrictEqual(bearing.computed, ["contact_pressure"]);
  assert.strictEqual(bearing.backend, "tier2_numpy");
  const slope = m.layers.find((l) => l.layer === "terrain.slope");
  assert.deepStrictEqual(slope.computed, []);        // terrain.slope is a raw term, computes nothing
});

test("buildSpineModel surfaces an error honestly (no fabrication)", () => {
  const m = T.buildSpineModel({ ok: false, error: "no dem for site" });
  assert.strictEqual(m.ok, false);
  assert.match(m.error, /no dem/);
  const empty = T.buildSpineModel(null);
  assert.strictEqual(empty.ok, false);
});

const AUTH = {   // real shape from GET /api/physics/authority?  (public, 2026-07-08)
  ok: true, backends: [
    { id: "tier2_numpy", authority_scope: ["terrain", "terramechanics"], conserves_mass: true, valid_for_planning: true, valid_for_rehearsal: true, valid_for_release: true, valid_for_execute: true, refusal_reason: null, description: "conserved authority" },
    { id: "gazebo", authority_scope: ["robot", "sensor"], conserves_mass: false, valid_for_planning: false, valid_for_rehearsal: true, valid_for_release: false, valid_for_execute: false, refusal_reason: "robot/sensor sim only; NOT terrain authority", description: "sim" },
    { id: "godot", authority_scope: [], conserves_mass: false, valid_for_planning: false, valid_for_rehearsal: false, valid_for_release: false, valid_for_execute: false, refusal_reason: "rendering only", description: "render" }
  ]
};

test("authorityUrl + buildAuthorityModel derive the tier + eligibility per backend", () => {
  assert.strictEqual(T.authorityUrl(), "/api/physics/authority");
  const m = T.buildAuthorityModel(AUTH);
  assert.strictEqual(m.ok, true);
  assert.strictEqual(m.count, 3);
  const t2 = m.backends.find((b) => b.id === "tier2_numpy");
  assert.strictEqual(t2.tier, "release authority");
  assert.strictEqual(t2.conserves, true);
  assert.strictEqual(t2.release, true);
  const gz = m.backends.find((b) => b.id === "gazebo");
  assert.strictEqual(gz.tier, "rehearsal only");
  assert.match(gz.refusal, /sim only/);
  const gd = m.backends.find((b) => b.id === "godot");
  assert.strictEqual(gd.tier, "render only");
  assert.strictEqual(T.buildAuthorityModel({ ok: false }).ok, false);
});
