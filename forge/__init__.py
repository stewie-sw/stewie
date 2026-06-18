"""FORGE -- the STEWIE physics / terramechanics / excavation subsystem.

FORGE owns the soil-mechanics models the planner and the conserved authority consume. Most of the
terramechanics (Bekker pressure-sinkage, Janosi-Hanamoto slip, the conserved cut/fill authority) lives in
``dart`` and the body-sourced soil constants in ``stewie.specs``; FORGE adds the geotechnical models that
sit on top of them. Current content:

- ``forge.bearing`` -- Terzaghi/Vesic static bearing-capacity (CP-06 berm/pad acceptance, the
  "berm-firming" check): can a built pad/berm carry a structural load, and does firming (compaction)
  make it hold.

Sourced models only -- no synthetic coefficients (see the per-module provenance docstrings).
"""
from forge import bearing
from forge.bearing import (
    allowable_bearing_pa,
    bearing_capacity_factors,
    ultimate_bearing_capacity_pa,
)

__all__ = [
    "bearing",
    "bearing_capacity_factors",
    "ultimate_bearing_capacity_pa",
    "allowable_bearing_pa",
]
