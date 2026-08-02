"""SG-01: the repo, its canonical remote, and its backups must not all live on one device.

The 2026-07-28 review found repo + "canonical" remote + every runtime volume on a single disk.
Measured on this host before the fix:

    repo (.git)                /mnt/projects/stewie/code        -> /dev/nvme0n1p1
    gitea (canonical remote)   /mnt/projects/docker/volumes/... -> /dev/nvme0n1p1
    runtime volumes (/data)    /mnt/projects/docker             -> /dev/nvme0n1p1

That is not a theoretical risk here. This repo had a git corruption event on 2026-07-28
(`_git_recovery_2026-07-28/`), and on 2026-08-02 a P0 authority fix (`dab8a5ce`, closing SR-01..04)
was found to exist on ZERO remotes -- it lived only in the working copy and a local gitea whose
`gate3` was 16 commits stale. Both of those sat on the same physical device. One disk failure would
have taken the work and its only backup together.

The invariant this gate enforces is deliberately weak and therefore honest: at least one durable copy
of the repo must be on a DIFFERENT block device than the working repo. It does not try to judge
whether a backup is fresh (see `--max-age-h`) or whether an off-HOST copy exists (reported, not
required, since that depends on network state a gate should not assume).

    python scripts/check_backup_separation.py           # exit 1 if every copy shares one device
    python scripts/check_backup_separation.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Candidate durable copies, in preference order. A path that does not exist is simply absent.
DEFAULT_BACKUPS = (
    os.path.expanduser("~/backups/stewie-mirror.git"),
)


def device_of(path: str) -> str | None:
    """The block-device id backing `path`, or None if it does not exist."""
    try:
        return str(os.stat(path).st_dev)
    except OSError:
        return None


def evaluate(repo_dev: str | None, backups: dict[str, str | None],
             *, ages_h: dict[str, float] | None = None, max_age_h: float | None = None) -> dict:
    """Pure verdict: is there a durable copy on a different device than the working repo?

    `backups` maps path -> device id (None = the path does not exist). `ages_h` is optional; when
    `max_age_h` is set, a copy older than that does not count as protection -- a stale mirror is a
    false sense of safety, which is worse than a missing one.
    """
    if repo_dev is None:
        return {"ok": False, "reason": "the repo path does not exist -- nothing to check"}
    present = {p: d for p, d in backups.items() if d is not None}
    if not present:
        return {"ok": False, "separated": [], "same_device": [],
                "reason": "no durable copy of the repo exists at all"}
    fresh = present
    stale: list[str] = []
    if max_age_h is not None and ages_h:
        fresh = {p: d for p, d in present.items() if ages_h.get(p, 0.0) <= max_age_h}
        stale = [p for p in present if p not in fresh]
    separated = [p for p, d in fresh.items() if d != repo_dev]
    same = [p for p, d in present.items() if d == repo_dev]
    if not separated:
        why = "every durable copy is on the SAME device as the working repo"
        if stale:
            why += f"; {len(stale)} copy/copies exist but are staler than the freshness limit: {stale}"
        return {"ok": False, "separated": [], "same_device": same, "stale": stale, "reason": why}
    return {"ok": True, "separated": separated, "same_device": same, "stale": stale,
            "reason": f"{len(separated)} durable copy/copies on a different device: {separated}"}


def check(repo: str = _REPO, backups=DEFAULT_BACKUPS, *, max_age_h: float | None = None) -> dict:
    devs = {p: device_of(p) for p in backups}
    ages: dict[str, float] = {}
    for p in backups:
        try:
            ages[p] = (time.time() - os.stat(p).st_mtime) / 3600.0
        except OSError:
            pass
    v = evaluate(device_of(repo), devs, ages_h=ages, max_age_h=max_age_h)
    v["repo"] = repo
    v["devices"] = {p: d for p, d in devs.items()}
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=_REPO)
    ap.add_argument("--backup", action="append", default=None, help="extra durable copy to consider")
    ap.add_argument("--max-age-h", type=float, default=None, help="a copy older than this does not count")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    paths = tuple(a.backup) if a.backup else DEFAULT_BACKUPS
    v = check(a.repo, paths, max_age_h=a.max_age_h)
    if a.json:
        print(json.dumps(v, indent=2, sort_keys=True))
    else:
        print(("OK: " if v["ok"] else "SINGLE POINT OF FAILURE: ") + str(v["reason"]))
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
