"""ARCH-2 (#123): the rover ENDURANCE / range / power-regime analytics, extracted from
lode.mission_planner.

Single-charge driving range (flat + slope/slip), the DEM-grounded reachable-radius field, the per-site
power model + thermal derating, the mission-scale endurance report, and the conserved-ladder
slip_alpha_to_slip used by the haul-energy estimator. A leaf: it imports only stewie.specs/physics +
the dependency-neutral lode.planner_constants + the lower leaves lode.planner_routing (costmap helpers)
and lode.planner_model (body/context helpers); it NEVER imports lode.mission_planner, so it introduces
no cycle. mission_planner re-exports every name here, so MP.endurance / MP.slip_alpha_to_slip / the
haul code's `slip_alpha_to_slip` call sites stay byte-identical.
"""
# PROVENANCE: STEWIE LODE subsystem (A. Storey)
from __future__ import annotations

import heapq
import math

import numpy as np

from stewie.specs import ipex_specs as S            # IPEx ConOps traverse/regolith/mission figures
from stewie.specs import constants as C              # default gravity for the slip ladder
from stewie.physics import slip as TMS               # conserved slip ladder -- weight-aware leg slip
from lode.planner_constants import (
    BATTERY_J, CHARGE_W, DRIVE_J_PER_M, RESERVE_FRAC, ROVER_MASS_KG, SLIP_ALPHA, _TM_PARAMS,
)
from lode.planner_routing import _ROUTE_NB, slope_deg_map  # costmap neighborhood + slope map (leaf)
from lode.planner_model import body_gravity, body_timescale, mission_soil_params, plan_context


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
                                               drive_j_per_m=DRIVE_J_PER_M,   # F10: the SELECTED vehicle's per-metre
                                               rover_mass_kg=ROVER_MASS_KG)   # H-01: vehicle usable + mass + drive cost
    return out


def slip_alpha_to_slip(slope_deg, payload_kg=0.0, g=None, params=None, rover_mass_kg=None, density=None):
    """Wheel slip from terrain slope AND the rover's laden weight, via the CONSERVED slip ladder
    (slip.slip_sinkage_equilibrium): a steeper grade OR a heavier rover (full drum) -> more slip,
    entrapping near ~45 deg. ``payload_kg`` is the regolith in the drum on this leg (0 = empty); ``g``
    defaults to lunar. This replaces the old slope-only [CALIB] curve so the planner's per-leg slip (and
    the 1/(1-slip) drive-energy inflation) is weight-coupled, consistent with the simulator authority.
    H-01: ``rover_mass_kg`` defaults to the IPEx global; pass the selected vehicle's mass so a heavier
    platform (rassor2, 65 kg) slips more. (The per-cell routing costmap keeps the SLIP_ALPHA*tan heuristic.)
    #242 1b: ``density`` is the per-cell regolith density [kg/m^3] WHERE this leg traverses; it stiffens
    BEARING (less sinkage -> less slip) via the same grounded density_stiffening relation the simulator
    drive loop uses (terramechanics.density_stiffening, consumed inside slip_sinkage_equilibrium). None ->
    the uniform surface density (factor 1), so absent/uniform terrain is byte-identical to before."""
    gg = C.g if g is None else float(g)
    p = params if params is not None else _TM_PARAMS     # soil model (params_for_body(soil)); default lunar
    m = ROVER_MASS_KG if rover_mass_kg is None else float(rover_mass_kg)
    weight_n = (m + max(0.0, payload_kg)) * gg
    eq = TMS.slip_sinkage_equilibrium(weight_n, math.radians(max(0.0, slope_deg)),
                                      params=p, contact_len_m=0.10, contact_width_m=0.18, density=density)
    return max(0.0, min(0.95, float(eq["slip"])))
