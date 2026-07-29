from __future__ import annotations

from pathlib import Path

from stewie.ultrabuild.faults import run_fault_injection


def test_fault_injection_probes_fail_closed(tmp_path: Path) -> None:
    report = run_fault_injection(tmp_path)
    assert report["failed"] == 0
    assert report["passed"] == len(report["faults"])
    assert report["unimplemented_fault_families"]
    assert (tmp_path / "fault-injection-report.json").is_file()
