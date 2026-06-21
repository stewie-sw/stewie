"""CP-07 (PRD §27.2.D): the SEPARABLE per-source plan-uncertainty model.

The core ``mission_planner._plan_uncertainty`` block aggregates the named uncertainty sources but
honestly leaves the *slip* term ``quantified: False`` -- "slip term un-quantified" is the open item.
This module closes it: a separable model that propagates each NAMED contribution into the plan's
reported energy band, where each contribution is independently inspectable and is sourced from a REAL
in-repo model / [CALIB] envelope -- NO fabricated sigmas.

The headline source is **slip**, quantified from the load-bearing Janosi-Hanamoto slip ladder
(``stewie.physics.slip.slip_sinkage_equilibrium``) swept over the SOURCED soil-traction [CALIB]
envelope (cohesion 0.1-1.0 kPa, internal friction 30-50 deg; constants.py §5.2). Re-driving each
cut->fill haul leg's ``1/(1-slip)`` drive-energy inflation at the soft and firm ends of that
envelope gives an honest energy band: it is ~ZERO on a flat haul (the real model develops ~0 slip
with no grade) and NON-ZERO on sloped terrain. The other sources reuse already-grounded figures
(the dig-rate energy band, the EP-02 operator material factor, the localization corridor margin, the
DEM per-cell sigma, the DrumSensor FDC cycle band).

This is a read-only VIEW over a finished ``PlanResult`` (RB-03): it never re-solves the plan and
never mutates the plan totals; ``mission_planner`` re-exports it lazily as ``plan_uncertainty_view``
so the existing planner outputs are byte-identical when the band is not requested.

The composite band is the honest ROOT-SUM-OF-SQUARES of the independent energy-channel
contributions -- independent errors add in quadrature, not linearly, so the composite never
over-states (no false precision; PRD risk note).
"""
from __future__ import annotations

import dataclasses
import math

from stewie.physics import slip as TMS
from stewie.physics import rassor_mass_model as RM

# ---------------------------------------------------------------------------------------------------
# The SOURCED soil-traction [CALIB] envelope (constants.py §5.2, the documented ranges). Slip on a
# slope is set by the Coulomb-Mohr traction budget c*A + N*tan(phi); a soft, low-cohesion / low-phi
# soil slips MORE (the "soft" end), a firm high-cohesion / high-phi soil slips LESS ("firm" end). We
# sweep the budget across these endpoints -- no fabricated spread, the published envelope itself.
# ---------------------------------------------------------------------------------------------------
COHESION_SOFT_PA = 100.0     # 0.1 kPa  (constants.py: c 0.1-1.0 kPa)
COHESION_FIRM_PA = 1000.0    # 1.0 kPa
PHI_SOFT_DEG = 30.0          # constants.py: phi 30-50 deg
PHI_FIRM_DEG = 50.0
_ENVELOPE_SOURCE = ("soil-traction [CALIB] envelope, constants.py §5.2 "
                    "(cohesion 0.1-1.0 kPa, internal friction 30-50 deg)")


def _soil_at(base, *, cohesion, phi_deg):
    """The base soil params with the traction-budget knobs (cohesion, friction angle) set to an
    envelope endpoint. Everything else (Bekker moduli, slip-sinkage coeffs) stays the nominal soil."""
    return dataclasses.replace(base, cohesion=float(cohesion), phi_rad=math.radians(float(phi_deg)))


def _leg_slip(slope_deg, *, payload_kg, g, soil, rover_mass_kg):
    """Wheel slip on one haul leg at the given soil, via the real slip ladder (the same call the
    planner uses in ``slip_alpha_to_slip``). Clamped to [0, 0.95] exactly as the planner clamps it."""
    weight_n = (float(rover_mass_kg) + max(0.0, float(payload_kg))) * float(g)
    eq = TMS.slip_sinkage_equilibrium(weight_n, math.radians(max(0.0, float(slope_deg))),
                                      params=soil, contact_len_m=0.10, contact_width_m=0.18)
    return max(0.0, min(0.95, float(eq["slip"])))


def _haul_energy_for_soil(dem, dem_origin, route, *, loads, drum_kg, g, soil, drive_j_per_m,
                          rover_mass_kg):
    """Round-trip drive ENERGY [J] of one cut->fill haul along its routed polyline, integrated
    segment-by-segment with the per-segment slip evaluated at ``soil`` -- the loaded outbound and the
    empty return paid separately. This MIRRORS ``mission_planner._segmented_haul_energy`` exactly but
    is parameterized over the soil so we can re-drive the same haul at the envelope endpoints. Returns
    None when the route has too few on-grid samples (caller falls back to the endpoint estimate)."""
    Z, cell = dem
    ox, oy = dem_origin
    H, W = Z.shape

    def _z(x, y):
        c, r = int(round((ox + x) / cell)), int(round((oy + y) / cell))
        return float(Z[r, c]) if (0 <= r < H and 0 <= c < W) else None

    pts = []
    for (x, y) in route:
        z = _z(x, y)
        if z is not None:
            pts.append((x, y, z))
    if len(pts) < 2:
        return None

    def _dir_energy(seq, payload_kg):
        e = 0.0
        for (x0, y0, z0), (x1, y1, z1) in zip(seq, seq[1:]):
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len <= 1e-9:
                continue
            slope_deg = math.degrees(math.atan2(abs(z1 - z0), seg_len))
            slip = _leg_slip(slope_deg, payload_kg=payload_kg, g=g, soil=soil,
                             rover_mass_kg=rover_mass_kg)
            e += seg_len * drive_j_per_m / (1.0 - slip)
        return e

    out_e = _dir_energy(pts, drum_kg)
    back_e = _dir_energy(list(reversed(pts)), 0.0)
    return (out_e + back_e) * loads


def _route_for_trip(routes, trip):
    """Match a cut->fill trip to its routed polyline by endpoints (the routes are stored in the plan
    totals as {from_xy, to_xy, waypoints, reached}). Returns the waypoint list, or None."""
    site = tuple(trip.get("site", ()))
    dest = tuple(trip.get("dest", ()))

    def _close(a, b):
        return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6

    for rt in routes or ():
        if not rt.get("reached"):
            continue
        wp = rt.get("waypoints") or []
        if len(wp) >= 2 and _close(tuple(rt.get("from_xy", ())), site) \
                and _close(tuple(rt.get("to_xy", ())), dest):
            return [(float(x), float(y)) for x, y in wp]
    return None


def slip_energy_band(result, *, dem=None, dem_origin=(0.0, 0.0)):
    """The slip term's contribution to the plan's drive ENERGY, quantified from the real slip ladder
    over the sourced soil-traction [CALIB] envelope. Returns {nominal_J, band_J=(lo,hi), quantified,
    per_trip}. On flat terrain every leg develops ~0 slip so lo==hi==nominal (a degenerate, honest
    zero band); on sloped terrain the soft/firm soil endpoints bracket the nominal."""
    from lode import mission_planner as MP   # deferred: avoids an import cycle (MP re-exports this view)

    mission = result.mission
    g = MP.body_gravity(mission.body)
    base_soil = MP.mission_soil_params(mission)
    ctx = MP.plan_context(mission)
    drum_kg = ctx.drum_kg
    drive_j_per_m = ctx.drive_j_per_m
    rover_mass_kg = ctx.rover_mass_kg
    soft = _soil_at(base_soil, cohesion=COHESION_SOFT_PA, phi_deg=PHI_SOFT_DEG)
    firm = _soil_at(base_soil, cohesion=COHESION_FIRM_PA, phi_deg=PHI_FIRM_DEG)

    routes = (result.totals.get("routes") or []) if dem is not None else []
    nominal = lo = hi = 0.0
    per_trip = []
    for tr in result.trips:
        if tr.get("kind") != "cutfill" or not tr.get("haul_m"):
            continue
        loads = max(1, math.ceil(float(tr["mass"]) / drum_kg))
        n_haul = float(tr.get("haul_e", 0.0))      # the planner's nominal (segment-integrated) haul energy
        route = _route_for_trip(routes, tr) if dem is not None else None
        if route is not None:
            soft_e = _haul_energy_for_soil(dem, dem_origin, route, loads=loads, drum_kg=drum_kg, g=g,
                                           soil=soft, drive_j_per_m=drive_j_per_m,
                                           rover_mass_kg=rover_mass_kg)
            firm_e = _haul_energy_for_soil(dem, dem_origin, route, loads=loads, drum_kg=drum_kg, g=g,
                                           soil=firm, drive_j_per_m=drive_j_per_m,
                                           rover_mass_kg=rover_mass_kg)
        else:
            soft_e = firm_e = None
        if soft_e is None or firm_e is None:
            # no routed polyline (no-DEM straight line / too few on-grid samples): the slip envelope
            # cannot be re-driven on real grade, so this trip contributes a degenerate band at nominal
            # (honest: we do NOT fabricate a slope-driven spread where there is no grade to drive it).
            t_lo = t_hi = n_haul
        else:
            t_lo, t_hi = sorted((firm_e, soft_e))   # firm soil -> less slip -> less energy (low end)
        nominal += n_haul
        lo += t_lo
        hi += t_hi
        per_trip.append({"label": tr.get("label", "?"), "nominal_J": round(n_haul, 1),
                         "band_J": [round(t_lo, 1), round(t_hi, 1)]})
    quantified = (hi - lo) > 1e-6
    return {"nominal_J": round(nominal, 1), "band": [round(lo, 1), round(hi, 1)],
            "quantified": bool(quantified), "into": "energy", "per_trip": per_trip,
            "source": _ENVELOPE_SOURCE}


def _dig_rate_band_j(result):
    """The dig-rate energy band [J] (rated-18 vs max-25 RPM, T2.4) -- already on the plan totals as
    ``dig_energy_bounds_MJ``; re-expressed in J as a (lo, hi) energy band about the dig energy."""
    band_mj = result.totals.get("dig_energy_bounds_MJ")
    if not band_mj:
        return None
    lo, hi = sorted(float(b) * 1e6 for b in band_mj)
    return (lo, hi)


def per_source_uncertainty(result, *, dem=None, dem_origin=(0.0, 0.0)):
    """CP-07: the SEPARABLE per-source uncertainty model. Each named contribution
    (slip, dig_rate, energy_estimate, localization, terrain, drum_fill) is independently inspectable;
    a contribution carries a numeric ``band`` ONLY where grounded in a real in-repo model / [CALIB]
    envelope -- never a fabricated fraction. The energy-channel contributions combine into one
    composite energy band as the honest ROOT-SUM-OF-SQUARES of their half-widths (independent errors
    add in quadrature). A read-only view over the finished plan; does not mutate the plan totals."""
    from lode import mission_planner as MP   # deferred (cycle break)

    mission = result.mission
    totals = result.totals

    # --- slip: the headline, quantified from the real Janosi-Hanamoto ladder over the soil envelope --
    slip = slip_energy_band(result, dem=dem, dem_origin=dem_origin)

    # --- dig_rate: the drum rated-vs-max RPM energy band (T2.4) -------------------------------------
    dig_band = _dig_rate_band_j(result)
    dig_rate = ({"quantified": True, "into": "energy", "band": [round(dig_band[0], 1), round(dig_band[1], 1)],
                 "nominal_J": round(0.5 * (dig_band[0] + dig_band[1]), 1),
                 "source": "drum rated-18 vs max-25 RPM dig-rate band (T2.4)"}
                if dig_band is not None else
                {"quantified": False, "into": "energy", "note": "no dig mass in this plan"})

    # --- energy_estimate: the EP-02 operator material-difficulty factor on the dig energy (J/kg) -----
    mat = float(getattr(mission, "dig_energy_factor", None) or 1.0)
    dig_energy_j = float(sum(tr.get("dig_e", 0.0) for tr in result.trips))
    if mat != 1.0 and dig_energy_j > 0.0:
        # the factor scaled the dig energy; the uncertainty it represents is the swing back to the
        # baseline (factor 1.0) -- a real, operator-declared band about the as-planned dig energy.
        baseline_j = dig_energy_j / mat
        e_lo, e_hi = sorted((baseline_j, dig_energy_j))
        energy_estimate = {"quantified": True, "into": "energy", "band": [round(e_lo, 1), round(e_hi, 1)],
                           "nominal_J": round(dig_energy_j, 1), "dig_energy_factor": mat,
                           "source": "EP-02 operator material-difficulty factor on dig energy"}
    else:
        energy_estimate = {"quantified": False, "into": "energy", "dig_energy_factor": mat,
                           "note": "no operator material factor -> baseline dig energy"}

    # --- localization: the P-06 corridor margin (a feasibility-channel band, not energy) ------------
    localization = {"quantified": True, "into": "feasibility",
                    "corridor_margin_m": MP.LOCALIZATION_MARGIN_M,
                    "source": "P-06 localization corridor margin"}

    # --- terrain: the DEM per-cell sigma (a feasibility-channel band, not energy) -------------------
    terrain = {"quantified": True, "into": "feasibility", "cell_sigma_m": 0.05,
               "source": "PM-09 DEM per-cell elevation sigma"}

    # --- drum_fill: the DrumSensor FDC MPE cycle band (a TIME-channel band, not energy) ------------
    nc = float(totals.get("drum_cycles", 0) or 0)
    mpe = float(RM.FDC_MPE_HALF_FULL)
    drum_fill = ({"quantified": True, "into": "time", "mpe_frac": mpe, "cycles": nc,
                  "band": [round(nc * (1.0 - mpe), 2), round(nc * (1.0 + mpe), 2)],
                  "source": "DrumSensor FDC MPE, ICE-RASSOR NTRS 20210022781"}
                 if nc > 0 else
                 {"quantified": False, "into": "time",
                  "note": "no drum cycles in this plan -> no fill-driven band"})

    sources = {"slip": slip, "dig_rate": dig_rate, "energy_estimate": energy_estimate,
               "localization": localization, "terrain": terrain, "drum_fill": drum_fill}

    # --- composite: honest RSS of the independent ENERGY-channel half-widths ------------------------
    energy_nominal = float(totals.get("energy_J", 0.0))
    halves = [0.5 * (s["band"][1] - s["band"][0])
              for s in sources.values() if s.get("quantified") and s.get("into") == "energy"]
    comp_half = math.sqrt(sum(h * h for h in halves))
    composite = {
        "energy_J_nominal": round(energy_nominal, 1),
        "energy_J_band": [round(energy_nominal - comp_half, 1), round(energy_nominal + comp_half, 1)],
        "half_width_J": round(comp_half, 1),
        "combination": "root-sum-of-squares of independent energy-channel sources (no false precision)",
        "contributing_sources": [k for k, s in sources.items()
                                 if s.get("quantified") and s.get("into") == "energy"],
    }
    return {"sources": sources, "composite": composite}
