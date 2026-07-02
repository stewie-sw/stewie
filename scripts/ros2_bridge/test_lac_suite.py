"""[REQ:PM-10] Fixed LAC-style benchmark suite test -- six metrics per condition + failure count.

PM-10 asks for ONE fixed LAC-style suite reporting localization RMSE, the 5 cm height-cell pass
fraction, rock F1, coverage, runtime, and failure count, swept over seeds x light x rocks.  These
tests run `lac_suite.run_lac_suite()` over the FIXED condition matrix and assert every row carries
all six metric slots plus an integer failure count aggregated across the sweep.

REAL DATA ONLY (and honest gating -- see lac_suite.py module docstring):
  * localization RMSE  -- the real ESA Katwijk dead-reckoning ATE on the COMMITTED ~30 s real
                          fixture (stewie/eval/tests/fixtures/katwijk_mini), CI-runnable.
  * height-cell pass   -- real committed scene heightmaps (samples/crater, samples/crater_boulders)
                          vs a real block-mean lower-resolution reconstruction, tol_m = 0.05.
  * coverage           -- dart.map_channel.coverage_mask over the real RTK station track.
  * rock F1            -- GATED (needs the Godot/GPU render + detector); asserted UN-fabricated
                          (value None, status 'gated'), never a number.
  * runtime            -- measured wall time per condition.
  * failure count      -- exceptions caught per leg, summed per row and across the sweep.

CC0-1.0 (see ../../LICENSE).
"""

from __future__ import annotations

import lac_suite


def _run_once():
    """Run the fixed suite once per test module (cached -- the sweep is deterministic)."""
    global _REPORT
    try:
        return _REPORT
    except NameError:
        _REPORT = lac_suite.run_lac_suite()
        return _REPORT


def test_fixed_suite_reports_six_metrics_per_condition_and_aggregate_failure_count():  # [REQ:PM-10]
    report = _run_once()

    # The FIXED condition matrix: 3 seeds x 2 light x 2 rocks = 12 conditions, all present exactly once.
    assert report["suite"] == lac_suite.SUITE_NAME
    rows = report["conditions"]
    assert len(rows) == len(lac_suite.LAC_CONDITIONS) == 12
    seen = {(r["condition"]["seed"], r["condition"]["light"], r["condition"]["rocks"]) for r in rows}
    want = {(c["seed"], c["light"], c["rocks"]) for c in lac_suite.LAC_CONDITIONS}
    assert seen == want

    for row in rows:
        metrics, status = row["metrics"], row["status"]
        # all six metric slots present on EVERY row
        assert set(metrics) == set(lac_suite.METRIC_KEYS)

        # executable legs carry real numbers in sane ranges
        assert status["localization_rmse_m"] == "ok"
        assert metrics["localization_rmse_m"] > 0.0
        assert status["height_cell_pass_frac"] == "ok"
        assert 0.0 <= metrics["height_cell_pass_frac"] <= 1.0
        assert status["coverage_frac"] == "ok"
        assert 0.0 < metrics["coverage_frac"] <= 1.0
        assert metrics["runtime_s"] > 0.0

        # the render/GPU-gated leg is FLAGGED, never fabricated
        assert status["rock_f1"] == "gated"
        assert metrics["rock_f1"] is None

        # per-row failure count is a non-negative int
        assert isinstance(metrics["failure_count"], int) and metrics["failure_count"] >= 0

    # aggregate failure count: an int, equal to the per-row sum, and 0 on the healthy committed data
    assert isinstance(report["failure_count"], int)
    assert report["failure_count"] == sum(r["metrics"]["failure_count"] for r in rows) == 0


def test_seed_axis_genuinely_binds_the_height_leg():  # [REQ:PM-10]
    """The sweep is real: different seeds pick different real-DEM crops -> different height RMSE."""
    report = _run_once()
    rows = [r for r in report["conditions"]
            if r["condition"]["light"] == "lit" and r["condition"]["rocks"]]
    rmses = [r["context"]["height_rmse_m"] for r in rows]
    assert len(rmses) == 3 and len(set(rmses)) > 1


def test_rocks_axis_selects_the_real_scene_and_truth_rock_count():  # [REQ:PM-10]
    """rocks=True scores the real crater_boulders bundle (143 committed clasts); rocks=False scores
    the clast-free crater bundle. The truth rock count is read from the real metadata, not invented."""
    report = _run_once()
    with_rocks = [r for r in report["conditions"] if r["condition"]["rocks"]]
    without = [r for r in report["conditions"] if not r["condition"]["rocks"]]
    assert all(r["scene"] == "crater_boulders" and r["n_truth_rocks"] > 0 for r in with_rocks)
    assert all(r["scene"] == "crater" and r["n_truth_rocks"] == 0 for r in without)


def test_localization_leg_is_the_real_katwijk_number_and_deterministic():  # [REQ:PM-10]
    """The localization leg is the real committed-fixture Katwijk dead-reckoning ATE (deterministic,
    condition-insensitive on the CPU path -- flagged as such, not faked into variation)."""
    report = _run_once()
    vals = {r["metrics"]["localization_rmse_m"] for r in report["conditions"]}
    assert len(vals) == 1
    # the same real ~1.46 m band test_katwijk_mini guards (a real regression bound, not a pass bar)
    assert 1.2 < vals.pop() < 1.7


def test_failure_accounting_counts_a_broken_leg():  # [REQ:PM-10]
    """A condition whose scene bundle cannot be loaded is COUNTED as a failure (leg status 'failed',
    metric None), and the aggregate failure count reflects it -- failures are surfaced, not hidden."""
    report = lac_suite.run_lac_suite(
        conditions=[{"seed": 0, "light": "lit", "rocks": True}],
        scene_by_rocks={True: "no_such_scene_bundle", False: "crater"},
    )
    row = report["conditions"][0]
    assert row["status"]["height_cell_pass_frac"] == "failed"
    assert row["metrics"]["height_cell_pass_frac"] is None
    assert row["metrics"]["failure_count"] >= 1
    assert report["failure_count"] == row["metrics"]["failure_count"]


if __name__ == "__main__":
    # pure-python runner, mirroring the sibling test modules' convention
    test_fixed_suite_reports_six_metrics_per_condition_and_aggregate_failure_count()
    test_seed_axis_genuinely_binds_the_height_leg()
    test_rocks_axis_selects_the_real_scene_and_truth_rock_count()
    test_localization_leg_is_the_real_katwijk_number_and_deterministic()
    test_failure_accounting_counts_a_broken_leg()
    print("test_lac_suite: all assertions passed")
