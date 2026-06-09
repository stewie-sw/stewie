from solnav.geometry import height_ref as hr
from solnav.geometry import shadow


def test_vertical_parallax_triangulation_recovers():
    # feature H=0.5 at D=8; two camera heights 2.0 and 1.0
    H, D = 0.5, 8.0
    d1 = hr.depression_to_landmark(2.0, H, D)
    d2 = hr.depression_to_landmark(1.0, H, D)
    Hr, Dr = hr.triangulate_landmark_height(2.0, d1, 1.0, d2)
    assert abs(Hr - H) < 1e-6 and abs(Dr - D) < 1e-6


def test_bigger_height_baseline_tightens_estimate():
    H, D = 0.5, 8.0
    s_small = hr.triangulation_height_sigma_m(1.1, 1.0, hr.depression_to_landmark(1.1, H, D),
                                              hr.depression_to_landmark(1.0, H, D), 0.5)   # 0.1 m lift
    s_big = hr.triangulation_height_sigma_m(2.0, 1.0, hr.depression_to_landmark(2.0, H, D),
                                            hr.depression_to_landmark(1.0, H, D), 0.5)     # 1.0 m lift
    assert s_big < s_small                       # wider height baseline -> tighter height


def test_equal_depressions_cannot_triangulate():
    import pytest
    with pytest.raises(ValueError):
        hr.triangulate_landmark_height(1.0, 5.0, 1.0, 5.0)


def test_shadow_and_landmark_agree_on_true_height():
    # both cues recover the same true feature height (cross-cue consistency)
    H, D, e = 0.5, 8.0, 6.0
    L = shadow.shadow_length_from_height(H, e)
    H_shadow = shadow.height_from_shadow(L, e)
    d1 = hr.depression_to_landmark(2.0, H, D); d2 = hr.depression_to_landmark(1.0, H, D)
    H_landmark, _ = hr.triangulate_landmark_height(2.0, d1, 1.0, d2)
    assert abs(H_shadow - H_landmark) < 1e-6
    assert abs(H_shadow - H) < 1e-6
