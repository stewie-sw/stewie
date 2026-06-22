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
from typing import TYPE_CHECKING
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

# ARCH-03: the SHARED planner constants live in the dependency-neutral lode.planner_constants so
# planner_views can import them WITHOUT importing this module (half of the cycle break). Re-imported
# here so MP.<const> and the internal uses below are unchanged; values are byte-identical.
from lode.planner_constants import (  # noqa: E402
    BATTERY_J, DIG_RATE_KG_S, DRIVE_J_PER_M, DRIVE_SPEED_MS, RESERVE_FRAC,
)
from lode import lander_return as LR  # noqa: E402  (#161; pure module, no cycle)
from lode import relocalization as REL  # noqa: E402  (#96; pure module, no cycle)
from stewie.physics import rassor_mass_model as RMM  # noqa: E402  (arm-raise fix energy; no lode import)
DIG_J_PER_KG    = S.dig_energy_per_kg()                  # ~4151 J/kg; also in planner_constants (same source)
DRUM_KG         = S.REGOLITH_PER_CYCLE_KG                # 30 kg/cycle (the ipex default; see _drum_kg)


def _drum_kg(mission):
    """RB-05: the per-cycle drum capacity [kg] of the mission's SELECTED vehicle (VehicleModel-driven),
    so vehicle choice changes the planner numbers (loads / drum cycles / haul energy). The default
    vehicle 'ipex' has drum_capacity_kg == DRUM_KG == 30, so an unspecified mission is byte-identical."""
    return float(V.get_vehicle(mission.vehicle).drum_capacity_kg)
SINTER_J_PER_KG = C.SINTER_ENERGY_J_PER_KG              # 0.92 MJ/kg [CALIB]
SINTER_POWER_W  = S.SINTER_HEAD_POWER_W                  # 1000 W [CALIB]
CHARGE_W        = S.RECHARGE_POWER_W                     # 700 W [CALIB]
# RESERVE_FRAC is re-imported from lode.planner_constants above (ARCH-03)
ROVER_MASS_KG   = S.ROVER_MASS_CLASS_KG                  # 30 kg-class (for gravity-climb drive energy)
RELOCALIZE_DRIFT_TOL_M = 0.5                             # #96: max tolerated DR drift before a parallax fix
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
    # EP-02: the dig model is a constant J/kg (BP-1-calibrated); an optional operator material-difficulty
    # factor scales it for a known harder/icier site. None -> 1.0 -> byte-identical to the constant baseline.
    dig_factor = float(getattr(mission, "dig_energy_factor", None) or 1.0)
    return PlanningContext(
        dig_j_per_kg=float(veh.dig_energy_j_per_kg) * dig_factor,
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


def footprint_shape_area_m2(shape: dict) -> float:
    """CP-05: planar area [m^2] of a typed build-order footprint in the local order frame. Kinds (with
    orientation where it applies): rectangle (w x h, theta_deg), circle (r), corridor (length x width,
    theta_deg -- a haul/grade strip), polygon (vertices [[x,y],...], shoelace). Orientation does not
    change area but is carried on the order for footprint geometry/acceptance. Raises ValueError on an
    unknown kind or non-positive/degenerate dimensions. Scalar `footprint_m2` stays the legacy input."""
    k = str(shape.get("kind", "")).lower()
    if k == "rectangle":
        w, h = float(shape["w"]), float(shape["h"])
        if w <= 0 or h <= 0:
            raise ValueError(f"rectangle footprint needs w,h > 0 (got {w},{h})")
        return w * h
    if k == "circle":
        r = float(shape["r"])
        if r <= 0:
            raise ValueError(f"circle footprint needs r > 0 (got {r})")
        return math.pi * r * r
    if k == "corridor":
        length, width = float(shape["length"]), float(shape["width"])
        if length <= 0 or width <= 0:
            raise ValueError(f"corridor footprint needs length,width > 0 (got {length},{width})")
        return length * width
    if k == "polygon":
        verts = [(float(x), float(y)) for x, y in shape["vertices"]]
        if len(verts) < 3:
            raise ValueError(f"polygon footprint needs >= 3 vertices (got {len(verts)})")
        a = sum(verts[i][0] * verts[(i + 1) % len(verts)][1] - verts[(i + 1) % len(verts)][0] * verts[i][1]
                for i in range(len(verts)))
        area = abs(a) * 0.5
        if area <= 0:
            raise ValueError("polygon footprint is degenerate (zero area)")
        return area
    raise ValueError(f"unknown footprint shape kind {k!r} (use rectangle|circle|corridor|polygon)")


@dataclasses.dataclass
class BuildOrder:
    action: str
    kind: str               # "cut" | "fill" | "sinter"
    x: float; y: float
    footprint_m2: float
    depth_m: float          # cut depth / fill height / sinter depth
    note: str = ""
    #: CP-05: optional typed footprint shape (rectangle/circle/corridor/polygon + orientation) in the
    #: local order frame. When present, footprint_m2 is DERIVED from its area; a bare scalar footprint_m2
    #: (no shape) is the legacy square-equivalent input. The shape carries orientation for acceptance.
    shape: dict | None = None
    def mass_kg(self, rho): return self.footprint_m2 * self.depth_m * rho


@dataclasses.dataclass
class Mission:
    name: str; body: str; orders: list
    charger: tuple = (0.0, 0.0); charger_capacity: int = 1; date: str = "2026-06-03"
    #: #161: the delivery lander = the rover's safe haven. None -> defaults to the charger. The return-to-
    #: lander feasibility (totals["return_to_lander"]) keeps an operator-ADJUSTABLE buffer over the bare
    #: return-drive energy so the rover can always get back before the battery dies.
    lander: tuple | None = None
    return_buffer_frac: float = LR.DEFAULT_RETURN_BUFFER_FRAC
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
    #: EP-05: ambient/electronics temperature [deg C] for thermal battery derating. None -> nominal
    #: (>=0 C, derate 1.0, byte-identical to an un-temperatured plan); a cold value shrinks the USABLE
    #: pack (thermal_derate) so the battery-aware sim plans fewer/shorter sorties and recharges sooner.
    temp_c: float | None = None
    #: CP-08: optional HARD CONSTRAINTS + risk term for order sequencing, beyond the weighted objective.
    #: {max_time_s, max_energy_J, max_charges, max_distance_m, risk_weight}. An ordering that overshoots a
    #: budget is penalized (pushed below any feasible ordering); risk_weight adds a recharge-exposure cost.
    #: None -> unconstrained weighted metrics only (byte-identical to a no-constraints plan).
    objective_constraints: dict | None = None
    #: EP-04: mission-clock windows gating actions/recharge by ACTION CLASS, as allowed [open_s, close_s]
    #: intervals in mission-clock seconds. Keys: "recharge" (solar/power illumination window for refilling),
    #: "work" (illumination/thermal window for digging/offload/sinter), "drive" (comms/teleop window for
    #: inter-site transit). When an action of class C would start outside every allowed interval, the clock
    #: IDLES to the next interval's open (a "wait" leg); if no future interval exists the action is
    #: infeasible. None (or a missing class key) -> that class is unconstrained -> byte-identical.
    mission_windows: dict | None = None
    #: FL-03: declared SHARED RESOURCES (pit / dump / vantage / corridor) the fleet contends for beyond the
    #: charger, as a list of {id, kind, capacity, sites:[[x,y],...]}. A multi-vehicle trip whose work site
    #: lies on one of a resource's sites OCCUPIES that resource for its trip window; when more than
    #: `capacity` rovers would occupy it at once the excess WAIT (capacity-k FCFS, like the charger queue).
    #: None/empty -> no extra contention -> single-vehicle AND non-reserved multi-vehicle byte-identical.
    shared_resources: list | None = None
    #: EP-02: operator material-difficulty multiplier on the dig energy. The baseline dig model is a CONSTANT
    #: J/kg (ipex_specs.dig_energy_per_kg, calibrated to BP-1 dry simulant -- material/density/ice-INDEPENDENT,
    #: with the drum-rate (0.72-1.0)x band the planner already reports as dig_energy_bounds_MJ). Physical
    #: auto-derivation of dig energy from density/ice is UNMODELED; this factor lets an operator scale it for
    #: a known harder/icier site (>1) so the plan's dig energy DEPENDS on the declared material. None -> 1.0
    #: -> byte-identical to the constant baseline.
    dig_energy_factor: float | None = None
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
        if o.get("shape"):                                 # CP-05: a typed shape supplies the area -> footprint_m2 optional
            req = tuple(k for k in req if k != "footprint_m2")
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
                          (VAL.ensure_positive_scalar(footprint_shape_area_m2(o["shape"]),
                                                      f"order {i} footprint shape area") if o.get("shape")
                           else VAL.ensure_positive_scalar(o["footprint_m2"], f"order {i} footprint_m2"))),
            depth_m=(0.0 if o.get("kind") == "goto" else
                     VAL.ensure_positive_scalar(o["depth_m"], f"order {i} depth_m")),
            note=str(o.get("note", "")),
            shape=(o.get("shape") if o.get("kind") != "goto" else None)))
    c = payload.get("charger", (0.0, 0.0))
    kwargs = dict(name=str(payload.get("name", "Build Mission")), body=body, orders=orders,
                  charger=(VAL.ensure_finite_scalar(c[0], "charger x"),
                           VAL.ensure_finite_scalar(c[1], "charger y")),
                  charger_capacity=max(1, min(8, int(payload.get("charger_capacity", 1) or 1))),
                  vehicle=veh, tools=tools, soil=soil)
    if "date" in payload:
        kwargs["date"] = str(payload["date"])
    if payload.get("lander") is not None:                  # #161: the delivery lander (safe haven)
        ld = payload["lander"]
        kwargs["lander"] = (VAL.ensure_finite_scalar(ld[0], "lander x"),
                            VAL.ensure_finite_scalar(ld[1], "lander y"))
    if "return_buffer_frac" in payload:                    # #161: operator-adjustable return-to-lander buffer
        rb = VAL.ensure_finite_scalar(payload["return_buffer_frac"], "return_buffer_frac")
        if rb < 0:
            raise ValueError(f"return_buffer_frac must be >= 0 (got {rb})")
        kwargs["return_buffer_frac"] = rb
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
    kos = payload.get("keepouts")                          # discrete keep-out obstacles (circle or rect, local m)
    if kos is not None:
        if not isinstance(kos, list):
            raise ValueError("'keepouts' must be a list of {x,y,r} circles or {x0,y0,x1,y1} rectangles")
        clean = []
        for j, k in enumerate(kos):
            if not isinstance(k, dict):
                raise ValueError(f"keepout {j} must be an object")
            if isinstance(k.get("points"), (list, tuple)):                     # #178 arbitrary polygon
                pts = k["points"]
                if len(pts) < 3:
                    raise ValueError(f"keepout {j} polygon needs >= 3 vertices")
                clean.append({"points": [[VAL.ensure_finite_scalar(p[0], f"keepout {j} vertex x"),
                                          VAL.ensure_finite_scalar(p[1], f"keepout {j} vertex y")] for p in pts]})
            elif all(f in k for f in ("x0", "y0", "x1", "y1")):                # #178 axis-aligned rectangle
                x0 = VAL.ensure_finite_scalar(k["x0"], f"keepout {j} x0")
                y0 = VAL.ensure_finite_scalar(k["y0"], f"keepout {j} y0")
                x1 = VAL.ensure_finite_scalar(k["x1"], f"keepout {j} x1")
                y1 = VAL.ensure_finite_scalar(k["y1"], f"keepout {j} y1")
                clean.append({"x0": min(x0, x1), "y0": min(y0, y1), "x1": max(x0, x1), "y1": max(y0, y1)})
            elif all(f in k for f in ("x", "y", "r")):                         # circle (existing)
                clean.append({"x": VAL.ensure_finite_scalar(k["x"], f"keepout {j} x"),
                              "y": VAL.ensure_finite_scalar(k["y"], f"keepout {j} y"),
                              "r": VAL.ensure_positive_scalar(k["r"], f"keepout {j} r")})
            else:
                raise ValueError(f"keepout {j} must be {{x,y,r}} (circle), {{x0,y0,x1,y1}} (rectangle), "
                                 f"or {{points}} (polygon)")
        kwargs["keepouts"] = tuple(clean)
    oc = payload.get("objective_constraints")              # CP-08: hard budgets + risk for sequencing
    if oc is not None:
        if not isinstance(oc, dict):
            raise ValueError("'objective_constraints' must be an object of {budget: value}")
        allowed = set(_CONSTRAINT_CAPS) | {"risk_weight"}
        clean_oc = {}
        for k, v in oc.items():
            if k not in allowed:
                raise ValueError(f"unknown objective constraint {k!r}; allowed: {sorted(allowed)}")
            fv = VAL.ensure_finite_scalar(v, f"objective_constraints[{k}]")
            if fv < 0:
                raise ValueError(f"objective constraint {k!r} must be >= 0 (got {fv})")
            clean_oc[k] = fv
        if clean_oc:
            kwargs["objective_constraints"] = clean_oc
    mw = payload.get("mission_windows")                    # EP-04: action-class mission-clock windows
    if mw is not None:
        if not isinstance(mw, dict):
            raise ValueError("'mission_windows' must be an object of {class: [[open_s, close_s], ...]}")
        allowed_cls = {"recharge", "work", "drive"}
        clean_mw: dict = {}
        for cls, ivals in mw.items():
            if cls not in allowed_cls:
                raise ValueError(f"unknown mission_window class {cls!r}; allowed: {sorted(allowed_cls)}")
            if not isinstance(ivals, (list, tuple)):
                raise ValueError(f"mission_windows[{cls!r}] must be a list of [open_s, close_s] pairs")
            clean_ivals = []
            for n, iv in enumerate(ivals):
                if not isinstance(iv, (list, tuple)) or len(iv) != 2:
                    raise ValueError(f"mission_windows[{cls!r}][{n}] must be a [open_s, close_s] pair")
                o = VAL.ensure_finite_scalar(iv[0], f"mission_windows[{cls}][{n}] open")
                c = VAL.ensure_finite_scalar(iv[1], f"mission_windows[{cls}][{n}] close")
                if c < o:
                    raise ValueError(f"mission_windows[{cls!r}][{n}]: close ({c}) must be >= open ({o})")
                clean_ivals.append([o, c])
            if clean_ivals:
                clean_mw[cls] = clean_ivals
        if clean_mw:
            kwargs["mission_windows"] = clean_mw
    sr = payload.get("shared_resources")                   # FL-03: declared capacity-k shared resources
    if sr is not None:
        if not isinstance(sr, (list, tuple)):
            raise ValueError("'shared_resources' must be a list of {id, kind, capacity, sites}")
        allowed_kinds = {"pit", "dump", "vantage", "corridor"}   # charger is handled by charger_capacity
        clean_sr = []
        seen_ids: set = set()
        for n, r in enumerate(sr):
            if not isinstance(r, dict):
                raise ValueError(f"shared_resources[{n}] must be an object")
            rid = str(r.get("id", "")).strip()
            if not rid:
                raise ValueError(f"shared_resources[{n}] needs a non-empty 'id'")
            if rid in seen_ids:
                raise ValueError(f"shared_resources[{n}]: duplicate id {rid!r}")
            seen_ids.add(rid)
            kind = r.get("kind")
            if kind not in allowed_kinds:
                raise ValueError(f"shared_resources[{rid!r}] kind {kind!r}; allowed: {sorted(allowed_kinds)}")
            cap = r.get("capacity", 1)
            if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
                raise ValueError(f"shared_resources[{rid!r}] capacity must be an int >= 1 (got {cap!r})")
            sites_in = r.get("sites")
            if not isinstance(sites_in, (list, tuple)) or not sites_in:
                raise ValueError(f"shared_resources[{rid!r}] needs a non-empty 'sites' list of [x, y]")
            sites = []
            for m, s in enumerate(sites_in):
                if not isinstance(s, (list, tuple)) or len(s) != 2:
                    raise ValueError(f"shared_resources[{rid!r}].sites[{m}] must be an [x, y] pair")
                sx = VAL.ensure_finite_scalar(s[0], f"shared_resources[{rid}].sites[{m}].x")
                sy = VAL.ensure_finite_scalar(s[1], f"shared_resources[{rid}].sites[{m}].y")
                sites.append([sx, sy])
            clean_sr.append({"id": rid, "kind": kind, "capacity": int(cap), "sites": sites})
        if clean_sr:
            kwargs["shared_resources"] = clean_sr
    df = payload.get("dig_energy_factor")                  # EP-02: operator material-difficulty multiplier
    if df is not None:
        fv = VAL.ensure_finite_scalar(df, "dig_energy_factor")
        if fv <= 0:
            raise ValueError(f"'dig_energy_factor' must be > 0 (got {fv})")
        kwargs["dig_energy_factor"] = fv
    return Mission(**kwargs)


def _d(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])


# ARCH-2 #2: the cut-fill MATERIAL BALANCE solver (SWELL + _mincost_transport + balance) lives in
# lode.planner_balance. balance() needs this module's _d / _make_routes / Mission, which it pulls via a
# deferred import (no cycle), so planner_balance imports first; this module imports the block back at
# scope (planner_balance has no scope-level dependency on mission_planner -- only inside balance()). The
# re-import keeps MP.balance / MP._mincost_transport / MP.SWELL call sites unchanged (values identical).
from lode.planner_balance import SWELL, _mincost_transport, balance  # noqa: E402,F401


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
                              actions=frozenset({fo.action}), shape=fo.shape))
        elif fo is None:
            # surplus (un-routed) cut mass: it is still EXCAVATED -- the dominant dig cost (4151 J/kg) must
            # enter the plan. Dig in place; the spoil-disposal haul to a dump is a separate unmodeled term
            # (no spoil-site coordinate to fabricate one), so haul/lift = 0 here.
            trips.append(dict(kind="dig", site=(co.x, co.y), label=f"Excavate spoil: {co.action}",
                              mass=mass, dig_e=mass*ctx.dig_j_per_kg, dig_t=mass/DIG_RATE_KG_S,
                              haul_m=0.0, haul_e=0.0, lift_e=0.0, dest=(co.x, co.y),
                              actions=frozenset({co.action}), shape=co.shape))
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
                              actions=frozenset({co.action, fo.action}), shape=co.shape))
    for o in sinters:
        m = o.mass_kg(rho)
        trips.append(dict(kind="sinter", site=(o.x, o.y), label=o.action, mass=m, lift_e=0.0,
                          sinter_e=m*SINTER_J_PER_KG, sinter_t=m*SINTER_J_PER_KG/SINTER_POWER_W,
                          dest=(o.x, o.y), actions=frozenset({o.action}), shape=o.shape))
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


def _window_gate(windows, action_class, t):
    """EP-04: gate an action of `action_class` against the mission-clock windows.

    `windows` is None or {class: [[open_s, close_s], ...]} in mission-clock seconds. Returns
    (start_t, wait_s, reason): the time the action may START, the idle wait it incurs, and an
    infeasibility reason (or None). Falsy `windows` or a missing class key -> UNCONSTRAINED,
    (t, 0.0, None) -> byte-identical to an un-windowed plan. Otherwise the action may only run inside
    an allowed interval: already inside one -> run now (no wait); before the next -> idle to its open;
    past the last interval's close -> cannot run this mission (reason set, caller skips the action)."""
    if not windows:
        return t, 0.0, None
    intervals = windows.get(action_class)
    if not intervals:
        return t, 0.0, None
    for open_s, close_s in sorted((float(a), float(b)) for a, b in intervals):
        if t <= close_s:                                   # first interval not yet ended
            if t < open_s:
                return open_s, open_s - t, None            # idle until the window opens
            return t, 0.0, None                            # already inside this window
    return t, 0.0, f"{action_class} window closed (no allowed interval at or after t={t:.0f}s)"


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
    # EP-05: thermal derating SHRINKS the usable pack on a cold mission (Li-ion cold capacity loss). The
    # whole battery-aware sim (reserve, charge target, reachable work) runs against this derated capacity,
    # so a cold plan genuinely recharges sooner / does fewer sorties. mission.temp_c None -> derate 1.0
    # -> usable_battery_j == BATTERY_J -> byte-identical to an un-temperatured plan (no test drift).
    usable_battery_j = BATTERY_J * thermal_derate(mission.temp_c)
    windows = mission.mission_windows                  # EP-04: action-class mission-clock windows (None -> unconstrained)
    pos = list(mission.charger); batt = usable_battery_j; t = 0.0
    cum_mass = 0.0; cum_energy = 0.0; charges = 0; reserve = RESERVE_FRAC * usable_battery_j
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
        _leg(mission.charger)
        # EP-04: solar/power recharge only inside an illumination/power window -- otherwise idle at the
        # charger until the next window opens (a "wait" leg, no energy drawn); if none remains, infeasible.
        start_t, wait_s, reason = _window_gate(windows, "recharge", t)
        if reason is not None:
            infeasible.append(f"recharge at charger: {reason}")
            return False
        if wait_s > 0:
            tl.append(dict(t0=t, t1=start_t, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))   # parked, awaiting the recharge window
            t = start_t
        need = usable_battery_j - batt; dur = need / CHARGE_W
        tl.append(dict(t0=t, t1=t+dur, kind="charge", batt0=batt, batt1=usable_battery_j, mass=0.0, speed=0.0,
                       x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))  # parked at charger
        batt = usable_battery_j; t += dur; charges += 1
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
        e = d * DRIVE_J_PER_M; usable = usable_battery_j - reserve
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
        # EP-04: work (dig/offload/sinter) only inside an illumination/thermal window -- idle to the next
        # window before starting; if none remains the work cannot be performed (no mass/energy credited).
        start_t, wait_s, reason = _window_gate(windows, "work", t)
        if reason is not None:
            infeasible.append(f"{kind} at ({work_pos[0]:.0f},{work_pos[1]:.0f}): {reason}")
            return
        if wait_s > 0:
            tl.append(dict(t0=t, t1=start_t, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=work_pos[0], y0=work_pos[1], x1=work_pos[0], y1=work_pos[1]))
            t = start_t
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
        # EP-04: comms/teleop transit window -- the inter-site drive may only begin inside a "drive" window
        # (e.g. a relay-in-view pass). Idle to the next window; if none remains, the trip is unreachable.
        d_start, d_wait, d_reason = _window_gate(windows, "drive", t)
        if d_reason is not None:
            infeasible.append(f"transit to ({tr['site'][0]:.0f},{tr['site'][1]:.0f}): {d_reason}")
            per_trip.append(dict(trip=tr, t_start=t0, t_end=t)); continue
        if d_wait > 0:
            tl.append(dict(t0=t, t1=d_start, kind="wait", batt0=batt, batt1=batt, mass=0.0, speed=0.0,
                           x0=pos[0], y0=pos[1], x1=pos[0], y1=pos[1]))
            t = d_start
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


_CONSTRAINT_CAPS = {"max_time_s": "time_s", "max_energy_J": "energy_J",
                    "max_charges": "charges", "max_distance_m": "distance_m"}


def _constraint_penalty(core, constraints) -> float:
    """CP-08: the hard-constraint + risk penalty added to an ordering's score. A candidate whose simulated
    `core` overshoots a budget (max_time_s / max_energy_J / max_charges / max_distance_m) gets a LARGE
    penalty scaled by the fractional overshoot, so any constraint-feasible ordering ranks below an
    infeasible one is impossible -- feasible always wins, and among infeasible ones the least-overshooting
    is preferred. ``risk_weight`` adds a recharge-exposure cost (more recharges = more operational risk).
    Returns 0.0 when ``constraints`` is None/empty or nothing is violated (byte-identical default)."""
    if not constraints:
        return 0.0
    pen = 0.0
    for cap_key, metric in _CONSTRAINT_CAPS.items():
        cap = constraints.get(cap_key)
        if cap is not None and metric in core:
            v, c = float(core[metric]), float(cap)
            if v > c:
                pen += 1e6 * (1.0 + (v - c) / max(abs(c), 1e-9))   # big + overshoot-scaled (least-bad first)
    rw = constraints.get("risk_weight")
    if rw is not None and "charges" in core:
        pen += float(rw) * float(core["charges"])
    return pen


def _make_core_scorer(mission, trips, objective, routes=None):
    """Return a function core -> sortable scalar (lower = better). For a single objective this is the raw
    metric (max objectives negated). For a WEIGHTED multi-objective it is the weighted sum of each metric
    normalized by a reference plan (the nearest-neighbour order), so differently-scaled metrics combine.
    H-02: `routes` is threaded into the reference simulation so the normalization uses routed geometry too.
    CP-08: a mission-level hard-constraint + risk penalty is added on top (0 when unset -> byte-identical)."""
    weights = parse_objective(objective)
    cons = getattr(mission, "objective_constraints", None)
    if len(weights) == 1:
        (name,) = weights
        return lambda core: _score(core, name)[0] + _constraint_penalty(core, cons)
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
        return s + _constraint_penalty(core, cons)
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
    lander = mission.lander or tuple(mission.charger)
    lx, ly = float(lander[0]), float(lander[1])
    pts = [(float(o.x), float(o.y)) for o in mission.orders] + [tuple(mission.charger)]
    reach = LR.furthest_reach_from_lander_m((lx, ly), pts)
    usable_j = BATTERY_J * (1.0 - RESERVE_FRAC)
    blk = LR.return_to_lander_feasible(furthest_reach_m=reach, energy_spent_at_reach_j=0.0,
                                       battery_j=usable_j, drive_j_per_m=DRIVE_J_PER_M,
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


# ARCH-2: the multi-vehicle allocation + space-time conflict layer lives in planner_multivehicle
# (self-contained geometry over duck-typed per_vehicle/trip structures; no planner-core dep, no
# cycle). Re-exported so MP.<fn> + plan_multi keep working unchanged.
from lode.planner_multivehicle import (  # noqa: E402,F401
    _trip_work_e, _allocate_trips, _allocate_components, _allocate_precedence_split,
    _resolve_cross_vehicle_precedence, _vehicle_conflicts,
    _charger_conflicts, _resolve_charger_queue, _resolve_shared_resources, _temporal_conflicts,
    _seg_seg_min_dist, _haul_path_conflicts, _resolve_spacetime_crowding, _rover_health,
)

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
    # FL-03: the fleet shares ONE charger -> serialise overlapping recharges (FCFS single-server queue).
    # Each vehicle's real finish is its independent time + the wait it accrues queueing for the charger;
    # the headline makespan is the max of those. parallel_makespan keeps the optimistic (unlimited-charger)
    # value for reference, and charger_conflicts still reports how many overlaps the queue had to resolve.
    charger_delays = _resolve_charger_queue(per_vehicle, capacity=mission.charger_capacity)
    charger_wait_s = float(sum(charger_delays))
    # FL-03: declared shared resources (pit/dump/vantage/corridor) add capacity-k contention beyond the
    # charger; a rover waits for an over-capacity resource the same way it queues for the charger. With no
    # declared resources, resource_delays is all 0 -> makespan/survival are byte-identical to a non-reserved fleet.
    resource_delays, resource_waits = _resolve_shared_resources(per_vehicle, mission.shared_resources)
    resource_wait_s = float(sum(resource_delays))
    # FL-02 re-sequencing: deconflict space-time crowding + haul-path crossings by the same FCFS wait the
    # charger queue uses (the loser yields). No crowding -> all 0 -> makespan/survival byte-identical.
    crowd_delays = _resolve_spacetime_crowding(per_vehicle)
    crowd_wait_s = float(sum(crowd_delays))
    # FL-04: cross-vehicle precedence chain-splitting -- a dependent leg on one rover waits for its
    # predecessor leg on another rover (the chain is SPLIT, not forced onto one vehicle). Same per-vehicle
    # wait discipline as the charger/crowding resolvers. No cross-vehicle edge -> all 0 -> byte-identical.
    precedence_delays = _resolve_cross_vehicle_precedence(per_vehicle, alloc, glob_prec, trips)
    precedence_wait_s = float(sum(precedence_delays))
    makespan = max((pv["core"]["time_s"] + charger_delays[i] + resource_delays[i]
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
              keepouts=(), footprint_radius_m=0.0, illum_cost=None, illum_weight=1.0,
              map_unc_cost=None, map_unc_weight=1.0, return_terms=False):
    """P-06: terrain-aware route between two LOCAL sites, with the rover treated as a FINITE-SIZE body.

    When `footprint_radius_m` > 0 the impassable hazards (slope cap, drop-offs, keep-outs) are inflated by
    the rover's swept radius -- a corridor narrower than the rover is impassable even though a point rover
    could thread it (the audit's 'routing treats the vehicle as a point' defect). `footprint_radius_m=0`
    reproduces the point-rover route_leg exactly (byte-identical). Returns (routed_m, grid_straight_m,
    reached, waypoints) with the same contract as the point router. The endpoints themselves are not
    eroded (a site placed on a valid pad is reachable even if its immediate cell touches the inflation).

    SN-05: ``illum_cost`` (DEM-aligned (H, W) illumination route-cost field) + ``illum_weight`` thread
    through to the slope costmap exactly as in the point router -- a SEPARABLE, severity-weighted soft cost
    that biases the corridor toward lit cells. ``illum_cost=None`` (default) is byte-identical (OFF).

    PM-08/09: ``map_unc_cost`` (DEM-aligned (H, W) residual map-uncertainty field [m]) + ``map_unc_weight``
    thread through the same way -- a SEPARABLE, severity-weighted soft cost biasing the corridor toward
    well-observed, low-uncertainty cells. Independent of ``illum_cost`` (both compose additively).
    ``map_unc_cost=None`` (default) is byte-identical (OFF)."""
    if not footprint_radius_m or footprint_radius_m <= 0:
        return _route_leg_point(dem, dem_origin, a_xy, b_xy, max_slope_deg=max_slope_deg,
                                slip_alpha=slip_alpha, margin_m=margin_m, keepouts=keepouts,
                                illum_cost=illum_cost, illum_weight=illum_weight,
                                map_unc_cost=map_unc_cost, map_unc_weight=map_unc_weight,
                                return_terms=return_terms)
    Z, cell = dem
    ox, oy = dem_origin
    ax, ay = ox + a_xy[0], oy + a_xy[1]
    bx, by = ox + b_xy[0], oy + b_xy[1]
    H, W = Z.shape
    if illum_cost is not None and not isinstance(illum_cost, dict):
        illum_cost = np.asarray(illum_cost, float)
        if illum_cost.shape != Z.shape:
            raise ValueError(f"illum_cost shape {illum_cost.shape} must match the DEM shape {Z.shape}")
    elif isinstance(illum_cost, dict):
        for k, v in illum_cost.items():
            if k == "weights":
                continue
            if np.asarray(v).shape != Z.shape:
                raise ValueError(f"illum_cost['{k}'] shape {np.asarray(v).shape} must match the DEM shape {Z.shape}")
    if map_unc_cost is not None:
        map_unc_cost = np.asarray(map_unc_cost, float)
        if map_unc_cost.shape != Z.shape:
            raise ValueError(f"map_unc_cost shape {map_unc_cost.shape} must match the DEM shape {Z.shape}")
    straight = math.hypot(bx - ax, by - ay)
    m = float(margin_m)
    while True:
        c0 = max(0, int((min(ax, bx) - m) / cell))
        c1 = min(W, int((max(ax, bx) + m) / cell) + 1)
        r0 = max(0, int((min(ay, by) - m) / cell))
        r1 = min(H, int((max(ay, by) + m) / cell) + 1)
        if c1 - c0 < 2 or r1 - r0 < 2:
            return (straight, straight, False, [], {}) if return_terms else (straight, straight, False, [])
        crop = Z[r0:r1, c0:c1]
        illum_crop = _crop_illum(illum_cost, r0, r1, c0, c1)   # SN-05: same window (array OR per-term dict)
        map_unc_crop = None if map_unc_cost is None else map_unc_cost[r0:r1, c0:c1]   # PM-08/09: same window
        cost, passable, terms = slope_costmap(crop, cell, max_slope_deg=max_slope_deg, slip_alpha=slip_alpha,
                                              max_drop_m=MAX_DROP_M, illum=illum_crop, illum_weight=illum_weight,
                                              map_unc=map_unc_crop, map_unc_weight=map_unc_weight,
                                              return_terms=True)
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
            if return_terms:
                breakdown = {name: [float(layer[r, c]) for (r, c) in path] for name, layer in terms.items()}
                return length_m, grid_straight, True, waypoints, breakdown
            return length_m, grid_straight, True, waypoints
        if c0 == 0 and c1 == W and r0 == 0 and r1 == H:
            return (straight, straight, False, [], {}) if return_terms else (straight, straight, False, [])
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
