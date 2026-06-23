#!/usr/bin/env python3
"""mission_planner.py — the lunar build-planner FACADE (ARCH-2).

This module is a thin FACADE. The planner was decomposed (ARCH-2, 2026-06-22) from a ~2110-line
god-module into 10 dependency-ordered leaf modules — `planner_constants` (shared constants),
`planner_model` (data model + order compilation), `planner_routing`, `planner_balance`,
`planner_multivehicle`, `planner_endurance`, `planner_trips`, `planner_sim`, `planner_optimize`,
`planner_assembly` (plan/compare/run) — plus `planner_views` (report/PDF/plan_math/commands) and
`planner_acceptance` (`validate_plan`). Every public symbol is RE-EXPORTED here, so `MP.<name>` and
`from lode.mission_planner import …` are byte-identical for all dependents; the former
lode↔planner_views import cycle is broken via `planner_constants`.

What the planner does (conceptually): takes a MISSION (build orders on a map), CUT-FILL BALANCES it
(route excavated material to fills, minimizing haul), OPTIMIZES the execution sequence (TSP +
battery-aware mid-task recharge), and outputs a 2-3 page mission-control REPORT (PDF + markdown):
coordinates, actions, speed, battery-draw over the project, cumulative mass/energy, the balance, metrics.

Order kinds:
  cut    — excavate a footprint to a depth -> PRODUCES regolith (energy: 4151 J/kg dig).
  fill   — berm/pad/road raise -> CONSUMES regolith (supplied from the nearest cut; hauled in drum loads).
  sinter — fuse a surface into hard pad/road (the lunar concrete analog) IN PLACE -> energy 0.92 MJ/kg
           (~220x dig; the energy bottleneck), no material moved.

Grounded: per-body density/gravity from bodies.json (sysrev the conserved authority/bodies.py); IPEx +
sinter constants from the conserved authority (ipex_specs, constants). The recharge power and sinter-head
power are [CALIB] (no IPEx solar/sinter spec).
Run:  python3 mission_planner.py
"""
from __future__ import annotations

import dataclasses
import hashlib
from typing import TYPE_CHECKING
import json
import os

import matplotlib
matplotlib.use("Agg")

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- grounded constants: imported from the .py source of truth (the conserved authority), not duplicated.
# The monorepo root (lode's parent) holds stewie/, dart/, samples/, scripts/; ensure it is
# importable. _REPO_ROOT also anchors the sample/script paths. (When stewie is pip-installed,
# the conserved authority imports directly; this insert is the run-from-source fallback.)
import sys
_REPO_ROOT = os.path.dirname(HERE)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
from stewie.specs import config                    # PO-02: configurable application-data (reports) dir
from stewie.specs import ipex_specs as S          # IPEx energy/battery (NTRS 20240008162) + planner knobs
from stewie.physics import rassor_mass_model as RM   # noqa: F401  re-exported as MP.RM (server /sense)
# ARCH-2 (#123): the vehicle registry (V), input validation (VAL), the body soil model
# (get_body/params_for_body) and the slip/terramechanics (TMS/TM) modules are used only by code now in
# the leaves lode.planner_model (data model) and lode.planner_endurance (range/slip) -- not here.

# ARCH-03: the SHARED planner constants live in the dependency-neutral lode.planner_constants so
# planner_views can import them WITHOUT importing this module (half of the cycle break). Re-imported
# here so MP.<const> and the internal uses below are unchanged; values are byte-identical. (DRIVE_SPEED_MS
# + CHARGE_W are rebound per-vehicle from ctx inside the sims; SLIP_ALPHA / _TM_PARAMS are used only by
# planner_endurance now -- so those three are not imported at module scope here.)
from lode.planner_constants import (  # noqa: E402,F401  (DIG_RATE_KG_S re-exported: MP.DIG_RATE_KG_S contract)
    BATTERY_J, DIG_RATE_KG_S, DRIVE_J_PER_M, LOCALIZATION_MARGIN_M,
    RESERVE_FRAC, ROVER_MASS_KG, _CONSTRAINT_CAPS,
)
# ARCH-2 (#123): lander_return (LR) / relocalization (REL) / rassor_mass_model (RMM) are used only by the
# plan-assembly helpers now in lode.planner_assembly; not imported here. (RM stays above for the MP.RM /sense
# re-export.)
# ARCH-2 (#123): the mission DATA MODEL + order compilation is the foundational LEAF lode.planner_model
# (imports only stewie.* + planner_constants + the pure lander_return; never imports THIS module). Re-export
# every name so MP.Mission and `from lode.mission_planner import Mission` stay byte-identical for dependents.
from lode.planner_model import (  # noqa: E402,F401
    BODY_TIMESCALE, KIND_CAPABILITY, BuildOrder, Mission, PlanningContext,
    _bodies, _d, _drum_kg, _ORDER_FIELDS, _ORDER_KINDS, _vehicle_battery_j,
    body_density, body_gravity, body_timescale, footprint_shape_area_m2,
    mission_from_dict, mission_soil_params, plan_context, vehicle_footprint_radius_m,
)
DIG_J_PER_KG    = S.dig_energy_per_kg()                  # ~4151 J/kg; also in planner_constants (same source)
DRUM_KG         = S.REGOLITH_PER_CYCLE_KG                # 30 kg/cycle (the ipex default; see _drum_kg)
# CHARGE_W / LOCALIZATION_MARGIN_M / _CONSTRAINT_CAPS / ROVER_MASS_KG / SLIP_ALPHA / _TM_PARAMS live in
# lode.planner_constants (ARCH-2 #123); RESERVE_FRAC likewise (ARCH-03). SINTER_J_PER_KG / SINTER_POWER_W /
# OFFLOAD_RATE_KG_S now live in lode.planner_trips (#4, the only consumer). Values are byte-identical.
# RELOCALIZE_DRIFT_TOL_M now lives in lode.planner_assembly (#7, its only consumer).
DRIVE_POWER_W   = S.drive_power_w()                      # ~40 W (Table 3 driving cases)
# IDLE_POWER_W stays HERE as the canonical, test-patchable survival-draw knob (the planner_assembly
# planners read MP.IDLE_POWER_W via a deferred import so a monkeypatch is honored). Default 0 = off.
IDLE_POWER_W    = S.IDLE_POWER_W                         # [ASSUMPTION] continuous survival draw (default 0 = off)


# ARCH-2 #2: the cut-fill MATERIAL BALANCE solver (SWELL + _mincost_transport + balance) lives in
# lode.planner_balance. balance() needs this module's _d / _make_routes / Mission, which it pulls via a
# deferred import (no cycle), so planner_balance imports first; this module imports the block back at
# scope (planner_balance has no scope-level dependency on mission_planner -- only inside balance()). The
# re-import keeps MP.balance / MP._mincost_transport / MP.SWELL call sites unchanged (values identical).
from lode.planner_balance import SWELL, _mincost_transport, balance  # noqa: E402,F401




# ARCH-2 (#123): order-independent trip construction + haul energy + routing memo + precedence + mission
# windows live in the leaf lode.planner_trips (imports the planner_constants / planner_endurance /
# planner_routing / planner_balance / planner_model leaves directly; pulls the route_leg WRAPPER below via
# a deferred import, no cycle). Re-export so the staying sim/sequencer code's unqualified _build_trips /
# trip_precedence / _make_routes / _window_gate calls + MP.* dependents stay byte-identical.
from lode.planner_trips import (  # noqa: E402,F401
    OFFLOAD_RATE_KG_S, SINTER_J_PER_KG, SINTER_POWER_W, _build_trips, _make_routes,
    _precedence_is_feasible, _segmented_haul_energy, trip_precedence, _window_gate,
)


# ARCH-2 (#123): the battery-aware ordered-trip SIMULATOR (_simulate) lives in the leaf lode.planner_sim
# (imports only the planner_model / planner_endurance / planner_trips leaves; never imports THIS module).
# Re-export so the sequencer/plan code's unqualified _simulate(...) calls + MP._simulate dependents stay
# byte-identical.
from lode.planner_sim import _simulate  # noqa: E402,F401


# ARCH-2 (#123): the OBJECTIVE scoring + sequence OPTIMIZER (OBJECTIVES/SEQUENCERS tables, the objective
# parser, the constraint penalty, the core scorer, nearest/greedy/2-opt/or-opt/LK heuristics, the
# Held-Karp exact DP, and optimize_sequence) lives in the leaf lode.planner_optimize (imports the
# planner_sim / planner_model / planner_trips / planner_constants leaves; never imports THIS module).
# Re-export every name so the plan/compare/timeline code's unqualified calls + MP.OBJECTIVES /
# MP.optimize_sequence / MP.parse_objective / MP.SEQUENCERS dependents stay byte-identical.
from lode.planner_optimize import (  # noqa: E402,F401
    BRUTE_MAX_TRIPS, HELD_KARP_EXACT_METRIC, HELD_KARP_MAX_TRIPS, OBJECTIVES, SEQUENCERS,
    _constraint_penalty, _held_karp, _make_core_scorer, _nn_order, _objective_is_only,
    _objective_optimality, _prec_masks, _respects, _score, optimize_sequence, parse_objective,
)


# ARCH-2 (#123): the PLAN-ASSEMBLY layer (the _relocalization/_return_to_lander/_plan_uncertainty/
# _mission_totals feasibility+totals helpers and the plan_multi / plan_multi_oracle / plan_and_simulate
# planners) lives in the leaf lode.planner_assembly (imports the planner leaves; never imports THIS
# module). It owns RELOCALIZE_DRIFT_TOL_M / MV_ORACLE_MAX_TRIPS now (IDLE_POWER_W stays the canonical knob
# on THIS facade -- the assembly planners read it via a deferred import). Re-export every name so
# plan()/compare_algorithms()/run()'s unqualified calls + MP.plan_and_simulate / MP.plan_multi /
# MP._mission_totals dependents stay byte-identical.
from lode.planner_assembly import (  # noqa: E402,F401
    MV_ORACLE_MAX_TRIPS, RELOCALIZE_DRIFT_TOL_M, _mission_totals, _plan_uncertainty,
    _relocalization, _return_to_lander, plan_and_simulate, plan_multi, plan_multi_oracle,
)


# ARCH-2: the multi-vehicle allocation + space-time conflict layer lives in planner_multivehicle
# (self-contained geometry over duck-typed per_vehicle/trip structures; no planner-core dep, no
# cycle). Re-exported so MP.<fn> + plan_multi keep working unchanged.
from lode.planner_multivehicle import (  # noqa: E402,F401
    _trip_work_e, _allocate_trips, _allocate_components, _allocate_precedence_split,
    _resolve_cross_vehicle_precedence, _vehicle_conflicts,
    _charger_conflicts, _resolve_charger_queue, _resolve_shared_resources, _temporal_conflicts,
    _seg_seg_min_dist, _haul_path_conflicts, _resolve_spacetime_crowding, _rover_health,
    _resolve_joint_resources,
)



# ---- RB-03: ONE immutable plan artifact that every output is a view of -----------------------------
PLAN_RESULT_VERSION = "1.0"


@dataclasses.dataclass(frozen=True)
class PlanResult:
    """The single source-of-truth plan (RB-03). Produced ONCE by ``plan()``; totals, report, Plan IR,
    timeline, and the browser are VIEWS over it, never independent recomputations of the planner.
    Frozen prevents field reassignment; the contained list/dicts are read-only by convention."""
    mission: "Mission"
    dem_origin: tuple
    trips: list
    flows: dict
    per_trip: list
    tl: list
    totals: dict
    provenance: dict
    validation: dict | None = None     # RB-03: as-built acceptance, attached when computed with_acceptance
    endurance: dict | None = None      # RB-03: single-sortie reachability, attached likewise

    def as_tuple(self):
        """The legacy (trips, flows, per_trip, tl, totals) shape older call sites consume."""
        return self.trips, self.flows, self.per_trip, self.tl, self.totals


_SOURCE_COMMIT: str | None = None


def _source_commit() -> str:
    """CT-07: the source commit the artifact was produced from, best-effort + cached. Prefers an
    explicit ``$STEWIE_COMMIT`` (baked into a wheel/container build), else `git rev-parse` in the repo,
    else "unknown" (a wheel with neither is HONESTLY unknown, never fabricated)."""
    global _SOURCE_COMMIT
    if _SOURCE_COMMIT is None:
        _SOURCE_COMMIT = os.environ.get("STEWIE_COMMIT", "").strip()
        if not _SOURCE_COMMIT:
            try:
                import subprocess
                _SOURCE_COMMIT = subprocess.run(
                    ["git", "rev-parse", "--short", "HEAD"],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    capture_output=True, text=True, timeout=2, check=True).stdout.strip() or "unknown"
            except (OSError, subprocess.SubprocessError):
                _SOURCE_COMMIT = "unknown"
    return _SOURCE_COMMIT


def _plan_provenance(mission, *, algorithm, objective, vehicles, dem_origin, seed=None):
    """CT-07: provenance for a PlanResult -- source commit + package version, schema version, mode, the
    planning config, the RNG seed, and a DETERMINISTIC content hash of the mission + origin + config, so
    a result is tied to exactly the inputs (and the code) that made it. ``seed`` is None for the
    deterministic optimizers (nearest / held-karp / beam) -- output is a pure function of input_sha256 --
    and carries the actual seed only when a stochastic algorithm is selected."""
    from stewie import __version__ as _version
    canon = json.dumps({
        "mission": dataclasses.asdict(mission), "dem_origin": list(dem_origin),
        "algorithm": str(algorithm), "objective": str(objective), "vehicles": int(vehicles), "seed": seed,
    }, sort_keys=True, default=str)
    return {
        "schema_version": PLAN_RESULT_VERSION, "mode": "PLAN",
        "commit": _source_commit(), "version": _version, "seed": seed,
        "config": {"algorithm": str(algorithm), "objective": str(objective), "vehicles": int(vehicles)},
        "input_sha256": hashlib.sha256(canon.encode()).hexdigest(),
    }


def plan(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
         algorithm="nearest", objective="time", vehicles=1, with_acceptance=False) -> PlanResult:
    """RB-03 keystone: compute the canonical plan ONCE and package it as an immutable PlanResult. Pass the
    result to ``run`` / ``build_timeline`` / ``plan_ir`` so they do NOT each re-run the planner (the server
    does this), guaranteeing totals/report/timeline/IR/playback describe one and the same plan. Wraps
    plan_and_simulate (single-vehicle or, for vehicles>1, the fleet planner).

    ``with_acceptance`` also computes the as-built validation + single-sortie endurance and attaches them,
    so the server's plan response is wholly a view of ONE result (RB-03: validation/acceptance live here)."""
    trips, flows, per_trip, tl, totals = plan_and_simulate(
        mission, dem=dem, dem_origin=dem_origin, max_traverse_slope_deg=max_traverse_slope_deg,
        algorithm=algorithm, objective=objective, vehicles=vehicles)
    prov = _plan_provenance(mission, algorithm=algorithm, objective=objective,
                            vehicles=vehicles, dem_origin=dem_origin)
    # CP-04: honor the mission's compiled as-built acceptance tolerance (from the objectives' MO-01
    # acceptance tolerance) when one was lowered onto the mission; else validate_plan keeps its default.
    _val_kw = ({} if mission.accept_flatness_tol_m is None
               else {"accept_flatness_tol_m": mission.accept_flatness_tol_m})
    validation = (validate_plan(mission, dem=dem, dem_origin=dem_origin, **_val_kw)
                  if with_acceptance else None)
    endu = endurance(mission, dem=dem, dem_origin=dem_origin) if with_acceptance else None
    return PlanResult(mission=mission, dem_origin=tuple(dem_origin), trips=trips, flows=flows,
                      per_trip=per_trip, tl=tl, totals=totals, provenance=prov,
                      validation=validation, endurance=endu)


# ---- executable Plan IR: the machine-consumable plan a rover / ROS executive runs (vs the human PDF) ----
# ARCH-2: PLAN_IR_VERSION + plan_ir (the machine-executable IR VIEW -- the executive's counterpart to
# the human PDF report) moved to lode.planner_views; re-exported at module END (with the other views)
# so MP.plan_ir / MP.PLAN_IR_VERSION call sites are unchanged.


# the min-objective metric columns used for Pareto non-domination across algorithms
_PARETO_METRICS = ("time_s", "energy_J", "distance_m", "charges")


def compare_algorithms(mission: Mission, *, objective="time", algorithms=None, dem=None,
                       dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0):
    """Run every concrete sequencer and return their metrics sorted by `objective` (best first) -- 'run
    different algorithms for path planning / optimization, however I sort it'. Each row carries that plan's
    full metrics (re-sort by any column) + a `pareto` flag (non-dominated across time/energy/distance/charges)
    so the trade-off frontier is visible. `objective` may be a single name or a weighted spec."""
    algos = algorithms or [a for a in SEQUENCERS if a != "auto"]   # compare the concrete solvers
    weights = parse_objective(objective)
    rows = []
    for a in algos:
        try:
            _, _, _, _, T = plan_and_simulate(mission, dem=dem, dem_origin=dem_origin,
                                              max_traverse_slope_deg=max_traverse_slope_deg,
                                              algorithm=a, objective=objective)
            rows.append({"algorithm": a, "resolved_algorithm": T["resolved_algorithm"],
                         "time_s": T["time_s"], "energy_J": T["energy_J"], "avg_power_w": T["avg_power_w"],
                         "distance_m": T["distance_m"], "charges": T["charges"], "mass_kg": T["mass_kg"],
                         "lift_energy_J": T["lift_energy_J"]})
        except Exception as e:                              # e.g. sinter gated -> report, don't crash the table
            rows.append({"algorithm": a, "error": str(e)})
    ok = [r for r in rows if "error" not in r]
    # objective_value: single objective = the raw metric; weighted = sum of metrics normalized to the best
    # in this comparison set (min-objectives /best, max-objectives best/), lower = better.
    best = {n: min((OBJECTIVES[n][1](r) for r in ok), default=1.0) for n in weights}
    bestmax = {n: max((OBJECTIVES[n][1](r) for r in ok), default=1.0) for n in weights}
    for r in ok:
        if len(weights) == 1:
            (name,) = weights
            r["objective_value"] = OBJECTIVES[name][1](r)
        else:
            s = 0.0
            for n, w in weights.items():
                direction, fn = OBJECTIVES[n]
                v = fn(r)
                # P-09: floor the normalizing denominator so a zero best/bestmax (e.g. every algorithm
                # makes 0 recharges, or zero distance) cannot divide by zero or produce NaN/Inf. A
                # degenerate metric (best and v both ~0) contributes a constant unit, not an undefined ratio.
                if direction == "min":
                    s += w * (1.0 if (abs(v) <= 1e-9 and abs(best[n]) <= 1e-9) else v / max(best[n], 1e-9))
                else:
                    s += w * (1.0 if (abs(v) <= 1e-9 and abs(bestmax[n]) <= 1e-9)
                              else max(bestmax[n], 0.0) / max(v, 1e-9))
            r["objective_value"] = s
    # Pareto: a plan is non-dominated if no other plan is <= on all metrics and < on at least one
    for r in ok:
        r["pareto"] = not any(o is not r
                              and all(o[m] <= r[m] + 1e-9 for m in _PARETO_METRICS)
                              and any(o[m] < r[m] - 1e-9 for m in _PARETO_METRICS) for o in ok)
    direction = "min" if len(weights) > 1 else OBJECTIVES[next(iter(weights))][0]
    inf = float("inf")
    rows.sort(key=lambda r: (r["objective_value"] if direction == "min" else -r["objective_value"])
              if "objective_value" in r else inf)
    return {"objective": str(objective), "direction": direction, "rows": rows}


def build_timeline(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
                   algorithm="nearest", objective="time", result=None):
    """P5 (execute + watch): turn the battery-aware simulation into a compact, animatable timeline. Each
    frame is a time-bounded segment carrying the rover's start/end position, battery fraction, phase, and
    cumulative mass moved; the browser interpolates the rover marker + telemetry HUD along it. Positions
    come from the actual sim moves (drive/charge/work), not a reconstruction. Honors the chosen sequencer
    so the animation matches the planned order."""
    if result is None:                                  # RB-03: reuse the shared plan if given (no recompute)
        result = plan(mission, dem=dem, dem_origin=dem_origin,
                      max_traverse_slope_deg=max_traverse_slope_deg,
                      algorithm=algorithm, objective=objective)
    _, _, _, tl, totals = result.as_tuple()
    frames = []
    cum = 0.0
    for s in tl:
        cum += s["mass"]
        frames.append(dict(
            t0=round(s["t0"], 3), t1=round(s["t1"], 3),
            x0=round(float(s["x0"]), 3), y0=round(float(s["y0"]), 3),
            x1=round(float(s["x1"]), 3), y1=round(float(s["y1"]), 3),
            phase=s["kind"], batt0_frac=s["batt0"] / BATTERY_J, batt1_frac=s["batt1"] / BATTERY_J,
            cum_mass_kg=round(cum, 1)))
    return dict(duration_s=round(totals["time_s"], 3), battery_J=float(BATTERY_J),
                charger=list(mission.charger), frames=frames,
                provenance=result.provenance)            # CT-07: ties this playback to the one plan


# ARCH-2: the DEM/site loaders moved to stewie.terrain.site_dem (the terrain layer, below lode +
# dart). Re-exported here so MP.load_site_dem / MP.flattest_anchor / ... and internal callers are
# unchanged; dart now imports site_dem directly (no dart->lode cycle).
from stewie.terrain.site_dem import (  # noqa: F401
    _haworth_bundle, bundle_for_site, dem_georef_corners, dem_grid_info, dem_origin_to_latlon,
    flattest_anchor, flattest_anchor_streamed, latlon_to_dem_origin, load_haworth_dem, load_site_dem,
    read_dem_window, slope_deg_map,
)
# ---- I10 routing moved to lode.planner_routing (ARCH-2 god-module split); re-exported so
# MP.route_leg / MP.slope_costmap / ... and the solver's internal calls are unchanged.
from lode.planner_routing import (  # noqa: F401
    _ROUTE_NB, MAX_DROP_M, _apply_keepouts, _crop_illum, haul_cumulative_ascent_m, haul_elevation_gain_m,
    keepout_is_rect, negative_obstacle_mask, point_in_keepout, route_least_cost, routed_distance,
    slope_costmap,
)
from lode.planner_routing import route_leg_inflated as route_leg  # noqa: F401  E402  (MP.route_leg = the footprint-inflating wrapper; planner_routing.route_leg stays the point router)


# ARCH-2 (#123): the endurance / single-charge range / power-regime analytics + slip_alpha_to_slip live
# in the leaf lode.planner_endurance (imports only stewie.* + planner_constants + the planner_routing /
# planner_model leaves; never imports THIS module). Re-export so MP.endurance / MP.slip_alpha_to_slip and
# the haul-energy code's slip_alpha_to_slip call sites stay byte-identical.
from lode.planner_endurance import (  # noqa: E402,F401
    POWER_KINDS, endurance, power_regime, reachable_radius_on_dem,
    single_charge_range_m, slip_alpha_to_slip, thermal_derate,
)


# ARCH-2: the conserved-authority plan ACCEPTANCE layer (validate_plan + execute_plan_acceptance)
# lives in planner_acceptance (rasterize orders onto a ColumnState + execute cuts/fills to test
# material realizability, siting, as-built, berm/repose/bearing). Re-exported so MP.validate_plan +
# MP.execute_plan_acceptance keep working unchanged. The module reads the planner-core helpers
# (SWELL/_drum_kg/plan_context/mission_soil_params/body_gravity) via a deferred import, so no cycle.
from lode.planner_acceptance import (  # noqa: E402,F401
    validate_plan, execute_plan_acceptance,
)


def _dur(s):
    h = s / 3600
    return f"{h:.1f} h" if h < 48 else f"{h/24:.1f} d"


def demo_mission():
    return Mission(name="South-Pole Site Development", body="moon", charger=(0, 0), orders=[
        BuildOrder("Level landing pad", "cut", 40, 30, 36, 0.04, "6x6 m"),
        BuildOrder("Grade access road", "cut", 15, 5, 30, 0.02, "15x2 m"),
        BuildOrder("Build blast berm", "fill", 44, 44, 14, 0.10, "from pad cut"),
        BuildOrder("Fill crater dip", "fill", -20, 30, 8, 0.08, "from road cut"),
        # Sinter is GATED OFF (energy/density [CALIB], not IPEx-grounded). Re-add once SINTER_ENABLED:
        #   BuildOrder("Sinter pad apron", "sinter", 40, 30, 9, 0.01, "fuse landing surface"),
    ])


def run(mission: Mission, stem=None, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
        algorithm="nearest", objective="time", vehicles=1, result=None):
    """Plan + simulate + render the report. ``stem`` names the output files (default = the date); the
    server passes a unique per-mission stem so concurrent plans don't overwrite each other. When ``dem``
    is supplied (server passes the real Haworth DEM for Moon), hauls are I10-routed around hazards.
    ``algorithm`` x ``objective`` select the pluggable sequencer + optimization metric. ``vehicles`` > 1
    plans a multi-vehicle fleet (plan_multi). ``result`` reuses a shared PlanResult (RB-03; no recompute)."""
    if result is None:
        result = plan(mission, dem=dem, dem_origin=dem_origin,
                      max_traverse_slope_deg=max_traverse_slope_deg,
                      algorithm=algorithm, objective=objective, vehicles=vehicles)
    trips, flows, per_trip, tl, totals = result.as_tuple()
    rdir = config.reports_dir()                         # PO-02: configurable app-data dir (where the server serves from)
    os.makedirs(rdir, exist_ok=True)
    stem = stem or f"{mission.date}_mission_plan"
    pdf = os.path.join(rdir, f"{stem}.pdf")
    md = os.path.join(rdir, f"{stem}.md")
    from lode.planner_views import report     # ARCH-03: the view is pulled at the render boundary (both
    report(mission, trips, flows, per_trip, tl, totals, pdf, md,   # modules are fully imported by now)
           endu=endurance(mission, dem=dem, dem_origin=dem_origin))
    return pdf, md, totals


def main():
    m = demo_mission(); pdf, md, totals = run(m)
    print(f"trips: {[t['label'] for t in plan_and_simulate(m)[0]]}")
    print(f"balance: cut {totals['cut_kg']/1000:.1f} t -> fill {totals['fill_kg']/1000:.1f} t, "
          f"surplus {totals['surplus_kg']/1000:.1f} t, deficit {totals['deficit_kg']/1000:.1f} t, "
          f"sinter {totals['sinter_kg']/1000:.2f} t")
    print(f"totals: {_dur(totals['time_s'])}, {totals['energy_J']/1e6:.1f} MJ, "
          f"{totals['energy_J']/BATTERY_J:.1f} charges, {totals['charges']} recharges")
    print(f"report -> {pdf}")


if __name__ == "__main__":
    main()


# ARCH-03: the planner VIEWS live in planner_views; re-exported here so MP.report / MP.plan_math /
# MP.plan_ir / MP.assumptions_register (+ the IR constants) call sites are unchanged. The re-export is
# LAZY (PEP 562 module __getattr__) rather than a module-scope `import planner_views`, which REMOVES the
# back-edge of the former bidirectional cycle: planner_views imports THIS module, and this module pulls
# the views only on first attribute access (after both are fully initialized). So either module now
# imports first without a circular-import crash (ARCH-03). The TYPE_CHECKING import gives mypy the static
# names with no runtime edge.
_VIEW_EXPORTS = frozenset({
    "report", "plan_math", "assumptions_register", "plan_ir", "plan_uncertainty_view",
    "PLAN_IR_VERSION", "_IR_OP", "_IR_DIG_OPS", "_IR_MODEL_ERR_FRAC",
})

if TYPE_CHECKING:                                 # static only -- never executed, so no runtime cycle
    from lode.planner_views import (  # noqa: F401
        PLAN_IR_VERSION, _IR_DIG_OPS, _IR_MODEL_ERR_FRAC, _IR_OP,
        assumptions_register, plan_ir, plan_math, plan_uncertainty_view, report,
    )


def __getattr__(name):
    """PEP 562: resolve the re-exported planner views lazily so this module does not import
    planner_views at scope (the cycle break, ARCH-03)."""
    if name in _VIEW_EXPORTS:
        from lode import planner_views as _views
        return getattr(_views, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
