"""SN-02 [REQ:SN-02]: the shadow-vector detection front-end that feeds the SN-03 yaw factor.

From a shadow mask + scene context, extract the dominant shadow-edge AZIMUTH and an acceptance
verdict, REJECTING: self/rover-cast shadows (near the rover footprint), LED-cast shadows (when the
LEDs are on), saturated regions, and ambiguous penumbra / texture edges (low edge sharpness). The
testable contract is the accept/reject decision -- only accepted vectors become yaw factors.
"""
import numpy as np

from dart.shadow_vectors import detect_shadow_vector


def _ridge_mask(h=40, w=40, ridge_rows=(18, 22)):
    from dart.shadow_predict import cast_shadow_mask
    z = np.zeros((h, w)); z[ridge_rows[0]:ridge_rows[1], :] = 6.0
    return cast_shadow_mask((z, 5.0), sun_az_deg=90.0, sun_el_deg=8.0), z


def test_accepts_a_clean_low_sun_shadow_and_reports_azimuth():
    mask, _ = _ridge_mask()
    v = detect_shadow_vector(mask, cell_m=5.0, sun_az_deg=90.0, sun_el_deg=8.0)
    assert v["accepted"] is True
    assert abs(v["azimuth_deg"] - 90.0) < 25.0          # the cast direction (anti-solar), within tol
    assert v["sigma_m"] > 0


def test_rejects_when_no_shadow_present():
    import numpy as np
    v = detect_shadow_vector(np.zeros((40, 40), bool), cell_m=5.0, sun_az_deg=90.0, sun_el_deg=8.0)
    assert v["accepted"] is False and "no shadow" in v["reason"].lower()


def test_rejects_rover_self_shadow_near_footprint():
    mask, _ = _ridge_mask()
    # a shadow blob right at the rover footprint = self-cast -> reject
    v = detect_shadow_vector(mask, cell_m=5.0, sun_az_deg=90.0, sun_el_deg=8.0,
                             rover_rc=(20, 20), rover_radius_cells=12)
    assert v["accepted"] is False and "rover" in v["reason"].lower()


def test_rejects_when_leds_on():
    mask, _ = _ridge_mask()
    v = detect_shadow_vector(mask, cell_m=5.0, sun_az_deg=90.0, sun_el_deg=8.0, leds_on=True)
    assert v["accepted"] is False and "led" in v["reason"].lower()


def test_rejects_fuzzy_penumbra_low_sharpness():
    # a fat, ill-defined shadow blob (no crisp edge) -> ambiguous -> reject
    import numpy as np
    fuzzy = np.zeros((40, 40), bool); fuzzy[5:35, 5:35] = True   # huge area, tiny boundary fraction
    v = detect_shadow_vector(fuzzy, cell_m=5.0, sun_az_deg=90.0, sun_el_deg=8.0)
    assert v["accepted"] is False and ("penumbra" in v["reason"].lower() or "sharp" in v["reason"].lower())
