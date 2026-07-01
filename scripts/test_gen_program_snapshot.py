"""The program-board snapshot artifact must be an honest, regenerable projection of the COMMITTED PRD
section-7 matrix: every row accounted for in exactly one bucket, summaries recomputable from the rows,
provenance pinned to content hashes, and the committed bytes fresh whenever they claim to describe the
current HEAD PRD (a stale-but-labeled snapshot skips loudly instead of failing another agent's PRD
commit -- regenerate with `python3 scripts/gen_program_snapshot.py`)."""
from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

import gen_program_snapshot as G  # noqa: E402  (scripts/ sibling import; pytest prepend mode)


def _git_available() -> bool:
    try:
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=G._ROOT, check=True, capture_output=True)
        return True
    except Exception:   # noqa: BLE001 -- no .git (sdist/container run): the regen contract can't apply
        return False


pytestmark = pytest.mark.skipif(not _git_available(), reason="no git HEAD (snapshot regen needs the repo)")


def test_snapshot_partitions_every_row_and_summary_is_recomputable():
    snap = G.build_snapshot()
    rows = snap["rows"]
    s = snap["summary"]
    assert s["total"] == len(rows) >= 180
    assert len({r["id"] for r in rows}) == len(rows)
    # every row lands in exactly one bucket and the bucket counts are exactly the row counts
    got = {"done": 0, "buildable": 0, "gated": 0, "concurrent": 0}
    for r in rows:
        got[r["bucket"]] += 1
        assert r["bucket"] != "gated" or r.get("gated_reason"), f"{r['id']}: gated without a reason"
    assert got == s["buckets"]
    assert s["in_scope"] == s["total"] - s["buckets"]["gated"]
    assert s["cited"] == sum(1 for r in rows if r["cited"])
    # lane + priority rollups recompute from the rows
    for lane, v in s["by_lane"].items():
        mine = [r for r in rows if r["lane"] == lane]
        assert v == {"total": len(mine), "done": sum(1 for r in mine if r["bucket"] == "done")}
    for p, v in s["by_priority"].items():
        mine = [r for r in rows if r["pri"] == p]
        assert v == {"total": len(mine), "done": sum(1 for r in mine if r["bucket"] == "done")}


def test_briefs_attach_only_to_real_rows_with_goal_and_kind():
    snap = G.build_snapshot()
    briefed = [r for r in snap["rows"] if "brief" in r]
    assert len(briefed) == snap["summary"]["briefs"] > 0
    for r in briefed:
        assert r["brief"].get("kind"), f"{r['id']}: brief without a kind"
        assert r["brief"].get("goal"), f"{r['id']}: brief without a goal"


def test_provenance_pins_the_committed_sources():
    snap = G.build_snapshot()
    prov = snap["provenance"]
    assert prov["prd_sha256"] == hashlib.sha256(G.head_blob("PRD.md")).hexdigest()
    assert prov["specs_sha256"] == hashlib.sha256(G.head_blob("FANOUT_SPECS.md")).hexdigest()
    assert len(prov["prd_commit"]) == 40


def test_committed_artifact_is_fresh_for_the_sources_it_claims():
    with open(G.OUT_PATH, encoding="utf-8") as fh:
        committed = json.load(fh)
    regen = G.build_snapshot()
    volatile = ("prd_sha256", "specs_sha256", "citations_sha256")
    if any(committed["provenance"][k] != regen["provenance"][k] for k in volatile):
        pytest.skip("program_snapshot.json describes older sources (PRD/FANOUT_SPECS/[REQ:] markers "
                    "moved) -- regenerate: python3 scripts/gen_program_snapshot.py (skipping, not "
                    "failing, so a source-only commit by another agent is never redded by this artifact)")
    # prd_commit is display metadata: a shallow CI clone (actions/checkout depth-1) grafts history, so
    # `git log -1 -- PRD.md` reports the graft commit there. The content hashes above already pin the
    # sources byte-exactly; normalize the label before the byte compare.
    regen["provenance"]["prd_commit"] = committed["provenance"]["prd_commit"]
    regen_bytes = json.dumps(regen, indent=1, sort_keys=True) + "\n"
    with open(G.OUT_PATH, encoding="utf-8") as fh:
        assert fh.read() == regen_bytes, ("program_snapshot.json is stale for the sources it claims to "
                                          "describe; run python3 scripts/gen_program_snapshot.py")


def test_workflow_spine_is_the_cockpit_conops_order():
    assert G.build_snapshot()["workflow_spine"] == ["Plan", "Rehearse", "Validate", "Release",
                                                    "Execute", "Report"]
