#!/usr/bin/env python3
"""Export the sysrev-sourced per-planet terramechanics (terrain_authority/bodies.py) to bodies.json,
so the planet browser LOADS the SAME constants the sim uses (single source of truth) when a body is
chosen -- no hardcoded/divergent copy. Re-run after editing bodies.py.
"""
import dataclasses
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))   # the monorepo root holds terrain_authority/

from terrain_authority import bodies as B  # noqa: E402
from terrain_authority import constants as K  # noqa: E402
from terrain_authority import ipex_specs as S  # noqa: E402
from terrain_authority import vehicles as V  # noqa: E402

out: dict = {}
for key, b in B.BODIES.items():
    d = dataclasses.asdict(b)
    d["bekker"] = ({"k_c": b.bekker[0], "k_phi": b.bekker[1], "n": b.bekker[2]} if b.bekker else None)
    # gravity-SWAPPED IPEx power for THIS body: steady-drive resistance ~ m*g, so drive power scales with
    # the body's surface gravity (Earth ~6x the Moon). Housekeeping (avionics/comms/thermal) is body-
    # independent [ASSUMPTION] (thermal in particular is environment-dependent -- a future per-body refine).
    _pfx = {"moon": "lunar", "mars": "mars", "earth": "earth"}.get(key)
    envs = ({e: round(S.thermal_heater_power_w(t), 2) for e, t in S.ENV_SINK_TEMP_C.items()
             if e.startswith(_pfx)} if _pfx else {})
    cold_c = S.ENV_SINK_TEMP_C[S.BODY_COLD_ENV[key]] if key in S.BODY_COLD_ENV else None
    d["ipex_power"] = {
        # 6 sig figs, not fixed decimals (audit L19: round(...,2) collapsed Bennu's 1e-4 W to 0.0)
        "drive_power_w": float(f"{S.lunar_drive_power_w(g_ms2=b.g):.6g}"),
        "drive_j_per_m": round(S.lunar_drive_power_w(g_ms2=b.g) / S.DRIVE_SPEED_MS, 2),
        "drive_power_15deg_w": round(S.lunar_drive_power_w(g_ms2=b.g, slope_deg=15.0), 2),
        # system at the body's COLDEST survival environment (worst-case thermal); thermal now per-environment
        "system_power_w": round(S.system_power_w(g_ms2=b.g, sink_temp_c=cold_c), 2),
        "avionics_w": S.AVIONICS_POWER_W, "comms_w": S.COMMS_TX_POWER_W,
        "thermal_survival_w": round(S.survival_heater_power_w(key), 2) if key in S.BODY_COLD_ENV
        else round(S.THERMAL_SURVIVAL_POWER_W, 2),
        "thermal_by_env_w": envs,
    }
    out[key] = d

# IPEx/energy constants for the browser's build estimate. JS can't import .py, so mirror them here
# from the source of truth (ipex_specs.py + constants.py). Underscore key -> not a body (inert to
# body lookups in the browser + mission_planner). Re-run this script after editing those .py files.
out["_ipex"] = {
    "drum_kg": S.REGOLITH_PER_CYCLE_KG,
    "dig_j_per_kg": round(S.dig_energy_per_kg(), 1),
    "drive_j_per_m": round(S.drive_energy_per_m(), 2),
    "battery_j": round(S.battery_energy_j(), 1),
    "dig_rate_kg_hr": S.DIG_RATE_KG_PER_HR,
    "sinter_enabled": K.SINTER_ENABLED,
}

# Fleet registries for the browser (terrain_authority/vehicles.py): vehicles with their CAPABILITIES,
# power sources, tools (the capability each grants), and the full action vocabulary -- so the UI can
# populate vehicle/power/tool pickers and gate the plannable actions per the selected vehicle+tools.
# Generated from the .py source of truth (no hand-authored copy); re-run after editing vehicles.py.
out["_vehicles"] = {
    name: {
        "label": v.label, "dry_mass_kg": v.dry_mass_kg, "n_wheels": v.n_wheels,
        "drum_capacity_kg": v.drum_capacity_kg, "drive_power_w": round(v.drive_power_w, 2),
        "dig_energy_j_per_kg": round(v.dig_energy_j_per_kg, 1),
        "capabilities": sorted(v.capabilities), "onboard_power": list(v.onboard_power),
        # geometry + render body so the UI/Godot can select the per-vehicle physics + mesh (both bodies)
        "gauge_m": v.gauge_m, "wheelbase_m": v.wheelbase_m, "wheel_radius_m": v.wheel_radius_m,
        "cg_height_m": v.cg_height_m, "render_assets": v.render_assets,
    }
    for name, v in V.VEHICLES.items()
}
out["_power"] = {
    name: {"label": p.label, "kind": p.kind, "capacity_j": round(p.capacity_j, 1),
           "recharge_w": p.recharge_w, "continuous_w": p.continuous_w}
    for name, p in V.POWER_SOURCES.items()
}
out["_tools"] = {
    name: {"label": t.label, "capability": t.capability, "energy_j_per_kg": t.energy_j_per_kg,
           "product_density_kg_m3": t.product_density_kg_m3}
    for name, t in V.TOOLS.items()
}
out["_actions"] = sorted(V.ACTIONS)   # the full action vocabulary, for the planner UI

path = os.path.join(HERE, "bodies.json")
with open(path, "w") as f:
    json.dump(out, f, indent=2)
n_bodies = sum(1 for k in out if not k.startswith("_"))
print(f"wrote {n_bodies} bodies (+{len(out) - n_bodies} meta blocks) -> {path}: "
      f"{', '.join(b.label for b in B.BODIES.values())}")
