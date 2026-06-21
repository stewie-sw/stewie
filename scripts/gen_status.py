#!/usr/bin/env python3
"""The §7 status-surface generator (PRD §19.2 companion).

ONE status surface, derived entirely from the live traceability tools -- never hand-numbered. It runs
``scripts/req_trace.trace`` (the PRD §7 matrix + the [REQ:] marker scan) and ``scripts/release_gate``
(the AS-01..17 capstone), and emits:

  * ``STATUS.md``   -- the human-readable §7 status (total requirements, cited count, the V!=D flagged
                       rows surfaced by the FS-22 audit, and the per-family rollup),
  * ``STATUS.json`` -- the same numbers as a machine artifact (for the cockpit /figures pane).

Every number comes from the tools at generation time, so the surface cannot silently drift from the
matrix. ``--check`` regenerates in memory and exits non-zero if either committed file is stale -- the
CI guard that keeps STATUS.md honest. Run: ``python3 scripts/gen_status.py`` (or ``--check``).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow running as a bare script (`python scripts/gen_status.py`, as the docstring + the drift-test
# error message instruct) and not only via `-m`/pytest: put the repo root on sys.path so the absolute
# `scripts.*` imports below resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.release_gate import release_report
from scripts.req_trace import parse_requirements, trace

# the same scan roots req_trace + release_gate use (the autonomy tests live in ros2_ws too)
_PATHS = ["stewie", "dart", "lode", "scripts", "ros2_ws"]
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _family(rid: str) -> str:
    """The 2-letter family prefix of a requirement id (e.g. AS-07 -> AS)."""
    return rid.split("-")[0]


def collect(prd_path: str, paths: list) -> dict:
    """Build the §7 status purely from the live tools. No hand numbers anywhere in this dict."""
    reqs = parse_requirements(prd_path)
    tr = trace(prd_path, paths)
    cited = set(tr["cited_ids"])

    # per-family rollup: total vs cited, straight off the parsed matrix + the marker scan.
    rollup: dict = {}
    for rid in reqs:
        fam = _family(rid)
        slot = rollup.setdefault(fam, {"total": 0, "cited": 0})
        slot["total"] += 1
        if rid in cited:
            slot["cited"] += 1
    rollup = {fam: rollup[fam] for fam in sorted(rollup)}

    # the V!=D flagged rows are the FS-22 "understated" audit: a row a test cites but the PRD has not
    # yet promoted to V=D. (id, current V) pairs, already sorted by req_trace.
    flagged = [{"id": rid, "v": v} for rid, v in tr["understated"]]

    rel = release_report()["summary"]
    return {
        "total": tr["total"],
        "cited": tr["cited"],
        "v_ne_d_flagged": flagged,
        "v_done_uncited": tr["v_done_uncited"],
        "unknown_markers": tr["unknown_markers"],
        "per_family": rollup,
        "autonomy_track": {
            "in_matrix": rel["in_matrix"],
            "total": rel["total"],
            "cited": rel["cited"],
            "currently_v_done": rel["currently_v_done"],
            "eligible_for_v_done": rel["eligible_for_v_done"],
        },
    }


def render_md(st: dict) -> str:
    """Render STATUS.md from the collected status. Deterministic (sorted), so it diffs cleanly."""
    out = ["# STEWIE §7 requirements status", ""]
    out.append("Generated from the live traceability tools (`scripts/req_trace.py` + "
               "`scripts/release_gate.py`) by `scripts/gen_status.py`. Do NOT hand-edit -- "
               "`gen_status.py --check` fails CI if this file drifts from the tools.")
    out.append("")
    out.append(f"- requirements (PRD §7 rows): **{st['total']}**")
    out.append(f"- cited by >=1 test ([REQ:] marker): **{st['cited']}**")
    out.append(f"- V!=D flagged (FS-22 audit: cited but not yet V=D): **{len(st['v_ne_d_flagged'])}**")
    out.append("")

    out.append("## V!=D flagged rows (cited, awaiting promotion)")
    out.append("")
    if st["v_ne_d_flagged"]:
        out.append("| ID | current V |")
        out.append("|----|-----------|")
        for row in st["v_ne_d_flagged"]:
            out.append(f"| {row['id']} | {row['v']} |")
    else:
        out.append("_none -- every cited row is V=D._")
    out.append("")

    out.append("## Per-family rollup (cited / total)")
    out.append("")
    out.append("| family | cited | total |")
    out.append("|--------|-------|-------|")
    for fam, slot in st["per_family"].items():
        out.append(f"| {fam} | {slot['cited']} | {slot['total']} |")
    out.append("")

    at = st["autonomy_track"]
    out.append("## §25 autonomy track (AS-01..17)")
    out.append("")
    out.append(f"- in matrix: {at['in_matrix']}/{at['total']}")
    out.append(f"- cited: {at['cited']}/{at['total']}")
    out.append(f"- currently V=D: {at['currently_v_done'] or 'none promoted yet'}")
    out.append(f"- eligible for V=D: {at['eligible_for_v_done'] or 'none'}")
    out.append("")
    return "\n".join(out)


def render_json(st: dict) -> str:
    """Render STATUS.json (sorted keys -> deterministic) for the cockpit /figures pane."""
    return json.dumps(st, indent=2, sort_keys=True) + "\n"


def generate(prd_path: str, paths: list) -> tuple:
    """Collect the status and return (markdown, json) text -- the single source for write + --check."""
    st = collect(prd_path, paths)
    return render_md(st), render_json(st)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prd", default="PRD.md")
    ap.add_argument("--paths", nargs="*", default=_PATHS)
    ap.add_argument("--md-out", default=os.path.join(_REPO_ROOT, "STATUS.md"))
    ap.add_argument("--json-out", default=os.path.join(_REPO_ROOT, "STATUS.json"))
    ap.add_argument("--check", action="store_true",
                    help="regenerate in memory and fail (exit 2) if a committed file is stale")
    args = ap.parse_args(argv)

    md, js = generate(args.prd, args.paths)

    if args.check:
        stale = []
        for path, fresh in ((args.md_out, md), (args.json_out, js)):
            current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if current != fresh:
                stale.append(path)
        if stale:
            print("STALE -- run `python3 scripts/gen_status.py` to regenerate: " + ", ".join(stale))
            return 2
        print("STATUS.md / STATUS.json are in sync with the live req_trace output")
        return 0

    with open(args.md_out, "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(args.json_out, "w", encoding="utf-8") as fh:
        fh.write(js)
    print(f"wrote {args.md_out} and {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
