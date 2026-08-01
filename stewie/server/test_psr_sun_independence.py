"""SR-07 [REQ:LY-05]: the `psr` drape must NOT be keyed on a sun it ignores.

`_layer_rgba`'s psr branch accepts `sun_az`/`sun_el` and uses neither -- it runs its own fixed
`for az in range(0, 360, 30)` horizon sweep at a fixed 3.0 deg elevation, so its pixels are a pure
function of (dem, cell_m). But `"psr"` sat in `_SUN_DEPENDENT_GLOBE_KINDS`, directly beneath a comment
stating the very invariant that placement violates.

Consequence, measured by the 2026-07-28 review: `render_globe('psr', sun_az=90)` = 9.41 s and
`sun_az=91` = 9.05 s, with `np.array_equal` True and two 4.19 MB files committed. Production held one
md5 across three distinct sun keys. The reachable key space is 360 x 181 = 65,160 per site (~273 GB,
~181 CPU-hours) through the deliberately public globe route -- the largest single contributor to
SR-06's live 672 MB.

`routers/dem.py` already excluded psr for exactly this reason (#239, "psr sweeps its own 12 azimuths
... else varying sun_az would bust the cache and re-trigger the expensive psr sweep every call"). The
two lists had drifted apart, so the fix is to make the drift itself detectable.

Real Haworth DEM, subsampled to a small crop so the horizon sweep stays cheap.

Run: <venv>/bin/python -m pytest stewie/server/test_psr_sun_independence.py -q
"""
from __future__ import annotations

import numpy as np
import pytest

from stewie.server import gis_layers as GL


@pytest.fixture(scope="module")
def dem_crop():
    """A small crop of the REAL Haworth LOLA tile (subsampled real data, never synthesised)."""
    from stewie.server.state import moon_dem
    dem, _anchor = moon_dem("haworth")
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        pytest.skip("real Haworth DEM not available in this environment")
    return np.asarray(base, dtype=float)[:96, :96]


def test_psr_pixels_ignore_the_sun(dem_crop):
    """The ground truth: psr output is identical across sun angles, so keying on the sun is waste."""
    a = GL._layer_rgba(dem_crop, 5.0, "psr", 90.0, 6.0)
    b = GL._layer_rgba(dem_crop, 5.0, "psr", 91.0, 40.0)
    assert a is not None and b is not None
    assert np.array_equal(a, b), "psr pixels changed with the sun -- it is genuinely sun-dependent"


def test_psr_is_not_keyed_on_the_sun(dem_crop):
    """The fix: psr must not be in the sun-dependent cache-key list."""
    assert "psr" not in GL._SUN_DEPENDENT_GLOBE_KINDS


def test_globe_and_dem_sun_keying_agree_on_psr():
    """The two sibling lists drifted apart, which IS the defect -- pin them together.

    `routers/dem.py` keys the work-area cache on the sun only for ("dem", "hillshade", "illumination",
    "incidence"). Whatever else changes, both modules must agree that psr is sun-INDEPENDENT.
    """
    import inspect

    from stewie.server.routers import dem as DEM
    src = inspect.getsource(DEM)
    assert '("dem", "hillshade", "illumination", "incidence")' in src, (
        "routers/dem.py sun-keying tuple changed shape; re-check it still excludes psr")
    assert "psr" not in GL._SUN_DEPENDENT_GLOBE_KINDS


def test_sun_dependent_kinds_actually_use_the_sun(dem_crop):
    """Guard the inverse error: every kind still CLAIMED sun-dependent must really vary with the sun.

    Without this, 'fixing' SR-07 by emptying the list would pass the tests above while silently serving
    a stale illumination drape -- a worse defect than the one being fixed.
    """
    for kind in ("illumination", "incidence"):
        a = GL._layer_rgba(dem_crop, 5.0, kind, 90.0, 6.0)
        b = GL._layer_rgba(dem_crop, 5.0, kind, 270.0, 45.0)
        if a is None or b is None:
            pytest.skip(f"{kind} drape unavailable in this environment")
        assert not np.array_equal(a, b), (
            f"{kind} is listed sun-dependent but its pixels did not change with the sun")
