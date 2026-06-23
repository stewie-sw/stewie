"""PO-13 [REQ:PO-13]: the release-evidence manifest is generated from REAL sources, never hand-numbered.

These tests pin the no-fabrication contract: every committed manifest field IS the corresponding live
tool's output (req_trace / release_gate / version), the committed surface is deterministic (no volatile
commit/coverage/timestamp that would make it perpetually stale), and the committed file is in sync with
the generator (the same --check gate gen_status.py uses). Modeled on scripts/test_gen_status.py.
"""
from __future__ import annotations

import os

import stewie
from scripts.gen_release_manifest import (
    _PATHS,
    _REPO_ROOT,
    collect_deterministic,
    render_json,
)
from scripts.release_gate import release_report
from scripts.req_trace import trace

_PRD = os.path.join(_REPO_ROOT, "PRD.md")
_MANIFEST = os.path.join(_REPO_ROOT, "release_manifest.json")


def _collect() -> dict:
    return collect_deterministic(_REPO_ROOT, _PRD, _PATHS)


def test_req_trace_block_is_the_live_tool_output():  # [REQ:PO-13]
    # no fabrication: the manifest's req_trace numbers ARE scripts/req_trace.trace() output, not a re-count.
    m = _collect()
    tr = trace(_PRD, _PATHS)
    assert m["req_trace"]["total"] == tr["total"]
    assert m["req_trace"]["cited"] == tr["cited"]
    assert m["req_trace"]["v_done_uncited"] == tr["v_done_uncited"]
    assert m["req_trace"]["unknown_markers"] == tr["unknown_markers"]
    # reconciles is the release-honesty condition (no V=D lacks a citing test, no orphan marker)
    assert m["req_trace"]["reconciles"] == (not tr["v_done_uncited"] and not tr["unknown_markers"])


def test_autonomy_gate_block_is_the_live_release_report():  # [REQ:PO-13]
    m = _collect()
    s = release_report()["summary"]
    for k in ("in_matrix", "total", "cited", "currently_v_done", "eligible_for_v_done"):
        assert m["autonomy_gate"][k] == s[k], f"autonomy_gate.{k} drifted from release_report()"


def test_version_is_the_single_source_and_in_sync():  # [REQ:PO-13]
    m = _collect()
    assert m["version"]["stewie___version__"] == stewie.__version__
    # the single-version-source rule: stewie.__version__ == pyproject [project].version
    assert m["version"]["in_sync"] is True, (
        f"version drift: {m['version']!r} -- stewie.__version__ must equal pyproject [project].version")


def test_changelog_and_semver_policy_are_present():  # [REQ:PO-13]
    m = _collect()
    assert m["changelog"]["present"] and m["changelog"]["documents_version"]
    assert m["changelog"]["semver_declared"]
    assert m["semver_policy"]["present"], "docs/RELEASE.md (the SemVer policy) must exist"


def test_committed_surface_is_deterministic_only():  # [REQ:PO-13]
    # the committed manifest must carry NO volatile field (commit/timestamp/coverage/tests) -- otherwise the
    # --check staleness gate would fire on every commit. Volatile fields live only in the --full release copy.
    m = _collect()
    for volatile in ("commit", "generated_at", "coverage", "tests"):
        assert volatile not in m, f"committed manifest leaked the volatile field {volatile!r}"


def test_committed_manifest_is_in_sync_with_the_generator():  # [REQ:PO-13]
    # the same honesty gate as `gen_release_manifest.py --check`: the committed file must equal a fresh render.
    assert os.path.exists(_MANIFEST), "release_manifest.json is not committed"
    committed = open(_MANIFEST, encoding="utf-8").read()
    assert committed == render_json(_collect()), (
        "release_manifest.json is STALE -- run `python3 scripts/gen_release_manifest.py`")
