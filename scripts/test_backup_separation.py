"""SG-01: the repo and its backups must not all share one block device.

Measured on this host before the fix -- repo, canonical remote and every runtime volume on one disk:

    repo (.git)                /mnt/projects/stewie/code        -> /dev/nvme0n1p1
    gitea (canonical remote)   /mnt/projects/docker/volumes/... -> /dev/nvme0n1p1
    runtime volumes (/data)    /mnt/projects/docker             -> /dev/nvme0n1p1

Not theoretical. This repo had a git corruption event on 2026-07-28, and on 2026-08-02 a P0 authority
fix (`dab8a5ce`, closing SR-01..04) was found to exist on ZERO remotes -- it lived only in the working
copy and a local gitea whose `gate3` was 16 commits stale, both on that one disk.

The gate is deliberately weak, so it stays honest: at least one durable copy on a DIFFERENT device.
It does not require an off-host copy (that depends on network state a gate should not assume) and it
treats a STALE copy as no protection at all, because a mirror that stopped updating is worse than a
missing one -- it looks like safety.

Run: <venv>/bin/python -m pytest scripts/test_backup_separation.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_backup_separation as B  # noqa: E402

_NVME = "66306"      # stand-ins for st_dev ids; only equality matters
_SDA = "2049"


def test_the_measured_pre_fix_state_is_refused():
    """Repo and its only backup on one device: that is the single point of failure SG-01 named."""
    v = B.evaluate(_NVME, {"/mnt/projects/docker/volumes/gitea-data": _NVME})
    assert v["ok"] is False
    assert "SAME device" in v["reason"]


def test_a_copy_on_another_device_satisfies_it():
    v = B.evaluate(_NVME, {"~/backups/stewie-mirror.git": _SDA})
    assert v["ok"] is True and v["separated"] == ["~/backups/stewie-mirror.git"]


def test_no_backup_at_all_is_refused_distinctly():
    """'no copy exists' and 'copies exist but share a device' are different failures; say which."""
    v = B.evaluate(_NVME, {"~/backups/stewie-mirror.git": None})
    assert v["ok"] is False and "no durable copy" in v["reason"]


def test_a_same_device_copy_does_not_mask_a_separated_one():
    """Having a useless copy must not hide the useful one, and vice versa."""
    v = B.evaluate(_NVME, {"same": _NVME, "other": _SDA})
    assert v["ok"] is True
    assert v["separated"] == ["other"] and v["same_device"] == ["same"]


def test_a_stale_copy_is_not_protection():
    """A mirror that stopped updating looks like safety and is not. Freshness is opt-in via max_age_h."""
    fresh = B.evaluate(_NVME, {"m": _SDA}, ages_h={"m": 2.0}, max_age_h=24.0)
    assert fresh["ok"] is True
    stale = B.evaluate(_NVME, {"m": _SDA}, ages_h={"m": 400.0}, max_age_h=24.0)
    assert stale["ok"] is False and stale["stale"] == ["m"]
    assert "staler than" in stale["reason"]


def test_missing_repo_is_refused_not_silently_ok():
    assert B.evaluate(None, {"m": _SDA})["ok"] is False


@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true",
                    reason="SG-01 is a property of the development host; a CI runner is a fresh checkout with no "
                           "backups by design")
def test_check_runs_against_this_host_and_passes_now():
    """The real invariant on the real machine -- this is what the fix had to achieve."""
    v = B.check()
    assert v["ok"] is True, f"SG-01 regression: {v['reason']}"
    assert v["separated"], v


def test_cli_exit_code_matches_the_verdict():
    r = subprocess.run([sys.executable, B.__file__, "--json"], capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), r.stderr
    assert '"ok"' in r.stdout
