"""[REQ:PO-04] the CI workflow must actually gate the tiers it claims: the traceability gate
(req_trace), the coverage-gated python suite, the multi-version python matrix, and the browser-JS
`node --test` tier (which was silently unrun until 2026-07-01 -- these asserts make that regression
impossible to reintroduce quietly). PO-04 stays partial (I=P) until Godot / package-smoke /
hardware-gated tiers are split out too; this test pins the tiers that exist."""
from __future__ import annotations

import os

import yaml

_CI = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".github", "workflows", "ci.yml")


def _jobs() -> dict:
    with open(_CI, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["jobs"]


def _steps_text(job: dict) -> str:
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_ci_gates_the_browser_js_tier_recursively():
    """[REQ:PO-04] the JS tier runs node --test over the FULL recursive asset tree (a flat glob once
    missed panes/; node v22 rejects a bare directory)."""
    job = _jobs()["test-js"]
    text = _steps_text(job)
    assert "node --test" in text
    assert "globstar" in text and "**/*.test.js" in text


def test_ci_gates_traceability_and_coverage_on_the_core_tier():
    """[REQ:PO-04] the python core tier runs req_trace (V=D must be test-cited) and the coverage-
    gated configured suite."""
    text = _steps_text(_jobs()["lint-type-cov"])
    assert "req_trace.py" in text
    assert "--cov" in text


def test_ci_runs_the_python_matrix_tier():
    """[REQ:PO-04] the configured suite runs across the supported python versions in parallel."""
    job = _jobs()["test"]
    versions = job["strategy"]["matrix"]["python-version"]
    assert len(versions) >= 2
    assert "pytest" in _steps_text(job)
