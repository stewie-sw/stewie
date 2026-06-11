"""Measured-edge sigma_n calibration, on real Chang'e-3 lunar surface imagery."""
import glob

import pytest

from dart.shadow_edge_sigma import calibrate_measured_edge_sigma, measure_edge_sigma_px

CE3 = sorted(glob.glob("/mnt/projects/datasets/lunar_ce3/yolo/images/**/*.png", recursive=True))


@pytest.mark.skipif(len(CE3) < 5, reason="CE-3 imagery not present")
def test_measured_edge_sigma_is_real_and_subpixel_penumbra():
    """The MEASURED edge sigma from real lunar shadow edges is a plausible penumbra/PSF width
    (sub-pixel-to-low, not the modelled 1.0 assumption); replaces the envelope's [CALIB] magnitude."""
    from PIL import Image
    r = measure_edge_sigma_px(Image.open(CE3[0]).convert("L"))
    assert r is not None and 0.2 < r["sigma_edge_px"] < 3.0   # a real transition width

    cal = calibrate_measured_edge_sigma(CE3[:12])             # subsample of REAL images
    assert cal["n_images"] >= 3
    assert 0.3 < cal["sigma_edge_px"] < 2.0                   # measured penumbra width [px]
    assert "MEASURED" in cal["provenance"]
