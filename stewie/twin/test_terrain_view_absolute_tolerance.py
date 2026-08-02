"""SR-17 [REQ:LY-07]: an as-built change is an ABSOLUTE elevation delta, never a relative one.

`compose_terrain_view` used `~np.isclose(ab, base)`, whose numpy default `rtol=1e-5` is RELATIVE --
applied to ABSOLUTE lunar elevations. Measured on the real Haworth tile (min -96.61 / max 2842.21 /
mean 1381.01 m): the drop threshold ran to 0.0284 m and **26.8% of the tile exceeded the 0.02 m
acceptance tolerance** (`lode.planner_acceptance.accept_flatness_tol_m`). At base 2800 m a +0.025 m
fill vanished entirely and the cell stayed PRISTINE -- so `as_built_dem` handed the planner the
pristine surface for ground TerrainMemory said was built, and the LY-07 drape rendered no change.

`terrain_memory.imprint_on_dem_resampled` divides by capacity=100, so every edge cell of every real
build is sub-centimetre and lands exactly in this hole. And the system already disagreed with itself:
`terrain_memory.summary()` counts changed cells with an ABSOLUTE `np.abs(d) > 1e-9`, so summary and
view could report different answers about whether the same build existed.

WHY THE OLD TESTS MISSED IT: every base in `test_terrain_view.py` is `np.full(..., 100.0)` -- three
orders of magnitude below the elevations where the relative threshold grows teeth. These tests use
real lunar magnitudes.

Run: <venv>/bin/python -m pytest stewie/twin/test_terrain_view_absolute_tolerance.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.twin.terrain_view import AS_BUILT_EPS_M, CurrentTerrainView, compose_terrain_view

#: The acceptance tolerance the planner measures builds against.
_ACCEPT_TOL_M = 0.02
#: Real Haworth tile statistics from the review's measurement.
_HIGH_BASE = 2800.0


@pytest.mark.parametrize("base_m", [0.0, 100.0, 1381.01, 2800.0, 2842.21])
def test_a_build_at_the_acceptance_tolerance_is_visible_at_every_elevation(base_m):
    """The core defect: visibility must not depend on how high the ground happens to be."""
    base = np.full((8, 8), base_m)
    ab = base.copy()
    ab[3, 3] += _ACCEPT_TOL_M + 0.005            # a fill the acceptance check would measure
    view = compose_terrain_view(base, 5.0, as_built_z=ab)
    assert view.source[3, 3] == CurrentTerrainView.AS_BUILT, (
        f"a {_ACCEPT_TOL_M + 0.005} m build vanished at base {base_m} m -- the planner would be handed "
        "the pristine surface for ground that was built")
    assert view.heights[3, 3] == pytest.approx(ab[3, 3])


def test_the_old_relative_threshold_would_have_erased_it():
    """Non-vacuity: prove the pre-fix comparison really does drop this build at lunar elevations."""
    base = np.full((4, 4), _HIGH_BASE)
    ab = base.copy()
    ab[1, 1] += 0.025
    assert np.isclose(ab[1, 1], base[1, 1]), (
        "np.isclose no longer swallows a 25 mm build at 2800 m -- this guard has gone vacuous")
    view = compose_terrain_view(base, 5.0, as_built_z=ab)
    assert view.source[1, 1] == CurrentTerrainView.AS_BUILT   # ... but the fixed path keeps it


def test_the_threshold_is_far_below_the_acceptance_tolerance():
    """A build the acceptance check can measure must never be invisible to the view."""
    assert AS_BUILT_EPS_M < _ACCEPT_TOL_M / 100.0


def test_sub_millimetre_noise_is_still_not_a_build():
    """The tolerance must still reject float noise, or every cell reads as built."""
    base = np.full((4, 4), 1381.01)
    ab = base + 1e-9
    view = compose_terrain_view(base, 5.0, as_built_z=ab)
    assert not (view.source == CurrentTerrainView.AS_BUILT).any()


def test_view_and_memory_summary_agree_about_whether_a_build_exists():
    """The internal inconsistency the review flagged: summary() used absolute, the view used relative."""
    base = np.full((6, 6), _HIGH_BASE)
    ab = base.copy()
    ab[2, 2] += 0.025
    d = ab - base
    memory_says_changed = int(np.count_nonzero(np.abs(d) > 1e-9))     # summary()'s convention
    view = compose_terrain_view(base, 5.0, as_built_z=ab)
    view_says_changed = int(np.count_nonzero(view.source == CurrentTerrainView.AS_BUILT))
    assert memory_says_changed == view_says_changed == 1


def test_an_unchanged_surface_stays_pristine():
    base = np.full((5, 5), 2842.21)
    view = compose_terrain_view(base, 5.0, as_built_z=base.copy())
    assert not (view.source == CurrentTerrainView.AS_BUILT).any()
