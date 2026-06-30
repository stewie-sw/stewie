"""Step 2 (gap A2): CurrentTerrainView -- one composed planning surface with retained provenance.

state.as_built_dem already composes the precedence stack OBSERVED-where-measured > AS-BUILT remembered
> pristine, but it returns only the (z, cell) array -- the provenance (which cells came from which
layer, how many missions, which twin version) is LOST. Gap A2: "current terrain" must mean ONE defined
composition with provenance + confidence, not an array whose origin is unknowable.

CurrentTerrainView is that typed object; compose_terrain_view is the pure composer (no server/DEM
deps). These tests pin the precedence + the retained provenance. Small real grids as structural
fixtures -- no fabricated terrain.
"""
from __future__ import annotations

import numpy as np

from stewie.twin.terrain_view import CurrentTerrainView, compose_terrain_view


def test_pristine_when_no_layers():
    base = np.full((5, 5), 100.0)
    v = compose_terrain_view(base, 5.0)
    assert np.array_equal(v.heights, base)
    assert (v.source == CurrentTerrainView.PRISTINE).all()
    assert v.observed_fraction == 0.0 and v.as_built_version == 0 and v.twin_version == 0
    assert v.heights is not base                          # never aliases the caller's array


def test_as_built_layer_tags_only_changed_cells():
    base = np.full((4, 4), 100.0)
    as_built = base.copy()
    as_built[0, 0] = 100.5                                # one recorded berm cell
    v = compose_terrain_view(base, 5.0, as_built_z=as_built, as_built_version=3)
    assert v.heights[0, 0] == 100.5
    assert v.source[0, 0] == CurrentTerrainView.AS_BUILT
    assert (v.source[1:, :] == CurrentTerrainView.PRISTINE).all()
    assert (v.source[0, 1:] == CurrentTerrainView.PRISTINE).all()
    assert v.as_built_version == 3


def test_observed_layer_tags_masked_cells_and_reports_fraction():
    base = np.full((4, 4), 100.0)
    observed = base.copy()
    observed[2, 2] = 105.0
    mask = np.zeros((4, 4), dtype=bool)
    mask[2, 2] = True
    v = compose_terrain_view(base, 5.0, observed_heights=observed, observed_mask=mask, twin_version=7)
    assert v.heights[2, 2] == 105.0
    assert v.source[2, 2] == CurrentTerrainView.OBSERVED
    assert v.twin_version == 7
    assert np.isclose(v.observed_fraction, 1.0 / 16)


def test_observed_wins_over_as_built_where_both_cover_a_cell():
    """Precedence: measured reality (observed) overrides the remembered build at a shared cell."""
    base = np.full((3, 3), 100.0)
    as_built = base.copy(); as_built[1, 1] = 102.0        # remembered build at (1,1)
    observed = base.copy(); observed[1, 1] = 108.0        # but perception MEASURED (1,1) higher
    mask = np.zeros((3, 3), dtype=bool); mask[1, 1] = True
    v = compose_terrain_view(base, 5.0, as_built_z=as_built, as_built_version=1,
                             observed_heights=observed, observed_mask=mask, twin_version=2)
    assert v.heights[1, 1] == 108.0                       # observed value wins
    assert v.source[1, 1] == CurrentTerrainView.OBSERVED  # observed provenance wins


def test_shape_mismatched_layers_are_ignored_defensively():
    base = np.full((4, 4), 100.0)
    bad_ab = np.full((2, 2), 1.0)                         # wrong shape as-built
    bad_obs = np.full((3, 3), 9.0); bad_mask = np.ones((3, 3), dtype=bool)
    v = compose_terrain_view(base, 5.0, as_built_z=bad_ab, observed_heights=bad_obs,
                             observed_mask=bad_mask)
    assert np.array_equal(v.heights, base)               # bad layers can never corrupt the surface
    assert (v.source == CurrentTerrainView.PRISTINE).all()
