"""Image-derived shadow candidates for Algorithm P4 section 15.2."""
import os

import numpy as np
import pytest

from solnav.perception import shadow_extract as se

CLEAN = os.path.join(os.path.dirname(__file__), "fixtures", "shadow_clean.png")


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="shadow fixture absent")
def test_extracts_clean_shadow_from_pixels():
    from imageio.v3 import imread
    o = se.extract_shadow_azimuth(np.asarray(imread(CLEAN)))
    assert o.provenance == "RUNTIME_DERIVED"
    assert o.coordinate_frame == "IMAGE_X_RIGHT_Y_DOWN"
    assert o.confidence > 0.5
    assert 0.0 <= o.z_shadow_image_deg < 360.0
    assert o.dispersion_deg > 0.0 and o.n_support > 100
    assert o.periodicity_deg == 360 and o.direction_resolved
    assert not o.covariance_calibrated


def test_confidence_gate_rejects_low_concentration():
    # flat image -> no shadow boundary -> gated
    with pytest.raises(ValueError):
        se.extract_shadow_azimuth(np.full((100, 100), 128, np.uint8))


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="shadow fixture absent")
def test_gate_threshold_enforced():
    from imageio.v3 import imread
    img = np.asarray(imread(CLEAN))
    # an impossibly high gate must reject even the clean shadow (gate is enforced, not cosmetic)
    with pytest.raises(ValueError):
        se.extract_shadow_azimuth(img, min_conf=0.999)
    # gate=False returns the (low-confidence-allowed) measurement
    o = se.extract_shadow_azimuth(img, min_conf=0.999, gate=False)
    assert o.confidence > 0.5


CLUTTER = os.path.join(os.path.dirname(__file__), "fixtures", "shadow_clutter.png")


@pytest.mark.skipif(not os.path.exists(CLUTTER), reason="clutter fixture absent")
def test_p7_passes_gate_in_clutter_where_boundary_fails():
    from imageio.v3 import imread
    img = np.asarray(imread(CLUTTER))
    # P7 blob segmentation recovers the shadow AXIS in dense clutter -> passes the gate
    o = se.extract_shadow_azimuth_p7(img)
    assert o.confidence > 0.30 and o.n_support >= 3
    assert o.provenance == "RUNTIME_DERIVED"
    assert o.periodicity_deg == 180 and not o.direction_resolved
    assert not o.covariance_calibrated
    # the per-pixel boundary method is (correctly) rejected on the same cluttered scene
    with pytest.raises(ValueError):
        se.extract_shadow_azimuth(img)


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="shadow fixture absent")
def test_image_direction_is_not_a_body_heading_factor():
    """Pixel extraction must stop before factorization without calibrated frame conversion."""
    from imageio.v3 import imread

    obs = se.extract_shadow_azimuth(np.asarray(imread(CLEAN)))
    assert obs.coordinate_frame == "IMAGE_X_RIGHT_Y_DOWN"
    assert not obs.covariance_calibrated
    assert not hasattr(obs, "z_shadow_body_deg")
