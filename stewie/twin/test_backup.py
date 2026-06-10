"""PRD 6.2 W-2/W-3: snapshot retention ladder + off-host replication (real files, real rsync)."""
import json
import os
import subprocess

import numpy as np
import pytest

from stewie.twin import backup as B
from stewie.twin import versioned as vt


def _base():
    return np.random.default_rng(3).normal(0.0, 0.05, (32, 32))


def _store(tmp_path):
    return vt.TwinStore(_base(), cell_m=0.5, journal_path=str(tmp_path / "twin.journal"))


def test_snapshot_writes_restorable_state(tmp_path):
    tw = _store(tmp_path)
    tw.apply_patch(np.full((3, 3), 0.2), origin_rc=(2, 2), provenance="edit")
    p = B.snapshot(tw, str(tmp_path / "snaps"))
    assert os.path.exists(p)
    cold = B.restore(p)
    assert cold.current().tobytes() == tw.current().tobytes()
    assert cold.version == tw.version and cold.verify_chain()


def test_retention_ladder_is_version_based(tmp_path):
    tw = _store(tmp_path)
    snaps = str(tmp_path / "snaps")
    for i in range(25):
        tw.apply_patch(np.full((2, 2), float(i)), origin_rc=(0, 0), provenance=f"e{i}")
        B.snapshot(tw, snaps)
    kept = B.apply_retention(snaps, keep_recent=5, ladder=10)
    names = sorted(os.listdir(snaps))
    assert names == sorted(kept)
    versions = sorted(int(n.split("_v")[1].split(".")[0]) for n in names)
    assert versions[-5:] == [21, 22, 23, 24, 25]          # the recent window, intact
    assert all(v % 10 == 0 for v in versions[:-5])        # older survivors: every ladder-th only


def test_replication_mirrors_journal_and_snapshots(tmp_path):
    if subprocess.run(["which", "rsync"], capture_output=True).returncode != 0:
        pytest.skip("rsync not available")
    tw = _store(tmp_path)
    tw.apply_patch(np.full((2, 2), 1.0), origin_rc=(1, 1), provenance="e")
    snaps = str(tmp_path / "snaps")
    B.snapshot(tw, snaps)
    dest = str(tmp_path / "offhost")                      # stands in for the second volume/host
    out = B.replicate(str(tmp_path), dest)
    assert out["ok"] and os.path.exists(os.path.join(dest, "twin.journal"))
    assert os.listdir(os.path.join(dest, "snaps"))
    # the replica alone is enough to cold-restore the world (the W-3 point)
    cold = vt.TwinStore.from_journal(_base(), cell_m=0.5,
                                     journal_path=os.path.join(dest, "twin.journal"))
    assert cold.version == tw.version
