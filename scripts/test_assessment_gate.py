"""FS-01 codebase-assessment gate, in machine-checkable form: before a roadmap slice is implemented,
its dispatch brief must inventory the touched files/modules (panes, routers, physics modules) AND the
existing/target tests, and the tracer must report the row's coverage. The gate FAILS when a buildable
slice's inventory is absent -- "no assessment, no slice"."""
import os

import fanout_plan as F  # noqa: E402  (scripts/ sibling import; pytest prepend mode)
from scripts.req_trace import trace

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATHS = ["stewie", "dart", "lode", "leap", "forge", "scripts", "ros2_ws", "stewie_qgis"]


def test_every_buildable_slice_has_a_file_and_test_inventory():  # [REQ:FS-01]
    # the assessment gate proper: every buildable ready-set row's brief names affected files/modules
    # AND a test target BEFORE the slice is implemented. An empty inventory fails the gate.
    p = F.plan()
    briefs = F.assessment_inventory()
    for lane in p["lanes"].values():
        for r in lane:
            inv = briefs.get(r["id"])
            assert inv is not None, f"{r['id']}: buildable row has no dispatch brief (no assessment)"
            assert inv["files"], f"{r['id']}: brief inventories no affected files/modules"
            assert inv["test_target"], f"{r['id']}: brief inventories no existing/target test"


def test_inventory_names_real_repo_paths():  # [REQ:FS-01]
    # grounding: each brief's file inventory must anchor to the real tree -- at least one named file
    # exists. Briefs may also name NEW files or '...'-abbreviated siblings (PO-10/11 style), so an
    # abbreviated entry counts when a real file with that basename exists in the repo's python/JS tree.
    briefs = F.assessment_inventory()
    basenames = None                      # built lazily; only briefs with zero direct anchors need it
    for rid, inv in briefs.items():
        entries = [e.split(" (")[0].strip() for e in inv["files"]]      # drop "(execDraw P5)" notes
        if any(os.path.exists(os.path.join(_ROOT, e)) for e in entries):
            continue
        if basenames is None:
            basenames = set()
            for sub in ("stewie", "dart", "lode", "leap", "forge", "scripts"):
                for _dir, _dirs, files in os.walk(os.path.join(_ROOT, sub)):
                    basenames.update(files)
        anchored = any(e.startswith(".../") and os.path.basename(e) in basenames for e in entries)
        assert anchored, f"{rid}: no inventoried file exists in the repo: {inv['files']}"


def test_absent_inventory_is_reported_empty(tmp_path):  # [REQ:FS-01]
    # boundary (mirrors test_orphan_citation_fails_the_gate's minimal-doc pattern): a brief that
    # inventories nothing parses to EMPTY fields, which the gate assertions above fail on -- the
    # machine-checkable form of "a slice plan without a file/test inventory is not a plan".
    bad = tmp_path / "specs.md"
    bad.write_text("### AB-01 (P1) -- atomic\n- goal: something with no inventory\n")
    inv = F.assessment_inventory(str(bad))
    assert inv["AB-01"] == {"files": [], "test_target": ""}


def test_tracer_reports_coverage_and_bucketing_is_complete():  # [REQ:FS-01]
    # the tracer half of the gate: FS-01 itself is cited (this file), every [REQ:] citation resolves
    # to a real row, no V=D row is uncited, and the fan-out partition accounts for every §7 row --
    # the complete-inventory property the assessment gate rides on.
    report = trace("PRD.md", PATHS)
    assert "FS-01" in report["cited_ids"]
    assert report["unknown_markers"] == [] and report["v_done_uncited"] == []
    p = F.plan()
    buildable = sum(len(v) for v in p["lanes"].values())
    gated = sum(len(v) for v in p["gated"].values())
    # [REQ:PO-19] BLOCKED is a fifth bucket: a not-done, not-gated row whose declared prerequisites are
    # unfinished. It is NOT buildable (the ATG readiness rule), so it must not be dispatched -- but it is
    # still a §7 row, so the complete-inventory partition has to account for it or this gate goes red.
    blocked = len(p["blocked"])
    assert p["done"] + buildable + gated + blocked + len(p["concurrent"]) == p["total"], (
        f"partition leak: done={p['done']} buildable={buildable} gated={gated} blocked={blocked} "
        f"concurrent={len(p['concurrent'])} != total={p['total']}")
