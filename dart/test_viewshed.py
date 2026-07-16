"""TW-12 [REQ:TW-12]: a viewshed/LOS layer producer fills terrain.los.

An r.viewshed-class line-of-sight raster from the site DEM + a localization anchor. Each ground cell
is True where a mast-height observer at that cell has line-of-sight to at least one anchor, False where
every anchor is terrain-occluded -- exactly the LOS that a fiducial pose-lock needs. This producer is
the terrain.los raster that SN-05's visibility route-cost term CONSUMES (previously SN-05 marched
`dart.visibility.is_visible` per route with no named producer).

Grounded on the REAL Haworth LOLA 5 m DEM (samples/lunar_dem/haworth_10km_5m) -- no synthetic terrain.
The window r0=340,c0=220,N=40 has genuine relief (~57 m); from the low corner anchor (39,0) the viewshed
is a real mix (142 cells with LOS, 1458 ridge-occluded), so the assertions below are non-vacuous.
"""
import os

import numpy as np

from dart.illumination_cost import illumination_cost
from dart.visibility import is_visible, viewshed

_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))
_HAVE = os.path.exists(os.path.join(_REPO_SAMPLES, "lunar_dem/haworth_10km_5m/heightmap.rf32"))

_R0, _C0, _N = 340, 220, 40
_ANCHOR_RC = (39, 0)                       # the low corner of the window (verified real mix of LOS/occluded)
_VISIBLE_RC = [(39, 1), (38, 0), (38, 1)]  # cells with a real line-of-sight to the anchor
_OCCLUDED_RC = [(0, 39), (0, 0), (20, 39)] # cells behind the intervening ridge -> no line-of-sight


def _real_crop():
    from stewie.terrain.site_dem import load_haworth_dem
    Z, cell = load_haworth_dem()
    return Z[_R0:_R0 + _N, _C0:_C0 + _N].astype(float), cell


def _anchor_xy(cell):
    ar, ac = _ANCHOR_RC
    return (ac * cell, ar * cell)


def test_viewshed_produces_terrain_los_over_real_dem():  # [REQ:TW-12]
    if not _HAVE:
        return
    crop, cell = _real_crop()
    dem = (crop, cell)
    anchor = _anchor_xy(cell)

    los = viewshed(dem, (0.0, 0.0), [anchor])

    # the terrain.los raster is a DEM-aligned boolean visibility field
    assert los.shape == crop.shape
    assert los.dtype == np.bool_
    # non-vacuous on real terrain: the ridge genuinely occludes some cells and not others
    assert los.any() and (~los).any()
    # the anchor's own cell always has line-of-sight to itself
    ar, ac = _ANCHOR_RC
    assert los[ar, ac]
    # open cells near the anchor are visible; cells behind the ridge are not (r.viewshed acceptance)
    for r, c in _VISIBLE_RC:
        assert los[r, c], f"open cell {(r, c)} must have line-of-sight to the anchor"
    for r, c in _OCCLUDED_RC:
        assert not los[r, c], f"ridge-occluded cell {(r, c)} must be blind to the anchor"

    # the producer IS the audited per-cell LOS march applied cell-wise (not a fabricated drape)
    ox, oy = 0.0, 0.0
    for r, c in [*_VISIBLE_RC, *_OCCLUDED_RC, _ANCHOR_RC]:
        assert bool(los[r, c]) == is_visible(dem, (ox, oy), (c * cell, r * cell), anchor)


def test_sn05_visibility_term_consumes_terrain_los():  # [REQ:TW-12]
    if not _HAVE:
        return
    crop, cell = _real_crop()
    anchor = _anchor_xy(cell)

    los = viewshed((crop, cell), (0.0, 0.0), [anchor])

    # SN-05 consumes the PRECOMPUTED terrain.los raster (no per-call anchor march when los is supplied)
    ic_los = illumination_cost(crop, cell_m=cell, sun_az_deg=45.0, sun_el_deg=15.0,
                               los=los, dem_origin=(0.0, 0.0))
    # blind cells (no LOS) carry visibility cost 1; cells with LOS carry 0 -> exactly 1 - terrain.los
    assert np.array_equal(ic_los["visibility"], 1.0 - los.astype(float))

    # the producer feeds SN-05 the SAME field SN-05 used to march inline from anchors
    ic_anchors = illumination_cost(crop, cell_m=cell, sun_az_deg=45.0, sun_el_deg=15.0,
                                   anchors=[anchor], dem_origin=(0.0, 0.0))
    assert np.array_equal(ic_los["visibility"], ic_anchors["visibility"])

    # concrete: a ridge-occluded cell is flagged, an open cell is not
    for r, c in _OCCLUDED_RC:
        assert ic_los["visibility"][r, c] == 1.0
    for r, c in _VISIBLE_RC:
        assert ic_los["visibility"][r, c] == 0.0
