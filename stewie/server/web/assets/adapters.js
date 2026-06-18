// Phase 2 / FS-15: typed frontend CONTRACT ADAPTERS. Pure functions that map a backend spine-contract
// payload -> a normalized VIEW MODEL the cockpit panes render, a fetch-outcome -> a {state} the UI shows
// (loading/ok/empty/error), and a work-area -> the minimum role its command affordances need (mirroring
// the AG-01 ladder). UI components consume these view models, NEVER raw backend JSON (FS-15). No DOM, no
// network here -> unit-testable with node:test; the cockpit wires fetch + render on top.
(function (root) {
  "use strict";

  // ---- the role ladder, mirrored from the backend (AG-01) for permission mapping ----
  var ROLE_LADDER = ["guest", "trainee", "operator", "director"];
  function roleRank(role) { return ROLE_LADDER.indexOf(role); }   // -1 for unknown = fail closed

  // which role a work area's COMMAND affordances require (reads stay open to guest+)
  var WORK_AREA_MIN_ROLE = {
    plan: "guest", navigation: "guest", perception: "guest", metrics: "guest", report: "guest",
    fleet: "operator", command: "operator", admin: "director",
  };
  function canAct(workArea, role) {
    var need = WORK_AREA_MIN_ROLE[workArea] || "operator";
    return roleRank(role) >= roleRank(need);
  }

  // ---- normalizers: spine-contract payload -> view model (with a couple of derived fields) ----
  function normalizeEphemeris(payload) {
    var e = payload && payload.ephemeris;
    if (!e) return null;
    return {
      missionTimeS: e.mission_t_s,
      site: { latDeg: e.site_lat_deg, lonDeg: e.site_lon_deg, frame: e.frame },
      sun: { azDeg: e.sun_az_deg, elDeg: e.sun_el_deg, convention: e.azimuth_convention },
      uncertaintyDeg: e.uncertainty_deg, source: e.source,
      lit: e.sun_el_deg > 0,                                // derived: is the site sunlit now?
    };
  }

  function normalizeWorld(payload) {
    var w = payload && payload.world;
    if (!w) return null;
    return {
      body: w.body, frame: w.frame,
      grid: { rows: w.rows, cols: w.cols, cellM: w.cell_m },
      datumRadiusM: w.datum_radius_m, demSource: w.dem_source,
      observedFraction: w.observed_fraction, mutated: w.mutated,
      extentM: { x: w.cols * w.cell_m, y: w.rows * w.cell_m }, // derived metric span
    };
  }

  // VehicleState -> the per-rover view model (pose, state-of-charge, slip/sinkage, posture-relevant status)
  function normalizeVehicle(payload) {
    var v = payload && payload.vehicle;
    if (!v) return null;
    return {
      id: v.vehicle_id, role: v.role,
      pos: { row: v.row, col: v.col, yawRad: v.yaw_rad },
      soc: v.soc, slip: v.slip, sinkageM: v.sinkage_m,
      entrapped: v.entrapped, status: v.status,
      moving: v.status === "driving",                                  // derived: under way?
      healthy: !v.entrapped && v.status !== "safed" && v.status !== "blocked", // derived: nominal?
    };
  }

  // FleetState -> the fleet view model; reuses the vehicle VM so one rover shape exists everywhere
  function normalizeFleet(payload) {
    var f = payload && payload.fleet;
    if (!f) return null;
    var vehicles = (f.vehicles || []).map(function (v) { return normalizeVehicle({ vehicle: v }); });
    return {
      vehicles: vehicles,
      reservations: (f.reservations || []).map(function (r) {
        return { resourceId: r.resource_id, vehicleId: r.vehicle_id, tStart: r.t_start, tEnd: r.t_end };
      }),
      conflicts: f.conflicts,
      count: vehicles.length,                                          // derived
      anyEntrapped: vehicles.some(function (v) { return v.entrapped; }), // derived: fleet needs replan?
      hasConflicts: f.conflicts > 0,                                   // derived
    };
  }

  // BeliefState -> the estimator-belief view model (pose + covariance + relocalization recency)
  function normalizeBelief(payload) {
    var b = payload && payload.belief;
    if (!b) return null;
    return {
      vehicleId: b.vehicle_id,
      pos: { row: b.row, col: b.col, yawRad: b.yaw_rad },
      posSigmaM: b.pos_sigma_m, yawSigmaRad: b.yaw_sigma_rad,
      localized: b.localized, lastRelocalizationTS: b.last_relocalization_t_s,
      diverged: !b.localized,                                          // derived: estimator lost?
    };
  }

  // PlanResult -> the plan-summary view model (totals + a display-friendly MJ + blocked-legs flag)
  function normalizePlanResult(payload) {
    var p = payload && payload.plan_result;
    if (!p) return null;
    return {
      planId: p.plan_id, feasible: p.feasible, nOrders: p.n_orders, vehicles: p.vehicles,
      makespanS: p.makespan_s, energyJ: p.energy_j, massMovedKg: p.mass_moved_kg,
      blockedLegs: p.blocked_legs,
      energyMJ: p.energy_j / 1e6,                                      // derived display convenience
      hasBlocked: p.blocked_legs > 0,                                  // derived
    };
  }

  // ExecutionEvent -> the timeline/ledger row view model (kind/outcome + an ok flag for styling)
  function normalizeExecutionEvent(payload) {
    var e = payload && payload.execution_event;
    if (!e) return null;
    return {
      tS: e.t_s, vehicleId: e.vehicle_id, kind: e.kind, detail: e.detail, outcome: e.outcome,
      ok: e.outcome === "ok",                                          // derived
    };
  }

  // ARGUSFactor -> the pose-graph factor view model (residual/information + accept/reject for the evidence pane)
  function normalizeARGUSFactor(payload) {
    var a = payload && payload.argus_factor;
    if (!a) return null;
    return {
      factorId: a.factor_id, kind: a.kind, keyframeI: a.keyframe_i, keyframeJ: a.keyframe_j,
      residual: a.residual, information: a.information, accepted: a.accepted,
      rejected: !a.accepted,                                           // derived
    };
  }

  // ModelArtifact -> the model-registry view model. `deploymentReady` MIRRORS the backend ML-01
  // ModelArtifact.deployment_ready property; the Python parity test (test_adapter_contract_parity.py)
  // guards these field names + that the canonical property still exists, so this cannot silently drift.
  function normalizeModelArtifact(payload) {
    var m = payload && payload.model_artifact;
    if (!m) return null;
    var deploymentReady = !!(
      m.input_schema && m.output_schema &&
      m.latency_budget_ms > 0 && m.memory_budget_mb > 0 &&
      m.calibrated && m.ood_detector && (m.fallback || m.rollback_to) && !m.command_path);
    return {
      modelId: m.model_id, name: m.name, version: m.version, task: m.task,
      datasetLineage: m.dataset_lineage, evalSplit: m.eval_split,
      inputSchema: m.input_schema, outputSchema: m.output_schema,
      latencyBudgetMs: m.latency_budget_ms, memoryBudgetMb: m.memory_budget_mb,
      calibrated: m.calibrated, oodDetector: m.ood_detector, fallback: m.fallback,
      quantization: m.quantization, rollbackTo: m.rollback_to, commandPath: m.command_path,
      deploymentReady: deploymentReady,                                // derived (mirrors backend ML-01 gate)
    };
  }

  // ConstructionSkill -> the recorded-primitive view model (step count + approval/closed-loop = usable)
  function normalizeSkill(payload) {
    var s = payload && payload.skill;
    if (!s) return null;
    return {
      skillId: s.skill_id, name: s.name, kind: s.kind, version: s.version,
      nSteps: s.n_steps, closedLoop: s.closed_loop, approved: s.approved,
      acceptanceNote: s.acceptance_note,
      usable: !!(s.approved && s.closed_loop),                         // derived: runnable primitive?
    };
  }

  // ---- fetch-outcome -> view STATE the UI renders (FS-15 loading/error/empty mapping) ----
  function toViewState(o) {
    if (o.status === "pending") return { state: "loading", data: null };
    var bad = (typeof o.status === "number" && o.status >= 400) || !o.json || o.json.ok === false;
    if (bad) return { state: "error", error: (o.json && o.json.error) || ("HTTP " + o.status), data: null };
    var vm = o.normalize(o.json);
    return vm ? { state: "ok", data: vm } : { state: "empty", data: null };
  }

  var API = {
    ROLE_LADDER: ROLE_LADDER, roleRank: roleRank, canAct: canAct,
    WORK_AREA_MIN_ROLE: WORK_AREA_MIN_ROLE,
    normalizeEphemeris: normalizeEphemeris, normalizeWorld: normalizeWorld,
    normalizeVehicle: normalizeVehicle, normalizeFleet: normalizeFleet,
    normalizeBelief: normalizeBelief, normalizePlanResult: normalizePlanResult,
    normalizeExecutionEvent: normalizeExecutionEvent, normalizeARGUSFactor: normalizeARGUSFactor,
    normalizeModelArtifact: normalizeModelArtifact, normalizeSkill: normalizeSkill,
    toViewState: toViewState,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;   // node:test
  if (root) root.STEWIE_ADAPTERS = API;                                        // browser (window)
})(typeof window !== "undefined" ? window : null);
