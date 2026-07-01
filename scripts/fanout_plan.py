#!/usr/bin/env python3
"""Fan-out planner: derive the ready-set of independent, buildable, unowned §7 requirement rows and group
them into parallel work lanes, so an orchestrator can dispatch verified parallel agents.

It reads the PRD §7 matrix (the single source of truth for requirement state) and classifies every
not-yet-verified-done row into exactly one bucket:

  - DONE            : V == "D" (skip; already verified).
  - CONCURRENT      : owned by another active lane (the ARGUS/autonomy + arms families) -- do NOT fan out
                      here or you collide with the concurrent session.
  - GATED           : blocked on an external resource STEWIE cannot self-provide (a ROS host, a live pit,
                      a PyChrono host/oracle, a GPU, or LAC/IPEx arm geometry). Marked either by the PRD's
                      own Q=G quality glyph OR by the curated prose-gated map below (the PRD tags some
                      gated rows in prose, not the glyph -- e.g. the GPU dense-stereo PM rows).
  - BUILDABLE       : everything else not-done -> the ready-set, grouped by family into parallel lanes.

This keeps the fan-out metadata OUT of the 188-row §7 matrix (no CI-coupled bloat there): lane / gated-on
ownership lives here as a small classifier, and the plan is regenerated on demand rather than committed as
a stale artifact. Run: python3 scripts/fanout_plan.py
"""
from __future__ import annotations

import os
import re
from collections import defaultdict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PRD = os.path.join(_ROOT, "PRD.md")

# families owned by the concurrent ARGUS / autonomy + arms lane (do not fan out here).
CONCURRENT_FAMILIES = {"AS", "AM"}

# rows the PRD gates in prose rather than with the Q=G glyph, with the reason (curated, verified against
# §0's gated frontier -- NOT substring-matched, which false-flags e.g. "cockpit" as "pit").
PROSE_GATED = {
    "PM-13": "GPU dense stereo", "PM-14": "GPU dense stereo",
    "PM-15": "GPU dense stereo", "PM-16": "GPU dense stereo",
    "CP-07": "PyChrono calibration oracle", "TM-01": "PyChrono calibration oracle",
}
# reason for a Q=G glyph-gated row, by family (falls back to "quality/hardware gated").
GLYPH_GATED_REASON = {
    "AM": "LAC/IPEx arm geometry", "VT": "LAC/IPEx arm/vehicle geometry",
    "SN": "LED/photometry hardware", "AS": "ROS host / live pit",
}


def parse_rows(prd_path: str = _PRD) -> list[dict]:
    rows = []
    for line in open(prd_path, encoding="utf-8"):
        if not re.match(r"\|\s*[A-Z]{2}-\d{2}\s*\|\s*P\d\s*\|", line):
            continue
        p = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(p) < 7:
            continue
        rows.append({"id": p[0], "pri": p[1], "I": p[-4], "X": p[-3], "V": p[-2], "Q": p[-1],
                     "fam": p[0].split("-")[0]})
    return rows


def classify(r: dict) -> tuple[str, str | None]:
    """Return (bucket, gated_reason). bucket in done|concurrent|gated|buildable."""
    if r["V"] == "D":
        return "done", None
    if r["fam"] in CONCURRENT_FAMILIES:
        return "concurrent", None
    if r["id"] in PROSE_GATED:
        return "gated", PROSE_GATED[r["id"]]
    if r["Q"] == "G" or "G" in (r["I"], r["X"], r["V"]):
        return "gated", GLYPH_GATED_REASON.get(r["fam"], "quality/hardware gated")
    return "buildable", None


def plan(prd_path: str = _PRD) -> dict:
    rows = parse_rows(prd_path)
    lanes: dict[str, list] = defaultdict(list)
    gated: dict[str, list] = defaultdict(list)
    concurrent: list[str] = []
    done = 0
    for r in rows:
        bucket, reason = classify(r)
        if bucket == "done":
            done += 1
        elif bucket == "concurrent":
            concurrent.append(r["id"])
        elif bucket == "gated":
            gated[reason].append(r["id"])
        else:
            lanes[r["fam"]].append(r)
    return {"total": len(rows), "done": done, "lanes": dict(lanes),
            "gated": dict(gated), "concurrent": sorted(concurrent)}


def render(p: dict) -> str:
    out = []
    not_done = p["total"] - p["done"]
    buildable = sum(len(v) for v in p["lanes"].values())
    gated_n = sum(len(v) for v in p["gated"].values())
    out.append(f"# STEWIE fan-out plan ({p['total']} §7 rows, {p['done']} done, {not_done} not-done)")
    out.append(f"buildable ready-set: {buildable} | gated: {gated_n} | concurrent-lane: {len(p['concurrent'])}\n")
    out.append("## Ready-set (buildable now) -- parallel lanes, one agent per lane")
    for fam in sorted(p["lanes"], key=lambda f: -len(p["lanes"][f])):
        ids = ", ".join(f"{r['id']}({r['pri']})" for r in p["lanes"][fam])
        out.append(f"  {fam:3s} [{len(p['lanes'][fam])}]: {ids}")
    out.append("\n## Gated (skip until the resource exists) -- auto-routed by reason")
    for reason in sorted(p["gated"], key=lambda r: -len(p["gated"][r])):
        out.append(f"  {reason}: {sorted(p['gated'][reason])}")
    out.append(f"\n## Concurrent lane (owned elsewhere, do not fan out): {p['concurrent']}")
    return "\n".join(out)


def main() -> int:
    print(render(plan()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
