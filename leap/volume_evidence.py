"""[REQ:FR-13] LEAP emits the RegolithVolumeEstimate for a site plan.

From the mission's before/after terrain delta (the conserved authority's own base vs as-built surfaces),
produce the typed, conserved, uncertainty-carrying volume evidence -- cross-checked against the
conserved-authority mass and (when a drum inference is supplied) the drum sensor -- linked to a world
transaction. Extends ML-06's estimate_moved_regolith; consumed by the cockpit/report volume surface.
"""
from __future__ import annotations

from lode.planner_acceptance import mission_terrain_delta

from stewie.contracts import RegolithVolumeEstimate


def siteplan_volume_evidence(mission, *, work_order_id: str, transaction_id: str, density_kg_m3: float,
                             density_frac: float = 0.0, height_rmse_m: float = 0.0,
                             drum_inferred_kg: float | None = None) -> RegolithVolumeEstimate:
    """Emit a RegolithVolumeEstimate for a LEAP mission. The conserved-authority mass is the mission's own
    moved mass (``mass_moved_kg`` from the terrain delta), so the estimate self-checks against conservation.
    The conserved surfaces are exact, so the estimate's uncertainty comes from the design-time envelopes the
    caller supplies: ``density_frac`` (in-situ density) and ``height_rmse_m`` (expected observation error).
    Pass ``drum_inferred_kg`` to add the independent drum-sensor cross-check."""
    d = mission_terrain_delta(mission)
    return RegolithVolumeEstimate.from_delta(
        d["base"], d["as_built"], d["cell_m"],
        work_order_id=work_order_id,
        before_source="conserved-authority:base",
        after_source="conserved-authority:as_built",
        transaction_id=transaction_id,
        density_kg_m3=density_kg_m3,
        density_frac=density_frac,
        height_rmse_m=height_rmse_m,
        conserved_mass_kg=d.get("mass_moved_kg"),
        drum_inferred_kg=drum_inferred_kg,
    )
