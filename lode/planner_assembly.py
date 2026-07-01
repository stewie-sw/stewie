"""ARCH-2 (#123): the PLAN-ASSEMBLY layer (single- + multi-vehicle planners + shared totals), extracted
from lode.mission_planner.

The order-independent feasibility/totals helpers (_relocalization, _return_to_lander, _plan_uncertainty,
_mission_totals) and the planners that orchestrate them: plan_multi (MV1-7 fleet: allocate -> per-vehicle
sequence+sim -> charger/resource/crowding/precedence deconfliction -> aggregate), plan_multi_oracle
(FL-06 exact small-problem validator), and plan_and_simulate (the single-vehicle product planner;
vehicles>1 dispatches to plan_multi). A leaf: it imports the planner_constants / planner_model /
planner_balance / planner_routing / planner_sim / planner_optimize / planner_trips / planner_multivehicle
leaves + stewie.* + lander_return/relocalization; it NEVER imports lode.mission_planner, so it introduces
no cycle. mission_planner re-exports every name here, so plan()/compare_algorithms()/run() and the
MP.plan_and_simulate / MP.plan_multi / MP._mission_totals dependents stay byte-identical.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import itertools
import math
import warnings

from stewie.specs import ipex_specs as S
from stewie.physics import rassor_mass_model as RM     # RM.FDC_MPE_HALF_FULL (plan-uncertainty drum-fill band)
from stewie.physics import rassor_mass_model as RMM    # RMM.arm_raise_lift_energy_j (relocalization fix energy)
from lode import lander_return as LR                   # #161 return-to-lander feasibility
from lode import relocalization as REL                 # #96 articulation-parallax relocalization scheduling
from lode.planner_constants import (
    LOCALIZATION_MARGIN_M, ROVER_MASS_KG,   # #297: BATTERY_J/DRIVE_J_PER_M/RESERVE_FRAC now via plan_context
)
from lode.planner_model import Mission, _drum_kg, body_gravity, plan_context
from lode.planner_balance import SWELL
from lode.planner_routing import point_in_keepout
from lode.planner_sim import _simulate
from lode.planner_optimize import (
    BRUTE_MAX_TRIPS, HELD_KARP_EXACT_METRIC, HELD_KARP_MAX_TRIPS, _objective_optimality, optimize_sequence,
)
from lode.planner_trips import _build_trips, _make_routes, _precedence_is_feasible, trip_precedence
from lode.planner_multivehicle import (
    _allocate_precedence_split, _allocate_trips, _charger_conflicts, _haul_path_conflicts,
    _resolve_charger_queue, _resolve_cross_vehicle_precedence, _resolve_joint_resources,
    _resolve_spacetime_crowding, _rover_health, _temporal_conflicts, _vehicle_conflicts,
)

RELOCALIZE_DRIFT_TOL_M = 0.5      # #96: max tolerated DR drift before a parallax fix (was a mission_planner const)
# IDLE_POWER_W stays the canonical knob on the facade (lode.mission_planner) -- it is the test-patchable
# survival-draw global; the two planners below read it via a DEFERRED import so a MP.IDLE_POWER_W patch is
# honored (no module-load cycle).


def _relocalization(mission, core) -> dict:
    """#96 (SN-10 tie-in B): schedule articulation-parallax relocalization stops along the plan's drive
    distance so the dead-reckoned pose drift never exceeds RELOCALIZE_DRIFT_TOL_M. Each fix is a standstill
    chassis-raise maneuver -- its energy is the gravity-aware arm-raise work at the body's g; the drift
    rate mirrors lode.autonomy.ODOM_DRIFT_FRAC (REL.DEFAULT_DRIFT_FRAC)."""
    traverse_m = float(core.get("distance_m", 0.0))
    fix_energy_j = RMM.arm_raise_lift_energy_j(ROVER_MASS_KG, body_gravity(mission.body))
    return REL.schedule_relocalization_stops(traverse_m, drift_tol_m=RELOCALIZE_DRIFT_TOL_M,
                                             per_fix_energy_j=fix_energy_j)


def _return_to_lander(mission) -> dict:
    """#161: return-to-lander feasibility for the plan. The lander (mission.lander, else the charger) is
    the safe haven; at its furthest order the rover must retain enough USABLE charge (after the general
    reserve) to drive back, keeping the operator-adjustable return_buffer_frac over the bare return drive
    energy. Conservative safe-operating-radius check (worst-case return from the furthest waypoint)."""
    # #297: price the return drive with the SELECTED vehicle's battery + the BODY-aware per-metre drive
    # energy (plan_context: gravity-aware lunar_drive_power_w at the mission body g + the vehicle mass),
    # NOT the hardcoded IPEx/lunar globals -- a heavier platform or a non-Moon body has a different
    # safe-operating radius. ipex on the Moon resolves to exactly the old globals (byte-identical).
    ctx = plan_context(mission)
    lander = mission.lander or tuple(mission.charger)
    lx, ly = float(lander[0]), float(lander[1])
    pts = [(float(o.x), float(o.y)) for o in mission.orders] + [tuple(mission.charger)]
    reach = LR.furthest_reach_from_lander_m((lx, ly), pts)
    usable_j = ctx.usable_j
    blk = LR.return_to_lander_feasible(furthest_reach_m=reach, energy_spent_at_reach_j=0.0,
                                       battery_j=usable_j, drive_j_per_m=ctx.drive_j_per_m,
                                       return_buffer_frac=float(mission.return_buffer_frac))
    blk["lander_xy"] = [round(lx, 1), round(ly, 1)]
    return blk


def _plan_uncertainty(mission, dig_bounds_mj, drum_cycles=0) -> dict:
    """CP-07: ONE plan-uncertainty block aggregating the named sources (DEM, material, slip, dig-rate,
    drum-fill, localization, power-window) into the feasibility/time/energy picture. HONEST: a source
    carries a numeric figure ONLY where the model is grounded in-repo -- the dig-rate energy band
    (rated-vs-max RPM, T2.4), the localization corridor margin (P-06), the DEM per-cell sigma (PM-09), the
    operator material factor (EP-02), and the drum-fill CYCLE band (DrumSensor FDC MPE, ICE-RASSOR
    NTRS 20210022781): fill-sensing error does NOT change the dig energy (the same total mass must be dug)
    but it perturbs WHEN the drum reads full -> a +/-MPE band on the offload cycle count, the time-relevant
    quantity. slip and power-window stay flagged `quantified: False` where not propagated -- slip's
    plan-level uncertainty is the [CALIB] Bekker/slip moduli, oracle-gated (FIX-1/2); power-window is
    quantified only when mission windows are declared. Never a fabricated fraction."""
    mat = float(getattr(mission, "dig_energy_factor", None) or 1.0)
    mpe = float(RM.FDC_MPE_HALF_FULL)                       # rover offloads at the upper confidence bound (>half full)
    nc = float(drum_cycles)
    drum_fill = ({"quantified": True, "into": "time", "mpe_frac": mpe, "cycles": nc,
                  "cycles_band": [round(nc * (1.0 - mpe), 2), round(nc * (1.0 + mpe), 2)],
                  "source": "DrumSensor FDC MPE, ICE-RASSOR NTRS 20210022781"}
                 if nc > 0 else
                 {"quantified": False, "into": "time", "note": "no drum cycles in this plan -> no fill-driven band"})
    return {
        "energy_MJ_band": list(dig_bounds_mj),                 # dig-rate sensitivity (rated-18 vs max-25 RPM)
        "sources": {
            "dig_rate":     {"quantified": True, "into": "energy", "band_MJ": list(dig_bounds_mj)},
            "material":     {"quantified": mat != 1.0, "into": "energy", "dig_energy_factor": mat},
            "localization": {"quantified": True, "into": "feasibility", "corridor_margin_m": LOCALIZATION_MARGIN_M},
            "dem":          {"quantified": True, "into": "feasibility", "cell_sigma_m": 0.05},
            "drum_fill":    drum_fill,                      # CP-07: cycle-count band from the grounded DrumSensor FDC MPE
            "slip":         {"quantified": False, "into": "time/energy", "note": "slip moduli are [CALIB]; plan band oracle-gated (FIX-1/2)"},
            "power_window": {"quantified": bool(getattr(mission, "mission_windows", None)), "into": "time",
                             "note": "EP-04 mission-clock windows gate timing"},
        },
    }


def _energy_ledger(mission, trips, tl, totals) -> dict:
    """[REQ:EP-01] ONE separable energy ledger over the plan's headline energy_J. Every named vehicle-
    energy term is its OWN line in terms_J -- drive (inter-site legs + the flat haul baseline), slope/slip
    (the per-segment slip surcharge, drive_e/slip_e split in _build_trips), payload lift, dig, offload,
    sinter, survival -- and every term the IPEx vehicle model genuinely LACKS (arm/drum motion,
    observation, LEDs, thermal, comms, compute) is an EXPLICIT documented zero in terms_J + `unmodeled`,
    never a silent omission. The terms sum EXACTLY to totals['energy_J'] on a feasible plan
    (matches_total); a stranded plan credits only partial work (P-01), so the planned lines can exceed the
    credited total and matches_total goes False rather than hiding the gap. recharge_J is the energy
    delivered INTO the pack at the charger (the timeline's charge legs) -- a pack-INPUT line reported
    alongside, never summed into the consumption total."""
    ctx = plan_context(mission)
    haul_m = sum(tr.get("haul_m", 0.0) for tr in trips)
    # inter-site drive legs: _simulate draws exactly d * drive_j_per_m per leg and distance_m = legs + haul
    drive_legs_j = max(0.0, float(totals.get("distance_m", 0.0)) - haul_m) * ctx.drive_j_per_m
    terms = {
        "drive": drive_legs_j + sum(tr.get("drive_e", 0.0) for tr in trips),
        "slope_slip": sum(tr.get("slip_e", 0.0) for tr in trips),
        "payload_lift": float(totals.get("lift_energy_J", 0.0)),
        "dig": sum(tr.get("dig_e", 0.0) for tr in trips),
        "offload": float(totals.get("offload_energy_J", 0.0)),
        "sinter": sum(tr.get("sinter_e", 0.0) for tr in trips),
        "arm_drum": 0.0, "observation": 0.0, "led": 0.0, "thermal": 0.0, "comms": 0.0, "compute": 0.0,
        "survival": float(totals.get("survival_energy_J", 0.0)),
    }
    unmodeled = {
        "arm_drum": ("not separately metered: bucket-drum excavation work is inside `dig` (the drum IS "
                     "the dig implement, ipex_specs); discrete arm-raise relocalization fixes are "
                     "scheduled + priced in totals['relocalization'] (#96), not folded into energy_J"),
        "observation": "sensing/camera draw is not modeled (no sourced per-sensor power for IPEx)",
        "led": "no LED/illumination load in the modeled IPEx TRL-5 power budget",
        "thermal": ("heater draw is not separately metered: the K11c survival idle draw (IDLE_POWER_W) "
                    "carries the whole idle/heater load when set; cold-pack capacity loss enters as the "
                    "EP-05 thermal derate (capacity, not consumption)"),
        "comms": "radio/telemetry draw is not modeled (no sourced comms power for IPEx)",
        "compute": "avionics/compute draw is not modeled (no sourced compute power for IPEx)",
    }
    recharge_j = sum(max(0.0, seg["batt1"] - seg["batt0"]) for seg in tl if seg.get("kind") == "charge")
    total_j = float(totals.get("energy_J", 0.0))
    sum_j = float(sum(terms.values()))
    return {
        "terms_J": {k: float(v) for k, v in terms.items()},
        "recharge_J": float(recharge_j),
        "sum_J": sum_j,
        "matches_total": bool(math.isclose(sum_j, total_j, rel_tol=1e-9, abs_tol=1e-6)),
        "unmodeled": unmodeled,
    }


def _mission_totals(mission, trips, flows, surplus_kg, meta, core):
    """The mission / material / routing / keep-out totals shared by the single- and multi-vehicle planners.
    `core` carries the simulated time/energy/distance/charges/mass; the caller applies survival + algorithm
    + vehicle fields. Kept DRY so the multi-vehicle aggregate reports the same fields as single-vehicle."""
    dig_bounds_mj = tuple(round(b * sum(tr["mass"] for tr in trips if tr["kind"] != "goto") / 1e6, 1)
                          for b in S.dig_energy_bounds_j_per_kg())   # T2.4 dig-rate band; CP-07 reuses it
    n_drum_cycles = sum(max(1, math.ceil(tr["mass"] / _drum_kg(mission)))
                        for tr in trips if tr["kind"] == "cutfill")   # CP-07: drum-fill cycle band reuses this
    return dict(
        core,
        cut_kg=sum(o.mass_kg(mission.density * SWELL) for o in mission.orders if o.kind == "cut"),
        fill_kg=sum(o.mass_kg(mission.density) for o in mission.orders if o.kind == "fill"),
        sinter_kg=sum(o.mass_kg(mission.density) for o in mission.orders if o.kind == "sinter"),
        surplus_kg=surplus_kg,
        waypoint_sequence=[next(iter(t["actions"])) for t in trips if t["kind"] == "goto"],
        deficit_kg=sum(m for c, f, m, d in flows if c is None),
        # P-04: imported fill mass, accounted SEPARATELY from excavated cut_kg (no local excavation
        # occurred). Equals deficit_kg; surfaced as import_kg so reports/comparisons can attribute it
        # to the procurement/logistics chain rather than to in-situ digging.
        import_kg=sum(m for c, f, m, d in flows if c is None),
        offload_energy_J=float(sum(tr.get("offload_e", 0.0) for tr in trips)),
        drum_cycles=n_drum_cycles,
        # T2.3 (BDS p.7): cut depth per pass <= 50% of the scoop opening -- a deep cut is MULTIPLE
        # passes over the footprint; report the binding pass count (the 42 kg/hr demo dig rate is a
        # steady-state figure that already embodies multi-pass operation, so duration stays rate-based).
        cut_passes=max([1] + [math.ceil(float(o.depth_m) / S.max_cut_per_pass_m())
                              for o in mission.orders if getattr(o, "kind", "") == "cut"]),
        # T2.4: the drum-rate sensitivity band -- dig energy at rated-18 vs max-25 RPM
        dig_energy_bounds_MJ=dig_bounds_mj,
        plan_uncertainty=_plan_uncertainty(mission, dig_bounds_mj, n_drum_cycles),   # CP-07: one aggregated uncertainty block
        lift_energy_J=float(sum(tr.get("lift_e", 0.0) for tr in trips)),
        routed_haul=meta["routed"], blocked_legs=meta["blocked_legs"], traverse_cap_deg=meta["traverse_cap_deg"],
        routes=meta.get("routes", []),
        # C-04: a plan is feasible only if BOTH the route has a safe corridor AND the battery can do it
        # (reserve-aware drive). Carry the combined reasons so the product boundary can fail closed.
        feasible=bool(meta.get("feasible", True) and core.get("feasible", True)),
        infeasible_reasons=(([f"{meta['blocked_legs']} route leg(s) have no safe corridor"]
                             if meta.get("blocked_legs") else []) + list(core.get("infeasible_reasons", []))),
        haul_detour_frac=(meta["routed_haul_m"] / meta["straight_haul_m"] - 1.0)
        if meta["straight_haul_m"] > 1e-9 else 0.0,
        n_keepouts=len(mission.keepouts),
        keepout_conflicts=sum(1 for o in mission.orders for k in mission.keepouts
                              if point_in_keepout(o.x, o.y, k)),    # #178 rect or circle build-on-obstacle
        return_to_lander=_return_to_lander(mission),   # #161 return-to-lander feasibility (adjustable buffer)
        relocalization=_relocalization(mission, core))  # #96 scheduled articulation-parallax relocalization stops


def plan_multi(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
               algorithm="nearest", objective="time", vehicles=2):
    """MV1-7: plan a multi-vehicle build mission. Build trips once, allocate them site-exclusively across V
    vehicles (load-balanced), sequence + battery-simulate EACH vehicle independently (they work in parallel
    from the shared charger), and aggregate: makespan = max per-vehicle time (the wall-clock the fleet
    finishes in), energy/distance/charges = fleet sums. Returns the same (trips, flows, per_trip, tl, totals)
    shape as the single-vehicle planner, with per-trip `vehicle` tags + a vehicles_detail breakdown.

    v1 scope + honest gaps: site-exclusive allocation guarantees no two rovers co-occupy a site (verified by
    a space-time conflict detector); the SHARED CHARGER is modelled as a one-server FCFS queue (FL-03) --
    overlapping recharges serialise, the loser waits, and the headline makespan reflects that wait
    (makespan_parallel_s keeps the optimistic unlimited-charger value); continuous haul-PATH collision
    avoidance and pit/dump/vantage/corridor as reservable resources are future MV work.
    Cross-vehicle PRECEDENCE (FL-04, supersedes v2): a precedence chain that spans two work sites is now
    SPLIT across vehicles and run in parallel -- the dependent leg waits (a per-vehicle delay, the same
    discipline as the charger/crowding resolvers) until its predecessor leg has finished on whichever rover
    does it, so the ordering is honored ACROSS vehicles instead of forcing the whole chain onto one rover.
    A cyclic precedence still raises (never silently mis-ordered)."""
    from lode.mission_planner import IDLE_POWER_W   # deferred: the test-patchable survival-draw knob lives on the facade
    if vehicles < 1:
        raise ValueError(f"vehicles must be >= 1 (got {vehicles})")
    trips, flows, surplus_kg, meta = _build_trips(mission, dem, dem_origin, max_traverse_slope_deg)
    routes = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)   # H-02: route inter-site legs ONCE (shared)
    glob_prec = trip_precedence(trips, mission)            # MV cross-precedence: trip-index constraints
    if glob_prec and not _precedence_is_feasible(len(trips), glob_prec):
        raise ValueError("precedence is infeasible (cyclic / unsatisfiable): no valid build ordering exists")
    # FL-04: precedence present -> SPLIT chains across vehicles (site-exclusive site-group LPT; cross-vehicle
    # ordering held by a per-vehicle wait below) so a precedence chain that spans two work sites runs in
    # parallel instead of collapsing onto one rover. No precedence -> site-only (byte-identical to before).
    alloc = _allocate_precedence_split(trips, vehicles, glob_prec) if glob_prec else _allocate_trips(trips, vehicles)
    per_vehicle = []
    for v, idxs in enumerate(alloc):
        vtrips = [trips[i] for i in idxs]
        if vtrips:
            # MV cross-precedence: remap the global precedence edges that fall within THIS vehicle's trips to
            # local indices (chains are whole here, so every edge for these trips is present) and let the
            # per-vehicle sequencer honor them. No precedence -> None -> byte-identical to the prior call.
            _li = {g: k for k, g in enumerate(idxs)}
            _lp = [(_li[i], _li[j]) for (i, j) in glob_prec if i in _li and j in _li]
            order = optimize_sequence(vtrips, mission, algorithm=algorithm, objective=objective,
                                      precedence=(_lp or None), routes=routes)
            vtrips = [vtrips[k] for k in order]
        for tr in vtrips:
            tr["vehicle"] = v
        tl, per_trip, core = _simulate(mission, vtrips, routes)
        per_vehicle.append({"vehicle": v, "trips": vtrips, "tl": tl, "per_trip": per_trip, "core": core})
    conflicts = _vehicle_conflicts(per_vehicle)
    parallel_makespan = max((pv["core"]["time_s"] for pv in per_vehicle), default=0.0)
    # FL-03: schedule the shared CHARGER and all declared resources (pit/dump/vantage/corridor) JOINTLY
    # against ONE multi-server ReservationLedger driven by ONE per-vehicle delay clock -- replacing v1's
    # independent per-server clocks (which double-counted a rover modelled as queued in two resources "at
    # once", a conservative over-estimate). A wait on any server shifts the rover's later events on every
    # server, so the reported makespan/waits are the REAL coupled FCFS schedule, not a sum of per-server
    # upper bounds. parallel_makespan keeps the optimistic (unlimited-server) reference; charger_conflicts
    # still reports the raw overlaps. With NO declared resources the joint schedule reduces to the
    # charger-only FCFS queue -> makespan/survival byte-identical to a non-reserved fleet.
    joint_delays, joint_bd = _resolve_joint_resources(
        per_vehicle, charger_capacity=mission.charger_capacity, shared_resources=mission.shared_resources)
    charger_delays = joint_bd["charger_delay"]        # per-vehicle charger-attributed slice (report column)
    charger_wait_s = joint_bd["charger_wait_s"]
    resource_delays = joint_bd["resource_delay"]      # per-vehicle resource-attributed slice (report column)
    resource_wait_s = joint_bd["resource_wait_s"]
    resource_waits = joint_bd["resource_waits"]
    # FL-02 re-sequencing: deconflict space-time crowding + haul-path crossings by the same FCFS wait the
    # charger queue uses (the loser yields). No crowding -> all 0 -> makespan/survival byte-identical.
    crowd_delays = _resolve_spacetime_crowding(per_vehicle)
    crowd_wait_s = float(sum(crowd_delays))
    # FL-04: cross-vehicle precedence chain-splitting -- a dependent leg on one rover waits for its
    # predecessor leg on another rover (the chain is SPLIT, not forced onto one vehicle). Same per-vehicle
    # wait discipline as the charger/crowding resolvers. No cross-vehicle edge -> all 0 -> byte-identical.
    precedence_delays = _resolve_cross_vehicle_precedence(per_vehicle, alloc, glob_prec, trips)
    precedence_wait_s = float(sum(precedence_delays))
    makespan = max((pv["core"]["time_s"] + joint_delays[i]
                    + crowd_delays[i] + precedence_delays[i]
                    for i, pv in enumerate(per_vehicle)), default=0.0)
    agg = dict(
        time_s=float(makespan),
        mass_kg=sum(pv["core"]["mass_kg"] for pv in per_vehicle),
        energy_J=sum(pv["core"]["energy_J"] for pv in per_vehicle),
        charges=sum(pv["core"]["charges"] for pv in per_vehicle),
        distance_m=sum(pv["core"]["distance_m"] for pv in per_vehicle),
        avg_power_w=0.0)
    agg["avg_power_w"] = agg["energy_J"] / makespan if makespan > 1e-9 else 0.0
    # idle/survival draw covers active per-vehicle time PLUS time a rover sits idle queueing (charger +
    # resources + waiting on a cross-vehicle precedence predecessor)
    survival_J = IDLE_POWER_W * (sum(pv["core"]["time_s"] for pv in per_vehicle)
                                 + charger_wait_s + resource_wait_s + precedence_wait_s)
    all_trips = [tr for pv in per_vehicle for tr in pv["trips"]]
    all_per_trip = [pt for pv in per_vehicle for pt in pv["per_trip"]]
    all_tl = [seg for pv in per_vehicle for seg in pv["tl"]]
    totals = _mission_totals(mission, all_trips, flows, surplus_kg, meta, agg)
    if survival_J > 0.0:
        totals["energy_J"] = agg["energy_J"] + survival_J
        totals["avg_power_w"] = totals["energy_J"] / makespan if makespan > 1e-9 else 0.0
    detail = [{"vehicle": pv["vehicle"], "n_trips": len(pv["trips"]), "time_s": pv["core"]["time_s"],
               "energy_J": pv["core"]["energy_J"], "distance_m": pv["core"]["distance_m"],
               "charges": pv["core"]["charges"], "charger_wait_s": float(charger_delays[pv["vehicle"]]),
               "crowd_wait_s": float(crowd_delays[pv["vehicle"]]),  # FL-02 re-sequencing wait (space-time crowding)
               "precedence_wait_s": float(precedence_delays[pv["vehicle"]]),  # FL-04 cross-vehicle precedence wait
               "health": _rover_health(pv)}                       # FL-04: per-rover belief/health/resource state
              for pv in per_vehicle]
    fleet_needs_replan = any(d["health"]["health"] == "stranded" for d in detail)   # FL-04 replan trigger
    totals.update(survival_energy_J=float(survival_J), idle_power_w=float(IDLE_POWER_W),
                  algorithm=algorithm, resolved_algorithm=algorithm, optimality="heuristic",
                  objective_exact=False, solved_metric="none",   # P-10: per-vehicle heuristic sequencing
                  n_precedence=len(glob_prec), objective=str(objective), vehicles=int(vehicles),
                  makespan_s=float(makespan), makespan_parallel_s=float(parallel_makespan),
                  charger_wait_s=charger_wait_s, charger_queue_modeled=True,
                  crowd_wait_s=crowd_wait_s, crowd_resequenced=bool(crowd_wait_s > 0.0),  # FL-02 re-sequencing
                  precedence_wait_s=precedence_wait_s,            # FL-04 cross-vehicle precedence wait
                  precedence_split=bool(precedence_wait_s > 0.0),  # FL-04 a chain was split across vehicles
                  vehicle_conflicts=int(conflicts), vehicles_detail=detail,
                  fleet_needs_replan=bool(fleet_needs_replan),
                  temporal_conflicts=int(_temporal_conflicts(per_vehicle)),   # FL-02: nearby-site space-time crowding
                  haul_path_conflicts=int(_haul_path_conflicts(per_vehicle)),  # FL-02: moving haul-PATH crossings
                  charger_conflicts=int(_charger_conflicts(per_vehicle, mission)))
    if mission.shared_resources:    # FL-03: only surface resource fields when declared (else byte-identical)
        for d, pv in zip(detail, per_vehicle):
            d["resource_wait_s"] = float(resource_delays[pv["vehicle"]])
        totals.update(resource_wait_s=resource_wait_s, resource_waits=resource_waits,
                      shared_resources_modeled=True)
    totals["energy_ledger"] = _energy_ledger(mission, all_trips, all_tl, totals)   # EP-01 separable terms
    return all_trips, flows, all_per_trip, all_tl, totals


MV_ORACLE_MAX_TRIPS = 6      # FL-06: the exact MV oracle brute-forces assignments x per-vehicle orders


def plan_multi_oracle(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
                      vehicles=2):
    """FL-06: the EXACT small-problem multi-vehicle oracle that the heuristic `plan_multi` is validated
    against. Brute-forces the TRUE site-exclusive optimum -- every assignment of whole site-groups to V
    vehicles x every per-vehicle trip order -- each candidate simulated battery-aware and resolved through
    the SAME one-server charger queue (FL-03) AND the SAME FL-02 space-time crowding re-sequencing the
    heuristic applies, returning the minimum-makespan plan. The search is a
    SUPERSET of what the heuristic can pick (identical site-exclusive policy + identical simulator), so
    oracle makespan <= heuristic makespan always; a heuristic that 'beats' it is a bug. The per-vehicle
    orders are bruted JOINTLY (the charger queue couples vehicles, so a vehicle cannot be optimised in
    isolation). Gated to small problems (<= MV_ORACLE_MAX_TRIPS trips, no cross-vehicle precedence); it
    RAISES rather than silently approximate a larger or precedence-constrained instance."""
    if vehicles < 1:
        raise ValueError(f"vehicles must be >= 1 (got {vehicles})")
    if mission.precedence:
        raise ValueError("plan_multi_oracle does not handle cross-vehicle precedence; it validates the "
                         "base site-exclusive allocation problem only (use plan_multi for precedence)")
    if mission.shared_resources:
        # FL-03/FL-06: the oracle scores candidates through the shared-CHARGER queue only -- it does NOT
        # model declared pit/dump/vantage/corridor resources, so it would NOT be a tight lower bound for a
        # resource-laden fleet (oracle <= heuristic would still hold, but the optimum could be looser).
        # RAISE rather than silently validate against an under-modelled optimum (the precedence pattern above).
        raise ValueError("plan_multi_oracle does not model declared shared_resources (pit/dump/vantage/"
                         "corridor); it validates the base site-exclusive allocation + shared-charger "
                         "problem only (use plan_multi for resource-laden fleets)")
    trips, _flows, _surplus, _meta = _build_trips(mission, dem, dem_origin, max_traverse_slope_deg)
    routes = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)
    if len(trips) > MV_ORACLE_MAX_TRIPS:
        raise ValueError(f"plan_multi_oracle is exact only up to {MV_ORACLE_MAX_TRIPS} trips "
                         f"(got {len(trips)}); use the heuristic plan_multi for larger fleets")
    groups: dict = {}                                            # site-exclusive: trips at a site move together
    for idx, tr in enumerate(trips):
        groups.setdefault(tuple(tr["site"]), []).append(idx)
    group_idxs = list(groups.values())
    G = len(group_idxs)
    best = None                                                  # (makespan, assignment)
    for assign in itertools.product(range(vehicles), repeat=G):
        veh_trip_idxs: list = [[] for _ in range(vehicles)]
        for g, v in enumerate(assign):
            veh_trip_idxs[v].extend(group_idxs[g])
        order_choices = [list(itertools.permutations(idxs)) for idxs in veh_trip_idxs]  # [()] when empty
        for orders in itertools.product(*order_choices):
            per_vehicle = []
            for v in range(vehicles):
                vtrips = [trips[i] for i in orders[v]]
                tl, _per_trip, core = _simulate(mission, vtrips, routes)
                per_vehicle.append({"vehicle": v, "tl": tl, "core": core})
            delays = _resolve_charger_queue(per_vehicle, capacity=mission.charger_capacity)
            crowd = _resolve_spacetime_crowding(per_vehicle)     # FL-02: same re-sequencing the heuristic applies
            mk = max((pv["core"]["time_s"] + delays[i] + crowd[i] for i, pv in enumerate(per_vehicle)),
                     default=0.0)
            if best is None or mk < best[0] - 1e-9:
                best = (mk, list(assign))
    if best is None:   # CT-06: the assignment x per-vehicle-order loop always runs >= once
        raise RuntimeError("planner: no assignment produced")
    mk, best_assign = best
    return {"makespan_s": float(mk), "vehicles": int(vehicles), "n_trips": len(trips),
            "n_groups": G, "assignment": best_assign, "exact": True}


def plan_and_simulate(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
                      algorithm="nearest", objective="time", vehicles=1):
    """Plan a single-vehicle build mission: build trips, choose a visit order (pluggable `algorithm` x
    `objective`), simulate it battery-aware, and return (trips, flows, per_trip, tl, totals).

    `vehicles` > 1 dispatches to the multi-vehicle planner (`plan_multi`: site-exclusive fleet allocation
    + per-vehicle battery sim + parallel makespan + space-time deconfliction). vehicles=1 is the default
    single-vehicle product planner."""
    if vehicles != 1:
        return plan_multi(mission, dem=dem, dem_origin=dem_origin,
                          max_traverse_slope_deg=max_traverse_slope_deg,
                          algorithm=algorithm, objective=objective, vehicles=vehicles)
    from lode.mission_planner import IDLE_POWER_W   # deferred: the test-patchable survival-draw knob lives on the facade
    trips, flows, surplus_kg, meta = _build_trips(mission, dem, dem_origin, max_traverse_slope_deg)
    routes = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)   # H-02: route inter-site legs ONCE
    prec = trip_precedence(trips, mission)                  # I9: order-level precedence -> trip constraints
    if not _precedence_is_feasible(len(trips), prec):       # AL2: fail loud, never a silent 0-trip "success"
        raise RuntimeError(
            "infeasible precedence: the mission's precedence constraints form a cycle, so no build "
            "sequence can satisfy them. Check `mission.precedence` for a loop (e.g. A->B and B->A).")
    order = optimize_sequence(trips, mission, algorithm=algorithm, objective=objective, precedence=prec,
                              routes=routes)                 # optimizer scores the SAME routed geometry as the IR
    trips = [trips[i] for i in order]
    tl, per_trip, core = _simulate(mission, trips, routes)
    resolved = algorithm                                    # what 'auto' actually dispatched to
    if algorithm == "auto":
        resolved = "brute" if len(trips) <= BRUTE_MAX_TRIPS else (
            "held_karp_lk" if len(trips) <= HELD_KARP_MAX_TRIPS else "lk")
    # AL1 + P-10: be explicit AND objective-specific about optimality. `brute` simulates every permutation
    # so it is EXACT on the chosen objective. `held_karp(_lk)` is exact only on routed DRIVING DISTANCE,
    # then LK-polished -- so its label must NAME that metric and it is objective_exact ONLY when the
    # objective IS distance. Anything else (lk past the cap) is unbounded local search.
    optimality, objective_exact = _objective_optimality(resolved, objective)
    if optimality == "heuristic" and len(trips) > HELD_KARP_MAX_TRIPS:
        warnings.warn(
            f"plan visit order is heuristic: {len(trips)} trips exceed the exact cap "
            f"(HELD_KARP_MAX_TRIPS={HELD_KARP_MAX_TRIPS}); algorithm '{resolved}' has no optimality bound.",
            stacklevel=2)
    # K11c: continuous idle/heater/survival draw over the WHOLE mission duration -- the likely-dominant
    # multi-day term the active-leg ledger omits. [ASSUMPTION] (IDLE_POWER_W, default 0 = not modelled);
    # folded into the headline energy/avg-power only when set, so a default plan is never silently inflated.
    survival_J = IDLE_POWER_W * core["time_s"]
    totals = _mission_totals(mission, trips, flows, surplus_kg, meta, core)
    if survival_J > 0.0:
        totals["energy_J"] = core["energy_J"] + survival_J
        totals["avg_power_w"] = totals["energy_J"] / core["time_s"] if core["time_s"] > 1e-9 else 0.0
    totals.update(
        survival_energy_J=float(survival_J), idle_power_w=float(IDLE_POWER_W),
        algorithm=algorithm, resolved_algorithm=resolved, optimality=optimality,
        objective_exact=bool(objective_exact),                # P-10: is the result EXACT for the chosen objective?
        solved_metric=(HELD_KARP_EXACT_METRIC if resolved in ("held_karp", "held_karp_lk") else
                       ("objective" if resolved == "brute" else "none")),
        n_precedence=len(prec),
        objective=str(objective), vehicles=1,
        makespan_s=float(core["time_s"]), vehicle_conflicts=0, charger_conflicts=0,   # 1 vehicle -> no fleet contention
        vehicles_detail=[])   # uniform fleet schema
    totals["energy_ledger"] = _energy_ledger(mission, trips, tl, totals)   # EP-01 separable terms
    return trips, flows, per_trip, tl, totals
