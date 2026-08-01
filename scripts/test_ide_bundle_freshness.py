"""SR-10: the /ide bundle-freshness gate must catch the exact failure that shipped.

On 2026-07-28 the review found the deployed bundle was 15 days behind its source: the newest file in
`gis/qwc2/prod` was built 2026-07-13T23:09:24, while commit `4fb8e3a8` (TR-03) touched `gis/qwc2/js` at
23:40:17. `grep -c start_xy` over the shipped bundle returned zero -- the operator click-to-place
worksite control did not exist in the deployed IDE, while the project banner recorded it as LIVE.

The trap this pins: the OBVIOUS check (newest prod/ mtime vs newest gis/qwc2/js mtime) would have
PASSED that failure, because working-tree mtimes record when git wrote the file, not when the change
was authored -- on the live host the sources read 09:41, older than the 23:09 bundle. The gate has to
compare against the newest COMMIT touching the source. `test_the_real_shipped_regression_is_caught`
replays the real epochs so that reasoning can never be quietly undone.

Run: <venv>/bin/python -m pytest scripts/test_ide_bundle_freshness.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_ide_bundle_freshness as F  # noqa: E402

# The real epochs from the shipped regression (2026-07-13, America/Chicago).
_BUNDLE_2309 = 1784002164.0      # newest file in gis/qwc2/prod
_COMMIT_2340 = 1784004017        # commit 4fb8e3a8, touching gis/qwc2/js
_SOURCE_MTIME_0941 = 1783953687.0  # newest gis/qwc2/js working-tree mtime -- OLDER than the bundle


def test_the_real_shipped_regression_is_caught():
    """The bundle predates the commit by ~31 min: that must fail the deploy."""
    v = F.evaluate(_BUNDLE_2309, _COMMIT_2340, "4fb8e3a8")
    assert v["ok"] is False and v["stale"] is True
    assert 1800 < v["lag_s"] < 1900, v
    assert "4fb8e3a8" in v["reason"]


def test_an_mtime_only_check_would_have_passed_it():
    """Why the gate compares COMMIT time, not file mtime.

    Feeding the real source MTIME in place of the commit time makes the same evaluator say OK -- which
    is precisely the wrong answer, and precisely what a naive implementation would have computed. If
    someone 'simplifies' this gate back to mtime-vs-mtime, this test explains what breaks.
    """
    naive = F.evaluate(_BUNDLE_2309, int(_SOURCE_MTIME_0941), "mtime-not-commit")
    assert naive["ok"] is True, "the mtime comparison no longer reproduces the false pass it used to give"


def test_a_bundle_built_after_the_commit_passes():
    v = F.evaluate(_COMMIT_2340 + 60, _COMMIT_2340, "4fb8e3a8")
    assert v["ok"] is True and v["stale"] is False


def test_a_missing_bundle_is_refused_not_ignored():
    """No build at all must fail the DEPLOY loudly rather than serve whatever is mounted."""
    v = F.evaluate(None, _COMMIT_2340, "4fb8e3a8")
    assert v["ok"] is False and v["stale"] is True
    assert "build it" in v["reason"]


def test_no_source_commit_is_not_a_failure():
    """A tree whose bundle source was never committed cannot be 'behind' anything."""
    assert F.evaluate(None, None, "")["ok"] is True


def test_grace_tolerates_a_build_started_just_before_the_commit():
    """A build kicked off seconds before the final commit lands is a real ordering, not a stale deploy."""
    assert F.evaluate(_COMMIT_2340 - 30, _COMMIT_2340, "abc", grace_s=0.0)["ok"] is False
    assert F.evaluate(_COMMIT_2340 - 30, _COMMIT_2340, "abc", grace_s=120.0)["ok"] is True


def test_check_runs_against_this_repo_without_crashing():
    """The IO wrappers must work on a real checkout (CI has no bundle -> a refusal, which is correct)."""
    v = F.check()
    assert set(v) >= {"ok", "reason", "stale"}
    assert isinstance(v["ok"], bool)


def test_cli_exit_code_matches_the_verdict(tmp_path):
    """The deploy runbook relies on the exit code, so pin it."""
    r = subprocess.run([sys.executable, F.__file__, "--json"], capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), r.stderr
    assert '"ok"' in r.stdout


def test_newest_source_commit_reads_real_git_history():
    """Guard against the gate going vacuous if the git plumbing stops resolving."""
    epoch, sha = F.newest_source_commit()
    if epoch is None:
        pytest.skip("no commit touches gis/qwc2/js in this checkout")
    assert epoch > 0 and sha
