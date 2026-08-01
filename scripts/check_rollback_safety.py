"""SR-12: refuse a rollback that would re-open a governance defect.

deploy/DEPLOY.md documents `stewie-backend:rollback` as the recovery path. On 2026-07-28 the review
found that executing it would have reverted the PUBLIC backend to a build predating the AR-005 fix:

    stewie-backend:latest              created 2026-07-26 12:57
    stewie-backend:rollback            created 2026-07-10 07:51   <-- 7 days BEFORE AR-005
    stewie-backend:rollback-2026-07-26 created 2026-07-11 14:13   <-- the NAME lies by 15 days
    commit 0946e1e8 (AR-005)           landed  2026-07-17 22:58

AR-005 is "anonymous /ide users are no longer director". Rolling back past it silently restores a
build in which every anonymous browser resolves to role director on the public origin. Nothing
verified tag age, and the `rollback-2026-07-26` name actively misleads -- it encodes a date fifteen
days newer than the image it points at, so an operator reaching for it under pressure gets the
opposite of what the name promises.

Two checks:

  * FLOOR      -- the image must not predate the newest commit in deploy/governance_floor.json.
  * NAME TRUTH -- a tag whose name encodes a date must point at an image built on that date.

Neither is a CI gate (they need the docker daemon and the built images); both belong to the deploy
runbook, before the re-tag or the rollback is executed.

    python scripts/check_rollback_safety.py stewie-backend:rollback
    python scripts/check_rollback_safety.py stewie-backend:rollback --force   # explicit override
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR_PATH = os.path.join(_REPO, "deploy", "governance_floor.json")

_TAG_DATE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _epoch(iso: str) -> float:
    return _dt.datetime.fromisoformat(iso).timestamp()


def load_floor(path: str = FLOOR_PATH) -> dict | None:
    """The newest governance commit on record: {sha, date, id, reason, epoch}, or None if empty."""
    try:
        with open(path, encoding="utf-8") as fh:
            commits = json.load(fh).get("commits") or []
    except (OSError, ValueError):
        return None
    best = None
    for c in commits:
        try:
            e = _epoch(str(c["date"]))
        except (KeyError, ValueError):
            continue
        if best is None or e > best["epoch"]:
            best = {**c, "epoch": e}
    return best


def evaluate(image_epoch: float | None, floor: dict | None, tag: str = "") -> dict:
    """The pure verdict: may this image be deployed as a rollback target?"""
    if image_epoch is None:
        return {"ok": False, "reason": f"image {tag!r} not found -- cannot verify what it would restore"}
    if floor is None:
        return {"ok": True, "reason": "no governance floor recorded -- nothing to re-open"}
    if image_epoch < floor["epoch"]:
        gap_d = (floor["epoch"] - image_epoch) / 86400.0
        return {"ok": False, "floor_id": floor.get("id", ""), "floor_sha": floor.get("sha", ""),
                "gap_days": gap_d,
                "reason": (f"{tag or 'image'} was built {gap_d:.1f} days BEFORE the governance fix "
                           f"{floor.get('id', '')} ({floor.get('sha', '')}): {floor.get('reason', '')}. "
                           "Deploying it would re-open that defect.")}
    return {"ok": True, "floor_id": floor.get("id", ""), "floor_sha": floor.get("sha", ""),
            "reason": f"image is at or after the governance floor {floor.get('id', '')}"}


def evaluate_tag_name_truth(tag: str, image_epoch: float | None, *, tolerance_days: float = 1.5) -> dict:
    """A tag whose NAME encodes a date must point at an image built on that date.

    `rollback-2026-07-26` pointing at a 2026-07-11 image is not a cosmetic problem: it is the label an
    operator trusts during an incident.
    """
    m = _TAG_DATE.search(tag or "")
    if not m or image_epoch is None:
        return {"ok": True, "reason": "tag encodes no date -- nothing to contradict"}
    named = _dt.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).timestamp()
    off_d = abs(image_epoch - named) / 86400.0
    if off_d > tolerance_days:
        built = _dt.datetime.fromtimestamp(image_epoch).strftime("%Y-%m-%d")
        return {"ok": False, "off_days": off_d,
                "reason": (f"tag {tag!r} names {m.group(0)} but points at an image built {built} "
                           f"({off_d:.1f} days off) -- the name misleads whoever reaches for it")}
    return {"ok": True, "reason": "tag name matches the image build date"}


def docker_image_epoch(tag: str) -> float | None:
    """Creation time of a local docker image, or None if docker or the image is unavailable."""
    try:
        r = subprocess.run(["docker", "inspect", "-f", "{{.Created}}", tag],
                           capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        return None
    try:
        return _epoch(out.replace("Z", "+00:00"))
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag", nargs="?", default="stewie-backend:rollback")
    ap.add_argument("--force", action="store_true", help="deploy anyway; prints what is being re-opened")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    epoch = docker_image_epoch(a.tag)
    floor_v = evaluate(epoch, load_floor(), a.tag)
    name_v = evaluate_tag_name_truth(a.tag, epoch)
    verdict = {"tag": a.tag, "floor": floor_v, "tag_name": name_v,
               "ok": bool(floor_v["ok"] and name_v["ok"])}
    if a.json:
        print(json.dumps(verdict, indent=2, sort_keys=True))
    else:
        for v in (floor_v, name_v):
            print(("OK: " if v["ok"] else "REFUSED: ") + str(v["reason"]))
    if verdict["ok"]:
        return 0
    if a.force:
        print("--force given: proceeding despite the above. Record why in the deploy log.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
