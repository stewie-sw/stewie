"""Closed-loop autonomy (P12) — the recursive belief-state estimator (the AutoNav "OD" analog).

DS1 AutoNav's core was an orbit-determination FILTER producing state + covariance, which the maneuver
planner then replanned against. Our planner has been deterministic (assumed-perfect state); this module
is the missing ESTIMATE half: a belief state where every quantity carries a 1-sigma uncertainty.

  predict(...)   — process / dead-reckoning step: move + spend; uncertainty GROWS (odometry drift,
                   energy-model error from slip/terrain). The AutoNav "time update".
  update_*(...)  — measurement fusion from a sensor; uncertainty SHRINKS via a scalar Kalman update.
                   The AutoNav "measurement update".

Measurements come from the real drum-sensor model (rassor_mass_model) and the conserved authority, never
fabricated. The closed loop (autonomy/controller, next increment) runs plan -> execute leg -> sense ->
estimate -> replan over the conserved authority first (AutoNav's self-simulation), then real telemetry.
"""

from __future__ import annotations

import dataclasses
import math

from dart import map_channel as MC
from lode import mission_planner as MP
from lode.mission_planner import BATTERY_J

ODOM_DRIFT_FRAC = 0.05   # [ASSUMPTION] along-track odometry drift per metre; an independent pose fix corrects it


@dataclasses.dataclass
class Belief:
    """Estimated mission state with 1-sigma uncertainty on each quantity (the AutoNav OD file analog)."""
    x: float
    y: float
    pos_sigma_m: float
    energy_J: float
    energy_sigma_J: float
    drum_kg: float
    drum_sigma_kg: float
    tasks_done: int
    tasks_total: int
    t_s: float = 0.0
    battery_j: float = BATTERY_J          # MODEL-01: the SELECTED vehicle's pack (SOC denominator)

    def soc_frac(self) -> float:
        """Battery state-of-charge estimate (fraction of the SELECTED vehicle's pack)."""
        return self.energy_J / self.battery_j

    def to_dict(self) -> dict:
        # battery_j is a per-vehicle constant, not an estimated state -> keep it out of the telemetry
        # dict (the per-leg SOC already folds it in) so the serialized shape is unchanged.
        d = dataclasses.asdict(self)
        d.pop("battery_j", None)
        return {**d, "soc_frac": self.soc_frac()}


def initial_belief(mission, tasks_total, *, pos_sigma_m=0.5, ctx=None):
    """A fresh belief at mission start: parked at the charger, full pack, empty drum — all well known.
    MODEL-01: the full-pack energy + the SOC denominator come from the SELECTED vehicle's PlanningContext
    (ctx), not the global IPEx pack. The default vehicle 'ipex' resolves ctx.battery_j == BATTERY_J, so an
    ipex mission is byte-identical."""
    ctx = ctx if ctx is not None else MP.plan_context(mission)
    cx, cy = mission.charger
    return Belief(x=float(cx), y=float(cy), pos_sigma_m=float(pos_sigma_m),
                  energy_J=float(ctx.battery_j), energy_sigma_J=0.0,
                  drum_kg=0.0, drum_sigma_kg=0.0, tasks_done=0, tasks_total=int(tasks_total),
                  battery_j=float(ctx.battery_j))


def _kf_update(mu, var, z, r):
    """Scalar Kalman / Bayesian fusion of a prior (mu, var) with a measurement (z, variance r).
    Returns (mu', var') with var' <= min(var, r). var=inf -> take the measurement; r=0 -> exact measurement."""
    if not math.isfinite(var):
        return z, r
    if r <= 0:
        return z, 0.0
    if var <= 0:
        return mu, 0.0
    k = var / (var + r)                                   # Kalman gain
    return mu + k * (z - mu), (1.0 - k) * var


def predict(b, *, moved_to=None, drive_m=0.0, odom_drift_frac=0.05,
            energy_spent_J=0.0, energy_model_sigma_frac=0.12,
            drum_delta_kg=0.0, drum_process_sigma_kg=0.0, dt_s=0.0):
    """Process step. `moved_to` sets the believed pose (the commanded destination); pose uncertainty grows
    by `odom_drift_frac * drive_m`. Energy drops by `energy_spent_J` with its uncertainty growing by
    `energy_model_sigma_frac` of the spend (the slip/terrain unknown -- exactly the AutoNav lesson that
    model error must be carried, not assumed away). The drum changes by `drum_delta_kg`."""
    x, y = (b.x, b.y) if moved_to is None else (float(moved_to[0]), float(moved_to[1]))
    pos_var = b.pos_sigma_m ** 2 + (odom_drift_frac * drive_m) ** 2
    e_var = b.energy_sigma_J ** 2 + (energy_model_sigma_frac * energy_spent_J) ** 2
    d_var = b.drum_sigma_kg ** 2 + drum_process_sigma_kg ** 2
    return dataclasses.replace(b, x=x, y=y, pos_sigma_m=math.sqrt(pos_var),
                               energy_J=b.energy_J - energy_spent_J, energy_sigma_J=math.sqrt(e_var),
                               drum_kg=b.drum_kg + drum_delta_kg, drum_sigma_kg=math.sqrt(d_var),
                               t_s=b.t_s + dt_s)


def update_drum(b, reading_kg, reading_sigma_kg):
    """Fuse a drum-mass measurement (motor-current inference, rassor_mass_model) into the belief."""
    mu, var = _kf_update(b.drum_kg, b.drum_sigma_kg ** 2, float(reading_kg), float(reading_sigma_kg) ** 2)
    return dataclasses.replace(b, drum_kg=mu, drum_sigma_kg=math.sqrt(max(0.0, var)))


def update_pose(b, fix_xy, fix_sigma_m):
    """Fuse a pose fix (landmark / map match) into the position belief."""
    vx, varx = _kf_update(b.x, b.pos_sigma_m ** 2, float(fix_xy[0]), float(fix_sigma_m) ** 2)
    vy, vary = _kf_update(b.y, b.pos_sigma_m ** 2, float(fix_xy[1]), float(fix_sigma_m) ** 2)
    return dataclasses.replace(b, x=vx, y=vy, pos_sigma_m=math.sqrt(max(0.0, max(varx, vary))))


def update_energy(b, reading_J, reading_sigma_J):
    """Fuse a battery state-of-charge measurement (coulomb count / voltage) into the energy belief."""
    mu, var = _kf_update(b.energy_J, b.energy_sigma_J ** 2, float(reading_J), float(reading_sigma_J) ** 2)
    return dataclasses.replace(b, energy_J=mu, energy_sigma_J=math.sqrt(max(0.0, var)))


# ---- EXECUTOR + CONTROLLER: the closed loop (plan -> execute -> sense -> estimate -> replan) -----
def nominal_leg_energy_J(pose, leg, *, ctx=None):
    """The planner's MODEL estimate for a leg: flat 135 J/m drive (pose->site) + the leg's dig/haul/lift.
    This is what the plan BUDGETED; `execute_leg` returns the slip-adjusted truth, and the gap is the model
    error the estimator carries and the controller replans against (the AutoNav model-vs-truth dynamic).
    MODEL-01: the per-metre drive energy comes from the SELECTED vehicle's ctx (ipex == the global)."""
    drive_j_per_m = ctx.drive_j_per_m if ctx is not None else MP.DRIVE_J_PER_M
    drive = MP._d(pose, leg["site"])
    haul_e = leg.get("haul_e", leg.get("haul_m", 0.0) * drive_j_per_m)      # #1 slip-aware haul (the plan's)
    return (drive * drive_j_per_m + leg.get("dig_e", 0.0) + leg.get("sinter_e", 0.0)
            + haul_e + leg.get("lift_e", 0.0))


def execute_leg(belief, leg, *, dem=None, dem_origin=(0.0, 0.0), g=None, body="moon", params=None, ctx=None):
    """Step the rover from its believed pose through one leg, returning the TRUE telemetry it experiences:
    the inter-leg drive costs `135/(1-slip) + rover_mass*g*Δh` (slope→slip from the real DEM + exact gravity
    climb), plus the leg's dig/haul/lift. This is the physical truth that diverges from the flat nominal plan.
    MODEL-01: the drum capacity, rover mass and per-metre drive energy come from the SELECTED vehicle's
    PlanningContext (ctx); ctx=None falls back to the module IPEx globals (byte-identical for the default)."""
    drum_kg = ctx.drum_kg if ctx is not None else MP.DRUM_KG
    rover_mass_kg = ctx.rover_mass_kg if ctx is not None else MP.ROVER_MASS_KG
    drive_j_per_m = ctx.drive_j_per_m if ctx is not None else MP.DRIVE_J_PER_M
    g = MP.body_gravity(body) if g is None else g
    pose = (belief.x, belief.y)
    site = leg["site"]
    # NOTE (audit L58): leg distances/slopes derive from the BELIEVED pose (the executive plans on its
    # estimate); the "true" energy is true w.r.t. the slip/grade PHYSICS of that leg, not a
    # truth-pose-referenced quantity. Pose-truth referencing lives in the eval channel only (I3).
    drive_m = MP._d(pose, site)
    dh = MP.haul_elevation_gain_m(dem, dem_origin, pose, site) if dem is not None else 0.0
    slope_deg = math.degrees(math.atan2(abs(dh), drive_m)) if drive_m > 1e-9 else 0.0
    # weight coupling (K10) at DRUM scale: the regolith carried on this drive drives both the slip and
    # the gravity climb -- but the rover can physically carry at most one drum (~MP.DRUM_KG). The
    # uncapped leg mass (a whole job, potentially tonnes) saturated slip and charged a phantom m*g*h
    # for mass never on the wheels in a single drive (audit 2026-06-09); the extra shuttles' costs are
    # priced in the leg's slip-aware haul_e.
    haul_mass_kg = min(max(0.0, float(leg.get("mass", 0.0))), float(drum_kg))
    slip = MP.slip_alpha_to_slip(slope_deg, payload_kg=haul_mass_kg, g=g, params=params)
    true_drive_J = (drive_m * drive_j_per_m / (1.0 - slip)
                    + (rover_mass_kg + haul_mass_kg) * g * max(0.0, dh))
    haul_e = leg.get("haul_e", leg.get("haul_m", 0.0) * drive_j_per_m)      # #1 slip-aware haul (the plan's)
    true_J = (true_drive_J + leg.get("dig_e", 0.0) + leg.get("sinter_e", 0.0)
              + haul_e + leg.get("lift_e", 0.0))
    return {"drive_m": drive_m, "true_energy_J": true_J, "new_pose": site,
            "slope_deg": slope_deg, "slip": slip, "drum_through_kg": leg.get("mass", 0.0),
            "haul_mass_capped_kg": haul_mass_kg}   # MODEL-01: mass actually on the wheels (vehicle drum cap)


def _canonical_plant(mission, *, dem, dem_origin, max_traverse_slope_deg, algorithm, objective):
    """A-03: the SINGLE canonical mission plant. Build the plan ONCE through the same planner services the
    PDF/report/Plan-IR use (``plan`` -> ``plan_and_simulate`` -> ``_simulate``) and return the immutable
    PlanResult, the canonical ordered trips, the canonical Plan IR, and a recharge ledger derived from the
    canonical timeline. The closed loop OVERLAYS belief estimation on this plant; it does NOT re-simulate
    energy/recharge/location with its own globals (the old A-03 bug). Recharge travel is NOT free here:
    the canonical sim charges the drive-to-charger AND the drive-back-to-site legs in ``core['energy_J']``,
    so the return-to-site travel is accounted by construction."""
    result = MP.plan(mission, dem=dem, dem_origin=dem_origin,
                     max_traverse_slope_deg=max_traverse_slope_deg,
                     algorithm=algorithm, objective=objective)
    trips, _flows, per_trip, tl, totals = result.as_tuple()
    ir = MP.plan_ir(mission, dem=dem, dem_origin=dem_origin,
                    max_traverse_slope_deg=max_traverse_slope_deg,
                    algorithm=algorithm, objective=objective, result=result)
    # recharge-travel energy = the drive legs that END at the charger (the return-to-charger trips the
    # canonical sim drives before each refill). This is the energy the old free-teleport recharge omitted.
    charger = tuple(mission.charger)
    recharge_travel_J = 0.0
    for e in tl:
        if e["kind"] == "drive" and math.hypot(e["x1"] - charger[0], e["y1"] - charger[1]) <= 1e-6:
            recharge_travel_J += e["batt0"] - e["batt1"]
    # A-03 #25: the CANONICAL departure pose for each trip, read from the plant timeline -- the position the
    # rover actually drives FROM to reach the trip's site (the charger when a recharge precedes the leg, else
    # the prior work site). The re-hazard path check uses this plant geometry, not a belief-walk approximation,
    # so the built-terrain crossing test is consistent with the one canonical plant.
    dep_by_trip = []
    for pt in per_trip:                                    # per_trip is in the canonical execution order
        tr = pt["trip"]; sx, sy = tr["site"]
        arr = [e for e in tl if e["kind"] == "drive" and e["t0"] >= pt["t_start"] - 1e-6
               and math.hypot(e["x1"] - sx, e["y1"] - sy) <= 1e-6]
        dep_by_trip.append((arr[0]["x0"], arr[0]["y0"]) if arr else tuple(charger))
    return result, trips, ir, totals, recharge_travel_J, dep_by_trip


def run_closed_loop(mission, *, dem=None, dem_origin=(0.0, 0.0), algorithm="auto", objective="time",
                    max_traverse_slope_deg=25.0, perception_sigma_m=None, dig_sigma_gate_m=0.20, seed=0):
    """Run the AutoNav-style loop as an OVERLAY on the ONE canonical plant (A-03). The plan, vehicle,
    routing, energy, and reserve all come from the planner (``_canonical_plant`` -> ``plan_and_simulate``
    -> ``_simulate``), so the closed-loop execution and the planner simulation describe the SAME mission:
    for deterministic zero-noise inputs (no DEM -> slip 0, no elevation gain, no perception noise) the
    reported plant energy / time / recharges AGREE with the planner totals within tolerance.

    The belief estimator is the overlay: it walks the SAME canonical trip order, dead-reckons pose with
    growing odometry uncertainty, fuses measurements (the AutoNav predict/update), and carries the
    slip-adjusted model error per leg (``true_J`` vs ``nominal_J``) as the model-vs-truth signal. It does
    NOT maintain a second, inconsistent energy/recharge plant: the authoritative ``plant_energy_J`` /
    ``plant_time_s`` / ``recharges`` come from the canonical sim, and recharge travel is fully accounted
    (no free teleport to the charger, return-to-site drive included)."""
    import numpy as _np
    g = MP.body_gravity(mission.body)
    ctx = MP.plan_context(mission)                         # MODEL-01: the SELECTED vehicle's constants
    _rng = _np.random.default_rng(seed)                    # MODEL-02: seeded perception-noise stream
    result, trips, ir, totals, recharge_travel_J, dep_by_trip = _canonical_plant(
        mission, dem=dem, dem_origin=dem_origin, max_traverse_slope_deg=max_traverse_slope_deg,
        algorithm=algorithm, objective=objective)
    plant_energy_J = float(totals["energy_J"])             # canonical reserve-aware ledger (the ONE plant)
    plant_time_s = float(totals["time_s"])
    recharges = int(totals["charges"])
    belief = initial_belief(mission, len(trips), ctx=ctx)
    replans = 0                                            # belief-driven re-sequencing diagnostics (overlay)
    perception_fixes = observe_more = 0
    map_observe_more = 0                                   # P6: digs gated on local map coverage
    survey_time_s = 0.0                                    # P6: real time the survey-before-dig gate costs
    stations = [tuple(mission.charger)]                   # P6: where the rover has observed the worksite from
    legs = []
    # Task #25 (Aaron: "everything is precision ops -- a high berm will flip the rover"): terrain
    # BUILT mid-mission was invisible to later legs (slopes derive from the PRIOR DEM). A fresh
    # loose-regolith edge stands at the REPOSE angle -- above the 20-deg tested envelope -- so any
    # later leg whose straight path crosses an EXECUTED cut/fill footprint gets flagged.
    built: list = []                                       # (cx, cy, half_m, label, kind)
    hazard_violations: list = []
    from stewie.specs.bodies import get_body
    _rep = get_body(mission.body).repose_deg
    repose_deg = float(_rep) if _rep else 35.0             # measured per body; 35 = lunar default

    def _seg_hits_box(p0, p1, cx, cy, half):
        import numpy as _np
        d = _np.array([p1[0] - p0[0], p1[1] - p0[1]], float)
        n = max(8, int(_np.hypot(*d) / max(half, 1.0)) * 4)
        for t in _np.linspace(0.0, 1.0, n):
            x, y = p0[0] + d[0] * t, p0[1] + d[1] * t
            if abs(x - cx) <= half and abs(y - cy) <= half:
                return True
        return False

    for ti, leg in enumerate(trips):
        # PERCEPTION-IN-THE-LOOP (Uncertainty-layer dig-ready gate): before committing to a dig, if the
        # pose estimate is too uncertain, dwell and take more observations until it is confident enough.
        if perception_sigma_m is not None and leg.get("dig_e", 0.0) > 0.0:
            while belief.pos_sigma_m > dig_sigma_gate_m:
                # ABSTRACTION (audit M44, documented): each dwell models acquiring an INDEPENDENT
                # map-relative fix of sigma=perception_sigma_m (localization.register_to_dem tier).
                # The mean is deliberately unchanged (no better estimate exists in this tier; no truth
                # may be used, I3); only the variance follows the KF fusion rate. It is a mission-time/
                # uncertainty model, not a real measurement.
                belief = update_pose(belief, (belief.x, belief.y), perception_sigma_m)
                observe_more += 1
        # MAP-CHANNEL-IN-THE-LOOP gate (P6 / LAC section 10): a dig commits only on terrain the route has
        # mapped. If the dig site's local coverage from PRIOR stations is below the gate, the rover SURVEYS
        # the approach first -- a real observe dwell (MC.OBSERVE_DWELL_S [ASSUMPTION]) that ADDS to mission
        # time -- before the (irreversible) excavation; the survey observation then raises coverage. This is
        # an action with a measurable cost, not just a counter.
        site = tuple(leg["site"])
        if leg.get("dig_e", 0.0) > 0.0 and MC.local_coverage(stations, site) < MC.COVERAGE_DIG_GATE:
            survey_time_s += MC.OBSERVE_DWELL_S
            map_observe_more += 1
        stations.append(site)                             # the rover observes the worksite from each station
        nominal_J = nominal_leg_energy_J((belief.x, belief.y), leg, ctx=ctx)
        # #25: the leg's path check uses the CANONICAL plant departure pose (where the rover actually drives
        # FROM per the plant timeline), not the belief estimate, so the re-hazard geometry matches the one
        # canonical plant (A-03). dep_by_trip is keyed by canonical trip index.
        dep_pose = dep_by_trip[ti] if ti < len(dep_by_trip) else (belief.x, belief.y)
        telem = execute_leg(belief, leg, dem=dem, dem_origin=dem_origin, g=g, body=mission.body,
                            params=MP.mission_soil_params(mission), ctx=ctx)
        # ESTIMATE -- DEAD-RECKON: the believed pose accumulates a deterministic along-track odometry drift
        # (ODOM_DRIFT_FRAC per metre); without an independent fix it compounds leg-over-leg. (pose sigma also
        # grows; energy sigma is grown below by the leg's a-priori model error.)
        true_pose = telem["new_pose"]
        odo = ODOM_DRIFT_FRAC * telem["drive_m"]
        belief = predict(belief, moved_to=(true_pose[0] + odo, true_pose[1]), drive_m=telem["drive_m"],
                         odom_drift_frac=ODOM_DRIFT_FRAC, energy_spent_J=0.0)
        # PERCEPTION MEASUREMENT: fuse the INDEPENDENT true pose (the SLAM / AprilTag map fix). The
        # measurement is the truth, NOT the belief's own estimate, so the Kalman update CORRECTS the
        # dead-reckoned drift (moves the mean back), not merely shrinks sigma. MODEL-02: a real fix is
        # only as good as its declared sigma -- the measurement is true_pose + N(0, perception_sigma_m)
        # (a seeded sensor-noise realization), NOT the exact truth, so the corrected mean lands NEAR
        # truth within the fix's own uncertainty rather than perfectly on it.
        if perception_sigma_m is not None:
            meas = (true_pose[0] + float(_rng.normal(0.0, perception_sigma_m)),
                    true_pose[1] + float(_rng.normal(0.0, perception_sigma_m)))
            belief = update_pose(belief, meas, perception_sigma_m)
            perception_fixes += 1
        e_sig = math.sqrt(belief.energy_sigma_J ** 2 + (0.12 * nominal_J) ** 2)
        belief = dataclasses.replace(belief, energy_sigma_J=e_sig)
        belief = dataclasses.replace(belief, tasks_done=belief.tasks_done + 1)
        # #25: does this leg's path cross terrain BUILT earlier in the mission? The path runs from the
        # canonical DEPARTURE pose to the leg site. A box AT the departure pose is the rover's own just-left
        # work site -- it cannot avoid sitting on the spot it starts from, so that box is excluded; only
        # crossing OTHER built terrain en route is a traverse hazard.
        for (bx, by, bh, blabel, bkind) in built:
            if math.hypot(dep_pose[0] - bx, dep_pose[1] - by) <= bh:   # departing its own work site: not a crossing
                continue
            if _seg_hits_box((dep_pose[0], dep_pose[1]), leg["site"], bx, by, bh):
                hazard_violations.append({
                    "leg": leg["label"], "crosses": blabel, "kind": bkind,
                    "slope_deg": repose_deg,
                    "rule": "fresh repose-angle edge exceeds the 20-deg tested traverse envelope"})
        if leg.get("kind") in ("cutfill", "import", "dig") or leg.get("dig_e", 0.0) > 0.0:
            import math as _math
            for (sx, sy), slabel in ((leg.get("dest"), leg["label"]),):
                if sx is not None:
                    # footprint half-extent from the order the site belongs to (sqrt area / 2)
                    half = 3.0
                    for o in mission.orders:
                        if abs(o.x - sx) < 1e-6 and abs(o.y - sy) < 1e-6 and o.footprint_m2 > 0:
                            half = _math.sqrt(o.footprint_m2) / 2.0
                    built.append((float(sx), float(sy), half, slabel, leg.get("kind", "work")))
        legs.append({"leg": leg["label"], "nominal_J": nominal_J, "true_J": telem["true_energy_J"],
                     "dig_e": float(leg.get("dig_e", 0.0)),     # dig doesn't slip; only the drive portion inflates
                     "soc": belief.soc_frac(), "slope_deg": telem["slope_deg"], "slip": telem["slip"],
                     "energy_sigma_J": e_sig})
    # A-03: reconcile the belief overlay to the canonical plant end state -- the canonical sim drives HOME
    # at mission end and the believed mission time IS the canonical plant time (the overlay does not invent
    # a location/energy the plant never had). Drive home through the SAME dead-reckoning machinery as a work
    # leg (the mean accumulates the home leg's odometry drift; pose sigma grows), then -- when perception is
    # on -- DOCK at the charger as a known-landmark pose fix (the old _recharge dock semantics): the fix
    # collapses the drift so the perception-on run stays bounded, exactly as a real charger redock would.
    cx, cy = mission.charger
    drive_home_m = MP._d((belief.x, belief.y), mission.charger)
    odo_home = ODOM_DRIFT_FRAC * drive_home_m
    belief = predict(belief, moved_to=(float(cx) + odo_home, float(cy)), drive_m=drive_home_m,
                     odom_drift_frac=ODOM_DRIFT_FRAC, energy_spent_J=0.0)
    if perception_sigma_m is not None:                 # docking at the charger is a known-landmark pose fix
        belief = update_pose(belief, (float(cx), float(cy)), perception_sigma_m)
    belief = dataclasses.replace(belief, t_s=plant_time_s)
    # P6: the closed map-channel reward -- how well the executed route observed the worksite (coverage +
    # residual map uncertainty), the LAC section 10 mapping objective fed back, not just pose/energy.
    map_channel = MC.map_channel_score(mission, stations)
    return {"belief": belief, "completed": belief.tasks_done == len(trips), "n_trips": len(trips),
            "hazard_violations": hazard_violations,
            "recharges": recharges, "replans": replans, "legs": legs,
            "perception_fixes": perception_fixes, "observe_more": observe_more,
            "map_observe_more": map_observe_more, "survey_time_s": survey_time_s, "map_channel": map_channel,
            # A-03: the ONE canonical plant ledger + the canonical Plan IR -- so the closed loop and the
            # planner simulation are provably the same mission (no second inconsistent simulator).
            "plant_energy_J": plant_energy_J, "plant_time_s": plant_time_s,
            "recharge_travel_J": recharge_travel_J, "plan_ir": ir, "feasible": bool(totals.get("feasible", True))}
