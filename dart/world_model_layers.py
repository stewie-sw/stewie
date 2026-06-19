"""[REQ:AS-10] Layered autonomous world model: truth / observed / forecast / edited as SEPARATE
layers (§25 Phase 8).

Over the conserved world model the autonomy keeps four DISTINCT elevation layers:
  * truth    -- the conserved-authority surface (eval-only reference; never an estimator input);
  * observed -- built by the mapper (dart.mapping.build_elevation_map -> ElevationMap) from
                observations ONLY (no truth read; the I3 firewall is enforced + tested in the mapper);
  * forecast -- a planned/predicted future surface (e.g. the post-excavation target);
  * edited   -- operator overrides.

The AS-10 invariant: an update to one layer NEVER mutates another (separate backing arrays), and the
observed-update path carries no truth. Each layer has provenance. NOT synthetic: the truth layer is a
real conserved DEM; the observed layer is fed by the real mapper's ElevationMap.
"""
from __future__ import annotations

import numpy as np

LAYERS = ("truth", "observed", "forecast", "edited")


class WorldModelLayers:
    def __init__(self, shape, *, cell_m: float = 0.02) -> None:
        self.shape = tuple(int(s) for s in shape)
        self.cell_m = float(cell_m)
        self._z = {n: np.full(self.shape, np.nan, dtype=float) for n in LAYERS}
        self._count = np.zeros(self.shape, dtype=int)        # observed-layer per-cell observation count
        self.provenance: dict[str, str | None] = {n: None for n in LAYERS}   # per-layer data source, set on write

    def layer(self, name: str) -> np.ndarray:
        """A COPY of a layer's elevation grid (callers can't mutate the store through it)."""
        return self._z[name].copy()

    @property
    def observed_count(self) -> np.ndarray:
        return self._count.copy()

    def coverage_frac(self, name: str) -> float:
        return float(np.mean(np.isfinite(self._z[name])))

    def set_truth(self, elevation, *, source: str = "conserved_authority") -> None:
        """Set the eval-only conserved-truth reference layer."""
        self._z["truth"] = np.asarray(elevation, float).reshape(self.shape).copy()
        self.provenance["truth"] = source

    def set_forecast(self, elevation, *, source: str = "planner") -> None:
        self._z["forecast"] = np.asarray(elevation, float).reshape(self.shape).copy()
        self.provenance["forecast"] = source

    def update_observed(self, elevation, mask=None, *, count=None,
                        source: str = "stereo_mapper") -> int:
        """Fuse an OBSERVED elevation into the observed layer ONLY (the mapper's output). NEVER reads
        or writes any other layer. ``mask`` (else the finite cells of ``elevation``) selects updated
        cells. Returns the number of cells written. No truth/pose/gt argument (I3)."""
        e = np.asarray(elevation, float).reshape(self.shape)
        m = np.asarray(mask, bool).reshape(self.shape) if mask is not None else np.isfinite(e)
        self._z["observed"][m] = e[m]
        self._count[m] += (np.asarray(count, int).reshape(self.shape)[m] if count is not None else 1)
        self.provenance["observed"] = source
        return int(np.count_nonzero(m))

    def update_observed_from_map(self, elevation_map, *, source: str = "stereo_mapper") -> int:
        """Fuse a dart.mapping.ElevationMap (the real observations-only mapper output)."""
        return self.update_observed(elevation_map.elevation, elevation_map.covered_mask(),
                                    count=elevation_map.count, source=source)

    def apply_edit(self, elevation, mask, *, source: str = "operator") -> int:
        """Operator override into the edited layer ONLY."""
        e = np.asarray(elevation, float).reshape(self.shape)
        m = np.asarray(mask, bool).reshape(self.shape)
        self._z["edited"][m] = e[m]
        self.provenance["edited"] = source
        return int(np.count_nonzero(m))
