"""SN-10: articulation-parallax triangulation (range + standstill position fix)."""
import math

import numpy as np
import pytest

from dart import articulated_parallax as AP


def test_range_round_trip_from_vertical_parallax():
    """A landmark at known range R, seen from h and h+dh, is recovered from the depression change."""
    h, dh, R_true = 0.5, 0.20, 8.0
    dtheta = AP.depression_angle(h + dh, R_true) - AP.depression_angle(h, R_true)
    assert AP.range_from_vertical_parallax(h, dh, dtheta) == pytest.approx(R_true, rel=1e-6)


def test_nearer_landmark_gives_more_parallax():
    h, dh = 0.5, 0.20
    near = AP.depression_angle(h + dh, 3.0) - AP.depression_angle(h, 3.0)
    far = AP.depression_angle(h + dh, 12.0) - AP.depression_angle(h, 12.0)
    assert near > far > 0                                  # closer -> larger depression-angle change


def test_position_fix_from_known_landmark_ranges():
    """Trilateration recovers the rover (x,y) from ranges to >=3 known landmarks (heading-free)."""
    rover = np.array([4.0, -2.0])
    L = np.array([[0.0, 0.0], [10.0, 0.0], [5.0, 9.0]])
    r = np.hypot(*(rover - L).T)
    x, y = AP.position_fix_from_ranges(L, r, guess=(0.0, 0.0))
    assert (x, y) == pytest.approx((4.0, -2.0), abs=1e-4)


def test_articulation_range_beats_bearing_only_under_heading_drift():
    """SN-10 [REQ:SN-10] THE IMPROVEMENT: range trilateration (from the articulation baseline) is
    HEADING-FREE, so a drifted heading does not bias it; a bearing-only fix from a static monocular
    camera rotates with the heading error and mislocates. We should see the error shrink."""
    rover = np.array([4.0, -2.0])
    L = np.array([[0.0, 0.0], [10.0, 0.0], [5.0, 9.0]])

    # articulation parallax -> ranges -> trilateration (no heading used)
    r = np.hypot(*(rover - L).T)
    x, y = AP.position_fix_from_ranges(L, r, guess=(6.0, 0.0))
    err_range = math.hypot(x - rover[0], y - rover[1])

    # bearing-only: true bearings to each landmark, but the rover's heading estimate is off by 8 deg,
    # so the world-frame bearing rays are rotated -> their intersection is displaced.
    yaw_err = math.radians(8.0)
    true_brg = np.arctan2((L - rover)[:, 1], (L - rover)[:, 0])
    rot = true_brg + yaw_err                               # bearings carried into the world with a wrong heading
    # intersect the (mis-rotated) bearing rays from a rough position prior by least squares
    A, b = [], []
    for (lx, ly), th in zip(L, rot):
        A.append([math.sin(th), -math.cos(th)]); b.append(lx * math.sin(th) - ly * math.cos(th))
    sol, *_ = np.linalg.lstsq(np.array(A), np.array(b), rcond=None)
    err_bearing = math.hypot(sol[0] - rover[0], sol[1] - rover[1])

    assert err_range < 1e-3                                # range fix is exact (heading-free)
    assert err_bearing > 0.3                               # bearing-only is biased by the heading error
    assert err_range < err_bearing                         # the improvement


def test_range_sigma_grows_with_range_shrinks_with_baseline():
    import math
    from dart import articulated_parallax as AP
    s = math.radians(0.05)                                 # 0.05 deg angular noise
    assert AP.parallax_range_sigma(10.0, 0.2, s) > AP.parallax_range_sigma(5.0, 0.2, s)   # ~R^2
    assert AP.parallax_range_sigma(10.0, 0.4, s) < AP.parallax_range_sigma(10.0, 0.2, s)  # bigger dh -> tighter


def test_position_sigma_improves_with_more_and_closer_landmarks():
    import math
    import numpy as np
    from dart import articulated_parallax as AP
    s = math.radians(0.05); rover = np.array([0.0, 0.0])
    far = np.array([[20.0, 0.0], [0.0, 20.0]])
    near = np.array([[6.0, 0.0], [0.0, 6.0]])
    assert AP.position_fix_sigma(near, rover, dh_m=0.2, sigma_theta_rad=s) <            AP.position_fix_sigma(far, rover, dh_m=0.2, sigma_theta_rad=s)
    three = np.array([[6.0, 0.0], [0.0, 6.0], [-5.0, -5.0]])
    two = np.array([[6.0, 0.0], [0.0, 6.0]])
    assert AP.position_fix_sigma(three, rover, dh_m=0.2, sigma_theta_rad=s) <=            AP.position_fix_sigma(two, rover, dh_m=0.2, sigma_theta_rad=s) + 1e-9


def test_pixel_parallax_round_trip_and_camera_capability():
    """SN-10 [REQ:SN-10] pixel-domain: we MEASURE a shadow-tip pixel shift and convert via fx. The
    pinhole identity dv = fx*dh/R round-trips, and a 0.2 m lift is comfortably resolvable on the real
    IMX547 + 6 mm lens (tens of px near, >1 px to hundreds of m)."""
    from dart import articulated_parallax as AP
    from stewie.specs import ipex_specs as S
    fx = S.flight_fx_px(6.0)                               # physical lens fx in px (~2190)
    dh = 0.202                                             # max camera lift (IRON_CROSS)
    dv = AP.pixel_shift_for_range(dh, 5.0, fx)
    assert dv > 50.0                                       # ~88 px at 5 m -> easily measured
    assert AP.range_from_pixel_parallax(dh, dv, fx) == pytest.approx(5.0, rel=1e-9)   # round-trip
    assert AP.pixel_shift_for_range(dh, 30.0, fx) > 1.0    # still multi-px at 30 m
    assert AP.camera_resolvable_range_m(dh, fx, min_pixel_shift=1.0) > 200.0          # within capability
    # sub-pixel edge localization (0.3 px) sharpens range error well below the angle assumption
    assert AP.range_sigma_from_pixel_noise(10.0, dh, fx, sigma_px=0.3) < 0.1
