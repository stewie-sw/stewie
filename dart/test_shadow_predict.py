"""Excavation-aware shadow prediction on the real Haworth DEM."""
import os

from dart import shadow_predict as SP
from stewie.twin import world_model as WM
_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))

_HAVE = os.path.exists(os.path.join(_REPO_SAMPLES, "lunar_dem/haworth_10km_5m/heightmap.rf32"))


def _crop():
    from lode import mission_planner as MP
    Z, cell = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor((Z, cell))
    r0, c0 = int(oy / cell), int(ox / cell)
    return (Z[r0:r0 + 50, c0:c0 + 50].copy(), cell)


def test_sun_down_all_shadow_high_sun_mostly_lit():
    if not _HAVE:
        return
    crop = _crop()
    assert SP.cast_shadow_mask(crop, 0.0, 0.0).all()                  # sun down -> all shadow
    assert SP.cast_shadow_mask(crop, 0.0, 80.0, max_range_m=100).mean() < 0.5   # high sun -> mostly lit


def test_excavation_creates_new_shadow():
    # [REQ:SN-04] shadow re-evaluated when terrain is excavated (excavation-aware prediction)
    if not _HAVE:
        return
    wm = WM.WorldModel(_crop())
    wm.add_event(125.0, 125.0, 15.0, 3.0, kind="fill")               # a 3 m berm
    newly_shadowed, _newly_lit = SP.excavation_shadow_delta(wm, sun_az_deg=0.0, sun_el_deg=15.0,
                                                            max_range_m=100)
    assert newly_shadowed.sum() > 0                                  # berm casts a NEW shadow (terrain change)
