#!/usr/bin/env python3
"""mission_planner.py — SimCity-Space lunar build planner + mission-control report.

Takes a MISSION (build orders on a map), CUT-FILL BALANCES it (route excavated material to fills,
minimizing haul), OPTIMIZES the execution sequence (TSP + battery-aware mid-task recharge), and outputs
a 2-3 page mission-control REPORT (PDF + markdown): coordinates, actions, speed, battery-draw over the
project, cumulative mass/energy, the material balance, and metrics.

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
import heapq
import itertools
import json
import math
import os
import warnings

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
import numpy as np                                      # for validate_plan (executes orders on the authority)
from stewie.specs import config                    # PO-02: configurable application-data (reports) dir
from stewie.specs import ipex_specs as S          # IPEx energy/battery (NTRS 20240008162) + planner knobs
from stewie.specs import constants as C            # materials + the SINTER_ENABLED gate
from stewie.physics import slip as TMS               # conserved slip ladder — weight-aware leg slip
from stewie.physics import terramechanics as TM      # TerramechanicsParams for the slip solve
from stewie.physics import rassor_mass_model as RM   # noqa: F401  re-exported as MP.RM (server /sense)
from stewie.physics import validation as VAL         # RB-01: physical-domain validation at this input boundary
from stewie.specs import vehicles as V             # vehicle/tool capability registry (gate order kinds)
from stewie.specs.bodies import get_body as _get_body, params_for_body  # soil model (soil override)
from stewie.physics.column_state import ColumnState  # conserved authority — for I8 plan validation

DRIVE_SPEED_MS  = S.DRIVE_SPEED_MS                       # 0.30 m/s
DIG_RATE_KG_S   = S.DIG_RATE_KG_PER_HR / 3600.0         # 42 kg/hr
DIG_J_PER_KG    = S.dig_energy_per_kg()                  # ~4151 J/kg (derived)
DRIVE_J_PER_M   = S.drive_energy_per_m()                 # ~135 J/m (derived)
BATTERY_J       = S.battery_energy_j()                   # ~4.79 MJ (12S/30Ah)
DRUM_KG         = S.REGOLITH_PER_CYCLE_KG                # 30 kg/cycle (the ipex default; see _drum_kg)


def _drum_kg(mission):
    """RB-05: the per-cycle drum capacity [kg] of the mission's SELECTED vehicle (VehicleModel-driven),
    so vehicle choice changes the planner numbers (loads / drum cycles / haul energy). The default
    vehicle 'ipex' has drum_capacity_kg == DRUM_KG == 30, so an unspecified mission is byte-identical."""
    return float(V.get_vehicle(mission.vehicle).drum_capacity_kg)
SINTER_J_PER_KG = C.SINTER_ENERGY_J_PER_KG              # 0.92 MJ/kg [CALIB]
SINTER_POWER_W  = S.SINTER_HEAD_POWER_W                  # 1000 W [CALIB]
CHARGE_W        = S.RECHARGE_POWER_W                     # 700 W [CALIB]
RESERVE_FRAC    = S.BATTERY_RESERVE_FRAC                 # 0.10
ROVER_MASS_KG   = S.ROVER_MASS_CLASS_KG                  # 30 kg-class (for gravity-climb drive energy)
DRIVE_POWER_W   = S.drive_power_w()                      # ~40 W (Table 3 driving cases)
IDLE_POWER_W    = S.IDLE_POWER_W                         # [ASSUMPTION] continuous survival draw (default 0 = off)
SLIP_ALPHA      = 2.0                                    # [CALIB] slip energy multiplier vs tan(slope) (I10 costmap)
_TM_PARAMS      = TM.TerramechanicsParams.from_constants()   # lunar defaults for the weight-aware leg-slip solve
# P-04: OFFLOAD/placement model for IMPORTED fill. Imported regolith arrives from an external supply
# (a separate logistics chain, not modelled here as a coordinate); the rover only DEPOSITS it. Depositing
# discharges the drum at its material-handling throughput (DIG_RATE_KG_S, the same drum rate used to
# collect/deposit), and the placement ENERGY is the drum-discharge handling at the drive/handling power --
# NOT the in-situ DIG energy (~4151 J/kg), because no bank material is cut. This keeps import comparable
# to in-situ construction with the RIGHT physical process. [DERIVED from grounded drive power + dig rate.]
OFFLOAD_RATE_KG_S = DIG_RATE_KG_S                        # drum deposit throughput == its collect throughput
# P-06: positional uncertainty added to the vehicle's physical swept radius when inflating routing hazards.
# A skid-steer rover localizes imperfectly (odometry drift ~ODOM_DRIFT_FRAC/m); a corridor only as wide as
# the bare body is not safe under pose error. [ASSUMPTION] -- a fixed margin floor; the per-leg drift-scaled
# term is future work. Keeps routing conservative: hazards are inflated by swept footprint PLUS this margin.
LOCALIZATION_MARGIN_M = 0.15


@dataclasses.dataclass(frozen=True)
class PlanningContext:
    """H-01: ONE immutable per-mission planning context resolved from the SELECTED vehicle, threaded
    through the energy / mass / range / slip / report / acceptance paths so the planner stops using the
    IPEx module globals for every vehicle. The default vehicle 'ipex' resolves to EXACTLY the module
    globals (verified: dig/drive energy, battery, mass, power, drum), so an ipex mission is byte-identical;
    rassor2 (65 kg, 80 kg drum) now drives the plan with its own mass. drive_speed / reserve_frac / charge_w
    are platform-neutral (not per-vehicle in the registry) and carry the module defaults."""
    dig_j_per_kg: float
    drive_j_per_m: float
    battery_j: float
    drum_kg: float
    rover_mass_kg: float
    drive_power_w: float
    drive_speed_ms: float = DRIVE_SPEED_MS
    reserve_frac: float = RESERVE_FRAC
    charge_w: float = CHARGE_W

    @property
    def reserve_j(self) -> float:
        return self.reserve_frac * self.battery_j

    @property
    def usable_j(self) -> float:
        return self.battery_j * (1.0 - self.reserve_frac)


def _vehicle_battery_j(veh) -> float:
    """Stored energy [J] a vehicle carries = the sum of its onboard battery PowerSources' capacity; falls
    back to the IPEx pack when the vehicle declares no onboard storage (a tower-fed/continuous vehicle)."""
    cap = sum(V.POWER_SOURCES[p].capacity_j for p in getattr(veh, "onboard_power", ())
              if p in V.POWER_SOURCES and V.POWER_SOURCES[p].capacity_j > 0)
    return float(cap) if cap > 0 else float(BATTERY_J)


def plan_context(mission) -> PlanningContext:
    """H-01: resolve the immutable PlanningContext for the mission's SELECTED vehicle. ipex -> the module
    globals (byte-identical); another vehicle -> its registry energy / mass / drum / power + onboard battery."""
    veh = V.get_vehicle(mission.vehicle)
    return PlanningContext(
        dig_j_per_kg=float(veh.dig_energy_j_per_kg),
        drive_j_per_m=float(veh.drive_power_w) / DRIVE_SPEED_MS,
        battery_j=_vehicle_battery_j(veh),
        drum_kg=float(veh.drum_capacity_kg),
        rover_mass_kg=float(veh.dry_mass_kg),
        drive_power_w=float(veh.drive_power_w))


def vehicle_footprint_radius_m(mission, *, localization_margin_m=LOCALIZATION_MARGIN_M):
    """P-06: the SWEPT footprint radius [m] of the mission's selected vehicle, used to inflate routing
    hazards so the rover is not modelled as a point. A skid-steer rover turns in place, so its swept
    obstacle radius is half the diagonal of the body bounding box (track gauge + wheel width laterally,
    wheelbase + wheel fore/aft extent longitudinally) PLUS a positional-uncertainty margin. Grounded in
    the registry geometry (gauge_m / wheelbase_m / wheel_width_m / wheel_radius_m); no fabricated size."""
    veh = V.get_vehicle(mission.vehicle)
    half_lat = (float(veh.gauge_m) + float(veh.wheel_width_m)) / 2.0
    half_lon = (float(veh.wheelbase_m) + 2.0 * float(veh.wheel_radius_m)) / 2.0
    return math.hypot(half_lat, half_lon) + float(localization_margin_m)

# Per-body OPERATING TIMESCALE (astronomical solar-day lengths; Earth-hours) — so the endurance/report
# prints the correct day/night + sunlit work-window scale for the selected body. solar_day_h = synodic
# (sun-to-sun) day; daylight_h ~= half; op_window_h = the usable high-sun window for solar power.
#   Moon: synodic day 29.53 Earth-days (708.7 h); ~9-11-day high-sun window (per project lead) = 216-264 h.
#   Mars: sol 24.66 h; Earth: 24 h; Ceres: 9.07 h rotation. op_window for non-Moon ~ the midday good-sun hours.
BODY_TIMESCALE = {
    "moon":  {"solar_day_h": 708.7, "daylight_h": 354.4, "op_window_h": (216.0, 264.0), "day_label": "lunar day"},
    "mars":  {"solar_day_h": 24.66, "daylight_h": 12.33, "op_window_h": (6.0, 8.0),     "day_label": "sol"},
    "earth": {"solar_day_h": 24.0,  "daylight_h": 12.0,  "op_window_h": (6.0, 8.0),     "day_label": "day"},
    "ceres": {"solar_day_h": 9.07,  "daylight_h": 4.54,  "op_window_h": (2.0, 3.0),     "day_label": "Ceres day"},
}


def body_timescale(body):
    """Operating timescale for `body` (per BODY_TIMESCALE); a generic ~24 h fallback for unlisted bodies."""
    return dict(BODY_TIMESCALE.get(body, {"solar_day_h": 24.0, "daylight_h": 12.0,
                                          "op_window_h": (6.0, 8.0), "day_label": "day"}), body=body)
# Sinter gate is C.SINTER_ENABLED (single source, in stewie.physics.constants); read live below.


def body_density(body):
    with open(os.path.join(__import__("stewie.server", fromlist=["__file__"]).__path__[0], "bodies.json")) as f:
        return float(json.load(f)[body]["bulk_density"])


def body_gravity(body):
    """Surface gravity [m/s^2] for the body (bodies.json, sysrev MEASURED). Used for haul lift energy."""
    with open(os.path.join(__import__("stewie.server", fromlist=["__file__"]).__path__[0], "bodies.json")) as f:
        return float(json.load(f)[body]["g"])


def _bodies():
    """Known body keys from bodies.json (the py-generated single source); excludes the _ipex block."""
    with open(os.path.join(__import__("stewie.server", fromlist=["__file__"]).__path__[0], "bodies.json")) as f:
        return {k for k in json.load(f) if not k.startswith("_")}


@dataclasses.dataclass
class BuildOrder:
    action: str
    kind: str               # "cut" | "fill" | "sinter"
    x: float; y: float
    footprint_m2: float
    depth_m: float          # cut depth / fill height / sinter depth
    note: str = ""
    def mass_kg(self, rho): return self.footprint_m2 * self.depth_m * rho


@dataclasses.dataclass
class Mission:
    name: str; body: str; orders: list
    charger: tuple = (0.0, 0.0); date: str = "2026-06-03"
    #: precedence as (before_action, after_action) pairs by order action-name (I9): the trip(s) touching
    #: `after` must be sequenced after the trip(s) touching `before` (e.g. grade road before hauling on it).
    precedence: list = dataclasses.field(default_factory=list)
    vehicle: str = "ipex"                              # the platform doing the work (vehicles.VEHICLES)
    tools: tuple = ()                                  # tools mounted on it (vehicles.TOOLS) -> extra capabilities
    soil: str = ""                                     # regolith model override (a body name); "" -> the body's own
    #: discrete keep-out obstacles (boulders / no-go zones) in the LOCAL order frame, as circles
    #: {x, y, r} in metres. Hauls route AROUND them (cells inside become impassable on the costmap) and a
    #: build placed inside one is rejected. Single-vehicle; complements the slope/crater hazard costmap (I10).
    keepouts: tuple = ()
    @property
    def density(self): return body_density(self.body)


def mission_soil_params(mission):
    """The TerramechanicsParams (soil/Bekker model) a mission's drive physics uses: its `soil` override
    (any body's regolith, e.g. Earth dry-sand on a lunar map) or the body's own when no override is set.
    Gravity stays the body's (see body_gravity) -- soil and gravity are independent (terramechanics.py)."""
    return params_for_body(mission.soil or mission.body)


_ORDER_KINDS = ("cut", "fill", "sinter", "goto")   # goto = S-3 path waypoint (zero mass, sequenced)
_ORDER_FIELDS = ("action", "kind", "x", "y", "footprint_m2", "depth_m")
#: order kind -> the vehicle capability it requires (vehicles.ACTIONS). The fleet (selected vehicle +
#: mounted tools) must have it or the order is refused -- e.g. sinter needs the separate sinter Tool.
KIND_CAPABILITY = {"cut": "excavate", "fill": "dump", "sinter": "sinter"}


def mission_from_dict(payload):
    """Build a Mission from a JSON-style dict (the browser's build-order queue: see index.html).

    Validates the body against bodies.json and every order's required fields + kind; raises ValueError
    on malformed input (NO silent defaults for the physics inputs). Sinter orders are accepted here but
    refused downstream in plan_and_simulate while the gate is off (see constants.SINTER_ENABLED)."""
    if not isinstance(payload, dict):
        raise ValueError("mission payload must be a JSON object")
    body = payload.get("body")
    if body not in _bodies():
        raise ValueError(f"unknown body {body!r}; known: {sorted(_bodies())}")
    # the fleet doing the work: a vehicle + mounted tools -> its capability set gates the order kinds.
    veh = str(payload.get("vehicle", V.DEFAULT_VEHICLE))
    tools = tuple(str(t) for t in (payload.get("tools") or ()))
    try:
        caps = V.capabilities_of(veh, tools=tools)
    except KeyError as e:
        raise ValueError(str(e))                       # unknown vehicle/tool -> 400, not 500
    soil = str(payload.get("soil") or "").strip()      # regolith model override (a body name); "" -> body's own
    if soil:
        try:
            _get_body(soil)                            # validate it is a known body (the soil source)
        except KeyError as e:
            raise ValueError(str(e))
        if _get_body(soil).name == _get_body(body).name:
            soil = ""                                  # same as the body -> no override stored
    raw = payload.get("orders")
    if not isinstance(raw, list) or not raw:
        raise ValueError("mission needs a non-empty 'orders' list")
    orders = []
    for i, o in enumerate(raw):
        if not isinstance(o, dict):
            raise ValueError(f"order {i} must be an object")
        # S-3: goto waypoints carry only a position -- no footprint/depth (zero-mass visits)
        req = ("action", "kind", "x", "y") if o.get("kind") == "goto" else _ORDER_FIELDS
        missing = [k for k in req if k not in o]
        if missing:
            raise ValueError(f"order {i} missing field(s): {missing}")
        if o["kind"] not in _ORDER_KINDS:
            raise ValueError(f"order {i} kind {o['kind']!r} not in {_ORDER_KINDS}")
        need = KIND_CAPABILITY.get(o["kind"])
        if need and need not in caps:                  # capability gate: does THIS fleet have the verb?
            if o["kind"] == "sinter":
                raise ValueError(
                    f"order {i}: sinter is GATED OFF -- no vehicle in the fleet carries a sinter tool "
                    f"({veh!r} is a drum excavator; sinter is a separate Tool to mount).")
            raise ValueError(
                f"order {i}: kind {o['kind']!r} needs the {need!r} capability, which the fleet "
                f"({veh!r} + tools {list(tools)}) lacks.")
        # RB-01: reject NaN/Inf coords and non-positive footprint/depth at this public boundary
        # (float() alone accepts float("nan"); a negative depth or zero area is physically meaningless).
        orders.append(BuildOrder(
            action=str(o["action"]), kind=str(o["kind"]),
            x=VAL.ensure_finite_scalar(o["x"], f"order {i} x"),
            y=VAL.ensure_finite_scalar(o["y"], f"order {i} y"),
            footprint_m2=(0.0 if o.get("kind") == "goto" else
                          VAL.ensure_positive_scalar(o["footprint_m2"], f"order {i} footprint_m2")),
            depth_m=(0.0 if o.get("kind") == "goto" else
                     VAL.ensure_positive_scalar(o["depth_m"], f"order {i} depth_m")),
            note=str(o.get("note", ""))))
    c = payload.get("charger", (0.0, 0.0))
    kwargs = dict(name=str(payload.get("name", "Build Mission")), body=body, orders=orders,
                  charger=(VAL.ensure_finite_scalar(c[0], "charger x"),
                           VAL.ensure_finite_scalar(c[1], "charger y")),
                  vehicle=veh, tools=tools, soil=soil)
    if "date" in payload:
        kwargs["date"] = str(payload["date"])
    # S-3: consecutive goto waypoints chain automatically -- a PATH is ordered by authorship
    gotos = [o.action for o in orders if o.kind == "goto"]
    auto_prec = [[a, b] for a, b in zip(gotos, gotos[1:])]
    prec = (payload.get("precedence") or []) + auto_prec if (payload.get("precedence") or auto_prec) else None
    prec = prec if prec else payload.get("precedence")     # I9: [[before_action, after_action], ...]
    if prec is not None:
        actions = {o.action for o in orders}
        pairs = []
        for p in prec:
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                raise ValueError(f"precedence entry {p!r} must be [before_action, after_action]")
            b, a = str(p[0]), str(p[1])
            if b not in actions or a not in actions:
                raise ValueError(f"precedence {b!r}->{a!r} references an unknown order action")
            pairs.append((b, a))
        kwargs["precedence"] = pairs
    kos = payload.get("keepouts")                          # discrete keep-out obstacles (circles, local m)
    if kos is not None:
        if not isinstance(kos, list):
            raise ValueError("'keepouts' must be a list of {x, y, r} circles")
        clean = []
        for j, k in enumerate(kos):
            if not isinstance(k, dict) or not all(f in k for f in ("x", "y", "r")):
                raise ValueError(f"keepout {j} must be an object with x, y, r")
            clean.append({"x": VAL.ensure_finite_scalar(k["x"], f"keepout {j} x"),
                          "y": VAL.ensure_finite_scalar(k["y"], f"keepout {j} y"),
                          "r": VAL.ensure_positive_scalar(k["r"], f"keepout {j} r")})
        kwargs["keepouts"] = tuple(clean)
    return Mission(**kwargs)


def _d(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])


# ---- cut-fill balance: route excavated material to fills, nearest-first ------------------------
# Bulking/swell (I7, planner side): a CUT excavates BANK (in-situ) material; a FILL places LOOSE spoil,
# which bulks. Mass is conserved: cut at rho_bank = bulk*SWELL, fill at rho_loose = bulk (bodies.json).
SWELL = C.RHO_DEEP / C.RHO_SPOIL


def _mincost_transport(supplies, demands, cost):
    """P-03: min-cost transportation over a bipartite cut->fill graph by successive-cheapest-augmenting
    (SSP). `supplies[i]` = cut i bank mass, `demands[j]` = fill j loose mass, `cost[i][j]` = the per-unit
    haul cost (math.inf = UNREACHABLE, no arc). Returns flow[i][j] (mass cut i -> fill j) minimizing total
    cost while never routing over an unreachable arc. Demand left unmet (no feasible reachable supply) is
    returned as `unmet[j]`; supply left over as `leftover[i]`. Globally min-cost over the FEASIBLE arcs --
    it never prefers a cheaper-but-blocked donor (inf cost) over a feasible one, the P-03 fix."""
    nI, nJ = len(supplies), len(demands)
    flow = [[0.0] * nJ for _ in range(nI)]
    sup = list(supplies)
    dem = list(demands)
    # candidate arcs by increasing cost; SSP for a transportation problem with no negative costs reduces
    # to repeatedly pushing as much as possible along the globally cheapest residual arc (a min-cost flow
    # is optimal when augmenting along shortest residual paths; with a single bipartite layer + nonneg
    # costs the shortest residual path is the single cheapest remaining direct arc).
    arcs = sorted(((cost[i][j], i, j) for i in range(nI) for j in range(nJ)
                   if math.isfinite(cost[i][j])), key=lambda a: a[0])
    for c, i, j in arcs:
        if sup[i] <= 1e-9 or dem[j] <= 1e-9:
            continue
        push = min(sup[i], dem[j])
        flow[i][j] += push
        sup[i] -= push
        dem[j] -= push
    unmet = [d if d > 1e-9 else 0.0 for d in dem]
    leftover = [s if s > 1e-9 else 0.0 for s in sup]
    return flow, unmet, leftover


def balance(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0):
    """Cut-fill material balance: route excavated regolith to fills, minimizing haul cost.

    P-03: with a DEM, allocation solves a min-cost TRANSPORTATION problem over a ROUTED, FEASIBILITY-aware
    cost matrix (route_leg gives routed distance; an unreachable cut->fill pair is an infinite-cost arc with
    NO flow), so the planner never assigns a Euclidean-nearest donor that is actually blocked while a
    feasible donor exists. Without a DEM there is no terrain to route over, so it falls back to the
    straight-line nearest-first allocation (byte-identical to the prior behavior)."""
    rho_bank, rho_loose = mission.density * SWELL, mission.density
    cuts = [(o, o.mass_kg(rho_bank)) for o in mission.orders if o.kind == "cut"]
    fills = [(o, o.mass_kg(rho_loose)) for o in mission.orders if o.kind == "fill"]

    if dem is not None and cuts and fills:
        # P-03: routed, feasibility-aware min-cost allocation.
        rd = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)   # memoized routed inter-site dist
        cost = [[rd((co.x, co.y), (fo.x, fo.y)) for fo, _ in fills] for co, _ in cuts]
        flowm, unmet, leftover = _mincost_transport([m for _, m in cuts], [m for _, m in fills], cost)
        flows = []
        for i, (co, _) in enumerate(cuts):
            for j, (fo, _) in enumerate(fills):
                m = flowm[i][j]
                if m > 1e-6:
                    flows.append((co, fo, m, _d((co.x, co.y), (fo.x, fo.y))))
        for j, (fo, _) in enumerate(fills):
            if unmet[j] > 1e-6:
                flows.append((None, fo, unmet[j], 0.0))          # deficit: imported material (flagged)
        for i, (co, _) in enumerate(cuts):
            if leftover[i] > 1e-6:
                flows.append((co, None, leftover[i], 0.0))       # surplus spoil
        surplus_kg = sum(m for c, f, m, _ in flows if c is not None and f is None)
        return flows, surplus_kg

    # no DEM (or no cut/fill pair): straight-line nearest-first allocation (unchanged).
    supply = {id(o): m for o, m in cuts}
    flows = []                                          # (cut, fill, mass, dist)
    for fo, need in fills:
        rem = need
        for co, _ in sorted(cuts, key=lambda cm: _d((cm[0].x, cm[0].y), (fo.x, fo.y))):
            if rem <= 1e-6: break
            avail = supply[id(co)]
            if avail <= 1e-6: continue
            take = min(rem, avail)
            flows.append((co, fo, take, _d((co.x, co.y), (fo.x, fo.y))))
            supply[id(co)] -= take; rem -= take
        if rem > 1e-6:
            flows.append((None, fo, rem, 0.0))          # deficit: imported material (flagged)
    for co, _ in cuts:                                  # un-routed cut mass: excavated spoil (dug, then piled)
        rem = supply[id(co)]
        if rem > 1e-6:
            flows.append((co, None, rem, 0.0))          # surplus: (cut, None) spoil flow, symmetric to import
    surplus_kg = sum(m for c, f, m, _ in flows if c is not None and f is None)
    return flows, surplus_kg


# ---- sequence + simulate (battery-aware, sinter, haul shuttles) --------------------------------
# ---- objectives: the metric the sequencer optimizes / the user sorts by ------------------------
# Each entry is (direction, totals -> scalar). "min" objectives are minimized, "max" maximized (the
# optimizer negates them). Every objective reads from the SIMULATED totals, so ANY algorithm can be
# scored against ANY objective -- overall duration/time, energy, average power, drive distance, recharge
# stops, or amount moved (constant for a full plan -> a sort key; the lever once plans are budgeted).
OBJECTIVES = {
    "time":     ("min", lambda T: T["time_s"]),
    "duration": ("min", lambda T: T["time_s"]),            # alias for "overall duration"
    "energy":   ("min", lambda T: T["energy_J"]),
    # P-10: this is AVERAGE power = total energy / duration, NOT peak/rated electrical demand. Minimizing
    # it can reward SLOWER execution (more time in the denominator), so it is named `average_power` to
    # stop users reading it as a peak-power constraint. `power` is kept as a legacy alias (the browser UI
    # still sends objective=power) and resolves to the same average-power metric.
    "average_power": ("min", lambda T: T["avg_power_w"]),  # average electrical power = energy / duration
    "power":    ("min", lambda T: T["avg_power_w"]),        # [LEGACY ALIAS of average_power -- UI compat]
    "distance": ("min", lambda T: T["distance_m"]),
    "charges":  ("min", lambda T: T["charges"]),
    "mass":     ("max", lambda T: T["mass_kg"]),            # amount moved
}
# P-10: the metric Held-Karp's exact DP actually minimizes (routed DRIVING DISTANCE). Any other objective
# is only HEURISTIC under held_karp (the LK polish improves it but gives no optimality bound), so the
# optimality label must be objective-specific -- "exact" only when the solved metric IS the objective.
HELD_KARP_EXACT_METRIC = "distance"
# Sequencer algorithms. nearest/greedy/two_opt/or_opt/lk are heuristics (objective-scored by simulation);
# brute + held_karp are EXACT (brute over permutations <=7; Held-Karp DP exact-on-driving-distance <=16);
# auto dispatches to the strongest solver the problem size + precedence allow ("solved in sequence").
SEQUENCERS = ("auto", "nearest", "greedy", "two_opt", "or_opt", "lk", "brute", "held_karp")
BRUTE_MAX_TRIPS = 7          # exhaustive permutation search only up to 7! = 5040
HELD_KARP_MAX_TRIPS = 16     # Held-Karp DP is O(2^n * n^2); ~16 trips is the practical ceiling


def _segmented_haul_energy(dem, dem_origin, waypoints, *, loads, drum_kg, g, soil, drive_j_per_m,
                           rover_mass_kg):
    """P-05: drive ENERGY of a shuttle haul, integrated SEGMENT-BY-SEGMENT along the routed polyline,
    separately for the LOADED outbound leg (cut->fill, carrying ~drum_kg) and the EMPTY return
    (fill->cut). Each segment pays seg_len * drive_j_per_m / (1 - slip), where slip is solved from THAT
    segment's grade and the rover's weight on that leg (loaded vs empty). A route that climbs a ridge and
    descends back to the same elevation therefore costs real per-segment grade work -- the prior code used
    only the endpoint slope abs(dh)/leg and read ~0 grade for such a roller-coaster. Returns the total
    round-trip haul energy [J] over all `loads` shuttle cycles."""
    Z, cell = dem
    ox, oy = dem_origin
    H, W = Z.shape

    def _z(x, y):
        c, r = int(round((ox + x) / cell)), int(round((oy + y) / cell))
        return float(Z[r, c]) if (0 <= r < H and 0 <= c < W) else None

    # sample elevation at each waypoint; drop off-grid points (keep order).
    pts = []
    for (x, y) in waypoints:
        z = _z(x, y)
        if z is not None:
            pts.append((x, y, z))
    if len(pts) < 2:
        return None                                   # not enough on-grid samples -> caller falls back

    def _dir_energy(seq, payload_kg):
        """Energy [J] for ONE traversal of the polyline `seq` carrying `payload_kg` (per-segment slip)."""
        e = 0.0
        for (x0, y0, z0), (x1, y1, z1) in zip(seq, seq[1:]):
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len <= 1e-9:
                continue
            slope_deg = math.degrees(math.atan2(abs(z1 - z0), seg_len))
            slip = slip_alpha_to_slip(slope_deg, payload_kg=payload_kg, g=g, params=soil,
                                      rover_mass_kg=rover_mass_kg)
            e += seg_len * drive_j_per_m / (1.0 - slip)
        return e

    out_e = _dir_energy(pts, drum_kg)                 # loaded outbound (cut -> fill)
    back_e = _dir_energy(list(reversed(pts)), 0.0)    # empty return (fill -> cut)
    return (out_e + back_e) * loads


def _build_trips(mission, dem, dem_origin, max_traverse_slope_deg):
    """Order-INDEPENDENT trip construction: cut->fill flows (I10-routed haul + exact gravity lift) and
    sinters. Returns (trips, flows, surplus_kg, meta). meta carries the routing summary; trips carry the
    per-trip dig/haul/lift energy so any visit order can be simulated/scored downstream."""
    rho = mission.density
    g = body_gravity(mission.body)                          # for haul lift energy (exact m*g*dh)
    _soil = mission_soil_params(mission)                    # soil model for the haul slip (soil override)
    ctx = plan_context(mission)                             # H-01: the SELECTED vehicle's energy/mass/drum
    drum_kg = ctx.drum_kg                                   # RB-05: the selected vehicle's per-cycle drum
    # P-03: routed, feasibility-aware allocation when a DEM is present (min-cost transport over the routed
    # cost matrix); straight-line nearest-first with no DEM (byte-identical to the prior behavior).
    flows, surplus_kg = balance(mission, dem=dem, dem_origin=dem_origin,
                                max_traverse_slope_deg=max_traverse_slope_deg)
    sinters = [o for o in mission.orders if o.kind == "sinter"]
    if sinters and not C.SINTER_ENABLED:
        raise RuntimeError(
            f"{len(sinters)} sinter order(s) present but sinter is GATED OFF for the IPEx baseline "
            "(drum excavator, no sinter tool; sinter energy ~14-20x the pack per kg). Enable a "
            "sinter-equipped variant via stewie.physics.constants.SINTER_ENABLED.")
    trips = []
    # S-3 path-first: goto waypoints become zero-mass VISIT trips; the auto-precedence chain
    # (mission_from_dict) keeps them in authored sequence through the sequencer.
    for o in mission.orders:
        if o.kind == "goto":
            trips.append(dict(kind="goto", site=(o.x, o.y), label=f"Waypoint: {o.action}",
                              mass=0.0, dig_e=0.0, dig_t=0.0, haul_m=0.0, haul_e=0.0,
                              lift_e=0.0, dest=(o.x, o.y), actions=frozenset({o.action})))
    straight_haul_m = 0.0; routed_haul_m = 0.0; blocked_legs = 0; leg_routes = []
    # P-04: per-kg offload (deposit) energy/time for imported fill -- drum-discharge handling at the
    # drive/handling power and the drum's deposit throughput, NOT the in-situ dig energy.
    offload_e_per_kg = ctx.drive_power_w / OFFLOAD_RATE_KG_S
    charger_xy = (float(mission.charger[0]), float(mission.charger[1]))
    for co, fo, mass, dist in flows:
        if co is None:
            # P-04: IMPORTED fill -- NO local excavation. dig_e/dig_t are ZERO (no in-situ cut). The only
            # local cost is depositing the delivered material (offload), tracked as offload_e/offload_t so
            # the import strategy is compared with the right physical process. import_kg is accounted
            # separately (deficit_kg) and never folded into the excavated cut_kg.
            # FEASIBILITY: an import must still be DELIVERED to the fill, which requires REACHING it. The
            # P-03 min-cost transport reclassifies an UNREACHABLE (enclosed) fill as unmet demand -> import;
            # without this delivery check that import silently masked an enclosed fill as feasible, so the
            # totals path disagreed with plan_ir (which catches it via the GoTo route). Route the delivery
            # from the base (charger): an unreachable fill is a blocked leg, exactly like a blocked cut->fill.
            if dem is not None:
                _il, _ib, reached_imp, _iw = route_leg(
                    dem, dem_origin, charger_xy, (fo.x, fo.y),
                    max_slope_deg=max_traverse_slope_deg, keepouts=mission.keepouts)
                if not reached_imp:
                    blocked_legs += 1                   # enclosed/stranded fill -> plan INFEASIBLE
                    leg_routes.append(dict(from_xy=charger_xy, to_xy=(fo.x, fo.y),
                                           waypoints=[], reached=False))
            trips.append(dict(kind="import", site=(fo.x, fo.y), label=f"Import fill: {fo.action}",
                              mass=mass, dig_e=0.0, dig_t=0.0,
                              offload_e=mass*offload_e_per_kg, offload_t=mass/OFFLOAD_RATE_KG_S,
                              haul_m=0.0, haul_e=0.0, lift_e=0.0, dest=(fo.x, fo.y),
                              actions=frozenset({fo.action})))
        elif fo is None:
            # surplus (un-routed) cut mass: it is still EXCAVATED -- the dominant dig cost (4151 J/kg) must
            # enter the plan. Dig in place; the spoil-disposal haul to a dump is a separate unmodeled term
            # (no spoil-site coordinate to fabricate one), so haul/lift = 0 here.
            trips.append(dict(kind="dig", site=(co.x, co.y), label=f"Excavate spoil: {co.action}",
                              mass=mass, dig_e=mass*ctx.dig_j_per_kg, dig_t=mass/DIG_RATE_KG_S,
                              haul_m=0.0, haul_e=0.0, lift_e=0.0, dest=(co.x, co.y),
                              actions=frozenset({co.action})))
        else:
            loads = max(1, math.ceil(mass / drum_kg))
            leg = base = dist                           # one-way cut<->fill distance (straight line)
            waypoints = [(co.x, co.y), (fo.x, fo.y)]; reached = True   # no-DEM: straight line, no hazard model
            if dem is not None:
                leg, base, reached, waypoints = route_leg(dem, dem_origin, (co.x, co.y), (fo.x, fo.y),
                                                          max_slope_deg=max_traverse_slope_deg,
                                                          keepouts=mission.keepouts)
                if not reached:
                    blocked_legs += 1                   # no safe corridor -> plan INFEASIBLE (item 2)
                    waypoints = []                      # do NOT fabricate a straight line through the hazard
            leg_routes.append(dict(from_xy=(co.x, co.y), to_xy=(fo.x, fo.y),
                                   waypoints=[list(p) for p in waypoints], reached=reached))
            straight_haul_m += base; routed_haul_m += leg
            haul_m = 2 * leg * loads                    # shuttle: cut<->fill, one round trip per drum load
            dh = haul_elevation_gain_m(dem, dem_origin, (co.x, co.y), (fo.x, fo.y))
            # H-06: lift energy is the CUMULATIVE positive ascent along the ROUTED polyline, not the net
            # endpoint gain -- a route that dips and climbs back still does gravity work on every climb. For
            # a straight/monotonic leg (incl. the no-DEM case) this equals max(0, dh), so behavior is unchanged.
            ascent = (haul_cumulative_ascent_m(dem, dem_origin, waypoints)
                      if (dem is not None and reached and len(waypoints) >= 2) else max(0.0, dh))
            # #1 slip-loss: the wheel travels 1/(1-slip) per metre of ground on a slope, so the haul costs
            # more than flat 135 J/m. P-05: integrate slip SEGMENT-BY-SEGMENT along the routed polyline,
            # separately for the loaded outbound and the empty return -- a route that climbs and descends
            # back to the same elevation still pays per-segment grade (the prior endpoint-slope estimate read
            # ~0 grade for such a roller-coaster). Fall back to the endpoint estimate only with no routed
            # polyline (no-DEM straight line / blocked leg).
            seg_e = None
            if dem is not None and reached and len(waypoints) >= 2:
                seg_e = _segmented_haul_energy(dem, dem_origin, waypoints, loads=loads, drum_kg=drum_kg,
                                               g=g, soil=_soil, drive_j_per_m=ctx.drive_j_per_m,
                                               rover_mass_kg=ctx.rover_mass_kg)
            if seg_e is not None:
                haul_e = seg_e
            else:
                # endpoint-slope fallback (no-DEM straight line, or too few on-grid samples).
                slope_haul = math.degrees(math.atan2(abs(dh), leg)) if leg > 1e-9 else 0.0
                out_m = back_m = leg * loads          # loaded out + empty back (haul_m = 2*leg*loads)
                slip_loaded = slip_alpha_to_slip(slope_haul, payload_kg=drum_kg, g=g, params=_soil,
                                                 rover_mass_kg=ctx.rover_mass_kg)
                slip_empty = slip_alpha_to_slip(slope_haul, payload_kg=0.0, g=g, params=_soil,
                                                rover_mass_kg=ctx.rover_mass_kg)
                haul_e = (out_m * ctx.drive_j_per_m / (1.0 - slip_loaded)
                          + back_m * ctx.drive_j_per_m / (1.0 - slip_empty))
            trips.append(dict(kind="cutfill", site=(co.x, co.y), label=f"{co.action} → {fo.action}",
                              mass=mass, dig_e=mass*ctx.dig_j_per_kg, dig_t=mass/DIG_RATE_KG_S,
                              haul_m=haul_m, haul_e=haul_e, lift_e=mass * g * ascent, dest=(fo.x, fo.y),
                              actions=frozenset({co.action, fo.action})))
    for o in sinters:
        m = o.mass_kg(rho)
        trips.append(dict(kind="sinter", site=(o.x, o.y), label=o.action, mass=m, lift_e=0.0,
                          sinter_e=m*SINTER_J_PER_KG, sinter_t=m*SINTER_J_PER_KG/SINTER_POWER_W,
                          dest=(o.x, o.y), actions=frozenset({o.action})))
    meta = dict(straight_haul_m=straight_haul_m, routed_haul_m=routed_haul_m, blocked_legs=blocked_legs,
                routed=dem is not None, traverse_cap_deg=float(max_traverse_slope_deg),
                routes=leg_routes, feasible=(blocked_legs == 0))   # item 1: route geometry; item 2: feasibility
    return trips, flows, surplus_kg, meta


def trip_precedence(trips, mission):
    """I9: lift the mission's order-level precedence (before_action -> after_action) to TRIP-index
    constraints (i, j): trip i must precede trip j. A trip 'touches' the actions of the orders it serves
    (a cut->fill trip touches both). Self-edges are dropped. Returns a list of (i, j)."""
    pairs = []
    for before, after in (mission.precedence or []):
        for i, ti in enumerate(trips):
            if before in ti["actions"]:
                for j, tj in enumerate(trips):
                    if i != j and after in tj["actions"]:
                        pairs.append((i, j))
    return sorted(set(pairs))


def _precedence_is_feasible(n, pairs):
    """AL2 guard: do the (i, j) 'trip i before trip j' constraints admit ANY valid ordering, or do they
    form a cycle (no build sequence can satisfy them)? Kahn topological sort over all n trips -- feasible
    iff every trip can be emitted. Returns True (acyclic / satisfiable) or False (cyclic / unsatisfiable)."""
    indeg = [0] * n
    succ = [[] for _ in range(n)]
    for i, j in pairs:
        succ[i].append(j)
        indeg[j] += 1
    queue = [k for k in range(n) if indeg[k] == 0]
    emitted = 0
    while queue:
        u = queue.pop()
        emitted += 1
        for v in succ[u]:
            indeg[v] -= 1
            if indeg[v] == 0:
                queue.append(v)
    return emitted == n


def _make_routes(mission, dem, dem_origin, max_traverse_slope_deg):
    """H-02: ONE memoized routed inter-site distance over the DEM. route_leg is called once per unique
    (unordered) leg and reused by every candidate order the optimizer scores, the timeline, and the report,
    so sequencing is optimized against the SAME geometry the executable Plan IR drives -- not straight
    lines. No DEM -> None (the simulator falls back to straight-line _d, byte-identical). An unreachable
    leg caches inf so the reserve-aware sim flags it infeasible, consistent with the routed Plan IR."""
    if dem is None:
        return None
    cache: dict = {}

    def rd(a, b):
        a = (round(float(a[0]), 6), round(float(a[1]), 6))
        b = (round(float(b[0]), 6), round(float(b[1]), 6))
        if a == b:
            return 0.0
        key = (a, b) if a <= b else (b, a)                  # symmetric (Dijkstra over an undirected costmap)
        if key not in cache:
            rm, _gs, reached, _wp = route_leg(dem, dem_origin, a, b,
                                              max_slope_deg=max_traverse_slope_deg, keepouts=mission.keepouts)
            cache[key] = rm if reached else math.inf
        return cache[key]
    return rd


def _simulate(mission, trips, routes=None):
    """Battery-aware simulation of an ORDERED trip list (phase-split recharging; intra-trip haul/lift baked
    into each trip). Pure in (mission, trips, routes) so the optimizer can score any candidate order. H-02:
    when `routes` (from _make_routes) is given the inter-site drive legs use the ROUTED DEM distance -- the
    same geometry the Plan IR executes -- instead of a straight line; None -> straight-line _d (no-DEM).
    Returns (tl, per_trip, core) -- core = the order-dependent metrics."""
    def _rd(a, b):
        return routes(a, b) if routes is not None else _d(a, b)   # H-02: routed inter-site distance
    # H-01: rebind the vehicle-dependent energy/speed names to the SELECTED vehicle's context as locals,
    # so every reference below (and in the nested _leg/charge/drive/spend closures) reads the vehicle's
    # values, not the IPEx module globals. ipex resolves to exactly the globals -> byte-identical.
    ctx = plan_context(mission)
    BATTERY_J = ctx.battery_j
    DRIVE_J_PER_M = ctx.drive_j_per_m
    DRIVE_SPEED_MS = ctx.drive_speed_ms
    CHARGE_W = ctx.charge_w
    RESERVE_FRAC = ctx.reserve_frac
    pos = list(mission.charger); batt = BATTERY_J; t = 0.0
    cum_mass = 0.0; cum_energy = 0.0; charges = 0; reserve = RESERVE_FRAC * BATTERY_J
    tl = []; per_trip = []; infeasible = []           # C-04: collected reachability / SoC-floor failures

    def _leg(to):
        """Raw drive leg: append the timeline + draw energy. The caller (drive/charge) has ensured the
        leg fits above reserve, so this never drives SoC below zero."""
        nonlocal pos, batt, t, cum_energy
        d = _rd(pos, to)                                   # H-02: routed inter-site distance (matches Plan IR)
        if d <= 1e-9: return
        e = d * DRIVE_J_PER_M; dur = d / DRIVE_SPEED_MS
        tl.append(dict(t0=t, t1=t+dur, kind="drive", batt0=batt, batt1=batt-e, mass=0.0, speed=DRIVE_SPEED_MS,
                       x0=pos[0], y0=pos[1], x1=to[0], y1=to[1]))   # P5: rover moves pos -> to
        pos = list(to); batt -= e; t += dur; cum_energy += e

    def charge():
        """Return to the charger and refill. C-04: guard the return leg -- the reserve EXISTS so the rover
        can always reach the charger, so the return leg may draw into reserve; it must only never go
        NEGATIVE. If even the full remaining charge can't reach the charger the rover is STRANDED; record
        it and return False (don't drive SoC negative, the caller stops drawing work it can never finish)."""
        nonlocal batt, t, charges
        if _d(pos, mission.charger) > 1e-9 and _rd(pos, mission.charger) * DRIVE_J_PER_M > batt + 1e-6:
            infeasible.append(f"stranded at ({pos[0]:.0f},{pos[1]:.0f}): cannot reach the charger to "
                              "recharge on the remaining charge")
            return False
        _leg(mission.charger); need = BATTERY_J - batt; dur = need / CHARGE_W
        tl.append(dict(t0=t, t1=t+dur, kind="charge", batt0=batt, batt1=BATTERY_J, mass=0.0, speed=0.0,
                       x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))  # parked at charger
        batt = BATTERY_J; t += dur; charges += 1
        return True

    def drive(to):
        """C-04: reserve-aware drive. Returns True when the rover actually reaches `to`, False when the
        leg is infeasible (and skipped + flagged). Driving to a WORK site keeps the reserve margin -- if
        the leg would dip SoC below reserve, recharge first (and if even a full charge can't reach it above
        reserve, the plan is infeasible). Driving HOME may draw into reserve (that is what reserve is for)
        but must never go NEGATIVE -- if the full remaining charge can't reach `to`, the rover is stranded.
        Either way the leg is skipped and flagged rather than run on negative SoC (a prior bug ran the pack
        to ~-14 MJ). P-01: the caller MUST check the return -- a failed transit means NO work happened at
        `to`, so the trip's dig/haul/fill is not credited (the prior bug ran spend() unconditionally)."""
        d = _rd(pos, to)                                  # H-02: routed inter-site distance (matches Plan IR)
        if d <= 1e-9: return True                         # already there (within tol): nothing to drive
        e = d * DRIVE_J_PER_M; usable = BATTERY_J - reserve
        going_home = _d(to, mission.charger) <= 1e-9
        if not going_home and e > batt - reserve:     # to a work site: keep the reserve margin -> recharge
            if _rd(mission.charger, to) * DRIVE_J_PER_M > usable:
                infeasible.append(f"leg to ({to[0]:.0f},{to[1]:.0f}) needs {e / 1e3:.0f} kJ; a full charge "
                                  f"reaches only {usable / 1e3:.0f} kJ above reserve")
                return False
            if not charge():                          # round-trip to the charger, then proceed from full
                return False                          # stranded (infeasible recorded); never drive SoC negative
        if e > batt + 1e-6:                           # can't physically reach `to` even on the full remaining
            infeasible.append(f"stranded at ({pos[0]:.0f},{pos[1]:.0f}): cannot reach ({to[0]:.0f},"
                              f"{to[1]:.0f}) on the remaining {batt / 1e3:.0f} kJ")
            return False
        _leg(to)
        return True

    def spend(kind, total_e, total_dur, work_pos, mass=0.0, speed=0.0, haul_m=0.0, haul_e=None, lift_e=0.0):
        # draw total_e at work_pos, splitting across recharges; haul_e is the haul drive ENERGY (#1
        # slip-adjusted; default flat 135 J/m), haul_m the haul distance (TIME); lift_e the uphill gravity work.
        nonlocal batt, t, cum_mass, cum_energy
        if haul_e is None:
            haul_e = haul_m * DRIVE_J_PER_M
        e = total_e + haul_e + lift_e
        dur = total_dur + (haul_m / DRIVE_SPEED_MS)
        spent = 0.0; completed = True
        while spent < e - 1e-6:
            usable = batt - reserve
            if usable <= 1e-3:
                if not charge():
                    completed = False; break          # C-04: stranded mid-work; stop (infeasible recorded)
                if not drive(work_pos):
                    completed = False; break          # P-01: can't return to the work site -> stop crediting
                continue
            chunk = min(e - spent, usable)
            cd = dur * (chunk / e) if e > 0 else 0.0
            tl.append(dict(t0=t, t1=t+cd, kind=kind, batt0=batt, batt1=batt-chunk,
                           mass=mass*(chunk/e) if e > 0 else 0.0, speed=speed,
                           x0=work_pos[0], y0=work_pos[1], x1=work_pos[0], y1=work_pos[1]))  # working at site
            batt -= chunk; t += cd; spent += chunk
        # P-01: credit only the COMPLETED work fraction. A normally-finished task credits its FULL mass/
        # energy (exact); a task the rover stranded mid-way through (broke out above) credits only the
        # fraction it actually performed -- crediting the full work would over-report what never finished.
        if completed:
            cum_mass += mass; cum_energy += e
        else:
            cum_mass += mass * (spent / e) if e > 1e-9 else 0.0
            cum_energy += spent

    for tr in trips:
        t0 = t
        # P-01: only credit a trip's work if the rover actually REACHED its site. A failed transit
        # (unreachable / stranded; recorded in `infeasible` by drive()) means no work was performed
        # there -- skip spend() entirely so no mass / energy / duration / dig entry is credited for a
        # site never visited (the prior bug ran spend() unconditionally after an infeasible drive).
        if drive(tr["site"]):
            if tr["kind"] == "sinter":
                spend("sinter", tr["sinter_e"], tr["sinter_t"], tr["site"], mass=0.0)
            elif tr["kind"] == "import":
                # P-04: imported fill spends only the OFFLOAD (deposit) energy/time -- NO local dig energy.
                spend("offload", tr.get("offload_e", 0.0), tr.get("offload_t", 0.0), tr["site"],
                      mass=tr["mass"], haul_m=tr.get("haul_m", 0.0), haul_e=tr.get("haul_e"),
                      lift_e=tr.get("lift_e", 0.0))
            else:
                spend("dig", tr["dig_e"], tr["dig_t"], tr["site"], mass=tr["mass"],
                      haul_m=tr.get("haul_m", 0.0), haul_e=tr.get("haul_e"), lift_e=tr.get("lift_e", 0.0))
        per_trip.append(dict(trip=tr, t_start=t0, t_end=t))
    drive(mission.charger)
    # distance_m = inter-site drive legs (timeline speed*dt) + the intra-trip haul shuttle (cut<->fill, baked
    # into each trip as haul_m but NOT a timeline drive leg). Omitting haul_m under-reported total driving
    # ~9x and made the `distance` objective optimize a quantity missing its largest term.
    drive_m = sum((p["t1"]-p["t0"])*p["speed"] for p in tl)
    haul_m = sum(tr.get("haul_m", 0.0) for tr in trips)
    distance_m = drive_m + haul_m
    core = dict(time_s=t, mass_kg=cum_mass, energy_J=cum_energy, charges=charges, distance_m=distance_m,
                avg_power_w=(cum_energy / t if t > 1e-9 else 0.0),
                feasible=(not infeasible), infeasible_reasons=list(infeasible))   # C-04
    return tl, per_trip, core


def _score(core, objective):
    """(sortable, raw) for a SINGLE objective: sortable is always MINIMIZED (max objectives negated)."""
    direction, fn = OBJECTIVES[objective]
    raw = fn(core)
    return (raw if direction == "min" else -raw), raw


def parse_objective(objective):
    """Normalize an objective spec to a weight dict. Accepts a single name ('time'), a dict
    ({'time': 0.6, 'energy': 0.4}), or a 'name:w,name:w' string. A single name -> {name: 1.0}. Every
    component must be a known objective. Weights are renormalized to sum to 1.

    P-08: the weight DOMAIN is validated, not just the names. A multi-objective spec is a convex
    combination, so every weight must be a FINITE, NON-NEGATIVE real number and the weights must sum to
    a STRICTLY POSITIVE finite total; NaN/Inf/negative weights, a zero (or non-positive) sum, duplicate
    components, and malformed (non-numeric) weight strings are all rejected with ValueError."""
    if isinstance(objective, str) and objective in OBJECTIVES:
        return {objective: 1.0}
    if isinstance(objective, str):                          # "time:0.6,energy:0.4"
        spec = {}
        for part in objective.split(","):
            name, _, w = part.partition(":")
            name = name.strip()
            if name in spec:                                # P-08: a repeated component is ambiguous
                raise ValueError(f"duplicate objective component {name!r} in {objective!r}")
            try:
                spec[name] = float(w) if w.strip() else 1.0   # P-08: a non-numeric weight (e.g. 'time:time')
            except ValueError:
                raise ValueError(f"malformed objective weight {w.strip()!r} for {name!r} in {objective!r}")
        objective = spec
    if not isinstance(objective, dict) or not objective:
        raise ValueError(f"unparseable objective {objective!r}")
    for k, v in objective.items():
        if k not in OBJECTIVES:
            raise ValueError(f"unknown objective {k!r}; known: {sorted(OBJECTIVES)}")
        fv = float(v)
        if not math.isfinite(fv) or fv < 0.0:               # P-08: weights are finite and non-negative
            raise ValueError(f"objective weight for {k!r} must be finite and >= 0 (got {v!r})")
    tot = sum(float(v) for v in objective.values())
    if not (math.isfinite(tot) and tot > 0.0):              # P-08: a convex combination needs a positive sum
        raise ValueError(f"objective weights must sum to a finite positive value (got {tot!r})")
    return {k: float(v) / tot for k, v in objective.items()}


def _objective_is_only(objective, metric):
    """True iff `objective` (single name / 'name:w,...' string / weight dict) is EXACTLY the one `metric`
    (a single-objective spec on that metric), accounting for aliases (time/duration, power/average_power)."""
    aliases = {"time": {"time", "duration"}, "duration": {"time", "duration"},
               "average_power": {"average_power", "power"}, "power": {"average_power", "power"}}
    target = aliases.get(metric, {metric})
    try:
        weights = parse_objective(objective)
    except ValueError:
        return False
    return len(weights) == 1 and next(iter(weights)) in target


def _objective_optimality(resolved, objective):
    """P-10: objective-SPECIFIC optimality label + an `objective_exact` flag.

    - brute simulates every permutation -> EXACT on whatever objective was chosen (objective_exact=True).
    - held_karp / held_karp_lk are exact only on routed DRIVING DISTANCE (then LK-polished). The label
      NAMES the exact metric ("distance-exact (heuristic for this objective)+polish"), and the result is
      objective_exact ONLY when the chosen objective IS distance.
    - everything else is heuristic.

    Returns (label, objective_exact)."""
    if resolved == "brute":
        return "exact", True
    if resolved in ("held_karp", "held_karp_lk"):
        is_distance = _objective_is_only(objective, HELD_KARP_EXACT_METRIC)
        if is_distance:
            return ("distance-exact" if resolved == "held_karp" else "distance-exact+polish"), True
        # exact on distance only -> name the metric and flag the chosen objective as NOT exact.
        return f"distance-exact (heuristic for this objective){'+polish' if resolved == 'held_karp_lk' else ''}", False
    return "heuristic", False


def _make_core_scorer(mission, trips, objective, routes=None):
    """Return a function core -> sortable scalar (lower = better). For a single objective this is the raw
    metric (max objectives negated). For a WEIGHTED multi-objective it is the weighted sum of each metric
    normalized by a reference plan (the nearest-neighbour order), so differently-scaled metrics combine.
    H-02: `routes` is threaded into the reference simulation so the normalization uses routed geometry too."""
    weights = parse_objective(objective)
    if len(weights) == 1:
        (name,) = weights
        return lambda core: _score(core, name)[0]
    ref = _simulate(mission, [trips[i] for i in _nn_order(trips, mission)], routes)[2]   # reference scales

    def scorer(core):
        s = 0.0
        for name, w in weights.items():
            direction, fn = OBJECTIVES[name]
            raw, r = fn(core), fn(ref)
            # P-09: stable normalization that handles a ZERO or constant reference. The reference comes
            # from a FIXED plan (nearest-neighbour), so scoring is candidate-set independent; floor the
            # denominator with a tiny positive scale so a zero reference (e.g. zero recharges/distance)
            # cannot divide by zero or produce NaN/Inf. When BOTH raw and reference are ~0 the metric is
            # degenerate (no signal) -> a constant unit contribution, so it never inverts the ranking by
            # the other objectives.
            if direction == "min":
                norm = 1.0 if (abs(raw) <= 1e-9 and abs(r) <= 1e-9) else raw / max(r, 1e-9)
            else:
                norm = 1.0 if (abs(raw) <= 1e-9 and abs(r) <= 1e-9) else max(r, 0.0) / max(raw, 1e-9)
            s += w * norm
        return s
    return scorer


def _nn_order(trips, mission, *, eligible_fn=None):
    """Nearest-neighbour order from the charger; if eligible_fn is given, only choose currently-eligible
    trips (precedence-aware)."""
    n = len(trips); seq = []; unv = list(range(n)); cur = mission.charger
    while unv:
        cands = [i for i in unv if eligible_fn(i, seq)] if eligible_fn else unv
        k = min(cands, key=lambda i: _d(cur, trips[i]["site"])); seq.append(k); unv.remove(k)
        cur = trips[k]["site"]
    return seq


def _prec_masks(n, precedence):
    """Per-trip predecessor bitmask: pred[j] has bit i set iff trip i must precede trip j."""
    pred = [0] * n
    for i, j in (precedence or []):
        pred[j] |= (1 << i)
    return pred


def _respects(order, pred):
    """True iff `order` honors every precedence constraint (each trip after all its predecessors)."""
    seen = 0
    for j in order:
        if pred[j] & ~seen:                                # a predecessor of j not yet visited
            return False
        seen |= (1 << j)
    return True


def _held_karp(trips, mission, pred, routes=None):
    """Exact min-DRIVING-DISTANCE Hamiltonian tour (charger -> all sites -> charger) by Held-Karp DP,
    honoring precedence (a Sequential Ordering Problem). O(2^n * n^2). Returns the trip order; the planner
    then simulates it for the chosen objective's true battery-aware totals (distance is the exact lever;
    it is a near-perfect proxy for time/energy here because dig energy dominates and is order-independent).
    H-02: the seed distance matrix uses the ROUTED inter-site distance (`routes`, the shared _make_routes
    cache) so the exact tour is min-ROUTED-distance -- the geometry the plan actually drives -- not min
    straight-line. No DEM (routes=None) -> straight-line _d, byte-identical; the cache is already built."""
    n = len(trips)
    pts = [tuple(mission.charger)] + [tuple(t["site"]) for t in trips]
    _md = (lambda a, b: routes(a, b)) if routes is not None else _d
    dmat = [[_md(pts[a], pts[b]) for b in range(n + 1)] for a in range(n + 1)]
    full = (1 << n) - 1
    dp = [[math.inf] * n for _ in range(1 << n)]
    par = [[-1] * n for _ in range(1 << n)]
    for j in range(n):
        if pred[j] == 0:                                   # may go first only if it has no predecessors
            dp[1 << j][j] = dmat[0][j + 1]
    for mask in range(1 << n):
        for j in range(n):
            base = dp[mask][j]
            if base == math.inf:
                continue
            for k in range(n):
                if mask & (1 << k):
                    continue
                if pred[k] & ~mask:                        # k's predecessors not all in `mask`
                    continue
                nm = mask | (1 << k); nd = base + dmat[j + 1][k + 1]
                if nd < dp[nm][k]:
                    dp[nm][k] = nd; par[nm][k] = j
    best, endj = math.inf, -1
    for j in range(n):
        v = dp[full][j] + dmat[j + 1][0]
        if v < best:
            best, endj = v, j
    if endj == -1:                                         # no complete tour honors the precedence DAG
        raise ValueError("precedence is infeasible (cyclic / unsatisfiable): no valid trip ordering exists")
    order = []; mask, j = full, endj
    while j != -1:
        order.append(j); pj = par[mask][j]; mask ^= (1 << j); j = pj
    order.reverse()
    return order


def optimize_sequence(trips, mission, *, algorithm="auto", objective="time", precedence=None, routes=None):
    """Return a visit order (trip indices) chosen by `algorithm` to optimize `objective` (a name, a
    'name:w,...' string, or a weight dict), honoring `precedence` (list of (i, j): trip i before trip j).

      auto       -- dispatch to the strongest solver the size + precedence allow (brute<=7, held_karp<=16,
                    else lk); precedence routes to the SOP-aware variants.
      nearest    -- distance nearest-neighbour from the charger (no simulation; fast; objective-agnostic).
      greedy     -- append the eligible trip minimizing the objective of the prefix-so-far (sim-scored).
      two_opt    -- nearest seed + 2-opt segment reversals improving the objective (precedence-valid only).
      or_opt     -- nearest seed + Or-opt relocations of 1-3 consecutive trips (precedence-valid only).
      lk         -- 2-opt + Or-opt to convergence (a Lin-Kernighan-STYLE composite, not full variable-depth LK).
      brute      -- exhaustive over (precedence-valid) permutations, <= BRUTE_MAX_TRIPS. Optimal.
      held_karp  -- exact min-driving-distance DP (SOP-aware), <= HELD_KARP_MAX_TRIPS, then simulated."""
    parse_objective(objective)                             # validates the objective spec (raises if bad)
    n = len(trips)
    if n <= 1:
        return list(range(n))
    pred = _prec_masks(n, precedence)
    has_prec = any(pred)

    def eligible(i, placed):
        seen = 0
        for p in placed:
            seen |= (1 << p)
        return (pred[i] & ~seen) == 0

    score_core = _make_core_scorer(mission, trips, objective, routes)

    def score(order):
        return score_core(_simulate(mission, [trips[i] for i in order], routes)[2])   # H-02: routed scoring

    if algorithm == "auto":
        if n <= BRUTE_MAX_TRIPS:
            return optimize_sequence(trips, mission, algorithm="brute", objective=objective,
                                     precedence=precedence, routes=routes)
        # 8..16: exact driving tour (Held-Karp) as a strong SEED, then LK-polish on the REAL (recharge-
        # coupled) objective -- "solved in sequence". >16: LK from the nearest seed.
        algorithm = "held_karp_lk" if n <= HELD_KARP_MAX_TRIPS else "lk"

    if algorithm == "nearest":
        return _nn_order(trips, mission, eligible_fn=eligible if has_prec else None)

    if algorithm == "held_karp" and n <= HELD_KARP_MAX_TRIPS:
        return _held_karp(trips, mission, pred, routes)    # PURE exact driving tour (no real-objective polish)

    if algorithm == "greedy":
        order = []; unv = list(range(n))
        while unv:
            cands = [i for i in unv if eligible(i, order)] if has_prec else unv
            nxt = min(cands, key=lambda i: score(order + [i]))
            order.append(nxt); unv.remove(nxt)
        return order

    if algorithm == "brute" and n <= BRUTE_MAX_TRIPS:
        perms = (p for p in itertools.permutations(range(n)) if not has_prec or _respects(p, pred))
        return list(min(perms, key=score))

    # ---- local-search family (2-opt / Or-opt / LK-style), precedence-valid moves only ----
    def two_opt_moves(o):
        for i in range(n - 1):
            for j in range(i + 1, n):
                yield o[:i] + o[i:j + 1][::-1] + o[j + 1:]

    def or_opt_moves(o):                                   # relocate a run of 1-3 consecutive trips
        for seg in (1, 2, 3):
            for i in range(n - seg + 1):
                chunk = o[i:i + seg]; rest = o[:i] + o[i + seg:]
                for k in range(len(rest) + 1):
                    if k != i:
                        yield rest[:k] + chunk + rest[k:]

    def local_search(seed, use_two_opt=True, use_or_opt=True):
        order = list(seed); best = score(order); gens = []
        if use_two_opt: gens.append(two_opt_moves)
        if use_or_opt: gens.append(or_opt_moves)
        improving = True
        while improving:
            improving = False
            for gen in gens:
                for cand in gen(order):
                    if has_prec and not _respects(cand, pred):
                        continue
                    s = score(cand)
                    if s < best - 1e-9:
                        order, best, improving = list(cand), s, True
        return order

    nn_seed = _nn_order(trips, mission, eligible_fn=eligible if has_prec else None)
    if algorithm == "two_opt":
        return local_search(nn_seed, use_or_opt=False)
    if algorithm == "or_opt":
        return local_search(nn_seed, use_two_opt=False)
    if algorithm == "held_karp_lk":                        # auto's 8-16 path: HK seed + LK polish
        return local_search(_held_karp(trips, mission, pred, routes))
    if algorithm in ("lk", "brute", "held_karp"):          # lk; also the >cap fallback for brute/held_karp
        return local_search(nn_seed)
    raise ValueError(f"unknown algorithm {algorithm!r}; known: {SEQUENCERS}")


# ---- sequence + simulate (battery-aware, sinter, haul shuttles) --------------------------------
def _mission_totals(mission, trips, flows, surplus_kg, meta, core):
    """The mission / material / routing / keep-out totals shared by the single- and multi-vehicle planners.
    `core` carries the simulated time/energy/distance/charges/mass; the caller applies survival + algorithm
    + vehicle fields. Kept DRY so the multi-vehicle aggregate reports the same fields as single-vehicle."""
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
        drum_cycles=sum(max(1, math.ceil(tr["mass"] / _drum_kg(mission))) for tr in trips if tr["kind"] == "cutfill"),
        # T2.3 (BDS p.7): cut depth per pass <= 50% of the scoop opening -- a deep cut is MULTIPLE
        # passes over the footprint; report the binding pass count (the 42 kg/hr demo dig rate is a
        # steady-state figure that already embodies multi-pass operation, so duration stays rate-based).
        cut_passes=max([1] + [math.ceil(float(o.depth_m) / S.max_cut_per_pass_m())
                              for o in mission.orders if getattr(o, "kind", "") == "cut"]),
        # T2.4: the drum-rate sensitivity band -- dig energy at rated-18 vs max-25 RPM
        dig_energy_bounds_MJ=tuple(round(b * sum(tr["mass"] for tr in trips if tr["kind"] != "goto")
                                          / 1e6, 1) for b in S.dig_energy_bounds_j_per_kg()),
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
                              if (o.x - k["x"]) ** 2 + (o.y - k["y"]) ** 2 <= k["r"] ** 2))


def _trip_work_e(tr):
    """A trip's work energy (dig + sinter + haul) -- the load used to balance the fleet allocation."""
    return tr.get("dig_e", 0.0) + tr.get("sinter_e", 0.0) + tr.get("haul_e", 0.0)


def _allocate_trips(trips, vehicles):
    """MV2: SITE-EXCLUSIVE, load-balanced (LPT) allocation of trips to V vehicles. Trips are grouped by
    site so no two vehicles ever work the SAME site (zero co-occupation by construction); whole site-groups
    are then assigned greedily to the least-loaded vehicle by work energy (longest-processing-time first).
    Returns a list of V index-lists (some may be empty if V exceeds the number of sites)."""
    groups: dict = {}
    for idx, tr in enumerate(trips):
        groups.setdefault(tuple(tr["site"]), []).append(idx)

    def gcost(idxs):
        return sum(_trip_work_e(trips[i]) for i in idxs)

    loads = [0.0] * vehicles
    alloc: list = [[] for _ in range(vehicles)]
    for idxs in sorted(groups.values(), key=gcost, reverse=True):   # biggest site-group first (LPT)
        v = min(range(vehicles), key=lambda k: loads[k])
        alloc[v].extend(idxs)
        loads[v] += gcost(idxs)
    return alloc


def _allocate_components(trips, vehicles, precedence):
    """MV cross-precedence allocation: like _allocate_trips, but the allocation UNIT also keeps
    precedence-connected work together. Union trips that share a SITE (site-exclusivity, as before) OR a
    precedence edge (so a whole precedence chain lands on ONE vehicle and the per-vehicle sequencer can
    honor its order); then LPT-assign whole units to the least-loaded vehicle by work energy. INDEPENDENT
    chains parallelize across the fleet; SPLITTING a single chain across vehicles with cross-vehicle
    wait-coordination is future MV work (documented in plan_multi). Returns a list of V index-lists."""
    n = len(trips)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    site_first: dict = {}
    for idx, tr in enumerate(trips):
        s = tuple(tr["site"])
        if s in site_first:
            union(site_first[s], idx)         # same site -> same vehicle (site-exclusivity preserved)
        else:
            site_first[s] = idx
    for i, j in (precedence or []):
        union(i, j)                           # precedence-connected -> same vehicle (intra-vehicle ordering)

    units: dict = {}
    for k in range(n):
        units.setdefault(find(k), []).append(k)

    def ucost(idxs):
        return sum(_trip_work_e(trips[i]) for i in idxs)

    loads = [0.0] * vehicles
    alloc: list = [[] for _ in range(vehicles)]
    for idxs in sorted(units.values(), key=ucost, reverse=True):    # biggest unit first (LPT)
        v = min(range(vehicles), key=lambda k: loads[k])
        alloc[v].extend(idxs)
        loads[v] += ucost(idxs)
    return alloc


def _vehicle_conflicts(per_vehicle):
    """MV5: count space-time conflicts -- two DIFFERENT vehicles whose per-trip time windows overlap at the
    SAME site. Site-exclusive allocation makes this 0 by construction; the detector verifies it (and would
    catch a future allocation that lets vehicles share a site). Continuous haul-PATH crossing avoidance is
    not modelled here (future MV work) -- this is site-level deconfliction."""
    spans = [(v, tuple(pt["trip"]["site"]), pt["t_start"], pt["t_end"])
             for v, pv in enumerate(per_vehicle) for pt in pv["per_trip"]]
    conflicts = 0
    for a in range(len(spans)):
        va, sa, s0, s1 = spans[a]
        for b in range(a + 1, len(spans)):
            vb, sb, t0, t1 = spans[b]
            if va != vb and sa == sb and s0 < t1 and t0 < s1:     # same site, overlapping windows
                conflicts += 1
    return conflicts


def _charger_conflicts(per_vehicle, mission):
    """P-06: count SHARED-CHARGER conflicts -- two DIFFERENT vehicles whose recharge (kind='charge')
    timeline windows overlap at the single shared charger. v1 plans each vehicle independently from the
    same charger, so a real fleet would queue at one charger; this detector SURFACES the contention the
    v1 schedule ignores (the audit's 'omits shared-resource constraints'). Each overlapping pair of charge
    windows is one conflict. Returns the integer count (0 when no two vehicles charge at the same time)."""
    charges = [(v, seg["t0"], seg["t1"])
               for v, pv in enumerate(per_vehicle)
               for seg in pv.get("tl", []) if seg.get("kind") == "charge"]
    conflicts = 0
    for a in range(len(charges)):
        va, a0, a1 = charges[a]
        for b in range(a + 1, len(charges)):
            vb, b0, b1 = charges[b]
            if va != vb and a0 < b1 and b0 < a1:                  # different vehicles, overlapping charge windows
                conflicts += 1
    return conflicts


def plan_multi(mission: Mission, *, dem=None, dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0,
               algorithm="nearest", objective="time", vehicles=2):
    """MV1-7: plan a multi-vehicle build mission. Build trips once, allocate them site-exclusively across V
    vehicles (load-balanced), sequence + battery-simulate EACH vehicle independently (they work in parallel
    from the shared charger), and aggregate: makespan = max per-vehicle time (the wall-clock the fleet
    finishes in), energy/distance/charges = fleet sums. Returns the same (trips, flows, per_trip, tl, totals)
    shape as the single-vehicle planner, with per-trip `vehicle` tags + a vehicles_detail breakdown.

    v1 scope + honest gaps: site-exclusive allocation guarantees no two rovers co-occupy a site (verified by
    a space-time conflict detector); the SHARED CHARGER is not contention-modelled (each vehicle recharges
    independently -- a stated simplification); continuous haul-PATH collision avoidance is future MV work.
    Cross-vehicle PRECEDENCE (v2): a precedence chain is kept WHOLE on one vehicle so its order is honored,
    and INDEPENDENT chains parallelize; SPLITTING one chain across vehicles with cross-vehicle wait-
    coordination is still future work. A cyclic precedence still raises (never silently mis-ordered)."""
    if vehicles < 1:
        raise ValueError(f"vehicles must be >= 1 (got {vehicles})")
    trips, flows, surplus_kg, meta = _build_trips(mission, dem, dem_origin, max_traverse_slope_deg)
    routes = _make_routes(mission, dem, dem_origin, max_traverse_slope_deg)   # H-02: route inter-site legs ONCE (shared)
    glob_prec = trip_precedence(trips, mission)            # MV cross-precedence: trip-index constraints
    if glob_prec and not _precedence_is_feasible(len(trips), glob_prec):
        raise ValueError("precedence is infeasible (cyclic / unsatisfiable): no valid build ordering exists")
    # precedence present -> keep each chain whole on one vehicle (site- + chain-exclusive); else site-only.
    alloc = _allocate_components(trips, vehicles, glob_prec) if glob_prec else _allocate_trips(trips, vehicles)
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
    makespan = max((pv["core"]["time_s"] for pv in per_vehicle), default=0.0)
    agg = dict(
        time_s=float(makespan),
        mass_kg=sum(pv["core"]["mass_kg"] for pv in per_vehicle),
        energy_J=sum(pv["core"]["energy_J"] for pv in per_vehicle),
        charges=sum(pv["core"]["charges"] for pv in per_vehicle),
        distance_m=sum(pv["core"]["distance_m"] for pv in per_vehicle),
        avg_power_w=0.0)
    agg["avg_power_w"] = agg["energy_J"] / makespan if makespan > 1e-9 else 0.0
    survival_J = IDLE_POWER_W * sum(pv["core"]["time_s"] for pv in per_vehicle)   # idle per vehicle * its time
    all_trips = [tr for pv in per_vehicle for tr in pv["trips"]]
    all_per_trip = [pt for pv in per_vehicle for pt in pv["per_trip"]]
    all_tl = [seg for pv in per_vehicle for seg in pv["tl"]]
    totals = _mission_totals(mission, all_trips, flows, surplus_kg, meta, agg)
    if survival_J > 0.0:
        totals["energy_J"] = agg["energy_J"] + survival_J
        totals["avg_power_w"] = totals["energy_J"] / makespan if makespan > 1e-9 else 0.0
    detail = [{"vehicle": pv["vehicle"], "n_trips": len(pv["trips"]), "time_s": pv["core"]["time_s"],
               "energy_J": pv["core"]["energy_J"], "distance_m": pv["core"]["distance_m"],
               "charges": pv["core"]["charges"]} for pv in per_vehicle]
    totals.update(survival_energy_J=float(survival_J), idle_power_w=float(IDLE_POWER_W),
                  algorithm=algorithm, resolved_algorithm=algorithm, optimality="heuristic",
                  objective_exact=False, solved_metric="none",   # P-10: per-vehicle heuristic sequencing
                  n_precedence=len(glob_prec), objective=str(objective), vehicles=int(vehicles),
                  makespan_s=float(makespan), vehicle_conflicts=int(conflicts), vehicles_detail=detail,
                  charger_conflicts=int(_charger_conflicts(per_vehicle, mission)))
    return all_trips, flows, all_per_trip, all_tl, totals


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
    return trips, flows, per_trip, tl, totals



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


def _plan_provenance(mission, *, algorithm, objective, vehicles, dem_origin):
    """CT-07: provenance for a PlanResult -- schema version, mode, the planning config, and a DETERMINISTIC
    content hash of the mission + origin + config, so a result is tied to exactly the inputs that made it."""
    canon = json.dumps({
        "mission": dataclasses.asdict(mission), "dem_origin": list(dem_origin),
        "algorithm": str(algorithm), "objective": str(objective), "vehicles": int(vehicles),
    }, sort_keys=True, default=str)
    return {
        "schema_version": PLAN_RESULT_VERSION, "mode": "PLAN",
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
    validation = validate_plan(mission, dem=dem, dem_origin=dem_origin) if with_acceptance else None
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
    _haworth_bundle, dem_georef_corners, dem_grid_info, flattest_anchor,
    flattest_anchor_streamed, latlon_to_dem_origin, load_haworth_dem, load_site_dem,
    read_dem_window, slope_deg_map,
)
# ---- I10 routing moved to lode.planner_routing (ARCH-2 god-module split); re-exported so
# MP.route_leg / MP.slope_costmap / ... and the solver's internal calls are unchanged.
from lode.planner_routing import (  # noqa: F401
    _ROUTE_NB, MAX_DROP_M, _apply_keepouts, haul_cumulative_ascent_m, haul_elevation_gain_m,
    negative_obstacle_mask, route_least_cost, routed_distance, slope_costmap,
)
from lode.planner_routing import route_leg as _route_leg_point   # P-06: the point-rover router (no inflation)


def _erode_passable(passable, cell_m, radius_m):
    """P-06: erode the passable mask by the rover's swept footprint -- a cell is passable for a finite-size
    rover only if EVERY cell within `radius_m` of it is passable (so the body never clips a hazard). This is
    a binary erosion by a disk of radius_m, the standard configuration-space inflation of obstacles by the
    robot radius. Returns the eroded boolean mask."""
    if radius_m is None or radius_m <= 0:
        return passable
    from scipy.ndimage import minimum_filter
    rad_cells = int(math.ceil(float(radius_m) / float(cell_m)))
    if rad_cells <= 0:
        return passable
    n = 2 * rad_cells + 1
    yy, xx = np.ogrid[-rad_cells:rad_cells + 1, -rad_cells:rad_cells + 1]
    disk = (yy * yy + xx * xx) <= (radius_m / cell_m) ** 2     # circular structuring element
    # minimum_filter over the disk: a cell stays True only if all True within the disk (erosion).
    return minimum_filter(passable.astype(np.uint8), footprint=disk, mode="constant", cval=0).astype(bool) \
        if n > 1 else passable


def route_leg(dem, dem_origin, a_xy, b_xy, *, max_slope_deg=25.0, slip_alpha=2.0, margin_m=20.0,
              keepouts=(), footprint_radius_m=0.0):
    """P-06: terrain-aware route between two LOCAL sites, with the rover treated as a FINITE-SIZE body.

    When `footprint_radius_m` > 0 the impassable hazards (slope cap, drop-offs, keep-outs) are inflated by
    the rover's swept radius -- a corridor narrower than the rover is impassable even though a point rover
    could thread it (the audit's 'routing treats the vehicle as a point' defect). `footprint_radius_m=0`
    reproduces the point-rover route_leg exactly (byte-identical). Returns (routed_m, grid_straight_m,
    reached, waypoints) with the same contract as the point router. The endpoints themselves are not
    eroded (a site placed on a valid pad is reachable even if its immediate cell touches the inflation)."""
    if not footprint_radius_m or footprint_radius_m <= 0:
        return _route_leg_point(dem, dem_origin, a_xy, b_xy, max_slope_deg=max_slope_deg,
                                slip_alpha=slip_alpha, margin_m=margin_m, keepouts=keepouts)
    Z, cell = dem
    ox, oy = dem_origin
    ax, ay = ox + a_xy[0], oy + a_xy[1]
    bx, by = ox + b_xy[0], oy + b_xy[1]
    H, W = Z.shape
    straight = math.hypot(bx - ax, by - ay)
    m = float(margin_m)
    while True:
        c0 = max(0, int((min(ax, bx) - m) / cell))
        c1 = min(W, int((max(ax, bx) + m) / cell) + 1)
        r0 = max(0, int((min(ay, by) - m) / cell))
        r1 = min(H, int((max(ay, by) + m) / cell) + 1)
        if c1 - c0 < 2 or r1 - r0 < 2:
            return straight, straight, False, []
        crop = Z[r0:r1, c0:c1]
        cost, passable = slope_costmap(crop, cell, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
                                       max_drop_m=MAX_DROP_M)
        _apply_keepouts(passable, cell, r0, c0, dem_origin, keepouts)
        hc, wc = crop.shape
        start = (min(max(int(ay / cell) - r0, 0), hc - 1), min(max(int(ax / cell) - c0, 0), wc - 1))
        goal = (min(max(int(by / cell) - r0, 0), hc - 1), min(max(int(bx / cell) - c0, 0), wc - 1))
        # P-06: inflate hazards by the swept footprint (erode passable), but keep the start/goal cells
        # themselves traversable so a validly-sited endpoint is not declared unreachable by its own pad edge.
        eroded = _erode_passable(passable, cell, footprint_radius_m)
        eroded[start] = passable[start]
        eroded[goal] = passable[goal]
        grid_straight = math.hypot((goal[1] - start[1]) * cell, (goal[0] - start[0]) * cell)
        path, length_m, reached = route_least_cost(cost, eroded, cell, start, goal)
        if reached:
            waypoints = [(((c0 + c) * cell) - ox, ((r0 + r) * cell) - oy) for (r, c) in path]
            return length_m, grid_straight, True, waypoints
        if c0 == 0 and c1 == W and r0 == 0 and r1 == H:
            return straight, straight, False, []
        m *= 2.0
# ---- endurance / single-charge range (the "true distance before recharge", grounded) ------------
def single_charge_range_m(g, *, slope_deg=0.0, slip=0.0, full_pack=False,
                          battery_j=None, drive_j_per_m=None, rover_mass_kg=None, reserve_frac=None):
    """One-way driving distance on a single charge [m]. Usable energy / effective drive cost, where the
    effective cost = the flat 135 J/m amplified by wheel slip (1/(1-slip), the wheel travels further than
    the ground) plus the exact gravity-climb term rover_mass*g*sin(slope) on the uphill. `full_pack` uses
    the whole pack; otherwise it stops at the operational reserve. H-01: the energy/mass terms default to
    the IPEx module globals; pass a PlanningContext's battery_j/drive_j_per_m/rover_mass_kg/reserve_frac to
    range a different vehicle (heavier mass / smaller pack -> shorter range)."""
    battery_j = BATTERY_J if battery_j is None else battery_j
    drive_j_per_m = DRIVE_J_PER_M if drive_j_per_m is None else drive_j_per_m
    rover_mass_kg = ROVER_MASS_KG if rover_mass_kg is None else rover_mass_kg
    reserve_frac = RESERVE_FRAC if reserve_frac is None else reserve_frac
    usable = battery_j * (1.0 if full_pack else (1.0 - reserve_frac))
    jpm = drive_j_per_m / max(1e-6, 1.0 - slip) + rover_mass_kg * g * math.sin(math.radians(max(0.0, slope_deg)))
    return usable / jpm


def reachable_radius_on_dem(dem, dem_origin, usable_j, g, *, stride=10, slip_alpha=SLIP_ALPHA,
                            drive_j_per_m=None, rover_mass_kg=None):
    """DEM-grounded one-charge reach: a Dijkstra DRIVE-ENERGY field from the anchor over a (coarsened)
    slope+slip costmap -- each edge costs seg*135*(1+slip_alpha*tan(theta)) + rover_mass*g*max(0, climb).
    Returns the iso-energy reachable set: radius_m (farthest reachable cell), area_m2, whether the whole
    tile is within one charge, and the worst-cell energy (the hardest point to reach). H-01: drive cost +
    rover mass default to the IPEx globals; pass the selected vehicle's values to reach a different vehicle."""
    drive_j_per_m = DRIVE_J_PER_M if drive_j_per_m is None else drive_j_per_m
    rover_mass_kg = ROVER_MASS_KG if rover_mass_kg is None else rover_mass_kg
    Z, cell = dem
    Zc = np.asarray(Z, dtype=np.float64)[::stride, ::stride]    # coarsen for a fast field; honest estimate
    cc = cell * stride
    H, W = Zc.shape
    ox, oy = dem_origin
    ar = min(max(int(round(oy / cell)) // stride, 0), H - 1)
    ac = min(max(int(round(ox / cell)) // stride, 0), W - 1)
    INF = math.inf
    energy = np.full((H, W), INF)
    energy[ar, ac] = 0.0
    pq = [(0.0, ar, ac)]
    while pq:
        e, r, c = heapq.heappop(pq)
        if e > energy[r, c]:
            continue
        for dr, dc, seg in _ROUTE_NB:
            nr, nc = r + dr, c + dc
            if 0 <= nr < H and 0 <= nc < W:
                dh = Zc[nr, nc] - Zc[r, c]
                slope = math.atan2(abs(dh), seg * cc)
                step = seg * cc * drive_j_per_m * (1.0 + slip_alpha * math.tan(slope)) + rover_mass_kg * g * max(0.0, dh)
                ne = e + step
                if ne < energy[nr, nc]:
                    energy[nr, nc] = ne
                    heapq.heappush(pq, (ne, nr, nc))
    reach = energy <= usable_j
    rr, cci = np.where(reach)
    dists = np.hypot((cci - ac) * cc, (rr - ar) * cc)
    finite = energy[np.isfinite(energy)]
    return {
        "radius_m": float(dists.max()) if dists.size else 0.0,
        "area_m2": float(reach.sum() * cc * cc),
        "tile_fully_reachable": bool(reach.all()),
        "worst_cell_J": float(finite.max()) if finite.size else 0.0,
        "worst_cell_pack_frac": float(finite.max() / BATTERY_J) if finite.size else 0.0,
        "grid_cell_m": float(cc),
    }


# ---- power model (P10/K8): per-site power source + thermal derating ------------------------------
POWER_KINDS = ("psr_tower", "sunlit_solar")


def thermal_derate(temp_c):
    """Usable Li-ion pack fraction vs temperature. [CALIB, general Li-ion cold behavior] ~1.0 at >=0 C,
    falling ~1%/C below 0 (a standard rough rule), floored at 0.5. `None` (no temp given) -> 1.0. The IPEx
    qual envelope is -35/+40 C (FIX-5); off-the-shelf cells can't meet -35 C without derating/heaters."""
    if temp_c is None or temp_c >= 0.0:
        return 1.0
    return max(0.5, 1.0 + 0.01 * float(temp_c))


def power_regime(mission, *, kind="psr_tower", charge_power_w=None, temp_c=None):
    """Per-site power model. A PSR (e.g. Haworth, the loaded DEM) has NO sun -> a lander/tower charging
    budget at the charger, available ANYTIME (this is what the planner's recharge actually models -- calling
    it solar was the error). A SUNLIT site recharges from solar, available only during the body's daylight
    fraction, so the EFFECTIVE recharge throughput is duty-limited (duty = daylight_h / solar_day_h).
    Optional cold thermal derating of the usable pack. Day/night from the grounded `body_timescale`."""
    if kind not in POWER_KINDS:
        raise ValueError(f"unknown power kind {kind!r}; known: {POWER_KINDS}")
    ts = body_timescale(mission.body)
    cw = CHARGE_W if charge_power_w is None else float(charge_power_w)
    if kind == "sunlit_solar":
        duty = ts["daylight_h"] / ts["solar_day_h"]
        avail = f"daylight only (~{ts['daylight_h']:.0f} h / {ts['solar_day_h']:.0f} h {ts['day_label']})"
    else:
        duty = 1.0
        avail = "anytime (lander/tower budget; a PSR has no sun)"
    derate = thermal_derate(temp_c)
    return {"kind": kind, "charge_power_w": cw, "duty_frac": duty, "effective_charge_w": cw * duty,
            "availability": avail, "thermal_derate": derate, "usable_pack_J": BATTERY_J * derate,
            "day_label": ts["day_label"], "daylight_h": ts["daylight_h"], "solar_day_h": ts["solar_day_h"]}


def endurance(mission, *, dem=None, dem_origin=(0.0, 0.0), power_site="psr_tower", temp_c=None):
    """Single-charge driving capability ("true distance before recharge"), grounded in the IPEx specs.
    Returns the flat range (full pack + to reserve), the slope+slip-adjusted range at the work-area's
    representative slope (if a DEM is given), and the DEM-grounded reachable radius from the charger."""
    g = body_gravity(mission.body)
    # H-01: the endurance/range math is the SELECTED vehicle's, not the IPEx globals. Rebind the names as
    # locals (so the inline ConOps/report references use the vehicle), and pass the same values explicitly
    # into single_charge_range_m / reachable_radius_on_dem (which read their own module-global defaults).
    ctx = plan_context(mission)
    BATTERY_J = ctx.battery_j
    DRIVE_J_PER_M = ctx.drive_j_per_m
    DRIVE_SPEED_MS = ctx.drive_speed_ms
    DRIVE_POWER_W = ctx.drive_power_w
    ROVER_MASS_KG = ctx.rover_mass_kg
    RESERVE_FRAC = ctx.reserve_frac
    DIG_J_PER_KG = ctx.dig_j_per_kg
    _rk = dict(battery_j=BATTERY_J, drive_j_per_m=DRIVE_J_PER_M, rover_mass_kg=ROVER_MASS_KG,
               reserve_frac=RESERVE_FRAC)                  # the vehicle's range kwargs
    out = {
        "pack_energy_MJ": BATTERY_J / 1e6, "drive_power_w": DRIVE_POWER_W, "flat_j_per_m": DRIVE_J_PER_M,
        "speed_ms": DRIVE_SPEED_MS, "rover_mass_kg": ROVER_MASS_KG, "g": g, "reserve_frac": RESERVE_FRAC,
        "range_flat_full_km": single_charge_range_m(g, full_pack=True, **_rk) / 1000.0,
        "range_flat_reserve_km": single_charge_range_m(g, **_rk) / 1000.0,
        "duration_flat_h": single_charge_range_m(g, **_rk) / DRIVE_SPEED_MS / 3600.0,
    }
    out["power"] = power_regime(mission, kind=power_site, temp_c=temp_c)   # #2 per-site power source
    # ConOps reconciliation [SCHULER24]: the per-charge range is a per-SORTIE bound, not a mission limit.
    # Over the 11-day mission the rover traverses ~70 km AND excavates 5-10 t -> the drums dominate the
    # energy budget, and the sunlit operating window (~9-11 Earth-days) dwarfs any single charge.
    # body-correct operating timescale: is a full-range sortie inside one sunlit window, or does it span days?
    ts = body_timescale(mission.body)
    dur_h = out["duration_flat_h"]
    win_lo, win_hi = ts["op_window_h"]
    ts["sortie_h"] = dur_h
    ts["sorties_per_window"] = win_lo / dur_h                  # how many full-range sorties fit one sun window
    ts["spans_days"] = dur_h / ts["daylight_h"]               # sols/lunar-days a continuous sortie would span
    ts["fits_in_window"] = dur_h <= win_hi
    out["timescale"] = ts
    drive_mj = S.TRAVERSE_KM * 1000.0 * DRIVE_J_PER_M / 1e6
    reg_lo, reg_hi = S.TOTAL_REGOLITH_KG
    out["conops"] = {
        "traverse_km": S.TRAVERSE_KM, "mission_days": S.MISSION_DAYS,
        "regolith_t": [reg_lo / 1000.0, reg_hi / 1000.0],
        "drive_energy_MJ": drive_mj, "drive_packs": drive_mj * 1e6 / BATTERY_J,
        "dig_energy_MJ": [reg_lo * DIG_J_PER_KG / 1e6, reg_hi * DIG_J_PER_KG / 1e6],
        "dig_packs": [reg_lo * DIG_J_PER_KG / BATTERY_J, reg_hi * DIG_J_PER_KG / BATTERY_J],
        "drums_dominate": (reg_lo * DIG_J_PER_KG) > (S.TRAVERSE_KM * 1000.0 * DRIVE_J_PER_M),
    }
    if dem is not None:
        Z, cell = dem
        H, W = np.asarray(Z).shape
        ox, oy = dem_origin
        rc = min(max(int(round(oy / cell)), 0), H - 1); cc0 = min(max(int(round(ox / cell)), 0), W - 1)
        r0 = min(max(0, rc - 200), max(0, H - 400)); c0 = min(max(0, cc0 - 200), max(0, W - 400))
        win = np.asarray(Z)[r0:r0 + 400, c0:c0 + 400]
        med_slope = float(np.median(slope_deg_map(win, cell))) if win.size else 0.0
        slip = min(0.95, slip_alpha_to_slip(med_slope, params=mission_soil_params(mission),
                                            rover_mass_kg=ROVER_MASS_KG))   # soil-aware + H-01 vehicle mass
        out["work_area_median_slope_deg"] = med_slope
        out["range_slopeslip_km"] = single_charge_range_m(g, slope_deg=med_slope, slip=slip, **_rk) / 1000.0
        out["reach"] = reachable_radius_on_dem(dem, dem_origin, BATTERY_J * (1 - RESERVE_FRAC), g,
                                               rover_mass_kg=ROVER_MASS_KG)   # H-01: vehicle usable + mass
    return out


def slip_alpha_to_slip(slope_deg, payload_kg=0.0, g=None, params=None, rover_mass_kg=None):
    """Wheel slip from terrain slope AND the rover's laden weight, via the CONSERVED slip ladder
    (slip.slip_sinkage_equilibrium): a steeper grade OR a heavier rover (full drum) -> more slip,
    entrapping near ~45 deg. ``payload_kg`` is the regolith in the drum on this leg (0 = empty); ``g``
    defaults to lunar. This replaces the old slope-only [CALIB] curve so the planner's per-leg slip (and
    the 1/(1-slip) drive-energy inflation) is weight-coupled, consistent with the simulator authority.
    H-01: ``rover_mass_kg`` defaults to the IPEx global; pass the selected vehicle's mass so a heavier
    platform (rassor2, 65 kg) slips more. (The per-cell routing costmap keeps the SLIP_ALPHA*tan heuristic.)"""
    gg = C.g if g is None else float(g)
    p = params if params is not None else _TM_PARAMS     # soil model (params_for_body(soil)); default lunar
    m = ROVER_MASS_KG if rover_mass_kg is None else float(rover_mass_kg)
    weight_n = (m + max(0.0, payload_kg)) * gg
    eq = TMS.slip_sinkage_equilibrium(weight_n, math.radians(max(0.0, slope_deg)),
                                      params=p, contact_len_m=0.10, contact_width_m=0.18)
    return max(0.0, min(0.95, float(eq["slip"])))


def validate_plan(mission, *, cell_m=0.5, regolith_depth_m=10.0, max_cells=500, dem=None,
                  dem_origin=(0.0, 0.0), max_slope_deg=15.0, accept_flatness_tol_m=0.02):
    """I8: MATERIAL-realizability acceptance on the CONSERVED authority (NOT full plan validation -- audit
    H-07). Rasterize each order's footprint onto a `ColumnState`, execute the cuts (into the drum) then the
    fills (from the drum), and report mass conservation + per-order feasibility + the executed (mass-exact)
    cut/fill vs the planner's abstract estimate, the slope/off-DEM siting gate, and the as-built flatness.
    A cut deeper than the regolith mantle floors at the datum (infeasible); a fill the drum can't supply
    is flagged; an order off the tile or on too steep a slope is rejected.

    SCOPE (audit H-07): this checks MATERIAL realizability + siting + as-built only. It executes all cuts
    then all fills through one pooled drum, so it deliberately does NOT re-derive sequence/precedence
    ordering, the drum-CAPACITY shuttle-cycle count, or route/battery dynamics -- the plan is already
    decomposed into self-balanced cut->fill trips, so an ordered re-execution is materially identical, and
    those feasibility axes are owned by the simulated `totals` (reserve-aware drive C-04, blocked-route
    feasibility) and surfaced/fail-closed at the /plan product boundary (H-03). The report carries
    `acceptance_scope` (what it covers vs defers) + `drum_capacity_kg`/`shuttle_cycles_est` so the
    single-pool execution is not mistaken for a capacity-bounded shuttle."""
    rho_bank, rho_loose = mission.density * SWELL, mission.density
    cuts = [o for o in mission.orders if o.kind == "cut"]
    fills = [o for o in mission.orders if o.kind == "fill"]
    sides = [math.sqrt(o.footprint_m2) for o in mission.orders]
    margin = 2.0 + (max(sides) / 2 if sides else 0.0)
    x0 = min(o.x - s / 2 for o, s in zip(mission.orders, sides)) - margin
    y0 = min(o.y - s / 2 for o, s in zip(mission.orders, sides)) - margin
    x1 = max(o.x + s / 2 for o, s in zip(mission.orders, sides)) + margin
    y1 = max(o.y + s / 2 for o, s in zip(mission.orders, sides)) + margin
    if max(x1 - x0, y1 - y0) / cell_m > max_cells:          # cap grid for speed; coarsen the cell
        cell_m = max(x1 - x0, y1 - y0) / max_cells
    W = max(1, int(math.ceil((x1 - x0) / cell_m)))
    H = max(1, int(math.ceil((y1 - y0) / cell_m)))
    cs = ColumnState(width=W, height=H, cell_m=cell_m,
                     mass_areal=np.full((H, W), rho_bank * regolith_depth_m, dtype=np.float64))
    # P0 as-built acceptance: when a DEM is given, start the surface at the REAL terrain (datum = terrain
    # - mantle so derive_height == terrain), not a flat mantle. A uniform-depth cut/fill on a sloped surface
    # then leaves a sloped surface -- so the as-built flatness check below actually reveals whether the plan
    # achieves a level pad (it can't on a flat mantle, where everything is trivially flat).
    on_real_dem = dem is not None
    if on_real_dem:
        Z, _dem_cell = dem
        ox, oy = dem_origin
        ci = np.clip(((x0 + (np.arange(W) + 0.5) * cell_m + ox) / _dem_cell).astype(int), 0, Z.shape[1] - 1)
        ri = np.clip(((y0 + (np.arange(H) + 0.5) * cell_m + oy) / _dem_cell).astype(int), 0, Z.shape[0] - 1)
        cs.datum = Z[np.ix_(ri, ci)] - regolith_depth_m
    m0 = cs.total_mass()
    rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")

    def _mask(o):
        s = math.sqrt(o.footprint_m2); half = (s / 2) / cell_m
        cx, cy = (o.x - x0) / cell_m, (o.y - y0) / cell_m
        return (np.abs(cc + 0.5 - cx) <= half) & (np.abs(rr + 0.5 - cy) <= half)

    cell_area = cell_m * cell_m
    feasible = True
    exec_cut = 0.0
    for o in cuts:                                          # cuts first -> load the global drum
        mask = _mask(o)
        if not mask.any():
            feasible = False; continue
        moved = cs.cut_to_inventory(mask, o.depth_m * rho_bank)
        exec_cut += moved
        # feasibility = did the authority move the asked-for depth over the RASTERIZED footprint? gate on
        # the on-grid area (mask cells x cell_area), not the analytic footprint, so a sub-grid footprint
        # under-covering the 0.5 m cells doesn't read as infeasible -- only a true datum-floor does.
        if moved < 0.99 * mask.sum() * cell_area * o.depth_m * rho_bank:   # floored at datum -> not enough material
            feasible = False
    exec_fill = 0.0
    for o in fills:                                         # fills from the drum
        mask = _mask(o)
        if not mask.any():
            feasible = False; continue
        target = cs.derive_height().copy(); target[mask] += o.depth_m
        placed = cs.fill_toward(mask, target, max_lift_m=o.depth_m, spoil_density=rho_loose)
        exec_fill += placed
    # fills draw from a SHARED drum -> fill feasibility is a global MATERIAL question, not per-order grid
    # coverage: the plan is fill-infeasible only when the drum ran dry while the executed fill fell short
    # of the analytic plan (a genuine under-supply), not when rasterization shifts the berm by a few cells.
    planned_fill_total = sum(o.footprint_m2 * o.depth_m * rho_loose for o in fills)
    if fills and exec_fill < 0.99 * planned_fill_total and cs.drum_inventory <= 1e-6 * max(1.0, planned_fill_total):
        feasible = False
    drift = abs(cs.total_mass() - m0)
    mass_conserved = drift <= 1e-6 * max(1.0, m0)
    # P0 as-built acceptance: measure the FLATNESS of the executed surface over each worked footprint
    # (RMSE of as-built height about the footprint mean) -- the "did we build a level pad to +/-tol" check
    # the flat-mantle path could never give. Reported per-order (worst + mean); on a flat mantle it is ~0.
    # NOT folded into `feasible` (a uniform-depth excavation of a slope is feasible but legitimately not flat).
    as_built = cs.derive_height()
    flat_rmses = []
    for o in mission.orders:
        mask = _mask(o)
        if int(mask.sum()) < 2:
            continue
        h = as_built[mask]
        flat_rmses.append(float(np.sqrt(np.mean((h - h.mean()) ** 2))))
    as_built_worst = max(flat_rmses) if flat_rmses else 0.0
    as_built_mean = (sum(flat_rmses) / len(flat_rmses)) if flat_rmses else 0.0
    # I6 + I11: terrain-aware siting against the real DEM. A pad on a crater wall fails even when material
    # is available. dem = (heightmap, cell_m). M11: the order's LOCAL x,y is anchored to a real DEM site via
    # dem_origin (DEM meters where local (0,0) sits). I11: gate the WHOLE footprint, not just the center cell
    # -- a pad whose centre is flat but whose edge straddles a steep rim must still fail (worst slope over the
    # footprint + the fraction of footprint cells over the threshold are reported as the acceptance check).
    slope_violations = []
    off_dem_orders = []
    if dem is not None:
        Z, dem_cell = dem
        smap = slope_deg_map(Z, dem_cell)
        Hd, Wd = smap.shape
        ox, oy = dem_origin
        for o in mission.orders:
            half = (math.sqrt(o.footprint_m2) / 2.0) / dem_cell
            cx, cy = (ox + o.x) / dem_cell, (oy + o.y) / dem_cell
            ur0, ur1 = int(round(cy - half)), int(round(cy + half)) + 1   # UNclamped footprint cell box
            uc0, uc1 = int(round(cx - half)), int(round(cx + half)) + 1
            if ur0 < 0 or uc0 < 0 or ur1 > Hd or uc1 > Wd:     # H-08: footprint leaves the DEM -> can't be
                off_dem_orders.append({"action": o.action, "x": o.x, "y": o.y})   # validated -> reject (no edge-clip)
                continue
            patch = smap[ur0:ur1, uc0:uc1]
            if not patch.size:
                continue
            worst = float(patch.max())
            if worst > max_slope_deg:                          # any cell in the footprint too steep -> reject
                slope_violations.append({"action": o.action, "slope_deg": round(worst, 1),
                                         "frac_over": round(float((patch > max_slope_deg).mean()), 2),
                                         "x": o.x, "y": o.y})
    # H-07: this is MATERIAL realizability + siting + as-built, NOT full plan validation. Make the scope
    # machine-readable (covers vs defers) and surface the drum capacity + shuttle-cycle count the pooled
    # single-drum execution abstracts away, so a consumer can't mistake it for a capacity-bounded shuttle.
    ctx = plan_context(mission)                            # H-01: the selected vehicle's drum + dig energy
    drum_cap = ctx.drum_kg
    shuttle_cycles_est = int(sum(max(1, math.ceil((o.footprint_m2 * o.depth_m * rho_bank) / drum_cap))
                                 for o in cuts)) if drum_cap > 0 else 0
    return {
        "feasible": bool(feasible and mass_conserved and not slope_violations and not off_dem_orders),
        "mass_conserved": bool(mass_conserved),
        "slope_violations": slope_violations,
        "off_dem_orders": off_dem_orders,                      # H-08: orders whose footprint left the DEM bounds
        # H-07: honest acceptance scope -- what this conserved-authority check covers vs what it defers to
        # the simulated totals / Plan IR (route, battery, sequence/precedence, drum-cycle), which the /plan
        # boundary fails closed on (H-03/C-04). The plan is self-balanced cut->fill trips, so an ordered IR
        # re-execution is materially identical -- this is acceptance, not a redundant second simulator.
        "acceptance_scope": {
            "covers": ["mass_conservation", "datum_floor_feasibility", "drum_supply",
                       "slope_siting", "off_dem_siting", "as_built_flatness"],
            "defers_to_totals": ["route_feasibility", "battery_reserve", "sequence_precedence",
                                 "drum_capacity_shuttle_cycles"]},
        "drum_capacity_kg": float(drum_cap),
        "shuttle_cycles_est": shuttle_cycles_est,              # ceil(cut_mass / drum_cap), summed over cuts
        "max_slope_deg": float(max_slope_deg),
        "mass_drift_kg": float(drift),
        "planned_cut_kg": float(sum(o.footprint_m2 * o.depth_m * rho_bank for o in cuts)),
        "executed_cut_kg": float(exec_cut),
        "planned_fill_kg": float(sum(o.footprint_m2 * o.depth_m * rho_loose for o in fills)),
        "executed_fill_kg": float(exec_fill),
        "drum_remaining_kg": float(cs.drum_inventory),
        "executed_dig_J": float(exec_cut * ctx.dig_j_per_kg),
        "grid": {"rows": H, "cols": W, "cell_m": cell_m},
        # P0 as-built acceptance (level-surface check on the executed surface):
        "as_built_on_real_dem": bool(on_real_dem),         # False -> measured on a flat mantle (trivially flat)
        "as_built_flatness_rmse_m": float(as_built_worst),  # worst footprint flatness RMSE
        "as_built_flatness_mean_m": float(as_built_mean),
        "as_built_tol_m": float(accept_flatness_tol_m),
        "as_built_pass": bool(as_built_worst <= accept_flatness_tol_m),
    }


def execute_plan_acceptance(mission, trips, *, cell_m=0.5, regolith_depth_m=10.0, max_cells=500,
                            dem=None, dem_origin=(0.0, 0.0)):
    """H-07 follow-up: ORDERED IR-replay acceptance (the literal "execute the exact Plan IR" path).

    Unlike validate_plan's pooled all-cuts-then-all-fills material check, this walks the TRIPS IN PLAN
    ORDER through a CAPACITY-BOUNDED drum -- each trip cuts its cut footprint INTO the drum, then fills its
    fill footprint FROM the drum -- so two order-dependent effects the pooled check flattens are caught:
      (1) drum-supply sequencing: a fill scheduled before its supplying cut draws from an EMPTY drum and
          places nothing (the pooled check always has every cut's material on hand, masking this);
      (2) overlapping cut/fill footprints across trips (berm on a just-cut pad, a re-grade) -- the as-built
          surface depends on the order, which all-cuts-then-fills cannot represent.
    Returns the ORDERED as-built surface + mass conservation + the running drum balance (the min inventory
    over the walk; < 0 means a fill out-ran its supply) + the max simultaneous drum load vs capacity +
    shuttle-cycle count. Mass is a density-only edit so it is conserved exactly. Self-contained (mirrors
    validate_plan's grid so the two as-built surfaces are directly comparable)."""
    rho_bank, rho_loose = mission.density * SWELL, mission.density
    cap = _drum_kg(mission)
    order_by_action = {o.action: o for o in mission.orders}
    sides = [math.sqrt(o.footprint_m2) for o in mission.orders]
    margin = 2.0 + (max(sides) / 2 if sides else 0.0)
    x0 = min(o.x - s / 2 for o, s in zip(mission.orders, sides)) - margin
    y0 = min(o.y - s / 2 for o, s in zip(mission.orders, sides)) - margin
    x1 = max(o.x + s / 2 for o, s in zip(mission.orders, sides)) + margin
    y1 = max(o.y + s / 2 for o, s in zip(mission.orders, sides)) + margin
    if max(x1 - x0, y1 - y0) / cell_m > max_cells:
        cell_m = max(x1 - x0, y1 - y0) / max_cells
    W = max(1, int(math.ceil((x1 - x0) / cell_m)))
    H = max(1, int(math.ceil((y1 - y0) / cell_m)))
    cs = ColumnState(width=W, height=H, cell_m=cell_m,
                     mass_areal=np.full((H, W), rho_bank * regolith_depth_m, dtype=np.float64))
    if dem is not None:
        Z, _dem_cell = dem
        ox, oy = dem_origin
        ci = np.clip(((x0 + (np.arange(W) + 0.5) * cell_m + ox) / _dem_cell).astype(int), 0, Z.shape[1] - 1)
        ri = np.clip(((y0 + (np.arange(H) + 0.5) * cell_m + oy) / _dem_cell).astype(int), 0, Z.shape[0] - 1)
        cs.datum = Z[np.ix_(ri, ci)] - regolith_depth_m
    m0 = cs.total_mass()
    rr, cc = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")

    def _mask(o):
        s = math.sqrt(o.footprint_m2); half = (s / 2) / cell_m
        cx, cy = (o.x - x0) / cell_m, (o.y - y0) / cell_m
        return (np.abs(cc + 0.5 - cx) <= half) & (np.abs(rr + 0.5 - cy) <= half)

    def _orders(tr, kind):
        return [order_by_action[a] for a in tr.get("actions", ())
                if a in order_by_action and order_by_action[a].kind == kind]

    # P-02: capacity-bounded shuttle. The drum is a PHYSICAL container of `cap` kg; cuts feed it in
    # cycles bounded by its FREE capacity and by each cut order's remaining footprint supply (tracked
    # in `supply_left` so re-referencing a cut across flows never over-extracts), and fills drain it. The
    # drum thus NEVER holds more than `cap` and a fill never out-runs the supply currently on board. The
    # peak load and the running minimum are observed across the bounded walk, not estimated from a cycle
    # count. (The prior bug cut whole order footprints into an unbounded drum -- 7680 kg in a 30 kg drum.)
    step = cap if cap > 0 else float("inf")               # max kg moved per shuttle cycle (drum capacity)
    supply_left = {id(o): o.footprint_m2 * o.depth_m * rho_bank for o in mission.orders if o.kind == "cut"}
    feasible = True; drum_max = 0.0; running_min = 0.0; shuttle_cycles = 0
    for tr in trips:                                       # PLAN ORDER -- the executable sequence
        for o in _orders(tr, "cut"):
            mask = _mask(o)
            if not mask.any(): feasible = False; continue
            n = int(mask.sum()); cell_area = cs.cell_area
            want = supply_left.get(id(o), o.footprint_m2 * o.depth_m * rho_bank)
            while want > 1e-6:                             # cut this order's remaining supply in bounded loads
                free = step - cs.drum_inventory           # P-02: only what the bounded drum can still hold
                if free <= 1e-6:                           # drum full and nothing has drained it -> overflow
                    feasible = False; break                # (a cut with no fill to drain it can't be held)
                take = min(want, free)
                moved = cs.cut_to_inventory(mask, take / (n * cell_area))   # cut exactly `take` kg as areal
                drum_max = max(drum_max, cs.drum_inventory)
                shuttle_cycles += 1
                if moved <= 1e-6:                          # footprint exhausted (datum floor) -> short supply
                    feasible = False; break
                want -= moved
            supply_left[id(o)] = want                      # carry the unspent supply forward (no double-cut)
        for o in _orders(tr, "fill"):
            mask = _mask(o)
            if not mask.any(): feasible = False; continue
            target = cs.derive_height().copy(); target[mask] += o.depth_m
            # drain the drum into this fill in bounded loads so it dips through, never below, zero.
            placed = 1.0
            while cs.drum_inventory > 1e-6 and placed > 1e-6:
                before = cs.drum_inventory
                cs.fill_toward(mask, target, max_lift_m=o.depth_m, spoil_density=rho_loose)
                placed = before - cs.drum_inventory
                running_min = min(running_min, cs.drum_inventory)
            running_min = min(running_min, cs.drum_inventory)
    drift = abs(cs.total_mass() - m0)
    mass_conserved = drift <= 1e-6 * max(1.0, m0)
    return {
        "executes_ordered_ir": True,
        "feasible": bool(feasible and mass_conserved),
        "mass_conserved": bool(mass_conserved),
        "mass_drift_kg": float(drift),
        "drum_capacity_kg": float(cap),
        "max_simultaneous_drum_kg": float(drum_max),       # the peak inventory the bounded drum had to hold
        "running_drum_min_kg": float(running_min),         # < 0 would mean a fill out-ran its supply in sequence
        "shuttle_cycles": int(shuttle_cycles),
        "as_built": cs.derive_height(),                    # the ORDER-dependent surface the pooled check flattens
        "grid": {"rows": H, "cols": W, "cell_m": cell_m},
    }


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
    report(mission, trips, flows, per_trip, tl, totals, pdf, md,
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


# ARCH-2: the planner VIEWS live in planner_views; re-exported here so MP.report / MP.plan_math /
# MP.assumptions_register call sites are unchanged (imported at module END so the solver names the
# views need are already defined -> no import cycle).
from lode import planner_views as _views          # noqa: E402
report = _views.report
plan_math = _views.plan_math
assumptions_register = _views.assumptions_register
plan_ir = _views.plan_ir                          # ARCH-2: the machine-executable IR view
PLAN_IR_VERSION = _views.PLAN_IR_VERSION
_IR_OP = _views._IR_OP
_IR_DIG_OPS = _views._IR_DIG_OPS
_IR_MODEL_ERR_FRAC = _views._IR_MODEL_ERR_FRAC
