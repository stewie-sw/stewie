"""[REQ:PO-04] the CI workflow must actually gate the tiers it claims: the traceability gate
(req_trace), the coverage-gated python suite, the multi-version python matrix, and the browser-JS
`node --test` tier (which was silently unrun until 2026-07-01 -- these asserts make that regression
impossible to reintroduce quietly). PO-04 stays partial (I=P) until Godot / package-smoke /
hardware-gated tiers are split out too; this test pins the tiers that exist.

[REQ:FS-09] the test PYRAMID itself is also pinned here: each layer (unit/contract, backend route,
frontend adapter JS, UI-to-backend integration) must stay present and non-trivial, with floor counts
deliberately well under today's real numbers (221/75/31/9) so growth never turns them brittle."""
from __future__ import annotations

import glob
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


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _py_test_files() -> dict[str, str]:
    """path -> source for every python test file in the shipped package tree."""
    paths = glob.glob(os.path.join(_ROOT, "stewie", "**", "test_*.py"), recursive=True)
    return {p: _read(p) for p in paths}


def test_pyramid_has_real_unit_and_route_layers():
    """[REQ:FS-09] each slice lands with unit tests for math/contracts AND backend route tests: the
    python tier must keep a deep unit/contract layer (no TestClient; today 146 files) and a wide
    route layer (TestClient; today 75 files), every file defining real test functions."""
    files = _py_test_files()
    unit = [p for p, src in files.items() if "TestClient" not in src]
    route = [p for p, src in files.items() if "TestClient" in src]
    assert len(unit) >= 100, f"unit/contract layer thinned to {len(unit)} files"
    assert len(route) >= 30, f"backend route layer thinned to {len(route)} files"
    empty = [p for p, src in files.items() if "def test_" not in src]
    assert not empty, f"test files without a single test function: {empty}"


def test_pyramid_has_a_real_frontend_adapter_js_layer():
    """[REQ:FS-09] frontend adapter tests exist as pure node:test modules under the served asset
    tree (today 31 files), each actually registering tests -- not empty shells."""
    js = glob.glob(os.path.join(_ROOT, "stewie", "server", "web", "assets", "**", "*.test.js"),
                   recursive=True)
    assert len(js) >= 15, f"frontend adapter JS layer thinned to {len(js)} files"
    shells = [p for p in js if "node:test" not in _read(p) or "test(" not in _read(p)]
    assert not shells, f"*.test.js without node:test registrations: {shells}"


def test_pyramid_has_real_ui_to_backend_integration_tests():
    """[REQ:FS-09] at least one integration test runs from UI action to backend effect: the
    end-to-end-marked python tests must drive the app through TestClient (today 9 files)."""
    files = _py_test_files()
    e2e = [p for p, src in files.items() if "end-to-end" in src and "TestClient" in src]
    assert len(e2e) >= 5, f"UI-to-backend integration layer thinned to {len(e2e)} files"


def test_pyramid_browser_js_layer_is_ci_gated():
    """[REQ:FS-09] the browser-JS tier is not just present on disk -- CI runs it (the dedicated
    node --test job over the recursive asset glob; the deeper shape asserts live under PO-04)."""
    text = _steps_text(_jobs()["test-js"])
    assert "node --test" in text and "*.test.js" in text


def test_pyramid_has_a_ci_gated_browser_smoke_tier():
    """[REQ:FS-09] the cockpit SHELL (the ~5.9k-line wiring layer where the unrun-JS-tier / stale-
    stamp / pane-wiring regressions all lived) is browser-smoke-gated in CI: a dedicated Playwright
    job boots the real server, clicks the six spine tabs, and renders the /program board -- with the
    npm playwright version pinned EXACTLY (no floating browser drift)."""
    import re
    job = _jobs()["ui-smoke"]
    text = _steps_text(job)
    assert "ui_smoke.mjs" in text, "CI must run the Playwright cockpit smoke (scripts/ui_smoke.mjs)"
    assert re.search(r"playwright@\d+\.\d+\.\d+", text), "the npm playwright package must be pinned exactly"
    assert "playwright install" in text and "chromium" in text
    assert "requirements-dev.lock" in text, "the smoke boots the REAL server from the hashed lock"
