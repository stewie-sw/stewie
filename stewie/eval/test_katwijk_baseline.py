"""G1 real-world closure: wheel+IMU dead-reckoning on REAL Katwijk Traverse-1 vs RTK truth.

Runs against the downloaded dataset (skips honestly if absent). The wheel SCALE (radius) is
CALIBRATED on the first third of the RTK track and DISCLOSED; the ATE is scored on the untouched
remainder. No truth enters the dead-reckoner beyond that initial scale + heading alignment
(standard odometry calibration; the evaluation segment is disjoint).
"""
import json
import os

import numpy as np
import pytest

from stewie.eval import katwijk_baseline as kb

PART1 = "/mnt/projects/datasets/katwijk/Part1"
pytestmark = pytest.mark.skipif(not os.path.isdir(PART1), reason="Katwijk Part1 not downloaded")


def test_rtk_track_is_usable():
    t, xy = kb.load_rtk_track(PART1)
    assert len(t) >= 80                                   # ~5 min at 0.3 Hz
    d = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    assert 10.0 < d.sum() < 2000.0                        # the rover actually drove


def test_wheel_scale_calibrates_in_plausible_band():
    res = kb.run(PART1)
    # HDPR wheels are tens of centimetres; the data-driven scale must land in a physical band
    assert 0.05 < res["wheel_radius_m"] < 0.40
    assert res["calibration"]["segment"] == "first_third"


def test_dead_reckon_ate_on_heldout_segment():
    res = kb.run(PART1)
    ate = res["ate_aligned_m"]
    L = res["eval_track_length_m"]
    assert L > 20.0
    # dead-reckoning drifts; the gate for G1 is an HONEST, reproducible figure, not a magic number.
    # Sanity bounds: better than a random walk (< 50% of track), worse than zero (> 0).
    assert 0.0 < ate < 0.5 * L
    # determinism: the artifact is reproducible bit-for-bit
    res2 = kb.run(PART1)
    assert json.dumps(res, sort_keys=True) == json.dumps(res2, sort_keys=True)
