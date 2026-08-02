"""Step 2 / gap A2: CurrentTerrainView -- the one defined composition of the planning surface.

Architecture gap A2: TerrainMemory (the remembered physical build) and TwinStore (the observed/resync
patch) are both valid, and ``state.as_built_dem`` already layers them OBSERVED-where-measured >
AS-BUILT remembered > pristine. But it returns only the composed ``(z, cell)`` array -- so "current
terrain" is an array whose per-cell ORIGIN is lost. A planner cannot tell a measured cell from a
remembered one from a pristine one, and cannot report provenance.

CurrentTerrainView makes the composition a typed, provenance-bearing object: the composed heights, the
cell size, a per-cell ``source`` map (pristine / as-built / observed), and the provenance counters
(how many recorded missions, which observed-twin version, what fraction is measured). ``state`` gathers
the layer inputs (load the site's TerrainMemory, read the observed twin) and calls the pure
``compose_terrain_view`` here; ``state.as_built_dem`` keeps its ``(z, cell)`` contract by returning the
view's heights.

Pure: numpy only, no server or DEM-IO dependency -- so the precedence + provenance logic is testable in
isolation, and the same composition serves the planner, the as-built mesh, and the cockpit read.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: SR-17: absolute elevation change that counts as "built" [m]. Absolute, never relative -- a relative
#: tolerance on absolute lunar elevations silently scales with altitude. Two orders of magnitude below
#: the 0.02 m acceptance tolerance (lode.planner_acceptance.accept_flatness_tol_m), so a build the
#: acceptance check can measure is never invisible here, and matching the absolute convention
#: `terrain_memory.summary()` already uses.
AS_BUILT_EPS_M = 1e-4


@dataclass(frozen=True)
class CurrentTerrainView:
    """One composed planning surface with retained provenance (gap A2).

    ``heights``: the composed surface (observed > as-built > pristine). ``cell_m``: grid cell size.
    ``source``: a per-cell uint8 provenance map -- ``PRISTINE`` / ``AS_BUILT`` / ``OBSERVED``.
    ``as_built_version``: the site TerrainMemory version folded in (0 = none). ``twin_version``: the
    observed-twin version overlaid (0 = none). ``observed_fraction``: fraction of cells taken from the
    observed twin (the measured-confidence signal)."""

    heights: np.ndarray
    cell_m: float
    source: np.ndarray
    as_built_version: int
    twin_version: int
    observed_fraction: float

    PRISTINE = 0
    AS_BUILT = 1
    OBSERVED = 2


def compose_terrain_view(base_z, cell_m: float, *, as_built_z=None, as_built_version: int = 0,
                         observed_heights=None, observed_mask=None,
                         twin_version: int = 0) -> CurrentTerrainView:
    """Compose the precedence stack into one CurrentTerrainView. ``base_z`` is the pristine planning
    DEM. ``as_built_z`` (optional) is the SAME-shaped surface after imprinting the site's TerrainMemory
    -- cells that differ from pristine are tagged AS_BUILT. ``observed_heights`` + ``observed_mask``
    (optional) are the observed twin's current surface + measured mask -- masked cells override and are
    tagged OBSERVED (measured reality wins). Each layer is defensive: a wrong-shaped layer is ignored,
    never corrupts the surface (planning must not fail on the world-model overlay)."""
    base = np.asarray(base_z, dtype=float)
    z = base.copy()
    source = np.zeros(z.shape, dtype=np.uint8)

    if as_built_z is not None:                            # layer 1: as-built remembered build
        ab = np.asarray(as_built_z, dtype=float)
        if ab.shape == z.shape:
            # SR-17 (2026-07-28 review): this was `~np.isclose(ab, base)`, whose numpy default rtol=1e-5
            # is RELATIVE -- applied to ABSOLUTE lunar elevations. On the real tile (min -96.61 /
            # max 2842.21 / mean 1381.01 m) the drop threshold ran to 0.0284 m, and 26.8% of the tile
            # exceeded the 0.02 m acceptance tolerance (planner_acceptance.accept_flatness_tol_m). At
            # base 2800 m a +0.025 m fill vanished entirely and the cell stayed PRISTINE, so
            # `as_built_dem` handed the planner the pristine surface for ground TerrainMemory said was
            # built, and the LY-07 drape rendered no change. terrain_memory.imprint_on_dem_resampled
            # divides by capacity=100, so every edge cell of every real build is sub-cm and hit this.
            #
            # Elevation deltas are ABSOLUTE quantities; the threshold must be too. Matches the
            # convention `terrain_memory.summary()` already used (`np.abs(d) > 1e-9`), which is why the
            # two disagreed about whether the same build existed.
            changed = np.abs(ab - base) > AS_BUILT_EPS_M
            z[changed] = ab[changed]
            source[changed] = CurrentTerrainView.AS_BUILT
        else:
            as_built_version = 0                          # an ignored layer contributed nothing

    if observed_heights is not None and observed_mask is not None:   # layer 2: observed (wins)
        oh = np.asarray(observed_heights, dtype=float)
        m = np.asarray(observed_mask, dtype=bool)
        if oh.shape == z.shape and m.shape == z.shape and m.any():
            z[m] = oh[m]
            source[m] = CurrentTerrainView.OBSERVED
        else:
            twin_version = 0

    n = source.size
    observed_fraction = (float(np.count_nonzero(source == CurrentTerrainView.OBSERVED)) / n
                         if n else 0.0)
    return CurrentTerrainView(heights=z, cell_m=float(cell_m), source=source,
                              as_built_version=int(as_built_version), twin_version=int(twin_version),
                              observed_fraction=observed_fraction)
