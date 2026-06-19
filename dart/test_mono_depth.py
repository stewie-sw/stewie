"""Monocular-depth producer + score-vs-stereo benchmark (PRD #185 perception track).

(No [REQ:] marker: this is a perception-densification cue + an honest mono-vs-stereo comparison; it
does not itself meet a §7 acceptance row -- SN-13's target is pose/feature-track improvement, which
this does not measure, so citing it would be a false trace.)

Real data only: the stereo-derived checks compute depth from the committed a6_traverse stereo frames
(deterministic, no model) and exercise the align/metric math on that real depth; the model-dependent
checks run DepthAnything-V2 on the same real frames and skip cleanly where transformers/the cached
weights are absent (e.g. CI). No fabricated arrays.
"""
import os

import numpy as np
import pytest

from dart import mono_depth as MD

_A6 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "stewie", "eval", "validation", "a6_traverse", "cam")
_FRAME0 = os.path.join(_A6, "frame_000")


def _real_stereo_depth():
    """Stereo metric depth from a committed real a6 frame (no model). fx scales with frame width."""
    import imageio.v2 as imageio

    from dart import stereo_depth as SD
    from stewie.specs.profiles import load_profile
    left = np.asarray(imageio.imread(os.path.join(_FRAME0, "front_left.png")))
    right = np.asarray(imageio.imread(os.path.join(_FRAME0, "front_right.png")))
    opt = load_profile("stewie").cameras["optics"]
    fx = opt["fx_px"] * (left.shape[1] / opt["width_px"])
    calib = SD.StereoCalibration(calibration_id="t", reference_camera="front_left",
                                 match_camera="front_right", fx_px=fx, baseline_m=0.05,
                                 disparity_sigma_px=1.0, covariance_calibrated=False,
                                 development_evidence=("a6_traverse",))
    return SD.compute_depth_frame(left, right, calib)


def test_metrics_identity_on_real_stereo_depth():
    sd = _real_stereo_depth()
    m = MD.depth_metrics(sd.depth_m, sd.depth_m, sd.valid_mask)   # a field vs itself
    assert m["abs_rel"] < 1e-9 and m["rmse_m"] < 1e-6 and m["delta1"] == 1.0
    assert m["n_pixels"] >= 50


def test_align_recovers_a_known_scale_shift_on_real_depth():
    sd = _real_stereo_depth()
    # ref is a KNOWN metric transform of the real stereo depth; a positively-correlated "pred" must
    # least-squares back to it (tests the scale+shift fit on real-derived data, not fabricated values).
    ref = 2.0 * sd.depth_m + 0.5
    aligned = MD.align_to_metric(sd.depth_m, ref, sd.valid_mask)
    m = sd.valid_mask & np.isfinite(sd.depth_m)
    assert np.allclose(aligned[m], ref[m], rtol=1e-3, atol=1e-2)


def test_depth_metrics_rejects_too_few_pixels():
    z = np.zeros((4, 4)); mask = np.zeros((4, 4), bool)
    with pytest.raises(ValueError):
        MD.depth_metrics(z + 1, z + 1, mask)


# ---- model-dependent (DepthAnything-V2): run where transformers + cached weights exist, else skip ----
def _have_model():
    try:
        import transformers  # noqa: F401
        MD._pipe()           # builds (and caches) the pipeline; raises if weights can't be fetched
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_model(), reason="DepthAnything-V2 / transformers not available")
def test_mono_producer_runs_on_a_real_frame():
    import imageio.v2 as imageio
    img = np.asarray(imageio.imread(os.path.join(_FRAME0, "front_left.png")))
    pred = MD.predict_relative_depth(img)
    assert pred.shape == img.shape[:2]
    assert np.isfinite(pred).all() and float(pred.std()) > 0      # a real, non-constant field


@pytest.mark.skipif(not _have_model(), reason="DepthAnything-V2 / transformers not available")
def test_benchmark_traverse_scores_real_frames():
    from stewie.specs.profiles import load_profile
    opt = load_profile("stewie").cameras["optics"]
    import imageio.v2 as imageio
    fw = imageio.imread(os.path.join(_FRAME0, "front_left.png")).shape[1]
    rep = MD.benchmark_traverse(_A6, fx_px=opt["fx_px"] * (fw / opt["width_px"]), baseline_m=0.05)
    assert rep["frames"] and "not ground truth" in rep["reference"]   # honest: stereo reference, NOT GT
    agg = rep["aggregate"]
    assert np.isfinite(agg["abs_rel"]) and agg["rmse_m"] > 0 and 0.0 <= agg["delta1"] <= 1.0
