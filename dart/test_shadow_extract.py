"""Image-derived shadow candidates for Algorithm P4 section 15.2."""
import os

import numpy as np
import pytest

from dart import shadow_extract as se

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


def test_shadow_segment_maps_to_ground_body_frame():
    q_down = np.array([-np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)])
    obs = se.map_shadow_segment_to_ground(
        base_uv=(49.5, 49.5),
        tip_uv=(74.5, 49.5),
        camera_position_base_m=(0.0, 1.0, 0.0),
        camera_quaternion_xyzw=q_down,
        width_px=100,
        height_px=100,
        vertical_fov_deg=90.0,
        ground_y_m=0.0,
        camera_id="down_cam",
        sample_id="frame0:down_cam",
        periodicity_deg=360,
        direction_resolved=True,
    )
    assert np.allclose(obs.base_ground_m, [0.0, 0.0, 0.0], atol=1e-9)
    assert np.allclose(obs.direction_body_xz, [1.0, 0.0], atol=1e-9)
    assert abs(obs.azimuth_body_deg) < 1e-9
    assert obs.variance_deg2 > 0.0
    assert obs.coordinate_frame == "BASE_LINK_GODOT_X_FORWARD_Z_RIGHT"


def test_axial_shadow_cannot_claim_resolved_direction():
    with pytest.raises(ValueError, match="resolved direction"):
        se.map_shadow_segment_to_ground(
            (49.5, 49.5),
            (74.5, 49.5),
            (0.0, 1.0, 0.0),
            (-np.sqrt(0.5), 0.0, 0.0, np.sqrt(0.5)),
            100,
            100,
            90.0,
            0.0,
            camera_id="down_cam",
            sample_id="frame0:down_cam",
            periodicity_deg=180,
            direction_resolved=True,
        )
