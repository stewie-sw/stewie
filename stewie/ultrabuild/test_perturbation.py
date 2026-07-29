from __future__ import annotations

from pathlib import Path

from stewie.ultrabuild.perturbation import FACTORS, METHODS, run_perturbation_study


def test_perturbation_study_registers_failure_boundaries(
    tmp_path: Path,
) -> None:
    report = run_perturbation_study(tmp_path)
    expected_cells = sum(
        len(levels) * len(METHODS)
        for levels, _ in FACTORS.values()
    )
    assert len(report["cells"]) == expected_cells
    assert report["registered_stewie_failure_cells"]
    assert report["unmeasured_factors"]
    assert (tmp_path / "perturbation-report.json").is_file()
