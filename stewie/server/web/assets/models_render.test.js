// FS-03 (node:test): the Models-pane renderers are pure -> unit-testable without a browser. FS-15: the
// registry fixture below is the RAW /models response shape, routed through adapters.normalizeModelsRegistry
// exactly as the cockpit does -- this tests the response-fixture -> adapter -> render chain, and the
// failure modes (empty registry, error/empty outcome mapping).
// Run: node --test stewie/server/web/assets/models_render.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const M = require("./models_render.js");
const A = require("./adapters.js");

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// a real /models payload shape (specs/profiles.py + specs/vehicles.py + specs/bodies.py + contracts).
const MODELS = {
  ok: true, profile_count: 2, profiles_deployable: 1, default_profile: "STEWIE_IPEX_V1",
  profiles: [
    { id: "OFFICIAL_LAC_2025_UNVERIFIED", status: "UNVERIFIED", substrate: "official_lac",
      sha256: "7d5c956469a31dda439b39265ccd81ea21f6574e738de6e3d85dadd8570ac551",
      n_cameras: 8, dry_mass_kg: 30.0, capacity_wh: 1332.0, deployment_ready: false },
    { id: "STEWIE_IPEX_V1", status: "VERIFIED", substrate: "stewie",
      sha256: "abc123def456abc123def456abc123def456abc123def456abc123def456abcd",
      n_cameras: 8, dry_mass_kg: 30.0, capacity_wh: 1332.0, deployment_ready: true },
  ],
  vehicle_count: 2, default_vehicle: "ipex",
  vehicles: [
    { id: "ipex", label: "ISRU Pilot Excavator (IPEx)", dry_mass_kg: 30.0,
      capabilities: ["excavate"], provenance: "NASA IPEx specs" },
    { id: "ez_rassor", label: "EZ-RASSOR", dry_mass_kg: 20.0, capabilities: ["drive"], provenance: "UCF EZ-RASSOR" },
  ],
  body_count: 2, default_body: "moon",
  bodies: [
    { id: "moon", label: "Moon", g_m_s2: 1.62, bekker_regime: "gravity-loaded",
      bulk_density_kg_m3: 1300.0, repose_deg: 35.0, confidence: "MEASURED", provenance: "NASA LTV" },
    { id: "bennu", label: "Bennu", g_m_s2: 6e-5, bekker_regime: "microgravity",
      bulk_density_kg_m3: 1190.0, repose_deg: null, confidence: "ESTIMATED", provenance: "Lauretta 2019" },
  ],
  model_governance: {
    contract: "ModelArtifact (stewie.contracts, FS-12/§25.3)",
    schema_endpoint: "/contracts/schema",
    deployment_ready_criteria: ["input_schema declared", "calibrated", "ood_detector present",
      "off the rover command path (command_path == False)"],
    command_path_invariant: "no learned model may be on the rover command path",
    command_path_enforced: true,
    deployed_models: [],
    status: "No learned model is deployed on the command path.",
  },
};

// the pane consumes the FS-15 view model, never the raw payload (mirrors cockpit loadModels).
const VM = A.normalizeModelsRegistry(MODELS);

test("modelsProfilesHTML: renders the system-profile registry with status + sha256", () => {
  const html = M.modelsProfilesHTML(VM, esc);
  assert.ok(html.includes("STEWIE_IPEX_V1"), "verified profile present");
  assert.ok(html.includes("OFFICIAL_LAC_2025_UNVERIFIED"), "unverified profile present");
  assert.ok(html.includes("VERIFIED"), "VERIFIED status rendered");
  assert.ok(html.includes("UNVERIFIED"), "UNVERIFIED status rendered");
  assert.ok(html.includes("7d5c956469a3"), "sha256 prefix rendered");
  assert.ok(html.includes("1 VERIFIED (deployable)"), "deployable count footer");
});

test("modelsProfilesHTML: honest empty when no profiles (adapter -> null VM)", () => {
  assert.strictEqual(A.normalizeModelsRegistry({ ok: true, profiles: [] }), null);
  assert.ok(M.modelsProfilesHTML(null, esc).includes("No profiles served"));
});

test("FS-15 failure modes: /models outcomes map to error/empty view states", () => {
  const err = A.toViewState({ status: 401, json: { ok: false, error: "sign in" },
    normalize: A.normalizeModelsRegistry });
  assert.strictEqual(err.state, "error");
  assert.strictEqual(err.error, "sign in");
  const empty = A.toViewState({ status: 200, json: { ok: true, profiles: [] },
    normalize: A.normalizeModelsRegistry });
  assert.strictEqual(empty.state, "empty");
});

test("modelsRegistriesHTML: renders the vehicle + body registries with provenance", () => {
  const html = M.modelsRegistriesHTML(VM, esc);
  assert.ok(html.includes("ipex"), "vehicle id present");
  assert.ok(html.includes("NASA IPEx specs"), "vehicle provenance rendered");
  assert.ok(html.includes("moon"), "body id present");
  assert.ok(html.includes("gravity-loaded"), "body regime rendered");
  assert.ok(html.includes("MEASURED"), "body confidence rendered");
});

test("modelsRegistriesHTML: honest empty when no registries", () => {
  assert.ok(M.modelsRegistriesHTML(null, esc).includes("No registries served"));
});

test("modelsGovernanceHTML: renders ML-01 gate + the no-command-path status", () => {
  const html = M.modelsGovernanceHTML(VM, esc);
  assert.ok(html.includes("ModelArtifact"), "contract named");
  assert.ok(html.includes("ML-01 deployment-ready gate"), "gate header");
  assert.ok(html.includes("calibrated"), "a gate criterion rendered");
  assert.ok(html.includes("✓ enforced"), "command-path invariant enforced flag");
  assert.ok(html.includes("none on the command path"), "honest no-deployed-model status");
});
