"""EDS (electrodynamic dust shield) lens-occlusion model (SCHULER24 §V.B). IPEx cameras carry a
transparent EDS lens cover that accumulates regolith dust (degrading transmittance), an AC clear cycle
that removes most but leaves a residual, and an HDRM that JETTISONS the cover as a last resort. This
models that degradation chain and applies it to a REAL rendered frame. The dust-rate / residual /
transmittance coefficients are [CALIB] (the paper documents the chain qualitatively, not numbers); the
STRUCTURE is sourced. Fixtures are literal arrays exercising the optics, not stand-in sensor data.

Run: <venv>/bin/python -m pytest scripts/ros2_bridge/test_eds_dust.py -q
"""
import os

import numpy as np
import pytest

import eds_dust as ED  # noqa: E402  (same-dir import, mirrors the other bridge scripts)

_EGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "stewie", "godot", "out", "cam", "crater_boulders", "000")


def test_transmittance_monotonic_decreasing_in_coverage():
    assert ED.dust_transmittance(0.0) == pytest.approx(1.0)
    assert ED.dust_transmittance(1.0) < ED.dust_transmittance(0.5) < ED.dust_transmittance(0.0)
    assert 0.0 <= ED.dust_transmittance(1.0) <= 1.0


def test_accumulate_then_clear_leaves_a_residual_floor():
    s = ED.EDSDustShield(accum_rate=0.2, clear_residual_frac=0.25)
    s.accumulate(3.0)                                   # 3 exposure units -> heavy dust
    dusty = s.coverage
    assert dusty > 0.4
    s.clear()                                           # EDS clear removes most, leaves 25%
    assert s.coverage == pytest.approx(dusty * 0.25)
    assert s.n_clear_cycles == 1
    # repeated clears converge toward 0 but each leaves the residual fraction (never negative)
    for _ in range(5):
        s.clear()
    assert 0.0 <= s.coverage < 1e-3


def test_jettison_is_one_shot_and_clears_the_cover():
    s = ED.EDSDustShield(accum_rate=0.5)
    s.accumulate(2.0)
    assert s.should_jettison(threshold=0.5) is True     # dust beyond EDS-recoverable
    s.jettison()
    assert s.jettisoned is True and s.coverage == 0.0   # bare clean lens after ejecting the cover
    # after jettison there is no cover to clear; dust still accrues on the bare lens (no EDS protection)
    s.accumulate(1.0)
    assert s.coverage > 0.0
    s.clear()                                           # no-op once jettisoned
    assert s.coverage > 0.0


def test_apply_occlusion_darkens_a_real_render(tmp_path):
    if not os.path.exists(os.path.join(_EGRESS, "front_left.png")):
        pytest.skip("no render egress (render with sidecar.tscn --cameras first)")
    from PIL import Image
    img = np.asarray(Image.open(os.path.join(_EGRESS, "front_left.png")).convert("L"))
    s = ED.EDSDustShield(accum_rate=0.3)
    s.accumulate(2.0)                                   # dusty cover
    out = ED.apply_occlusion(img, s.transmittance(), haze=8.0)
    assert out.shape == img.shape and out.dtype == img.dtype
    assert out.mean() < img.mean()                      # dust attenuates the real frame
    # a clean (coverage 0) shield is a near-identity pass (only the additive haze, which we set to 0)
    clean = ED.apply_occlusion(img, ED.dust_transmittance(0.0), haze=0.0)
    assert np.array_equal(clean, img)
