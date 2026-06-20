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

test("normalizeARGUSFactor maps ARGUSFactor + derives rejected", () => {
  const vm = A.normalizeARGUSFactor({ argus_factor: {
    factor_id: "f1", kind: "shadow", keyframe_i: 0, keyframe_j: 1,
    residual: 0.02, information: 1.5, accepted: true } });
  assert.strictEqual(vm.kind, "shadow");
  assert.strictEqual(vm.rejected, false);
  assert.strictEqual(A.normalizeARGUSFactor({ argus_factor: { factor_id: "f2", kind: "loop",
    keyframe_i: 3, keyframe_j: 9, residual: 5, information: 0, accepted: false } }).rejected, true);
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
