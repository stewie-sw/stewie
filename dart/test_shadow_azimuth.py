"""C-03 (audit 2026-06-13): the two shadow engines share ONE azimuth->grid convention.

Before the fix, shadow_predict.cast_shadow_mask marched (col,row)=(cos,sin) while illumination.horizon_clip
marched (row,col)=(cos,sin) -- a row/col swap that rotated shadow behavior 90deg between them (the audit
probed 210 disagreeing cells on a horizontal ridge). Both now use illumination.sun_march_dir_rowcol, the
canonical cartographic convention (north-clockwise az; row=+Z, col=+X; 90deg = +X = image right).
"""
import numpy as np

from dart import illumination as IL
from dart import shadow_predict as SP


def test_sun_march_dir_cardinals():
    """az=0 -> +Z(+row); az=90 -> +X(+col); az=180 -> -row; az=270 -> -col."""
    for az, (er, ec) in [(0.0, (1, 0)), (90.0, (0, 1)), (180.0, (-1, 0)), (270.0, (0, -1))]:
        dr, dc = IL.sun_march_dir_rowcol(az)
        assert abs(dr - er) < 1e-9 and abs(dc - ec) < 1e-9, (az, dr, dc)


def test_shadow_modules_agree_on_a_cardinal_sun():
    """A N-S wall under an east (az=90, +X) low sun casts its shadow WEST (-col). Both the cast-shadow
    mask and the horizon clip must shadow the same (west) side and agree on most cells."""
    n, cell = 40, 1.0
    z = np.zeros((n, n), float)
    z[:, 20] = 6.0                                    # a north-south wall at col=20
    az, el = 90.0, 8.0                                # sun from +X (east), low elevation
    cast = SP.cast_shadow_mask((z, cell), az, el, max_range_m=40.0)   # True = shadowed
    lit = IL.horizon_clip(z, cell, az, el)                            # True = illuminated
    hor_shadow = ~lit
    west = (slice(None), slice(5, 19))                # west of the wall (down-sun) -> shadowed
    east = (slice(None), slice(21, 35))               # east of the wall (sun-facing) -> lit
    assert cast[west].mean() > 0.3 and cast[east].mean() < 0.05
    assert hor_shadow[west].mean() > 0.3 and hor_shadow[east].mean() < 0.05
    assert (cast == hor_shadow).mean() > 0.85         # agree (a 90deg swap would put cast on the row axis)
