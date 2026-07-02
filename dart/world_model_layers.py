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

from dataclasses import dataclass

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


@dataclass(frozen=True)
class WorldStateGrid:
    """[REQ:TW-05] ONE per-cell WorldState the fleet reads, instead of four scattered rasters.

    The four per-cell systems used to live disjoint -- material in ``ColumnState``, traversability in
    the ``lode`` costmap, observed/unobserved in :class:`WorldModelLayers`, and calibrated uncertainty
    in ``dart.mapping.ElevationMap.cell_uncertainty``. This bundles all four into one coherent grid so a
    consumer reasons over a single object per twin:

      * ``material_density``        [kg/m^3] the conserved per-cell bulk density -- the MATERIAL identity
                                    the strength/slip maps derive from (``stewie.physics.ColumnState``);
      * ``traversability_cost``     the composed per-cell navigation cost (``lode`` ``CompositeCostmap.cost``);
      * ``traversability_passable`` the per-cell passable mask (False = impassable; the costmap block);
      * ``observed_mask``           which cells the mapper has actually surveyed (True = observed);
      * ``cell_uncertainty_sigma``  the calibrated per-cell elevation sigma [m], KEYED to observation --
                                    finite where observed, NaN where unobserved (``ElevationMap
                                    .cell_uncertainty``).

    Material + traversability are terrain properties defined EVERYWHERE (from the conserved authority +
    the prior DEM); the observed mask + uncertainty track what perception has actually measured. All five
    grids share ONE (rows, cols) shape (checked at construction) and the uncertainty is LOCKED to the
    observed mask: an unobserved cell carries no sigma, an observed cell a finite one. This is the
    twin-store side of the FS-02 WorldState split -- the pydantic ``stewie.contracts.WorldState`` is the
    JSON metadata DESCRIPTOR of this grid (produced by :meth:`contract`); the rasters live here.
    """

    material_density: np.ndarray
    traversability_cost: np.ndarray
    traversability_passable: np.ndarray
    observed_mask: np.ndarray
    cell_uncertainty_sigma: np.ndarray
    cell_m: float

    def __post_init__(self) -> None:
        grids = {
            "material_density": self.material_density,
            "traversability_cost": self.traversability_cost,
            "traversability_passable": self.traversability_passable,
            "observed_mask": self.observed_mask,
            "cell_uncertainty_sigma": self.cell_uncertainty_sigma,
        }
        shapes = {name: np.asarray(a).shape for name, a in grids.items()}
        shape = shapes["material_density"]
        if len(shape) != 2:
            raise ValueError(f"WorldStateGrid fields must be 2-D (rows, cols); got {shape}")
        mismatched = {n: s for n, s in shapes.items() if s != shape}
        if mismatched:
            raise ValueError(f"all per-cell fields must share the grid shape {shape}; mismatched: {mismatched}")
        if not (np.isfinite(self.cell_m) and self.cell_m > 0.0):
            raise ValueError(f"cell_m must be finite and > 0 (got {self.cell_m})")
        # uncertainty is keyed to observation: finite sigma EXACTLY on observed cells, NaN elsewhere
        observed = np.asarray(self.observed_mask, bool)
        finite_sigma = np.isfinite(np.asarray(self.cell_uncertainty_sigma, float))
        if not np.array_equal(finite_sigma, observed):
            raise ValueError(
                "cell_uncertainty_sigma must be finite exactly on observed cells and NaN on "
                "unobserved cells (uncertainty is keyed to the observed mask)")

    @property
    def shape(self) -> tuple[int, int]:
        s = self.material_density.shape
        return (int(s[0]), int(s[1]))

    @property
    def impassable(self) -> np.ndarray:
        """Per-cell impassable mask (the complement of ``traversability_passable``)."""
        return ~np.asarray(self.traversability_passable, bool)

    @property
    def observed_fraction(self) -> float:
        m = np.asarray(self.observed_mask, bool)
        return float(np.mean(m)) if m.size else 0.0

    @classmethod
    def assemble(cls, *, material, traversability, observed_mask, uncertainty, cell_m,
                 per_sample_sigma_m: float = 0.05, floor_m: float = 0.02, correlation_cap: int = 8):
        """Assemble one WorldStateGrid from the four real per-cell sources. Inputs are DUCK-TYPED so this
        stays free of a ``dart``<->``lode`` import cycle:

          * ``material``       -- a ``ColumnState``-like object (uses ``.density``) or a density array;
          * ``traversability`` -- a ``CompositeCostmap``-like object (uses ``.cost`` + ``.passable``);
          * ``observed_mask``  -- the surveyed-cell boolean mask (e.g. ``WorldModelLayers`` observed coverage);
          * ``uncertainty``    -- an ``ElevationMap``-like object (uses ``.cell_uncertainty(...)``) or a
                                  per-cell sigma array already keyed to the observed mask.

        The ``per_sample_sigma_m`` / ``floor_m`` / ``correlation_cap`` [CALIB] knobs are forwarded to
        ``cell_uncertainty`` when an ElevationMap-like object is supplied.
        """
        density = material.density if hasattr(material, "density") else material
        cost = traversability.cost
        passable = traversability.passable
        if hasattr(uncertainty, "cell_uncertainty"):
            sigma = uncertainty.cell_uncertainty(per_sample_sigma_m=per_sample_sigma_m,
                                                 floor_m=floor_m, correlation_cap=correlation_cap)[0]
        else:
            sigma = uncertainty
        return cls(
            material_density=np.asarray(density, float),
            traversability_cost=np.asarray(cost, float),
            traversability_passable=np.asarray(passable, bool),
            observed_mask=np.asarray(observed_mask, bool),
            cell_uncertainty_sigma=np.asarray(sigma, float),
            cell_m=float(cell_m),
        )

    def contract(self, *, body: str = "moon", frame: str = "MOON_ME",
                 dem_source: str = "haworth_10km_5m", datum_radius_m: int = 1737400,
                 mutated: bool = False):
        """Surface this grid as the typed ``stewie.contracts.WorldState`` metadata DESCRIPTOR (FS-02):
        grid geometry + lunar datum + provenance + observed coverage. The descriptor is the JSON snapshot
        a route/consumer reasons over; the per-cell rasters stay in this twin-side grid."""
        from stewie.contracts import WorldState
        rows, cols = self.shape
        return WorldState(body=body, frame=frame, rows=rows, cols=cols, cell_m=float(self.cell_m),
                          datum_radius_m=datum_radius_m, observed_fraction=self.observed_fraction,
                          dem_source=dem_source, mutated=mutated)
