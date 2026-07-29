from __future__ import annotations

from pathlib import Path

from stewie.ultrabuild.benchmark import run_benchmarks


def test_benchmark_reports_measured_and_unmeasured_budgets(
    tmp_path: Path,
) -> None:
    report = run_benchmarks(tmp_path, measured_runs=20)
    assert report["status"] == "measured_partial_budget"
    assert report["protocol"]["measured_runs"] == 20
    assert report["integrity"]["append_store"]["ok"] is True
    assert report["integrity"]["query_store"]["ok"] is True
    assert (
        report["budget_results"]["deterministic_replay_mismatch_count"][
            "observed"
        ]
        == 0
    )
    assert report["unmeasured_budget_items"]
    assert (tmp_path / "performance-report.json").is_file()
