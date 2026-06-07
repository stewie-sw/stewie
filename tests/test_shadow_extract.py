"""Image-derived shadow azimuth (Algorithm P4 sec 15.2): the first genuine sensor->factor."""
import os

import numpy as np
import pytest

from solnav.perception import shadow_extract as se

CLEAN = os.path.join(os.path.dirname(__file__), "fixtures", "shadow_clean.png")


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="shadow fixture absent")
def test_extracts_clean_shadow_from_pixels():
    from imageio.v3 import imread
    o = se.extract_shadow_azimuth(np.asarray(imread(CLEAN)))
    assert o.provenance == "IMAGE_DERIVED"           # I3: measurement from pixels, not truth
    assert o.confidence > 0.5                          # clean single cast shadow -> high concentration
    assert 0.0 <= o.z_shadow_body_deg < 360.0
    assert o.sigma_deg > 0.0 and o.n_edge_px > 100     # I4: covariance accompanies the measurement


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
    assert o.confidence > 0.30 and o.n_edge_px >= 3 and o.provenance == "IMAGE_DERIVED"
    # the per-pixel boundary method is (correctly) rejected on the same cluttered scene
    with pytest.raises(ValueError):
        se.extract_shadow_azimuth(img)


@pytest.mark.skipif(not os.path.exists(CLEAN), reason="shadow fixture absent")
def test_image_derived_factor_bounds_gyro_drift_end_to_end():
    """First end-to-end sensor->factor: an IMAGE-DERIVED shadow heading bounds a real gyro drift."""
    from imageio.v3 import imread

    from solnav.eval import metrics
    from solnav.geometry import shadow
    from solnav.slam import posegraph as pg
    true = pg.integrate_odometry([0, 0, 0.0], [[0.6, 0.0, 0.0]] * 30)
    bias = np.radians(0.4)
    odo = [z + np.array([0, 0, bias]) for z in pg.relative_odometry(true)]
    dr = pg.integrate_odometry(true[0], odo)
    obs = se.extract_shadow_azimuth(np.asarray(imread(CLEAN)))      # from pixels, no truth
    yaw_raw = shadow.heading_from_shadow(obs.z_shadow_body_deg, 30.0)
    yaw_abs = np.radians(yaw_raw + (np.degrees(true[0, 2]) - yaw_raw))   # one-time start calibration
    info = 1.0 / np.radians(obs.sigma_deg) ** 2

    def slv(use):
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo):
            g.add_odom(i, i + 1, z)
        if use:
            for i in range(0, 31, 3):
                g.add_heading(i, yaw_abs, info=info)
        return g.solve(np.array(dr))
    ate_odom = metrics.ate_rmse_raw(slv(False), true)
    ate_sensor = metrics.ate_rmse_raw(slv(True), true)
    assert ate_sensor < 0.2 * ate_odom        # the image-derived factor bounds the gyro drift
