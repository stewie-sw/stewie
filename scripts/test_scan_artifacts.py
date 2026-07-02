"""OPS-03 (PRD §27.2.A / PO-05) — acceptance test for the resolved-artifact CVE scan.

`scripts/scan_artifacts.py` is the missing "scan resolved artifacts" step of the PO-05 dependency
row: the lock (`requirements-*.lock`) and the CycloneDX SBOM (`scripts/gen_sbom.py`) already exist and
are tested; this closes the loop by running a REAL vulnerability scan (`pip-audit` over the resolved
lock) and FAILING the CI gate on a finding at/above the configured severity threshold.

Two honesty rules the row demands:
  * a live CVE scan needs a network vulnerability DB, so the scan itself is a soft-gated leg. The
    PARSE + GATE logic is proven here against REAL captured `pip-audit --format json` output (a clean
    run and a run over the genuinely-vulnerable jinja2 2.11.2 with real CVE IDs), never a fabricated
    finding. `run_scan()` is exercised live only where the scanner + network are present, and it must
    have RUN + returned a real report (it never invents a result).
  * the gate is real: a report with a finding at/above threshold refuses (non-zero), a clean report
    passes, and the components scanned are the packages actually resolved in the lock.

[REQ:PO-05]
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess

import pytest


def _scanner_runs() -> bool:
    """pip-audit is usable here only if it is on PATH AND can execute (its shebang interpreter can
    import pip_audit). `which` alone is not enough -- under PYTHONNOUSERSITE the user-site install is
    hidden, so the console script fails to import. The live test gates on a real `--version` run."""
    exe = shutil.which("pip-audit")
    if exe is None:
        return False
    try:
        return subprocess.run([exe, "--version"], capture_output=True,
                              timeout=30.0, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCAN = os.path.join(_ROOT, "scripts", "scan_artifacts.py")
_FIX = os.path.join(_ROOT, "scripts", "fixtures", "pip_audit")
_CLEAN = os.path.join(_FIX, "clean_report.json")
_VULN = os.path.join(_FIX, "vulnerable_report.json")
_DEV_LOCK = os.path.join(_ROOT, "requirements-dev.lock")


def _load_module():
    import sys
    spec = importlib.util.spec_from_file_location("scan_artifacts", _SCAN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_parses_a_real_clean_pip_audit_report():
    # the REAL clean capture parses to per-package records, every one with an empty vuln list
    mod = _load_module()
    report = mod.parse_pip_audit(json.loads(open(_CLEAN).read()))
    assert report.n_packages >= 1
    assert report.findings == []          # a clean scan surfaces no findings
    assert report.n_findings == 0
    # the parsed component names are real lock packages (no fabricated components)
    names = {c.name for c in report.components}
    assert "anyio" in names and "certifi" in names


def test_parses_a_real_vulnerable_pip_audit_report_with_real_cve_ids():
    # the REAL jinja2 2.11.2 capture parses to genuine findings carrying genuine advisory IDs
    mod = _load_module()
    report = mod.parse_pip_audit(json.loads(open(_VULN).read()))
    assert report.n_findings >= 1
    ids = {f.id for f in report.findings}
    # PYSEC-2021-66 / CVE-2024-22195 are real advisories pip-audit reported for jinja2 2.11.2
    assert any(i.startswith(("PYSEC-", "CVE-", "GHSA-")) for i in ids), ids
    # each finding names the affected package + version it was resolved at (traceable to the lock)
    for f in report.findings:
        assert f.package and f.version and f.id
        assert f.fix_versions is not None   # list (possibly empty) -- never None


def test_gate_passes_on_a_clean_report_and_refuses_on_a_vulnerable_one():
    # the GATE is the point of the step: clean -> ok (exit 0), any finding at/above threshold -> refuse
    mod = _load_module()
    clean = mod.parse_pip_audit(json.loads(open(_CLEAN).read()))
    vuln = mod.parse_pip_audit(json.loads(open(_VULN).read()))
    assert mod.gate(clean) == 0, "a clean scan must pass the gate"
    assert mod.gate(vuln) != 0, "a scan with real findings must refuse (fail the CI gate)"


def test_ignore_list_can_waive_a_tracked_advisory_but_not_hide_the_rest():
    # a documented, tracked waiver (an accepted-risk advisory ID) can be excluded from the gate; an
    # unrelated finding is NOT hidden by it.
    mod = _load_module()
    vuln = mod.parse_pip_audit(json.loads(open(_VULN).read()))
    all_ids = {f.id for f in vuln.findings}
    # waive every id -> the gate then passes (nothing left above threshold)
    waived = mod.gate(vuln, ignore_ids=all_ids)
    assert waived == 0
    # waive all-but-one -> the gate still refuses on the remaining finding
    keep = sorted(all_ids)[0]
    partial = mod.gate(vuln, ignore_ids=all_ids - {keep})
    assert partial != 0


def test_report_carries_the_source_it_scanned():
    mod = _load_module()
    report = mod.parse_pip_audit(json.loads(open(_VULN).read()), source="requirements-dev.lock")
    assert report.source == "requirements-dev.lock"


@pytest.mark.skipif(not _scanner_runs(),
                    reason="pip-audit not runnable in this env (soft-gated: the live scan needs a "
                           "working scanner + a network vuln DB; under PYTHONNOUSERSITE the console "
                           "script cannot import pip_audit); the parse/gate logic is proven above on "
                           "real captured output")
def test_live_scan_runs_the_real_scanner_over_the_lock_and_returns_a_real_report():
    # where the scanner IS present, run_scan actually invokes it over the resolved lock and returns a
    # parsed report (it RAN + parsed real output -- it never fabricates a result). Whether findings
    # exist depends on the live vuln DB, so we assert the run happened + is well-formed, not a count.
    mod = _load_module()
    report = mod.run_scan(_DEV_LOCK)
    assert report is not None
    assert report.ran is True
    assert report.source.endswith("requirements-dev.lock")
    assert report.n_packages >= 1        # the resolved lock has packages
    for f in report.findings:            # any finding is real (has an advisory id + package)
        assert f.id and f.package
