#!/usr/bin/env python3
"""Generate stewie/server/program_snapshot.json -- the committed program-board artifact the /program
cockpit page serves.

Why an artifact: the backend image ships only the installed packages (deploy/Dockerfile.backend copies
stewie/dart/lode/leap/forge), NOT PRD.md / FANOUT_SPECS.md / scripts/, so the deployed server cannot
parse the matrix at runtime. Same pattern as bodies.json (gen_bodies_json.py): generate from the source
of truth, commit the artifact, serve the bytes.

Honesty rules baked in:
  - Reads the COMMITTED state (`git show HEAD:...`), never the working tree -- a concurrent agent's
    uncommitted PRD.md edits must not leak into the published board.
  - Deterministic: no timestamps; provenance is the HEAD commit + content sha256 of each source, so the
    same commit always regenerates byte-identical output (and the page can show exactly what snapshot
    it is looking at).
  - Row classification is delegated to scripts/fanout_plan.py (the single classifier), not duplicated.

Regenerate after any committed PRD.md / FANOUT_SPECS.md / [REQ:] marker change:
    python3 scripts/gen_program_snapshot.py
scripts/test_gen_program_snapshot.py enforces byte-freshness whenever the committed snapshot's
prd_sha256 matches HEAD's PRD.md (and skips -- loudly, not silently red -- when the PRD moved without a
regen, so another agent's PRD commit is never failed by this artifact).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fanout_plan  # noqa: E402  (scripts/ sibling import, same as test_fanout_plan.py)

OUT_PATH = os.path.join(_ROOT, "stewie", "server", "program_snapshot.json")

#: the six-slot ConOps spine the cockpit is organized around (2026-06-23 reorg) -- the board links the
#: program state back to the operator workflow it exists to ship.
WORKFLOW_SPINE = ("Plan", "Rehearse", "Validate", "Release", "Execute", "Report")

_ROW_RE = re.compile(r"^\|\s*([A-Z]{2}-\d{2})\s*\|\s*(P\d)\s*\|")
_BRIEF_HEAD_RE = re.compile(r"^### ([A-Z]{2}-\d{2}) \((P\d)(?:, [^)]+)?\) — (.+)$")
_REQ_RE = re.compile(r"\[REQ:([A-Z]{2}-\d{2})\]")


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=_ROOT, check=True, capture_output=True).stdout


def head_blob(path: str) -> bytes:
    """The committed (HEAD) content of a repo file -- immune to concurrent uncommitted edits."""
    return _git("show", f"HEAD:{path}")


def parse_row_texts(prd_text: str) -> dict[str, str]:
    """id -> the 'Requirement and acceptance' column of each section-7 matrix row."""
    texts: dict[str, str] = {}
    for line in prd_text.splitlines():
        if not _ROW_RE.match(line):
            continue
        parts = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(parts) >= 7:
            texts[parts[0]] = parts[2]
    return texts


def parse_briefs(specs_text: str) -> dict[str, dict[str, str]]:
    """id -> {kind, goal, test_target} from the FANOUT_SPECS.md dispatch briefs."""
    briefs: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in specs_text.splitlines():
        m = _BRIEF_HEAD_RE.match(line)
        if m:
            cur = {"kind": m.group(3).strip()}
            briefs[m.group(1)] = cur
            continue
        if cur is None:
            continue
        for field in ("goal", "test_target"):
            prefix = f"- {field}:"
            if line.startswith(prefix):
                cur[field] = line[len(prefix):].strip()
    return briefs


def cited_ids() -> set[str]:
    """Requirement ids cited by a COMMITTED python test marker (the req_trace done-gate's scan shape)."""
    try:
        hits = _git("grep", "-h", "-o", r"\[REQ:[A-Z][A-Z]-[0-9][0-9]\]", "HEAD", "--", "*test_*.py")
    except subprocess.CalledProcessError:   # no matches
        return set()
    return set(_REQ_RE.findall(hits.decode()))


def build_snapshot() -> dict:
    prd = head_blob("PRD.md")
    specs = head_blob("FANOUT_SPECS.md")
    prd_text = prd.decode("utf-8")

    # classify via the single classifier, off the committed PRD bytes
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(prd_text)
        tmp = fh.name
    try:
        rows = fanout_plan.parse_rows(tmp)
    finally:
        os.unlink(tmp)

    texts = parse_row_texts(prd_text)
    briefs = parse_briefs(specs.decode("utf-8"))
    cited = cited_ids()

    out_rows = []
    buckets = {"done": 0, "buildable": 0, "gated": 0, "concurrent": 0}
    lanes: dict[str, dict[str, int]] = {}
    pri: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket, reason = fanout_plan.classify(r)
        buckets[bucket] += 1
        lane = lanes.setdefault(r["fam"], {"total": 0, "done": 0})
        lane["total"] += 1
        p = pri.setdefault(r["pri"], {"total": 0, "done": 0})
        p["total"] += 1
        if bucket == "done":
            lane["done"] += 1
            p["done"] += 1
        row = {"id": r["id"], "pri": r["pri"], "lane": r["fam"], "text": texts.get(r["id"], ""),
               "I": r["I"], "X": r["X"], "V": r["V"], "Q": r["Q"],
               "bucket": bucket, "cited": r["id"] in cited}
        if reason:
            row["gated_reason"] = reason
        if r["id"] in briefs:
            row["brief"] = briefs[r["id"]]
        out_rows.append(row)

    total = len(out_rows)
    in_scope = total - buckets["gated"]
    return {
        "provenance": {
            # the last commit that TOUCHED PRD.md (stable across unrelated commits, unlike HEAD)
            "prd_commit": _git("log", "-1", "--format=%H", "HEAD", "--", "PRD.md").decode().strip(),
            "prd_sha256": hashlib.sha256(prd).hexdigest(),
            "specs_sha256": hashlib.sha256(specs).hexdigest(),
            "citations_sha256": hashlib.sha256(",".join(sorted(cited)).encode()).hexdigest(),
            "generated_by": "scripts/gen_program_snapshot.py",
        },
        "workflow_spine": list(WORKFLOW_SPINE),
        "summary": {
            "total": total,
            "buckets": buckets,
            "in_scope": in_scope,
            "done_pct": round(100.0 * buckets["done"] / total, 1) if total else 0.0,
            "in_scope_done_pct": round(100.0 * buckets["done"] / in_scope, 1) if in_scope else 0.0,
            "cited": sum(1 for r in out_rows if r["cited"]),
            "briefs": len(briefs),
            "by_priority": {k: pri[k] for k in sorted(pri)},
            "by_lane": {k: lanes[k] for k in sorted(lanes)},
        },
        "rows": sorted(out_rows, key=lambda r: r["id"]),
    }


def main() -> int:
    snap = build_snapshot()
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, sort_keys=True)
        fh.write("\n")
    s = snap["summary"]
    print(f"wrote {os.path.relpath(OUT_PATH, _ROOT)}: {s['total']} rows, "
          f"{s['buckets']['done']} done ({s['in_scope_done_pct']}% in-scope), "
          f"{s['briefs']} briefs, PRD @ {snap['provenance']['prd_commit'][:9]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
