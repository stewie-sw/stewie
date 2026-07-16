"""ARCH-2 (#123): the mission DATA MODEL + order compilation, extracted from lode.mission_planner.

The PlanningContext / BuildOrder / Mission dataclasses, the body / footprint / vehicle model helpers,
and mission_from_dict (the browser build-queue -> Mission validator) -- the foundational leaf every
other planner cluster depends on. Imports only stewie.specs/physics + the dependency-neutral
lode.planner_constants + the pure lode.lander_return; it NEVER imports lode.mission_planner, so it
introduces no import cycle. mission_planner re-exports every name here, so ``MP.Mission`` and
``from lode.mission_planner import Mission`` stay byte-identical for all dependents.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import dataclasses
import json
import math
import os

from stewie.specs import ipex_specs                 # #273: gravity-aware lunar drive power (not the Earth-test draw)
from stewie.specs import vehicles as V             # vehicle/tool capability registry (gate order kinds)
from stewie.physics import validation as VAL        # RB-01: physical-domain validation at this input boundary
from stewie.specs.bodies import get_body as _get_body, params_for_body  # soil model (soil override)
from lode import lander_return as LR                # #161; pure module, no cycle
from lode.mission_schema import migrate_mission     # PO-09: version-migrate a mission artifact before parse
from lode.planner_constants import (
    BATTERY_J, CHARGE_W, DRIVE_SPEED_MS, LOCALIZATION_MARGIN_M, RESERVE_FRAC, _CONSTRAINT_CAPS,
)


def _drum_kg(mission):
    """RB-05: the per-cycle drum capacity [kg] of the mission's SELECTED vehicle (VehicleModel-driven),
    so vehicle choice changes the planner numbers (loads / drum cycles / haul energy). The default
    vehicle 'ipex' has drum_capacity_kg == DRUM_KG == 30, so an unspecified mission is byte-identical."""
    return float(V.get_vehicle(mission.vehicle).drum_capacity_kg)


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
        # #273: the FLAT per-metre drive ENERGY is the gravity-aware lunar tractive draw at the mission's
        # body g (lunar_drive_power_w), NOT the Earth-test Table-3 motor draw (veh.drive_power_w, ~40 W,
        # which over-estimates the lunar flat-drive ~6x). For an ipex Moon mission this == the module
        # drive_energy_per_m() default (byte-identical); a higher-g body costs proportionally more. The
        # per-segment slope/soil effect enters via slip in _segmented_haul_energy, so this is slope=0.
        # drive_power_w stays the raw spec (offload energy uses it).
        drive_j_per_m=ipex_specs.lunar_drive_power_w(
            slope_deg=0.0, mass_kg=float(veh.dry_mass_kg), g_ms2=body_gravity(mission.body)) / DRIVE_SPEED_MS,
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
    #: task #78 Part C: the ACTUAL in-situ bulk density [kg/m^3] of the cut material at this cell, when the
    #: conserved authority knows it (column_state per-cell density / a compacted haul-road cell / a DEM
    #: material sample). None -> lode.planner_balance falls back to the depth-averaged loose-over-dense
    #: in-situ profile, so a shallow near-surface cut is NOT costed at the deep RHO_DEEP density.
    insitu_density_kg_m3: float | None = None
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
    #: FL-07: declared RAISED OBSERVATIONS (Solar/Meerkat vantage holds) the fleet deconflicts, as a list
    #: of {vehicle, x, y, t_start, t_end, kind}. A raised observation (an Observe action is lowered to the
    #: raised MEERKAT posture -- stewie.bridge.plan_lowering; a solar fix is a raised sun sight --
    #: dart.solar_observation) claims a capacity-1 VANTAGE for its window; two observations within the
    #: exclusion radius of each other CONFLICT (occlusion/collision) and the loser WAITS (FCFS, like the
    #: charger queue), the wait folding into the makespan. None/empty, or single-vehicle -> byte-identical.
    observations: list | None = None
    #: EP-02: operator material-difficulty multiplier on the dig energy. The baseline dig model is a CONSTANT
    #: J/kg (ipex_specs.dig_energy_per_kg, calibrated to BP-1 dry simulant -- material/density/ice-INDEPENDENT,
    #: with the drum-rate (0.72-1.0)x band the planner already reports as dig_energy_bounds_MJ). Physical
    #: auto-derivation of dig energy from density/ice is UNMODELED; this factor lets an operator scale it for
    #: a known harder/icier site (>1) so the plan's dig energy DEPENDS on the declared material. None -> 1.0
    #: -> byte-identical to the constant baseline.
    dig_energy_factor: float | None = None
    #: CP-04: the as-built FLATNESS acceptance tolerance [m] the conserved-authority acceptance gate
    #: (validate_plan) measures the worked footprints against (as-built RMSE <= tol -> as_built_pass).
    #: Compiled from the mission objectives' structured acceptance tolerance (MO-01
    #: AcceptanceCriterion.tolerance_m, tightest over objectives). None -> validate_plan keeps its
    #: documented default (byte-identical to a pre-CP-04-tolerance plan).
    accept_flatness_tol_m: float | None = None
    #: PX-02: the SELECTABLE physics backend the plan's terramechanics run on (stewie.physics.backend).
    #: Default "tier2_numpy" = the conserved Tier-2 NumPy authority, the only registered/selectable engine
    #: (the PX-03 Chrono oracle is NOT release-authority until it conserves mass, so it is not selectable
    #: here). Validated against list_backends() at the mission_from_dict boundary; carried into the plan so
    #: plan/report/release evidence names the physics engine. A default mission is byte-identical.
    physics_backend_id: str = "tier2_numpy"
    @property
    def density(self): return body_density(self.body)


def mission_soil_params(mission):
    """The TerramechanicsParams (soil/Bekker model) a mission's drive physics uses: its `soil` override
    (any body's regolith, e.g. Earth dry-sand on a lunar map) or the body's own when no override is set.
    Gravity stays the body's (see body_gravity) -- soil and gravity are independent (terramechanics.py)."""
    return params_for_body(mission.soil or mission.body)


_ORDER_KINDS = ("cut", "fill", "sinter", "goto")   # goto = S-3 path waypoint (zero mass, sequenced)
_ORDER_FIELDS = ("action", "kind", "x", "y", "footprint_m2", "depth_m")
# #305: cap a polygon keep-out's vertex count at the boundary. _apply_keepouts (planner_routing) runs an
# O(vertices) point-in-polygon for EVERY bbox cell on the real 2000x2000 DEM, re-run by the adaptive-window
# retry, so an unbounded vertex list (a 4 MiB body can encode ~1e5 verts) is an O(cells x verts) routing
# DoS. A real keep-out is a simple footprint; 256 verts is generous.
_MAX_KEEPOUT_VERTS = 256
#: order kind -> the vehicle capability it requires (vehicles.ACTIONS). The fleet (selected vehicle +
#: mounted tools) must have it or the order is refused -- e.g. sinter needs the separate sinter Tool.
KIND_CAPABILITY = {"cut": "excavate", "fill": "dump", "sinter": "sinter"}


def _require_xy(val, name):
    """#284: validate a 2-element [x, y] (charger/lander) BEFORE indexing, so a malformed shape (a scalar,
    a 1-element list, null, a string) is a clean ValueError (-> 400 at the route) rather than an uncaught
    IndexError/TypeError 500. ensure_finite_scalar then rejects NaN/Inf/non-numeric values."""
    if not (isinstance(val, (list, tuple)) and len(val) == 2):
        raise ValueError(f"{name} must be a 2-element [x, y]; got {val!r}")
    return (VAL.ensure_finite_scalar(val[0], f"{name} x"), VAL.ensure_finite_scalar(val[1], f"{name} y"))


def mission_from_dict(payload):
    """Build a Mission from a JSON-style dict (the browser's build-order queue: see index.html).

    Validates the body against bodies.json and every order's required fields + kind; raises ValueError
    on malformed input (NO silent defaults for the physics inputs). Sinter orders are accepted here but
    refused downstream in plan_and_simulate while the gate is off (see constants.SINTER_ENABLED)."""
    if not isinstance(payload, dict):
        raise ValueError("mission payload must be a JSON object")
    # PO-09: upgrade a prior-version mission artifact to the current schema_version before validation
    # (an unversioned payload -- the genuine legacy wire format -- is walked forward; an unknown version
    # is a clear "no migration path" 400). Additive + byte-identical for today's unversioned payloads.
    payload = migrate_mission(payload)
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
    # PX-02: the SELECTABLE physics backend (stewie.physics.backend). Absent -> tier2_numpy (the conserved
    # default). Validated against the REGISTERED engines here (fail-closed, NO silent default for a bad id):
    # an unknown or not-yet-registered backend (e.g. the PX-03 Chrono oracle) is a 400 at the route, not 500.
    from stewie.physics.backend import list_backends as _list_backends
    pbid = str(payload.get("physics_backend_id") or "tier2_numpy").strip() or "tier2_numpy"
    if pbid not in _list_backends():
        raise ValueError(
            f"unknown/unselectable physics_backend_id {pbid!r}; selectable: {_list_backends()} "
            f"(the PX-03 Chrono oracle is not a release-authority backend until it conserves mass)")
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
            shape=(o.get("shape") if o.get("kind") != "goto" else None),
            insitu_density_kg_m3=(   # task #78 Part C: optional real in-situ density of the cut material
                VAL.ensure_positive_scalar(o["insitu_density_kg_m3"], f"order {i} insitu_density_kg_m3")
                if o.get("insitu_density_kg_m3") is not None else None)))
    c = payload.get("charger", (0.0, 0.0))
    kwargs = dict(name=str(payload.get("name", "Build Mission")), body=body, orders=orders,
                  charger=_require_xy(c, "charger"),       # #284: shape-validate before indexing (bad shape -> 400)
                  charger_capacity=max(1, min(8, int(payload.get("charger_capacity", 1) or 1))),
                  vehicle=veh, tools=tools, soil=soil, physics_backend_id=pbid)
    if "date" in payload:
        kwargs["date"] = str(payload["date"])
    if payload.get("lander") is not None:                  # #161: the delivery lander (safe haven)
        kwargs["lander"] = _require_xy(payload["lander"], "lander")   # #284: shape-validate (bad shape -> 400)
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
                if not (3 <= len(pts) <= _MAX_KEEPOUT_VERTS):   # #305: upper bound -> no O(cells x verts) routing DoS
                    raise ValueError(f"keepout {j} polygon needs 3..{_MAX_KEEPOUT_VERTS} vertices (got {len(pts)})")
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
    ob = payload.get("observations")                       # FL-07: declared raised Solar/Meerkat observations
    if ob is not None:
        if not isinstance(ob, (list, tuple)):
            raise ValueError("'observations' must be a list of {vehicle, x, y, t_start, t_end, kind}")
        allowed_obs = {"meerkat", "solar"}                 # the two raised-observation classes (FL-07)
        clean_ob = []
        for n, o in enumerate(ob):
            if not isinstance(o, dict):
                raise ValueError(f"observations[{n}] must be an object")
            veh = o.get("vehicle")
            if not isinstance(veh, int) or isinstance(veh, bool) or veh < 0:
                raise ValueError(f"observations[{n}] vehicle must be an int >= 0 (got {veh!r})")
            okind = o.get("kind", "meerkat")               # an Observe lowers to the raised MEERKAT posture
            if okind not in allowed_obs:
                raise ValueError(f"observations[{n}] kind {okind!r}; allowed: {sorted(allowed_obs)}")
            for key in ("x", "y", "t_start", "t_end"):
                if key not in o:
                    raise ValueError(f"observations[{n}] needs '{key}'")
            ox = VAL.ensure_finite_scalar(o["x"], f"observations[{n}].x")
            oy = VAL.ensure_finite_scalar(o["y"], f"observations[{n}].y")
            ot0 = VAL.ensure_finite_scalar(o["t_start"], f"observations[{n}].t_start")
            ot1 = VAL.ensure_finite_scalar(o["t_end"], f"observations[{n}].t_end")
            if ot1 <= ot0:
                raise ValueError(f"observations[{n}] window must have t_end > t_start (got [{ot0}, {ot1}))")
            clean_ob.append({"vehicle": veh, "x": ox, "y": oy, "t_start": ot0, "t_end": ot1, "kind": okind})
        if clean_ob:
            kwargs["observations"] = clean_ob
    df = payload.get("dig_energy_factor")                  # EP-02: operator material-difficulty multiplier
    if df is not None:
        fv = VAL.ensure_finite_scalar(df, "dig_energy_factor")
        if fv <= 0:
            raise ValueError(f"'dig_energy_factor' must be > 0 (got {fv})")
        kwargs["dig_energy_factor"] = fv
    aft = payload.get("accept_flatness_tol_m")             # CP-04: compiled as-built acceptance tolerance
    if aft is not None:
        tv = VAL.ensure_finite_scalar(aft, "accept_flatness_tol_m")
        if tv <= 0:
            raise ValueError(f"'accept_flatness_tol_m' must be > 0 (got {tv})")
        kwargs["accept_flatness_tol_m"] = tv
    return Mission(**kwargs)


def _d(a, b): return math.hypot(a[0] - b[0], a[1] - b[1])
