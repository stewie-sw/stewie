#!/usr/bin/env python3
"""Fan-out planner: derive the ready-set of independent, buildable, unowned §7 requirement rows and group
them into parallel work lanes, so an orchestrator can dispatch verified parallel agents.

It reads the PRD §7 matrix (the single source of truth for requirement state) and classifies every
not-yet-verified-done row into exactly one bucket:

  - DONE            : V == "D" (skip; already verified).
  - CONCURRENT/OWNED: the AS autonomy stack is CONTAINER-BUILDABLE (Gazebo/ROS2 via the compose `ros2`
                      profile -- osrf/ros:jazzy-desktop / stewie-gazebo:jazzy are on this host) but is
                      currently OWNED by the live AS-lane agent; keep it out of the fan-out to avoid
                      collision, NOT because it is gated. AM (arms) is genuinely data-gated on LAC/IPEx
                      geometry. Both stay out of the ready-set for now.
  - GATED           : blocked on a resource STEWIE genuinely cannot self-provide -- a LIVE PIT / real
                      rover, external DATA (LAC/IPEx arm geometry), a PyChrono calibration oracle, or a
                      physical GPU where the Docker render/depth container will not substitute. NOTE:
                      containerized ROS2/Gazebo is AVAILABLE, so a row needing only that is buildable-in-
                      container, not gated (the earlier "AS needs a ROS host" framing was wrong). Marked
                      by the Q=G glyph OR the curated prose-gated map below (e.g. the depth-source PM rows).
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

# kept out of the fan-out ready-set because a live agent owns them RIGHT NOW (avoid double-dispatch).
# 2026-07-02: the AS flight-autonomy lane is COMMITTED + CLEAR (no live owner), so AS is no longer
# concurrent -- it falls through to the normal buckets and is container-buildable (Gazebo/ROS2 via the
# compose `ros2` profile; osrf/ros:jazzy-desktop / stewie-gazebo:jazzy are on this host). Empty until a
# real concurrent agent reappears.
CONCURRENT_FAMILIES: set[str] = set()

# whole families gated on a resource STEWIE cannot self-provide, regardless of per-row glyph. AM = the
# arm/MEERKAT rows: every one needs the non-public LAC/IPEx arm geometry, so gate the family uniformly
# (AM-09 has Q=N yet is just as geometry-dependent -- a family gate catches it; a per-glyph gate would not).
FAMILY_GATED = {"AM": "LAC/IPEx arm geometry"}

# rows the PRD gates in prose rather than with the Q=G glyph, with the reason (curated, verified against
# §0's gated frontier -- NOT substring-matched, which false-flags e.g. "cockpit" as "pit").
PROSE_GATED = {
    "PM-13": "GPU/live depth-source pipeline", "PM-14": "GPU/live depth-source pipeline",
    "PM-15": "GPU/live depth-source pipeline", "PM-16": "GPU/live depth-source pipeline",
    "CP-07": "PyChrono calibration oracle", "TM-01": "PyChrono calibration oracle",
}
# reason for a Q=G glyph-gated row, by family (falls back to "quality/hardware gated").
# (No "AS" entry: AS is caught by the concurrent/owned bucket above and is container-buildable, not gated.)
GLYPH_GATED_REASON = {
    "AM": "LAC/IPEx arm geometry", "VT": "LAC/IPEx arm/vehicle geometry",
    "SN": "LED/photometry hardware",
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
    if r["fam"] in FAMILY_GATED:
        return "gated", FAMILY_GATED[r["fam"]]
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
        elif bucket == "gated" and reason is not None:   # classify() always gives a reason for gated
            gated[reason].append(r["id"])
        else:
            lanes[r["fam"]].append(r)
    return {"total": len(rows), "done": done, "lanes": dict(lanes),
            "gated": dict(gated), "concurrent": sorted(concurrent)}


def assessment_inventory(specs_path: str = os.path.join(_ROOT, "FANOUT_SPECS.md")) -> dict[str, dict]:
    """FS-01 codebase-assessment gate: the per-slice inventory of touched files/modules + the test
    target, parsed from the FANOUT_SPECS.md dispatch briefs. A brief that inventories nothing parses
    to empty fields so a gate test can FAIL it -- no assessment, no slice."""
    briefs: dict[str, dict] = {}
    cur = None
    for line in open(specs_path, encoding="utf-8"):
        m = re.match(r"^### ([A-Z]{2}-\d{2})", line)
        if m:
            cur = m.group(1)
            briefs[cur] = {"files": [], "test_target": ""}
            continue
        if cur is None:
            continue
        ln = line.strip()
        if ln.startswith("- files:"):
            briefs[cur]["files"] = [f.strip() for f in ln[len("- files:"):].split(",") if f.strip()]
        elif ln.startswith("- test_target:"):
            briefs[cur]["test_target"] = ln[len("- test_target:"):].strip()
    return briefs


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
    out.append("\nPer-row dispatch briefs (goal / acceptance / files / test target) for the buildable "
               "ready-set: see FANOUT_SPECS.md.")
    return "\n".join(out)


def main() -> int:
    print(render(plan()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
