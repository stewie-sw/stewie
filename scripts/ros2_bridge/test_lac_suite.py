"""[REQ:PM-10] Fixed LAC-style benchmark suite test -- measured metrics per condition + failure count.

These tests run `lac_suite.run_lac_suite()` over the FIXED seeds x light x rocks matrix and assert
every row carries the metric slots the suite measures plus an integer failure count aggregated
across the sweep. Localization RMSE, coverage and rock F1 are not measured on this host (see the
lac_suite.py module docstring), so PM-10 stays partial.

REAL DATA ONLY:
  * height-cell pass   -- real committed scene heightmaps (samples/crater, samples/crater_boulders)
                          vs a real block-mean lower-resolution reconstruction, tol_m = 0.05.
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


def test_fixed_suite_reports_metrics_per_condition_and_aggregate_failure_count():  # [REQ:PM-10]
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
        # every metric slot present on EVERY row
        assert set(metrics) == set(lac_suite.METRIC_KEYS)

        # executable legs carry real numbers in sane ranges
        assert status["height_cell_pass_frac"] == "ok"
        assert 0.0 <= metrics["height_cell_pass_frac"] <= 1.0
        assert metrics["runtime_s"] > 0.0

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
    test_fixed_suite_reports_metrics_per_condition_and_aggregate_failure_count()
    test_seed_axis_genuinely_binds_the_height_leg()
    test_rocks_axis_selects_the_real_scene_and_truth_rock_count()
    test_failure_accounting_counts_a_broken_leg()
    print("test_lac_suite: all assertions passed")
