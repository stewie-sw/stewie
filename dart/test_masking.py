import os

import numpy as np
import pytest

from dart import masking

# Real dustgym Godot render used as a fixture (no synthetic image data).
REAL_FRAME = "/mnt/projects/foss_ipex/dustgym/godot_sidecar/out/crater_boulders.png"


def test_filter_keypoints_keeps_only_ground_and_rock():
    # known 4x4 label mask: row0 ground, row1 rock, row2 sky, row3 lander
    g, r, s, l = (masking.CLASSES[c] for c in ("ground", "rock", "sky", "lander"))
    mask = np.array([[g, g, g, g],
                     [r, r, r, r],
                     [s, s, s, s],
                     [l, l, l, l]])
    kps = np.array([[0, 0], [1, 1], [2, 2], [3, 3]])   # (u,v): ground, rock, sky, lander
    kept = masking.filter_keypoints(kps, mask)
    assert kept.tolist() == [[0, 0], [1, 1]]           # sky + lander removed


def test_filter_keypoints_drops_out_of_bounds():
    mask = np.zeros((4, 4), dtype=int)                 # all ground
    kps = np.array([[10, 10], [0, 0]])
    kept = masking.filter_keypoints(kps, mask)
    assert kept.tolist() == [[0, 0]]


def test_class_pixel_fraction():
    mask = np.array([[0, 0], [1, 5]])
    assert abs(masking.class_pixel_fraction(mask, 0) - 0.5) < 1e-9
    assert abs(masking.class_pixel_fraction(mask, 5) - 0.25) < 1e-9


def test_detect_shadow_mask_known_array():
    # bright field with a dark patch -> patch flagged shadow
    img = np.full((10, 10), 200, dtype=np.uint8)
    img[:3, :3] = 10
    m = masking.detect_shadow_mask(img, rel_threshold=0.35)
    assert m[:3, :3].all() and not m[5:, 5:].any()


@pytest.mark.skipif(not os.path.exists(REAL_FRAME), reason="dustgym render not present")
def test_detect_shadow_mask_on_real_low_sun_render():
    from imageio.v3 import imread
    img = np.asarray(imread(REAL_FRAME))
    m = masking.detect_shadow_mask(img)
    frac = m.mean()
    # a real low-sun lunar scene has substantial but not total shadow
    assert 0.05 < frac < 0.98


def test_overlay_returns_rgb():
    img = np.full((8, 8), 100, dtype=np.uint8)
    m = np.zeros((8, 8), dtype=bool); m[0, 0] = True
    out = masking.overlay(img, m)
    assert out.shape == (8, 8, 3) and out.dtype == np.uint8


def test_detect_shadow_mask_mostly_shadowed_scene():
    # audit 2026-06-09: with <1% sunlit pixels the p99 bright reference sat ON a shadow pixel and
    # inverted the mask -- exactly the grazing-sun polar regime this detector exists for
    import numpy as np

    from dart import masking as MK
    img = np.full((100, 100), 10.0, dtype=np.float32)           # 99.5% deep shadow
    img[:5, :10] = 200.0                                        # 0.5% sunlit strip
    m = MK.detect_shadow_mask(img, rel_threshold=0.35)
    assert m.mean() > 0.9                                       # the shadowed majority IS marked shadow
    assert not m[:5, :10].any()                                 # the sunlit strip is NOT
