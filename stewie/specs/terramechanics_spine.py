"""[REQ:TM-02] the terramechanics spine — the terms the conserved tier2_numpy solver computes, each an
inspectable entry (name / symbol / unit / description / calibration status) BOUND to the REAL solver callable
that produces it. Binding the live functions (stewie.physics.sinkage / slip) means the spine cannot drift from
the solver: a wrong reference fails at import, not silently. Terms tagged source `input:*` are terrain-derived
(slope/roughness), not solver outputs. Config sourced from the real physics, not synthetic data."""
from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from stewie.physics import sinkage, slip


class TerraTerm(TypedDict):
    id: str
    name: str
    symbol: str
    unit: str
    description: str
    backend: str
    calibration: str   # measured | calibrated | unknown
    source: str        # "module.function" (a real callable) or "input:<origin>"


# each computed term binds the REAL callable that produces it (import-checked at module load);
# input terms name their terrain origin and have no solver callable.
_TERMS: list[tuple[TerraTerm, Callable | None]] = [
    ({"id": "slope", "name": "Surface slope", "symbol": "theta", "unit": "deg",
      "description": "Local terrain slope; sets the gravity load component and the slip demand.",
      "backend": "tier2_numpy", "calibration": "measured", "source": "input:dem"}, None),
    ({"id": "roughness", "name": "Terrain roughness", "symbol": "sigma_h", "unit": "m RMS",
      "description": "Local elevation roughness over the contact patch.",
      "backend": "tier2_numpy", "calibration": "measured", "source": "input:dem"}, None),
    ({"id": "regolith_density", "name": "Regolith bulk density", "symbol": "rho", "unit": "kg/m^3",
      "description": "In-situ bulk density; sets bearing + the sinkage-to-density coupling.",
      "backend": "tier2_numpy", "calibration": "calibrated", "source": "input:body_params"}, None),
    ({"id": "contact_pressure", "name": "Ground contact pressure", "symbol": "p", "unit": "Pa",
      "description": "Normal load over the contact patch; the Bekker bearing driver.",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.sinkage.contact_pressure"}, sinkage.contact_pressure),
    ({"id": "sinkage", "name": "Wheel sinkage", "symbol": "z", "unit": "m",
      "description": "Bekker pressure-sinkage depth under the wheel/drum contact.",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.sinkage.bekker_sinkage"}, sinkage.bekker_sinkage),
    ({"id": "slip", "name": "Wheel slip ratio", "symbol": "i", "unit": "1",
      "description": "Slip ratio for the demanded thrust; entraps when demand exceeds the traction budget.",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.slip.slip_for_demand"}, slip.slip_for_demand),
    ({"id": "traction", "name": "Traction budget", "symbol": "H_max", "unit": "N",
      "description": "Available thrust ceiling from cohesion + friction under the normal load.",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.slip.traction_budget"}, slip.traction_budget),
    ({"id": "compaction_resistance", "name": "Compaction resistance", "symbol": "R_c", "unit": "N",
      "description": "Bekker motion resistance from the sinkage the wheel must climb out of.",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.slip.compaction_resistance"}, slip.compaction_resistance),
    ({"id": "drive_energy", "name": "Drive power", "symbol": "P", "unit": "W",
      "description": "Terramechanics drive power at the commanded speed on the slope (energy per traverse).",
      "backend": "tier2_numpy", "calibration": "calibrated",
      "source": "stewie.physics.slip.bekker_drive_power_w"}, slip.bekker_drive_power_w),
]

TERRA_SPINE: list[TerraTerm] = [t for t, _ in _TERMS]
TERRA_SOLVERS: dict[str, Callable] = {t["id"]: fn for t, fn in _TERMS if fn is not None}


def list_terra_spine() -> list[TerraTerm]:
    return list(TERRA_SPINE)


# [REQ:TM-03] the derived LY-01 catalog layers each terramechanics term feeds: every derived physics/traffic/
# terrain layer is COMPUTED FROM one or more TM-02 spine terms, on the conserved tier2_numpy backend -- so a
# traversability/slip-risk/energy-cost/costmap layer names the terramechanics it is built from.
TERRA_DERIVED: dict[str, list[str]] = {
    "terrain.slope": ["slope"],
    "terrain.roughness": ["roughness"],
    "physics.bearing": ["contact_pressure"],
    "physics.sinkage": ["sinkage"],
    "physics.slip_risk": ["slip", "slope"],
    "physics.traction_margin": ["traction", "slip"],
    "physics.energy_cost": ["drive_energy"],
    "physics.excavation_resistance": ["compaction_resistance"],
    "physics.compaction": ["compaction_resistance", "sinkage"],
    "traffic.traversability": ["slip", "slope", "traction"],
    "traffic.cost_global": ["drive_energy", "slope"],
    # [REQ:TW-11] the traversal-hardening layer: repeated traffic drives per-cell density toward the conserved
    # Bekker equilibrium (contact_pressure is the equilibrium driver; sinkage is its mass-conserving density
    # coupling), served as the traffic.compaction Dr raster from the TrafficMemory accumulator.
    "traffic.compaction": ["contact_pressure", "sinkage"],
}

# validate at import: every source term is a real TM-02 spine term (the mapping cannot drift from the spine).
# An explicit raise, not a bare assert (CT-06: asserts are stripped under `python -O`, silencing the check).
_SPINE_IDS = {t["id"] for t in TERRA_SPINE}
_UNKNOWN_TERMS = sorted({t for terms in TERRA_DERIVED.values() for t in terms if t not in _SPINE_IDS})
if _UNKNOWN_TERMS:
    raise ValueError(f"TERRA_DERIVED references terms not in the terramechanics spine: {_UNKNOWN_TERMS}")


def terra_derived_layers() -> list[dict]:
    """Each derived catalog layer + the TM-02 spine terms it is computed from + which of those are real solver
    outputs (TERRA_SOLVERS callables) + the producing backend."""
    return [{"layer": layer_id, "from_terms": terms, "backend": "tier2_numpy",
             "computed_terms": [t for t in terms if t in TERRA_SOLVERS]}
            for layer_id, terms in TERRA_DERIVED.items()]
