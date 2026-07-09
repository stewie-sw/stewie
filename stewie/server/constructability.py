"""[REQ:SD-01] Per-structure CONSTRUCTABILITY EVIDENCE from the REAL decompose orders + the terramechanics
spine -- the evidence the Surface-Design authoring surface needs before a structure is staged.

Nothing here is fabricated. Three real sources:

  * VOLUME / MASS -- straight from the mass-balanced cut/fill orders leap.structures.decompose issues
    (volume = footprint_m2 x depth_m, exact from the order; mass = volume x the conserved bank(cut)/loose
    (fill) regolith density profile, stewie.specs.constants). A fill consumes exactly the paired cut's bank
    mass, so a balanced structure's cut and fill masses match by construction.

  * LOCAL TERRAMECHANICS -- bearing (applied wheel contact pressure vs the FORGE Terzaghi/Vesic allowable
    soil bearing capacity) + expected sinkage/slip from the terramechanics spine (stewie.physics.sinkage /
    slip) evaluated at the structure's SITE SLOPE. This is the SAME spine solve the physics globe drape uses
    (stewie/server/gis_layers.py `_terra_fields`), so the per-structure verdict matches the bearing/sinkage
    layers the operator sees on the map.

  * A DERIVED constructability VERDICT -- constructable iff the rover does not entrap at the site slope AND
    the expected sinkage stays within the wheel-radius mobility limit AND the applied contact pressure stays
    within the allowable bearing capacity. The status string names which check drives the verdict; every
    number comes from the spine / forge / order, never a hand-picked constant.

The volume/mass estimates carry their DEM resolution, material (density) assumption, and the spine terms'
calibration status (the honest uncertainty) so the evidence is self-describing.
"""
from __future__ import annotations

import math

from lode.planner_balance import insitu_bank_density   # task #78: per-cut depth-averaged in-situ bank density
from stewie.specs import constants as K
from stewie.specs import ipex_specs as IPX

#: conserved regolith density profile (the SAME source leap.structures balances mass on).
RHO_BANK = float(K.RHO_DEEP)    # in-situ (cut) bulk density [kg/m^3]
RHO_LOOSE = float(K.RHO_SPOIL)  # loose placed (fill) spoil density [kg/m^3]

#: the contact patch the terramechanics-spine physics-layer fields use (gis_layers._terra_fields) -- reuse it
#: verbatim so the per-structure bearing/sinkage matches the globe drape's per-cell field.
_CONTACT_LEN_M = 0.10
_CONTACT_WIDTH_M = 0.18

#: mobility sinkage limit: sinkage past the wheel radius buries the hub and immobilizes the rover (a real
#: geometric limit from the sourced IPEx wheel, not a hand-picked threshold).
_SINKAGE_LIMIT_M = float(IPX.WHEEL_RADIUS_M)

#: standard shallow-foundation factor of safety (Das/Bowles) -- the same default the plan acceptance uses.
_BEARING_FS = 3.0


def order_earthwork(orders: list[dict]) -> dict:
    """Volume [m^3] + mass [kg] per decomposed order + cut/fill totals.

    volume = footprint_m2 x depth_m (exact from the order); mass = volume x the conserved bank(cut)/loose
    (fill) density. A balanced structure's cut mass == fill mass (a fill consumes exactly the paired cut's
    bank mass), so ``mass_balanced`` confirms the decompose is volume-conserved."""
    per: list[dict] = []
    cut_vol = fill_vol = cut_mass = fill_mass = 0.0
    for o in orders:
        footprint = float(o["footprint_m2"])
        depth = float(o["depth_m"])
        vol = footprint * depth
        is_cut = o["kind"] == "cut"
        # task #78: cost a CUT at its PER-CUT depth-averaged in-situ bank density (shallow surface cut ~RHO_LOOSE,
        # deep cut -> RHO_BANK ceiling), the SAME density the planner (lode.planner_balance) uses -- not a flat
        # RHO_BANK that over-states a shallow scrape and reads a balanced structure as a phantom deficit.
        rho = insitu_bank_density(depth, RHO_LOOSE) if is_cut else RHO_LOOSE
        mass = vol * rho
        per.append({
            "action": o.get("action", ""), "kind": o["kind"],
            "footprint_m2": round(footprint, 3), "depth_m": round(depth, 4),
            "volume_m3": round(vol, 4), "mass_kg": round(mass, 1), "density_kg_m3": rho,
        })
        if is_cut:
            cut_vol += vol
            cut_mass += mass
        else:
            fill_vol += vol
            fill_mass += mass
    balanced = bool(cut_mass > 0.0 and fill_mass > 0.0
                    and abs(cut_mass - fill_mass) <= 1e-6 * max(cut_mass, fill_mass))
    # the EFFECTIVE (volume-weighted) in-situ bank density actually used for the cut(s) -- honest per-cut
    # value (== RHO_LOOSE for an all-shallow structure, -> RHO_BANK for a deep one), for the material block.
    cut_density = round(cut_mass / cut_vol, 1) if cut_vol > 0.0 else 0.0
    return {
        "orders": per,
        "cut_volume_m3": round(cut_vol, 4), "fill_volume_m3": round(fill_vol, 4),
        "cut_mass_kg": round(cut_mass, 1), "fill_mass_kg": round(fill_mass, 1),
        "cut_density_kg_m3": cut_density,
        "excavated_volume_m3": round(cut_vol, 4), "excavated_mass_kg": round(cut_mass, 1),
        "mass_balanced": balanced,
    }


def site_terramechanics(slope_deg: float) -> dict:
    """Applied bearing (wheel contact pressure) + allowable bearing capacity (FORGE) + expected sinkage/slip
    at ``slope_deg``, from the REAL terramechanics spine (stewie.physics.sinkage / slip). Same spine + geometry
    the physics globe bearing/sinkage/slip drape uses."""
    from forge.bearing import allowable_bearing_pa
    from stewie.physics import sinkage as SK
    from stewie.physics import slip as SL

    mass = float(IPX.ROVER_MASS_CLASS_KG)
    g = float(IPX.LUNAR_G_MS2)
    weight = mass * g
    n = int(K.N_WHEELS)
    th = math.radians(float(slope_deg))
    n_cell = weight * math.cos(th) / n                                    # per-wheel normal load on the grade
    applied_pa = SK.contact_pressure(n_cell, _CONTACT_WIDTH_M, _CONTACT_LEN_M)   # spine: contact_pressure
    eq = SL.slip_sinkage_equilibrium(weight, th)                          # spine: bekker_sinkage (+slip) solve
    gamma_loose = RHO_LOOSE * g                                           # loose-surface unit weight [N/m^3]
    allowable_pa = allowable_bearing_pa(float(K.COHESION), float(K.PHI), gamma_loose,
                                        _CONTACT_WIDTH_M, factor_of_safety=_BEARING_FS)
    return {
        "slope_deg": round(float(slope_deg), 2),
        "contact_pressure_pa": round(float(applied_pa), 1),
        "bearing_capacity_pa": round(float(allowable_pa), 1),
        "bearing_fs": _BEARING_FS,
        "bearing_ok": bool(applied_pa <= allowable_pa),
        "sinkage_m": round(float(eq["sinkage_m"]), 4),
        "static_sinkage_m": round(float(eq["static_sinkage_m"]), 4),
        "slip": round(float(eq["slip"]), 4),
        "entrapped": bool(eq["entrapped"]),
    }


def constructability_verdict(terra: dict) -> dict:
    """DERIVED constructability verdict from the terramechanics: constructable iff the rover does not entrap,
    the expected sinkage stays within the wheel-radius mobility limit, and the applied contact pressure stays
    within the allowable bearing capacity. The status names the driving check -- nothing fabricated."""
    sink = float(terra["sinkage_m"])
    entrapped = bool(terra["entrapped"])
    bearing_ok = bool(terra["bearing_ok"])
    within_sinkage = sink <= _SINKAGE_LIMIT_M
    constructable = (not entrapped) and within_sinkage and bearing_ok
    if entrapped:
        status = (f"NOT constructable — sinkage runaway (entrapment) at "
                  f"{terra['slope_deg']:.0f}° (slip {terra['slip']:.2f})")
    elif not within_sinkage:
        status = (f"NOT constructable — sinkage {sink:.3f} m exceeds the "
                  f"{_SINKAGE_LIMIT_M:.3f} m wheel-radius mobility limit")
    elif not bearing_ok:
        status = (f"NOT constructable — contact pressure {terra['contact_pressure_pa']:.0f} Pa exceeds "
                  f"allowable bearing {terra['bearing_capacity_pa']:.0f} Pa")
    else:
        status = (f"bearing OK ({terra['contact_pressure_pa']:.0f} ≤ {terra['bearing_capacity_pa']:.0f} Pa) · "
                  f"sinkage within limit ({sink:.3f} ≤ {_SINKAGE_LIMIT_M:.3f} m)")
    return {
        "constructable": constructable,
        "status": status,
        "bearing_ok": bearing_ok,
        "sinkage_within_limit": bool(within_sinkage),
        "sinkage_limit_m": round(_SINKAGE_LIMIT_M, 4),
        "sinkage_limit_basis": "wheel radius (IPEx WHEEL_RADIUS_M) — sinkage past it buries the hub",
    }


def _spine_calibration() -> dict:
    """The calibration status of the spine terms the evidence rests on, read straight from the terramechanics
    spine (stewie.specs.terramechanics_spine) so the uncertainty characterization cannot drift from it."""
    from stewie.specs.terramechanics_spine import list_terra_spine
    cal = {t["id"]: t["calibration"] for t in list_terra_spine()}
    return {
        "slope": cal.get("slope", "measured"),
        "regolith_density": cal.get("regolith_density", "calibrated"),
        "sinkage": cal.get("sinkage", "calibrated"),
        "contact_pressure": cal.get("contact_pressure", "calibrated"),
    }


def structure_evidence(name: str | None, orders: list[dict], *, site: str | None = None,
                       site_slope_deg: float | None = None, dem_resolution_m: float | None = None,
                       slope_source: str | None = None) -> dict:
    """Assemble the full per-structure constructability evidence block: earthwork (volume/mass) + local
    terramechanics (bearing/sinkage at the site slope) + a derived verdict + the material assumption, DEM
    resolution, and spine calibration status (the honest uncertainty). Terramechanics/verdict are ``None``
    when the site slope is unavailable (no DEM) -- never a fabricated slope."""
    earthwork = order_earthwork(orders)
    terra: dict | None = None
    verdict: dict | None = None
    if site_slope_deg is not None:
        terra = site_terramechanics(site_slope_deg)
        verdict = constructability_verdict(terra)
    cal = _spine_calibration()
    return {
        "name": name,
        "site": site,
        "site_slope_deg": (round(float(site_slope_deg), 2) if site_slope_deg is not None else None),
        "slope_source": slope_source,
        "earthwork": earthwork,
        "terramechanics": terra,
        "verdict": verdict,
        "material": {
            "cut_density_kg_m3": earthwork["cut_density_kg_m3"],
            "fill_density_kg_m3": RHO_LOOSE,
            "assumption": ("conserved regolith: the cut is costed at its PER-CUT depth-averaged in-situ bank "
                           "density (task #78: shallow surface cut ~loose, deep cut -> RHO_DEEP ceiling); the "
                           "fill places loose spoil (RHO_SPOIL); mass = volume × density"),
            "provenance": "lode.planner_balance.insitu_bank_density over stewie.specs.constants RHO_SURFACE/RHO_DEEP/RHO_SPOIL",
        },
        "uncertainty": {
            "dem_resolution_m": (round(float(dem_resolution_m), 3) if dem_resolution_m is not None else None),
            "slope_calibration": cal["slope"],
            "density_calibration": cal["regolith_density"],
            "sinkage_calibration": cal["sinkage"],
            "bearing_calibration": cal["contact_pressure"],
            "note": ("volume = footprint × depth (exact from the decomposed order); mass uses the calibrated "
                     "bank/loose density profile; bearing/sinkage are calibrated Tier-2 spine terms (not "
                     "oracle-fit); site slope is measured on the real DEM at the resolution above."),
        },
    }


def site_slope_deg(site: str | None, lat: float | None, lon: float | None) -> tuple[float | None, float | None, str]:
    """Median surface slope [deg] over a work-area window at the structure's placement (or the site centre),
    from the REAL site DEM (stewie.terrain.site_dem). Returns ``(slope_deg, cell_m, source)``; slope is
    ``None`` (and source names why) when the DEM or the point is unavailable -- never a fabricated slope."""
    if not site:
        return None, None, "no-site"
    try:
        import numpy as np

        from stewie.terrain.site_dem import (
            bundle_for_site,
            latlon_to_dem_origin,
            load_site_dem,
            slope_deg_map,
        )
        Z, cell = load_site_dem(site)
        arr = np.asarray(Z)
        h, w = arr.shape
        rc, cc = h // 2, w // 2
        source = "site-median"
        if lat is not None and lon is not None:
            try:
                ox, oy = latlon_to_dem_origin(float(lat), float(lon), bundle_dir=bundle_for_site(site))
                rc = min(max(int(round(oy / cell)), 0), h - 1)
                cc = min(max(int(round(ox / cell)), 0), w - 1)
                source = "placement"
            except (ValueError, ImportError, KeyError, FileNotFoundError, OSError):
                source = "site-median"          # off-tile / pyproj absent -> fall back to the site-centre window
        half = 200                               # ~1 km window at 5 m (matches planner_endurance's work-area window)
        r0 = min(max(0, rc - half), max(0, h - 2 * half))
        c0 = min(max(0, cc - half), max(0, w - 2 * half))
        win = arr[r0:r0 + 2 * half, c0:c0 + 2 * half]
        if win.size < 4:
            return None, None, "dem-window-empty"
        return float(np.median(slope_deg_map(win, cell))), float(cell), source
    except (FileNotFoundError, KeyError, ValueError, ImportError, OSError):
        return None, None, "site-dem-unavailable"
