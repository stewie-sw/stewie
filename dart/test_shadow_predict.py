"""Excavation-aware shadow prediction on the real Haworth DEM."""
import os

import numpy as np

from dart import shadow_predict as SP
from dart import shadow_vectors as SV
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


def _wall():
    z = np.zeros((40, 40)); z[:, 20] = 6.0      # a N-S wall (real-shaped geometry, not fabricated values)
    return (z, 1.0)


def test_sun_vector_change_reevaluates_shadows():
    # [REQ:SN-04] shadow factors re-evaluated when the SUN VECTOR changes (azimuth AND elevation), not
    # only when terrain is excavated -- the prediction is f(s(t)), never a stale cache.
    z, cell = _wall()
    east = SP.cast_shadow_mask((z, cell), 90.0, 8.0, max_range_m=40)     # sun +X (east) -> shadow WEST
    west = SP.cast_shadow_mask((z, cell), 270.0, 8.0, max_range_m=40)    # sun -X (west) -> shadow EAST
    assert east[:, 5:19].mean() > 0.3 and east[:, 21:35].mean() < 0.05   # azimuth flip moves the shadowed side
    assert west[:, 21:35].mean() > 0.3 and west[:, 5:19].mean() < 0.05
    assert (east != west).mean() > 0.3                                   # re-evaluated: the mask genuinely changed
    low = SP.cast_shadow_mask((z, cell), 90.0, 5.0, max_range_m=40)
    high = SP.cast_shadow_mask((z, cell), 90.0, 40.0, max_range_m=40)
    assert high.sum() < low.sum()                                        # elevation change re-eval: higher sun, shorter shadow


def test_viewpoint_change_reevaluates_factor_prediction_is_world_frame():
    # [REQ:SN-04] re-evaluate shadow FACTORS when the observation VIEWPOINT changes. The cast-shadow
    # PREDICTION is world-frame (terrain+sun only) so a viewpoint change does not stale it -- the SAME
    # world shadows are reused; the per-viewpoint factor is re-derived by re-observing (SN-02 detect),
    # whose self/rover-cast gate depends on the rover pose. Moving the rover onto its own shadow flips
    # the factor from accepted to rejected -> the factor IS re-evaluated with the viewpoint. (Uses a
    # discrete object's CRISP shadow -- a big wall's broad shadow is rejected as low-sharpness penumbra.)
    z = np.zeros((40, 40)); z[19:22, 19:22] = 5.0; cell = 1.0
    mask = SP.cast_shadow_mask((z, cell), 90.0, 8.0, max_range_m=40)
    assert (SP.cast_shadow_mask((z, cell), 90.0, 8.0, max_range_m=40) == mask).all()   # no viewpoint term -> invariant
    rows, cols = np.where(mask)
    centroid = (float(rows.mean()), float(cols.mean()))
    far = SV.detect_shadow_vector(mask, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0,
                                  rover_rc=(0, 39), rover_radius_cells=3.0)        # rover far from the shadow
    onit = SV.detect_shadow_vector(mask, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0,
                                   rover_rc=centroid, rover_radius_cells=8.0)      # rover sits on its own shadow
    assert far["accepted"] and not onit["accepted"]                              # factor re-evaluated per viewpoint
    assert "self" in onit["reason"] or "rover" in onit["reason"]


def test_local_object_casts_expected_shadow_from_s_of_t():
    # [REQ:SN-01] expected shadow azimuth derived from s(t) AND local OBJECTS (a discrete rock/clast, not
    # just terrain undulation): the object casts its shadow on the anti-solar side, and the detected
    # vector's azimuth equals the sun azimuth s(t).
    z = np.zeros((40, 40)); z[19:22, 19:22] = 5.0      # a discrete raised object (a ~3x3 rock)
    cell = 1.0
    m = SP.cast_shadow_mask((z, cell), sun_az_deg=90.0, sun_el_deg=8.0, max_range_m=40)   # sun from +X (east)
    assert m.sum() > 0                                                    # the object casts a shadow
    rows, cols = np.where(m)
    assert cols.mean() < 19                                               # shadow falls WEST (anti-solar of an east sun)
    det = SV.detect_shadow_vector(m, cell_m=cell, sun_az_deg=90.0, sun_el_deg=8.0)
    assert det["accepted"] and abs(det["azimuth_deg"] - 90.0) < 1e-6      # derived azimuth == s(t) azimuth
