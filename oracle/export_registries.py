"""Oracle export: write the real body registry and site catalog as JSON contract fixtures.

Source of truth today is the Python registry (stewie_bodies.BODIES, stewie.specs.sites.SITES); the Rust
contracts are tested against exactly these values. Output is byte-stable (sorted keys, fixed indent).

    python oracle/export_registries.py   # writes crates/stewie-contracts/fixtures/{bodies,sites,soil_baseline,rover_ipex,eva_crew}.json
"""
from __future__ import annotations

import dataclasses
import json
import math
import os

from stewie.physics import material as M
from stewie.specs import constants as K
from stewie.specs.sites import SITES
from stewie_bodies import BODIES

_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "crates", "stewie-contracts", "fixtures")


def bodies() -> dict:
    out = {}
    for key, b in BODIES.items():
        d = dataclasses.asdict(b)
        k = d.pop("bekker")
        d["bekker"] = None if k is None else {"k_c": k[0], "k_phi": k[1], "n": k[2]}
        out[key] = d
    return out


def sites() -> dict:
    out = {}
    for key, s in SITES.items():
        d = dataclasses.asdict(s)
        bundle_dir = d.pop("bundle_dir")
        d["bundle"] = None if bundle_dir is None else os.path.basename(bundle_dir)
        out[key] = d
    return out


def soil_baseline() -> dict:
    """The constants.py regolith values the body registry lacks, with their honesty tags (see constants.py)."""
    spec = "spec section 5.2, stewie/specs/constants.py"
    return {"k_shear_m": {"value": float(K.K_SHEAR), "tag": "CALIB", "source": f"{spec} (1.0-1.8 cm)"},
            "slip_c1": {"value": float(K.SLIP_C1), "tag": "UNKNOWN", "source": f"{spec} (c1 ~0.4)"},
            "slip_c2": {"value": float(K.SLIP_C2), "tag": "UNKNOWN", "source": f"{spec} (c2 ~0.3)"},
            "rho_deep": {"value": float(K.RHO_DEEP), "tag": "CALIB", "source": f"{spec} (1.8-2.0 g/cm^3)"},
            "rho_grain": {"value": float(K.RHO_GRAIN), "tag": "FIXED",
                          "source": "spec section 5.1 grain specific gravity G_s 3.1 x water"},
            "rho_spoil": {"value": float(K.RHO_SPOIL), "tag": "CALIB",
                          "source": "loose surface density (Carrier & Mitchell, Lunar Sourcebook 1991, ch. 9)"},
            "rho_sintered": {"value": float(K.RHO_SINTERED), "tag": "SOURCED",
                             "source": "microwave-sintered simulant 2.23-2.34 g/cm^3 (Lin et al. 2024, J. Eur. Ceram. Soc.)"},
            "z_t_m": {"value": float(K.Z_T), "tag": "CALIB", "source": f"{spec} (z_t 10-15 cm)"},
            "d50_m": {"value": float(K.D50), "tag": "CALIB",
                      "source": f"{spec} (median grain 40-130 um, ~70); the smallest column a sandpile donor sheds"},
            "w_ice_max": {"value": float(K.W_ICE_MAX), "tag": "UNKNOWN",
                          "source": f"{spec} (0-5.6 % PSR, LCROSS-derived)"},
            "phi_dense_deg": {"value": float(M.PHI_DENSE_DEG), "tag": "CALIB",
                              "source": f"{spec} (dense end of phi 30-50 deg), stewie/physics/material.py"},
            "cohesion_dense_pa": {"value": float(M.COHESION_DENSE_PA), "tag": "CALIB",
                                  "source": f"{spec} (dense end of c 0.1-1.0 kPa), stewie/physics/material.py"}}


def rover_ipex() -> dict:
    """The IPEx rover profile, every figure from the Python source with the tag its comment gives."""
    from stewie.physics import excavation as EX, rover as RV
    from stewie.specs import ipex_specs as I

    def v(value, tag, source):
        return {"value": float(value), "tag": tag, "source": source}

    s24, wt, bds = "SCHULER24 (IPEx TRL-5)", "WHEELTEST (Zhang, Schuler et al.)", "BDSCALE (Schuler, Nick et al.)"
    model = "Godot model sidecar.gd WHEEL_ORIGINS, not a publication (stewie/physics/rover.py)"
    drums = {}
    for k, d in I.DRUM_DIMENSIONS_M.items():
        drums[k] = {"width_m": v(d["width"], "SOURCED", f"{bds} Table 1"),
                    "diameter_m": v(d["diameter"], "SOURCED", f"{bds} Table 1"),
                    "scoop_width_m": v(d["scoop_width"], "SOURCED", f"{bds} Table 1"),
                    "scoop_height_m": v(d["scoop_height"], "SOURCED", f"{bds} Table 1"),
                    "capacity_kg": v(I.DRUM_CAPACITY_KG[k], "SOURCED", f"{bds}; Schuler 2022 Table 3")}
    return {"name": "ipex", "label": "NASA ISRU Pilot Excavator (IPEx)",
            "mass_dry_kg": v(K.ROVER_MASS_DRY_KG, "CALIB", f"{s24} '30 kg-class excavator'"),
            "n_wheels": v(I.N_WHEELS, "SOURCED", f"{s24} 4-wheel skid-steer"),
            "wheel_radius_m": v(I.WHEEL_RADIUS_M, "SOURCED", f"{wt}: 30.5 cm diameter wheels"),
            "track_gauge_m": v(RV.WHEEL_GAUGE_M, "MODEL", model),
            "wheelbase_m": v(RV.WHEEL_BASE_M, "MODEL", model),
            "skid_steer_track_m": v(I.SKID_STEER_TRACK_M, "SOURCED", f"{wt} Eq. 1, RASSOR 2 test platform"),
            "cg_height_m": v(K.CG_HEIGHT_M, "ASSUMPTION", "IPEx CG not public (stewie/specs/constants.py)"),
            "contact_len_m": v(0.10, "ASSUMPTION", "nominal wheel contact patch length, spec section 4 (stewie_forge)"),
            "contact_width_m": v(0.18, "ASSUMPTION", "wheel contact width (stewie_forge, rover.py)"),
            "drive_speed_ms": v(I.DRIVE_SPEED_MS, "SOURCED", f"{s24} nominal 30 cm/s"),
            "nominal_slope_deg": v(I.NOMINAL_SLOPE_DEG, "SOURCED", f"{s24} inclinations up to 15 deg"),
            "obstacle_height_m": v(I.OBSTACLE_HEIGHT_M, "SOURCED", f"{s24} rock obstacles up to 7.5 cm"),
            "drivetrain_efficiency": v(I.DRIVETRAIN_EFFICIENCY, "CALIB", "electrical to tractive, not in SCHULER24"),
            "rolling_resistance_coeff": v(I.ROLLING_RESISTANCE_COEFF, "ASSUMPTION", "rigid wheel on loose regolith 0.1-0.4"),
            "battery_series_cells": v(I.BATTERY_SERIES_CELLS, "SOURCED", "BATTERY: project lead 2026-06-02, 12S Li-ion"),
            "battery_capacity_ah": v(I.BATTERY_CAPACITY_AH, "SOURCED", "BATTERY: project lead 2026-06-02, ~30 Ah"),
            "liion_v_per_cell": v(I.LIION_NOMINAL_V_PER_CELL, "FIXED", "standard Li-ion nominal cell voltage"),
            "drum_speed_rpm": v(I.DRUM_SPEED_RPM, "ASSUMPTION", "R2D RASSOR-2.0 drum actuator maximum (rated 18)"),
            "max_cut_depth_frac": v(I.MAX_CUT_DEPTH_FRAC, "SOURCED", f"{bds}: cut depth <= 50% of scoop opening"),
            "rake_deg": v(math.degrees(EX.RAKE_ANGLE_RAD), "CALIB_PENDING", "mid-range blade rake (McKyes 1985 30-90 deg)"),
            "soil_tool_friction_frac": v(EX.SOIL_TOOL_FRICTION_FRAC, "CALIB_PENDING", "delta/phi, steel on regolith 0.3-0.6"),
            "drums": drums}


def eva_crew() -> dict:
    """The suited-crew EVA profile (RW-30h, Aaron D-R78): every figure copied from the cited page, converted to SI by an
    exact factor; the printed value and unit stay in its source. Walking speed against slope has no source and is
    deliberately absent: it is a required mission-config input. Evidence: design/evidence_2026-10-31_eva/EVA_SOURCES.md."""
    mph, lb, btu_hr = 0.44704, 0.45359237, 0.29307107      # m/s, kg, W per unit (exact definitions; Btu IT)
    tn = "NASA TN D-7883 (Waligora & Horrigan 1975, NTRS 19750010199) Table I, mean row, p. 9"
    wb = "Norcross et al. 2008, 10-km walkback (NTRS 20080014853), slide 14; MKIII suit, simulated 1/6 g, level, self-paced"
    tp = ("NASA/TP-2010-216125 (Norcross et al., NTRS 20110003409) Fig. 16, p. 22; MKIII, 121 kg suit, lunar g, "
          "29.6 kPa trend line, read off the plot")

    def v(value, tag, source, uncertainty=None):
        out = {"value": float(value), "tag": tag, "source": source}
        if uncertainty is not None:
            out["uncertainty"] = float(uncertainty)
        return out

    rates = {"alsep_deployment": 1024, "geology_station": 1024, "overhead": 1130, "lrv_operations": 518,
             "all_activities": 980}
    return {"name": "eva_crew",
            "label": "Suited crew member (Apollo A7L lunar-surface rates; MKIII 1/6-g walking tests)",
            "metabolic_w": {k: v(kj / 3.6, "SOURCED", f"{tn}: {kj} kJ/hr") for k, kj in rates.items()},
            "level_walk_speed_ms": v(3.9 * mph, "SOURCED", f"{wb}: 3.9 mph mean"),
            "level_walk_speed_sd_ms": v(0.5 * mph, "SOURCED", f"{wb}: 0.5 mph SD"),
            "level_walk_metabolic_w": v(2374 * btu_hr, "SOURCED", f"{wb}: 2374 Btu/hr mean"),
            "level_walk_o2_kg_per_hr": v(0.4 * lb, "SOURCED", f"{wb}: O2 usage 0.4 lb/hr"),
            "level_walk_cooling_water_kg_per_hr": v(3.1 * lb, "SOURCED", f"{wb}: cooling water 3.1 lb/hr"),
            "apollo_o2_kg_per_hr": v(0.15 * lb, "SOURCED", f"{wb}: Apollo comparison, O2 usage 0.15 lb/hr"),
            "apollo_cooling_water_kg_per_hr": v(0.98 * lb, "SOURCED", f"{wb}: Apollo comparison, cooling water 0.98 lb/hr"),
            "grade_vo2": [{"grade_pct": g, "vo2_ml_min_kg": v(vo2, "FIGURE_READ", f"{tp}: {label}", 1.0)}
                          for g, vo2, label in ((0.0, 15.5, "Level"), (10.0, 16.0, "10%"), (20.0, 18.0, "20%"),
                                                (30.0, 21.5, "30%"))]}


def _write(name: str, data: dict) -> str:
    path = os.path.normpath(os.path.join(_OUT, name))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def main() -> None:
    print(_write("bodies.json", bodies()))
    print(_write("sites.json", sites()))
    print(_write("soil_baseline.json", soil_baseline()))
    print(_write("rover_ipex.json", rover_ipex()))
    print(_write("eva_crew.json", eva_crew()))


if __name__ == "__main__":
    main()
