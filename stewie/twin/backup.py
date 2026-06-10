"""W-2/W-3 (PRD 6.2): twin snapshot retention + off-host replication.

W-2 -- snapshots are full restorable state (base + events + version) written per call and pruned
by a VERSION-based retention ladder (deterministic, no wall-clock: keep the most recent N, plus
every ladder-th version older than that). W-3 -- replicate() mirrors the twin journal + snapshots
to a destination directory (a second volume, a mounted remote, or an rsync-reachable path) so the
replica ALONE cold-restores the world; RPO = the replication cadence (the journal itself is
fsync-per-edit locally, W-1). CLI: python -m stewie.twin.backup <data_dir> <dest>.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import numpy as np

from stewie.twin.versioned import TwinStore


def snapshot(tw: TwinStore, snaps_dir: str) -> str:
    """Write a full restorable snapshot (base + event log + version) named by version."""
    os.makedirs(snaps_dir, exist_ok=True)
    path = os.path.join(snaps_dir, f"twin_v{tw.version:06d}.npz")
    np.savez_compressed(path, base=np.asarray(tw.base),
                        cell_m=np.array([tw.cell_m]),
                        events=np.frombuffer(json.dumps(tw.events).encode(), dtype=np.uint8))
    return path


def restore(path: str) -> TwinStore:
    z = np.load(path)
    tw = TwinStore(z["base"], cell_m=float(z["cell_m"][0]))
    for ev in json.loads(bytes(z["events"].tobytes()).decode()):
        tw.apply_event(ev)                                # hash-verified replay
    return tw


def apply_retention(snaps_dir: str, *, keep_recent: int = 5, ladder: int = 10) -> list:
    """Prune snapshots: keep the most recent ``keep_recent`` versions plus every ``ladder``-th
    older version. Returns the kept filenames."""
    names = sorted(n for n in os.listdir(snaps_dir) if n.startswith("twin_v"))
    if not names:
        return []
    def ver(n: str) -> int:
        return int(n.split("_v")[1].split(".")[0])
    names.sort(key=ver)
    recent = set(names[-keep_recent:]) if keep_recent else set()
    kept = []
    for n in names:
        if n in recent or ver(n) % ladder == 0:
            kept.append(n)
        else:
            os.unlink(os.path.join(snaps_dir, n))
    return kept


def replicate(data_dir: str, dest: str) -> dict:
    """W-3: mirror the journal + snapshots to ``dest`` (rsync -a --delete on the twin artifacts).
    The replica alone must cold-restore the world -- tested. RPO = how often this runs."""
    os.makedirs(dest, exist_ok=True)
    items = [p for p in ("twin.journal", "snaps", "twin") if os.path.exists(os.path.join(data_dir, p))]
    if not items:
        return {"ok": False, "error": f"nothing to replicate in {data_dir}"}
    cmd = ["rsync", "-a", "--delete"] + [os.path.join(data_dir, p) for p in items] + [dest + "/"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return {"ok": r.returncode == 0, "items": items,
            "error": r.stderr[-300:] if r.returncode else ""}


def main(argv=None):
    a = argv or sys.argv[1:]
    if len(a) != 2:
        print("usage: python -m stewie.twin.backup <data_dir> <dest>")
        return 2
    out = replicate(a[0], a[1])
    print(json.dumps(out))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
