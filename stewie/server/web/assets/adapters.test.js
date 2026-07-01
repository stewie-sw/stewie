// Phase 2 / FS-15 (node:test): the typed frontend contract adapters are pure -> unit-testable without a
// browser. Run: node --test stewie/server/web/assets/adapters.test.js
"use strict";
const { test } = require("node:test");
const assert = require("node:assert");
const A = require("./adapters.js");

test("normalizeEphemeris maps the contract + derives lit", () => {
  const vm = A.normalizeEphemeris({ ephemeris: {
    mission_t_s: 0, site_lat_deg: -87.45, site_lon_deg: 0, frame: "MOON_ME",
    sun_az_deg: 90, sun_el_deg: 6, azimuth_convention: "from_north_eastward",
    uncertainty_deg: 0, source: "analytic" } });
  assert.strictEqual(vm.sun.convention, "from_north_eastward");   // the explicit convention carries through
  assert.strictEqual(vm.site.frame, "MOON_ME");
  assert.strictEqual(vm.lit, true);                                // el 6 > 0 -> sunlit
  assert.strictEqual(A.normalizeEphemeris({}), null);              // no payload -> null
});

test("normalizeWorld maps grid + derives metric extent", () => {
  const vm = A.normalizeWorld({ world: {
    body: "moon", frame: "MOON_ME", rows: 2000, cols: 2000, cell_m: 5,
    datum_radius_m: 1737400, observed_fraction: 0, mutated: false, dem_source: "haworth_10km_5m" } });
  assert.strictEqual(vm.grid.rows, 2000);
  assert.strictEqual(vm.extentM.x, 10000);                         // 2000 * 5 m
  assert.strictEqual(vm.demSource, "haworth_10km_5m");
});

test("toViewState maps loading / ok / empty / error", () => {
  assert.strictEqual(A.toViewState({ status: "pending" }).state, "loading");
  assert.strictEqual(A.toViewState({ status: 500, json: { ok: false, error: "boom" } }).state, "error");
  assert.strictEqual(
    A.toViewState({ status: 200, json: { world: null }, normalize: A.normalizeWorld }).state, "empty");
  assert.strictEqual(
    A.toViewState({ status: 200, json: { ephemeris: { sun_el_deg: 1 } }, normalize: A.normalizeEphemeris }).state, "ok");
});

test("canAct mirrors the AG-01 role ladder (FS-15 permission mapping)", () => {
  assert.strictEqual(A.canAct("command", "trainee"), false);      // command needs operator+
  assert.strictEqual(A.canAct("command", "operator"), true);
  assert.strictEqual(A.canAct("admin", "operator"), false);       // admin needs director
  assert.strictEqual(A.canAct("plan", "guest"), true);            // reads open to guest
  assert.strictEqual(A.canAct("command", "bogus"), false);        // unknown role -> fail closed
});

// ---- the 8 spine contracts completing the FS-15 adapter layer (real VehicleState/FleetState/... fields) ----

test("normalizeVehicle maps VehicleState + derives moving/healthy", () => {
  const vm = A.normalizeVehicle({ vehicle: {
    vehicle_id: "ipex-1", role: "ipex", row: 10, col: 20, yaw_rad: 0.5,
    soc: 0.8, slip: 0.1, sinkage_m: 0.02, entrapped: false, status: "driving" } });
  assert.strictEqual(vm.id, "ipex-1");
  assert.strictEqual(vm.pos.row, 10);
  assert.strictEqual(vm.moving, true);                              // status driving -> under way
  assert.strictEqual(vm.healthy, true);
  const safed = A.normalizeVehicle({ vehicle: { vehicle_id: "x", role: "ipex", row: 0, col: 0,
    yaw_rad: 0, soc: 1, slip: 0, sinkage_m: 0, entrapped: false, status: "safed" } });
  assert.strictEqual(safed.healthy, false);                         // safed -> not healthy
  assert.strictEqual(A.normalizeVehicle({}), null);
});

test("normalizeFleet maps FleetState, reuses the vehicle VM, derives rollups", () => {
  const vm = A.normalizeFleet({ fleet: {
    vehicles: [
      { vehicle_id: "a", role: "ipex", row: 1, col: 1, yaw_rad: 0, soc: 1, slip: 0, sinkage_m: 0, entrapped: false, status: "idle" },
      { vehicle_id: "b", role: "ipex", row: 2, col: 2, yaw_rad: 0, soc: 0.5, slip: 0.2, sinkage_m: 0.3, entrapped: true, status: "blocked" },
    ],
    reservations: [{ resource_id: "charger-1", vehicle_id: "a", t_start: 0, t_end: 100 }],
    conflicts: 1 } });
  assert.strictEqual(vm.count, 2);
  assert.strictEqual(vm.vehicles[0].id, "a");
  assert.strictEqual(vm.anyEntrapped, true);                        // b is entrapped
  assert.strictEqual(vm.hasConflicts, true);
  assert.strictEqual(vm.reservations[0].resourceId, "charger-1");
  assert.strictEqual(A.normalizeFleet({}), null);
});

test("normalizeBelief maps BeliefState + derives diverged", () => {
  const vm = A.normalizeBelief({ belief: {
    vehicle_id: "ipex-1", row: 5, col: 6, yaw_rad: 0.1,
    pos_sigma_m: 0.3, yaw_sigma_rad: 0.01, localized: true, last_relocalization_t_s: 42 } });
  assert.strictEqual(vm.vehicleId, "ipex-1");
  assert.strictEqual(vm.posSigmaM, 0.3);
  assert.strictEqual(vm.diverged, false);
  assert.strictEqual(vm.lastRelocalizationTS, 42);
  const lost = A.normalizeBelief({ belief: { vehicle_id: "x", row: 0, col: 0, yaw_rad: 0,
    pos_sigma_m: 9, yaw_sigma_rad: 1, localized: false, last_relocalization_t_s: null } });
  assert.strictEqual(lost.diverged, true);                          // not localized -> estimator diverged
});

test("normalizePlanResult maps PlanResult + derives MJ/hasBlocked + FS-15 dashboard fields", () => {
  const vm = A.normalizePlanResult({ plan_result: {
    plan_id: "p1", feasible: true, n_orders: 3, vehicles: 1,
    makespan_s: 7200, energy_j: 2000000, mass_moved_kg: 4584.8, blocked_legs: 0,
    recharges: 2, drum_cycles: 61, cut_passes: 2, resolved_algorithm: "nearest" } });
  assert.strictEqual(vm.planId, "p1");
  assert.strictEqual(vm.energyMJ, 2);                               // 2e6 J -> 2 MJ
  assert.strictEqual(vm.hasBlocked, false);
  // FS-15: the dashboard/CONOPS fields the cockpit consumes (so it stops reading legacy `totals` keys)
  assert.strictEqual(vm.recharges, 2);
  assert.strictEqual(vm.drumCycles, 61);
  assert.strictEqual(vm.cutPasses, 2);
  assert.strictEqual(vm.solver, "nearest");
  assert.strictEqual(vm.durationH, 2);                              // 7200 s -> 2 h
  assert.ok(Math.abs(vm.massMovedT - 4.5848) < 1e-9);               // 4584.8 kg -> 4.5848 t
  assert.strictEqual(A.normalizePlanResult({}), null);
});

test("normalizeExecutionEvent maps ExecutionEvent + derives ok", () => {
  const vm = A.normalizeExecutionEvent({ execution_event: {
    t_s: 12, vehicle_id: "ipex-1", kind: "leg", detail: "leg 2", outcome: "blocked" } });
  assert.strictEqual(vm.kind, "leg");
  assert.strictEqual(vm.ok, false);                                 // blocked != ok
  assert.strictEqual(A.normalizeExecutionEvent({ execution_event: {
    t_s: 0, vehicle_id: "x", kind: "command", detail: "", outcome: "ok" } }).ok, true);
});

test("normalizeTimelineFrame maps TimelineFrame + derives durationS (FS-15 gantt)", () => {
  const vm = A.normalizeTimelineFrame({ timeline_frame: {
    t0: 100, t1: 275, phase: "drive", x0: 0, y0: 0, x1: 40, y1: 30,
    batt0_frac: 1.0, batt1_frac: 0.998, cum_mass_kg: 0 } });
  assert.strictEqual(vm.phase, "drive");
  assert.strictEqual(vm.batt0Frac, 1.0);
  assert.strictEqual(vm.batt1Frac, 0.998);
  assert.strictEqual(vm.durationS, 175);                            // t1 - t0
  assert.strictEqual(A.normalizeTimelineFrame({}), null);
});

test("normalizeLocalizationFix maps LocalizationFix + derives errM (FS-15 nav trace)", () => {
  const vm = A.normalizeLocalizationFix({ localization_fix: {
    est: [40, 30], true: [43, 34], sigma: 0.2, fix: "beacon" } });
  assert.deepStrictEqual(vm.truePose, [43, 34]);
  assert.strictEqual(vm.fix, "beacon");
  assert.strictEqual(vm.errM, 5);                                   // hypot(3,4) = 5 est-vs-truth error
  assert.strictEqual(A.normalizeLocalizationFix({}), null);
});

test("normalizeNavFactor maps NavFactor + derives rejected", () => {
  const vm = A.normalizeNavFactor({ nav_factor: {
    factor_id: "f1", kind: "shadow", keyframe_i: 0, keyframe_j: 1,
    residual: 0.02, information: 1.5, accepted: true } });
  assert.strictEqual(vm.kind, "shadow");
  assert.strictEqual(vm.rejected, false);
  assert.strictEqual(A.normalizeNavFactor({ nav_factor: { factor_id: "f2", kind: "loop",
    keyframe_i: 3, keyframe_j: 9, residual: 5, information: 0, accepted: false } }).rejected, true);
});

test("normalizePerception maps depth-source health + derives readiness", () => {
  const vm = A.normalizePerception({ perception_state: {
    source_profile: "stereo_sgbm", frame_id: "ipex_front_stereo_optical",
    point_topic: "/stewie/perception/points", point_count: 65710, valid_fraction: 0.8,
    range_min_m: 0.37, range_max_m: 4.0, covariance_m: 0.3,
    panorama_cameras: 8, shadow_landmarks: 12, accepted_factors: 2,
    no_truth: true, evidence_class: "simulation" } });
  assert.strictEqual(vm.sourceProfile, "stereo_sgbm");
  assert.strictEqual(vm.pointTopic, "/stewie/perception/points");
  assert.strictEqual(vm.pointCount, 65710);
  assert.strictEqual(vm.hasCloud, true);
  assert.strictEqual(vm.hasPanorama, true);
  assert.strictEqual(vm.rangeSpanM, 3.63);
  assert.strictEqual(vm.ready, true);                              // truth-denied cloud/panorama present
  assert.strictEqual(A.normalizePerception({ perception_state: {
    source_profile: "replay", frame_id: "map", point_topic: "/stewie/perception/points",
    point_count: 0, valid_fraction: 0, range_min_m: 0, range_max_m: 0, covariance_m: 0,
    panorama_cameras: 0, shadow_landmarks: 0, accepted_factors: 0,
    no_truth: true, evidence_class: "replay" } }).ready, false);    // no observable input yet
  assert.strictEqual(A.normalizePerception({}), null);
});

test("normalizeModelArtifact mirrors the ML-01 deployment_ready gate", () => {
  const ready = A.normalizeModelArtifact({ model_artifact: {
    model_id: "m1", name: "terrain", version: "1.0", task: "terrain_assess",
    dataset_lineage: "ds1", eval_split: "split1", input_schema: "WorldState", output_schema: "Traversability",
    latency_budget_ms: 50, memory_budget_mb: 512, calibrated: true, ood_detector: true,
    fallback: "deterministic_costmap", quantization: "int8", rollback_to: null, command_path: false } });
  assert.strictEqual(ready.deploymentReady, true);
  const undeclared = A.normalizeModelArtifact({ model_artifact: {
    model_id: "m2", name: "rock", version: "0.1", task: "rock_classify",
    dataset_lineage: "ds2", eval_split: "split2", input_schema: "", output_schema: "",
    latency_budget_ms: 0, memory_budget_mb: 0, calibrated: false, ood_detector: false,
    fallback: null, quantization: "fp32", rollback_to: null, command_path: false } });
  assert.strictEqual(undeclared.deploymentReady, false);            // undeclared schemas/budgets -> not deployable
  assert.strictEqual(A.normalizeModelArtifact({}), null);
});

// ---- FS-15 pane-payload normalizers: the registry work areas' route responses -> view models ----
// (field parity vs the LIVE routes is proven in test_adapter_contract_parity.py; shapes here mirror
// the real /fleet, /construction, /models payloads built by the routers.)

test("normalizeFleetRoster maps the /fleet registry payload + derives capacityMJ/digCount", () => {
  const vm = A.normalizeFleetRoster({ ok: true, count: 2, ui_visible_count: 1, default_vehicle: "ipex",
    live_allocation_source: "plan.totals.vehicles_detail + makespan_s + vehicle_conflicts",
    vehicles: [
      { id: "ipex", label: "ISRU Pilot Excavator (IPEx)", dry_mass_kg: 30.0, n_wheels: 4,
        drum_capacity_kg: 30.0, drive_power_w: 40.38, dig_energy_j_per_kg: 4151.4, can_dig: true,
        ui_visible: true, capabilities: ["drive", "excavate"], provenance: "SCHULER24",
        onboard_power: [{ id: "ipex_battery", label: "IPEx 12S/30Ah Li-ion", kind: "battery",
                          capacity_j: 4795200 }] },
      { id: "hauler", label: "Hauler", dry_mass_kg: 20.0, n_wheels: 4, drum_capacity_kg: 0.0,
        drive_power_w: 40.0, dig_energy_j_per_kg: 0.0, can_dig: false, ui_visible: false,
        capabilities: ["drive"], provenance: "x", onboard_power: [] },
    ] });
  assert.strictEqual(vm.vehicles[0].id, "ipex");
  assert.strictEqual(vm.vehicles[0].dryMassKg, 30.0);
  assert.strictEqual(vm.vehicles[0].onboardPower[0].capacityMJ, 4.7952);  // derived: J -> MJ
  assert.strictEqual(vm.defaultVehicle, "ipex");
  assert.strictEqual(vm.uiVisibleCount, 1);
  assert.strictEqual(vm.digCount, 1);                                     // derived: only ipex digs
  assert.strictEqual(A.normalizeFleetRoster({ ok: true, vehicles: [] }), null);
  assert.strictEqual(A.normalizeFleetRoster(null), null);
});

test("normalizeConstructionCatalog maps the /construction payload (templates + acceptance)", () => {
  const vm = A.normalizeConstructionCatalog({ ok: true, count: 1, balanced_count: 1,
    live_acceptance_source: "plan.validation (validate_plan) + plan.ordered_acceptance (IR replay)",
    templates: [{ id: "blast_berm", doc: "A loose fill ridge.", n_orders: 2, n_cut: 1, n_fill: 1,
      balanced: true,
      orders: [{ action: "Borrow pit (berm)", kind: "cut", footprint_m2: 15.2, depth_m: 0.3, note: "src" },
               { action: "Blast berm", kind: "fill", footprint_m2: 45.0, depth_m: 0.5, note: "ridge" }] }],
    acceptance: {
      checks: [{ id: "as_built_flatness", what: "flatness RMSE within tol", tol_m: 0.02 },
               { id: "slope_siting", what: "no order above max slope", max_slope_deg: 15.0 },
               { id: "bearing_capacity", what: "allowable bearing", factor_of_safety: 3.0 }],
      defers_to_totals: ["route_feasibility", "battery_reserve"] } });
  assert.strictEqual(vm.templates[0].nOrders, 2);
  assert.strictEqual(vm.templates[0].orders[0].footprintM2, 15.2);
  assert.strictEqual(vm.balancedCount, 1);
  assert.strictEqual(vm.acceptance.checks[0].tolM, 0.02);
  assert.strictEqual(vm.acceptance.checks[1].maxSlopeDeg, 15.0);
  assert.strictEqual(vm.acceptance.checks[2].factorOfSafety, 3.0);
  assert.deepStrictEqual(vm.acceptance.defersToTotals, ["route_feasibility", "battery_reserve"]);
  assert.strictEqual(A.normalizeConstructionCatalog({ ok: true, templates: [] }), null);
});

test("normalizeModelsRegistry maps the /models payload + derives anyOnCommandPath", () => {
  const vm = A.normalizeModelsRegistry({ ok: true,
    profile_count: 1, profiles_deployable: 1, default_profile: "STEWIE_IPEX_V1",
    profiles: [{ id: "STEWIE_IPEX_V1", status: "VERIFIED", substrate: "stewie", sha256: "abc123def456",
                 source: "specs/profiles", n_cameras: 8, dry_mass_kg: 30.0, capacity_wh: 1332.0,
                 deployment_ready: true }],
    vehicle_count: 1, default_vehicle: "ipex",
    vehicles: [{ id: "ipex", label: "IPEx", dry_mass_kg: 30.0, provenance: "SCHULER24" }],
    body_count: 1, default_body: "moon",
    bodies: [{ id: "moon", label: "Moon", g_m_s2: 1.62, bekker_regime: "gravity-loaded",
               confidence: "MEASURED", provenance: "NASA LTV" }],
    model_governance: { contract: "ModelArtifact", schema_endpoint: "/contracts/schema",
      deployment_ready_criteria: ["calibrated"], command_path_invariant: "no learned model on command path",
      command_path_enforced: true, deployed_models: [], status: "none deployed" } });
  assert.strictEqual(vm.profiles[0].deploymentReady, true);
  assert.strictEqual(vm.profiles[0].nCameras, 8);
  assert.strictEqual(vm.vehicles[0].dryMassKg, 30.0);
  assert.strictEqual(vm.bodies[0].gMS2, 1.62);
  assert.strictEqual(vm.bodies[0].bekkerRegime, "gravity-loaded");
  assert.strictEqual(vm.governance.commandPathEnforced, true);
  assert.strictEqual(vm.governance.anyOnCommandPath, false);              // derived: §25.3 stays false
  assert.strictEqual(A.normalizeModelsRegistry({ ok: true, profiles: [] }), null);
});

test("normalizeSkill maps ConstructionSkill + derives usable", () => {
  const vm = A.normalizeSkill({ skill: {
    skill_id: "s1", name: "dig-pad", kind: "excavate", version: "1.0",
    n_steps: 12, closed_loop: true, approved: true, acceptance_note: "RMSE 1.4 cm" } });
  assert.strictEqual(vm.kind, "excavate");
  assert.strictEqual(vm.usable, true);                              // approved + closed-loop -> runnable
  const unapproved = A.normalizeSkill({ skill: { skill_id: "s2", name: "berm", kind: "berm",
    version: "0.1", n_steps: 8, closed_loop: true, approved: false, acceptance_note: "" } });
  assert.strictEqual(unapproved.usable, false);
});
