"""Measured-edge sigma_n calibration, on real Chang'e-3 descent-camera imagery."""
import glob
import os

import pytest

from dart.shadow_edge_sigma import calibrate_measured_edge_sigma, measure_edge_sigma_px, per_edge_sigma

_CE3_DIR = os.environ.get("STEWIE_CE3_DIR", "/mnt/projects/datasets/lunar_ce3/yolo/images")
CE3 = sorted(glob.glob(os.path.join(_CE3_DIR, "**", "*.png"), recursive=True))


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
    assert cal["n_edges_rejected"] >= 0                       # rejection accounting present


@pytest.mark.skipif(len(CE3) < 5, reason="CE-3 imagery not present")
def test_per_edge_widths_are_returned_for_per_measurement_sigma():
    """The bimodality fix: every fitted edge width is returned individually so a consumer can
    carry the per-edge width as that measurement's sigma instead of the global median."""
    from PIL import Image
    r = measure_edge_sigma_px(Image.open(CE3[0]).convert("L"))
    assert r is not None and len(r["widths"]) == r["n"]
    assert all(0.2 < w < 6.0 for w in r["widths"])            # the fitter's own plausibility range


def test_per_edge_sigma_gate_refuses_soft_edges():
    """A sharp edge passes through as its own sigma; a soft-tail edge is refused at the gate."""
    assert per_edge_sigma(0.35) == 0.35                       # sharp CE-3 population
    assert per_edge_sigma(2.8) is None                        # soft tail -> refuse
    assert per_edge_sigma(2.8, gate_px=3.0) == 2.8            # explicit wider gate carries it
    assert per_edge_sigma(0.0) is None                        # degenerate width is not a sigma


def test_edge_sigma_generalizes_across_datasets():
    """The shadow-edge-localization sigma generalizes across real planetary datasets (sub-pixel-to-~2px
    on every one), under the SAME airless-tuned gate -- not per-dataset tuning."""
    import glob
    from dart.shadow_edge_sigma import cross_dataset_edge_sigma
    nd = {
        "CE-3": sorted(glob.glob("/mnt/projects/datasets/lunar_ce3/yolo/images/**/*.png", recursive=True)),
        "LRO_NAC": [p for p in sorted(glob.glob("/mnt/projects/datasets/bouldering/**/*image*.png", recursive=True)) if "mask" not in p],
    }
    if min(len(v) for v in nd.values()) < 10:
        pytest.skip("datasets not present")
    r = cross_dataset_edge_sigma(nd, n_per=20)
    for label, m in r.items():
        assert m["median_px"] is not None and 0.2 < m["median_px"] < 2.5   # generalizes
        assert m["yield"] > 0.5
