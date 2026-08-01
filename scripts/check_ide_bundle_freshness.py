"""SR-10: refuse to deploy an `/ide` bundle older than the source it is supposed to contain.

`gis/qwc2/prod` is gitignored and bind-mounted read-only into `stewie-artemis-web`, so "building
locally IS the deploy" (deploy/DEPLOY.md). Nothing checked that the built bundle actually contained the
committed source, and on 2026-07-28 the review found it did not: the newest file in `gis/qwc2/prod` was
built 2026-07-13T23:09:24, while commit `4fb8e3a8` (TR-03, "the operator picks the worksite section")
touched `gis/qwc2/js` at 2026-07-13T23:40:17 -- 31 minutes later. `grep -c start_xy` over the shipped
bundle returned zero: the operator click-to-place control did not exist in the deployed IDE, while the
project banner recorded it as LIVE on artemis.stewie.space/ide/.

WHY COMMIT TIME, NOT FILE MTIME. The obvious check -- newest `prod/` mtime vs newest `gis/qwc2/js`
mtime -- gives the WRONG answer here, and would have passed this exact failure. Working-tree mtimes
record when git last wrote the file, not when the change was authored: on the live host the sources
read 2026-07-13T09:41 (older than the 23:09 bundle) even though the change that mattered was committed
at 23:40. Comparing against the newest COMMIT that touches the source is the signal that actually
tracks "is the shipped bundle behind the code".

This is a DEPLOY gate, not a CI gate: `gis/qwc2/prod` is gitignored, so a CI checkout has no bundle at
all and `bundle_epoch` is None. Run it from the deploy runbook before rsyncing a build into the live
mount -- the failure belongs to the deploy, not to the operator's browser.

    python scripts/check_ide_bundle_freshness.py            # exit 1 if the bundle is behind
    python scripts/check_ide_bundle_freshness.py --json     # machine-readable verdict
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCE_PATH = "gis/qwc2/js"
BUNDLE_PATH = "gis/qwc2/prod"


def evaluate(bundle_epoch: float | None, commit_epoch: int | None, commit_sha: str = "",
             *, grace_s: float = 0.0) -> dict:
    """The pure verdict, so the decision is testable without a repo or a build.

    `grace_s` tolerates a build kicked off slightly before the final commit lands (a real ordering in
    practice); default 0 keeps it strict.
    """
    if commit_epoch is None:
        return {"ok": True, "reason": "no commit touches the bundle source yet -- nothing to be behind",
                "stale": False, "bundle_epoch": bundle_epoch, "commit_epoch": None, "commit_sha": ""}
    if bundle_epoch is None:
        return {"ok": False, "reason": f"no built bundle found under {BUNDLE_PATH}/ -- build it before deploying",
                "stale": True, "bundle_epoch": None, "commit_epoch": commit_epoch, "commit_sha": commit_sha}
    lag = commit_epoch - bundle_epoch
    if lag > grace_s:
        return {"ok": False, "stale": True, "bundle_epoch": bundle_epoch, "commit_epoch": commit_epoch,
                "commit_sha": commit_sha, "lag_s": lag,
                "reason": (f"the built bundle is {lag:.0f}s older than commit {commit_sha} which touches "
                           f"{SOURCE_PATH}/ -- deploying it would serve code that predates the source")}
    return {"ok": True, "stale": False, "bundle_epoch": bundle_epoch, "commit_epoch": commit_epoch,
            "commit_sha": commit_sha, "lag_s": lag, "reason": "bundle is at or ahead of the newest source commit"}


def newest_source_commit(repo: str = _REPO, ref: str = "HEAD") -> tuple[int, str] | tuple[None, str]:
    """(epoch, sha) of the newest commit touching the bundle source, or (None, '') if there is none."""
    try:
        out = subprocess.run(["git", "-C", repo, "log", ref, "-1", "--format=%ct %h", "--", SOURCE_PATH],
                             capture_output=True, text=True, timeout=30, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, ""
    if not out:
        return None, ""
    parts = out.split()
    try:
        return int(parts[0]), (parts[1] if len(parts) > 1 else "")
    except ValueError:
        return None, ""


def newest_bundle_mtime(repo: str = _REPO) -> float | None:
    """The mtime of the most recently written file in the built bundle, or None if nothing is built."""
    root = os.path.join(repo, BUNDLE_PATH)
    newest: float | None = None
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                mt = os.stat(os.path.join(dirpath, fn)).st_mtime
            except OSError:
                continue
            if newest is None or mt > newest:
                newest = mt
    return newest


def check(repo: str = _REPO, ref: str = "HEAD", *, grace_s: float = 0.0) -> dict:
    epoch, sha = newest_source_commit(repo, ref)
    return evaluate(newest_bundle_mtime(repo), epoch, sha, grace_s=grace_s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=_REPO)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--grace-s", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    v = check(a.repo, a.ref, grace_s=a.grace_s)
    if a.json:
        print(json.dumps(v, indent=2, sort_keys=True))
    else:
        print(("OK: " if v["ok"] else "STALE BUNDLE: ") + str(v["reason"]))
    return 0 if v["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
