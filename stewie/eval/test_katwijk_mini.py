"""CI-enforceable G1 navigation gate on a tiny COMMITTED real-Katwijk fixture (#214).

`stewie/eval/test_katwijk_baseline.py` runs the full ESA Katwijk Traverse-1 but SKIPS without the ~76 GB
ESA mount, so the wheel+IMU dead-reckoning pipeline is unguarded in CI. This runs the SAME `kb.run` on a
committed ~30 s REAL subsample (a verbatim time-window slice of the real gps/odometry/imu -- no synthetic
data, no downsampling; provenance in the fixture dir) so a regression in the dead-reckoning math is caught
in CI too, not only on the host that mounts the full dataset.

Scope: this guards the PIPELINE on a real short segment. The full-track 3.35 m headline ATE stays the
(skippable) nightly full-data run in test_katwijk_baseline.py -- this fixture's track is ~11 m, so its ATE
is its own reproduced figure, not the headline.
"""
import json
import os

from stewie.eval import katwijk_baseline as kb

FIXTURE = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "katwijk_mini")


def test_mini_fixture_is_committed():
    # the fixture is checked in (no skipif) so this gate RUNS in CI
    for f in ("gps-latlong.txt", "odometry.txt", "imu.txt"):
        assert os.path.isfile(os.path.join(FIXTURE, f)), f"missing real fixture file {f}"


def test_dead_reckon_on_mini_fixture_is_reproducible_and_sane():
    r = kb.run(FIXTURE)
    # wheel radius is data-calibrated on the first third; must land in the HDPR physical band (tens of cm)
    assert 0.05 < r["wheel_radius_m"] < 0.40
    assert r["eval_track_length_m"] > 5.0
    # reproduced deterministic ATE on this real ~30 s slice (~1.46 m / 11.4 m). The band catches a real
    # dead-reckoning regression while tolerating benign numerical drift. NOT the full-track headline.
    assert 1.2 < r["ate_aligned_m"] < 1.7
    # determinism: bit-for-bit reproducible (the gate's honesty invariant)
    assert json.dumps(r, sort_keys=True) == json.dumps(kb.run(FIXTURE), sort_keys=True)
