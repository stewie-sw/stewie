"""VehicleTwin — ONE pluggable record per vehicle instance (the extensibility contract).

Assembles, from the existing registries, everything the stack needs to operate a vehicle on a
body: identity (instance/vehicle/body), resolved physics (gravity + terramechanics params via
Placement semantics: soil and g decoupled), geometry (gauge/wheelbase/wheel radius/CG), the
grounded energy model, capabilities (base + mounted tools), and render assets. IPEx is the first
twin; ANY registry vehicle (ez_rassor, rassor2, future LTV-class entries) plugs in through the
same record — proven by the second-vehicle end-to-end tests.

The twin is a VIEW over the registries (no duplicated constants): vehicles.py stays the single
source of truth; assemble() fails loudly on anything unknown or incomplete.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from stewie.specs import bodies as B
from stewie.specs import vehicles as V


def sample_scene_dir(name: str) -> str:
    """Repo-relative sample scene path (test/demo convenience)."""
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..",
                                         "samples", name))


@dataclass(frozen=True)
class VehicleTwin:
    instance: str
    vehicle: str
    body: str
    gravity_ms2: float
    mass_kg: float
    geometry: dict
    energy: dict
    capabilities: frozenset
    render_assets: str
    params: object                       # TerramechanicsParams (soil-resolved)
    tools: tuple = field(default=())

    @classmethod
    def assemble(cls, instance: str, *, vehicle: str, body: str, tools: tuple = (),
                 soil: str = "", g_override: float | None = None) -> "VehicleTwin":
        veh = V.get_vehicle(vehicle)                     # KeyError on unknown -- loud by design
        bod = B.get_body(body)
        placement = V.Placement(instance=instance, vehicle=vehicle, body=body,
                                tools=tuple(tools), soil=soil, g=g_override)
        dep = V.Deployment([placement])
        params = dep.params_for(instance)
        gravity = dep.gravity_for(instance)
        geometry = {"gauge_m": veh.gauge_m, "wheelbase_m": veh.wheelbase_m,
                    "wheel_radius_m": veh.wheel_radius_m, "cg_height_m": veh.cg_height_m,
                    "n_wheels": veh.n_wheels}
        if any(v is None or (isinstance(v, (int, float)) and v <= 0)
               for v in geometry.values()):
            raise ValueError(f"vehicle {vehicle!r} has incomplete geometry: {geometry}")
        energy = {"drive_power_w": veh.drive_power_w,
                  "drive_j_per_m": veh.drive_power_w / 0.30,     # at the nominal 0.30 m/s
                  "dig_j_per_kg": veh.dig_energy_j_per_kg,
                  "drum_capacity_kg": veh.drum_capacity_kg}
        return cls(instance=instance, vehicle=vehicle, body=bod.name, gravity_ms2=gravity,
                   mass_kg=veh.dry_mass_kg, geometry=geometry, energy=energy,
                   capabilities=dep.capabilities_for(instance),
                   render_assets=str(veh.render_assets or "assets/"), params=params,
                   tools=tuple(tools))

    def drive_context(self) -> dict:
        """Exactly the per-vehicle kwargs the conserved drive loop consumes."""
        return {"g": self.gravity_ms2, "params": self.params,
                "wheel_width_m": max(0.05, self.geometry["wheel_radius_m"] * 0.6)}

    def plan_context(self) -> dict:
        """The per-vehicle numbers the mission planner consumes."""
        return {"vehicle": self.vehicle, "tools": list(self.tools),
                "drum_capacity_kg": self.energy["drum_capacity_kg"],
                "dig_j_per_kg": self.energy["dig_j_per_kg"],
                "drive_j_per_m": self.energy["drive_j_per_m"]}
