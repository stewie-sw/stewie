#!/usr/bin/env python3
"""The requirements tracer (PRD §19.2): NASA-style traceability, enforced.

Parses the PRD §7 matrix (| ID | P | text | I | X | V | Q |), scans the test suite for
[REQ:<ID>] markers, and reports coverage. THE RULE: a requirement may only hold V=D if at
least one test cites it. CI fails on violations.

Usage: python3 scripts/req_trace.py [--prd PRD.md] [--paths stewie dart lode scripts]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROW = re.compile(r"\|\s*([A-Z]{2}-\d{2})\s*\|\s*(P\d)\s*\|(.+?)\|\s*([DPNG]|NA)\s*\|"
                  r"\s*([DPNG]|NA)\s*\|\s*([DPNG]|NA)\s*\|\s*([DPNG]|NA)\s*\|")
_MARK = re.compile(r"\[REQ:([A-Z]{2}-\d{2})\]")


def parse_requirements(prd_path: str) -> dict:
    reqs: dict = {}
    for ln in open(prd_path, encoding="utf-8"):
        m = _ROW.match(ln)
        if m:
            reqs[m.group(1)] = {"pri": m.group(2), "text": m.group(3).strip(),
                                "I": m.group(4), "X": m.group(5), "V": m.group(6), "Q": m.group(7)}
    return reqs


def scan_markers(paths: list) -> dict:
    """[REQ:ID] -> [file:line, ...] across test files."""
    found: dict = {}
    for root in paths:
        for dirpath, _dirs, files in os.walk(root):
            if any(part.startswith(".") or part == "__pycache__" for part in dirpath.split(os.sep)):
                continue
            for fn in files:
                if not (fn.startswith("test_") and fn.endswith(".py")):
                    continue
                p = os.path.join(dirpath, fn)
                for i, ln in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
                    for m in _MARK.finditer(ln):
                        found.setdefault(m.group(1), []).append(f"{p}:{i}")
    return found


def trace(prd_path: str, paths: list) -> dict:
    reqs = parse_requirements(prd_path)
    marks = scan_markers(paths)
    cited = sorted(set(marks) & set(reqs))
    unknown = sorted(set(marks) - set(reqs))
    v_done_uncited = sorted(r for r, d in reqs.items() if d["V"] == "D" and r not in marks)
    # FS-22 reconciliation audit (reverse staleness): a row that HAS a citing test but is NOT yet V=D --
    # a PRD status that may lag the code. Legitimate mid-development (a test can cite a partial row), so
    # it is SURFACED for review, not failed. Pairs with the v_done_uncited rule (which fails) to keep the
    # PRD <-> test mapping honest in BOTH directions.
    understated = sorted((r, reqs[r]["V"]) for r in cited if reqs[r]["V"] != "D")
    return {"total": len(reqs), "cited": len(cited), "cited_ids": cited,
            "unknown_markers": unknown, "v_done_uncited": v_done_uncited,
            "understated": understated, "markers": marks}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prd", default="PRD.md")
    ap.add_argument("--paths", nargs="*",
                    # aligned with pyproject testpaths so every CI-run test package is scanned for [REQ:]
                    # markers (stewie_qgis was missing -> its [REQ:QG-01] citation was invisible to the tracer).
                    default=["stewie", "dart", "lode", "leap", "forge", "scripts", "ros2_ws", "stewie_qgis"])
    args = ap.parse_args(argv)
    r = trace(args.prd, args.paths)
    print(f"requirements: {r['total']} · cited by tests: {r['cited']}")
    if r["understated"]:        # FS-22 audit: cited-but-not-V=D, surfaced for promotion review (not a failure)
        print(f"audit (FS-22): {len(r['understated'])} row(s) cited but V!=D — review for promotion: "
              + ", ".join(f"{rid}({v})" for rid, v in r["understated"]))
    violations = []
    if r["unknown_markers"]:    # FS-22: an orphan [REQ:] citation -- a test claims a requirement that does
        print(f"VIOLATION — orphan [REQ:] citation to a non-existent requirement: {r['unknown_markers']}")
        violations.append("unknown_markers")   # not exist (typo / deleted row). The mapping must be exact.
    if r["v_done_uncited"]:
        print(f"VIOLATION — V=D without a citing test: {r['v_done_uncited']}")
        violations.append("v_done_uncited")
    if violations:
        return 1
    print("reconciliation holds: every [REQ:] citation resolves to a real row, every V=D is test-cited")
    return 0


if __name__ == "__main__":
    sys.exit(main())
