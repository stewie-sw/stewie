"""#NASA-standards: the requirements tracer -- PRD section-7 IDs must trace to tests.

A requirement may only claim V=D if at least one test cites it with a [REQ:<ID>] marker. The FS-22
reconciliation gate additionally fails on an orphan [REQ:] citation (a marker for a non-existent row)
and surfaces 'understated' rows (cited but not yet V=D) for promotion review."""
import os

from scripts.req_trace import main, parse_requirements, scan_markers, trace

# the autonomy-track tests live in ros2_ws too (AS-02/03/04/05/06), so the trace must scan it
PATHS = ["stewie", "dart", "lode", "scripts", "ros2_ws"]


def test_parses_the_prd_matrix():
    reqs = parse_requirements("PRD.md")
    assert len(reqs) >= 110                                # the 2026-06-10 census found 112
    assert "CT-01" in reqs and reqs["CT-01"]["pri"] == "P0"
    assert "SN-01" in reqs                                 # the research track family


def test_markers_are_found_and_traced():
    markers = scan_markers(PATHS)
    assert isinstance(markers, dict)
    report = trace("PRD.md", PATHS)
    assert report["total"] >= 110
    assert report["cited"] == len(report["cited_ids"])
    # the seeded markers exist (CT-01 cites its real input-validation tests)
    assert "CT-01" in report["cited_ids"]


def test_v_done_requires_a_citation():
    report = trace("PRD.md", PATHS)
    # the ENFORCED rule: every requirement whose V column is D must be cited by a test
    assert report["v_done_uncited"] == []


def test_full_autonomy_track_is_traced():
    # the §25 release gate: every AS-01..17 row (except AS-16, the cross-method benchmark suite moved to
    # the dissertation acceptance extract) exists in the matrix AND is cited by >=1 test
    # (the ros2_ws scan is what makes AS-02/03/04/05/06 visible)
    report = trace("PRD.md", PATHS)
    as_rows = {f"AS-{n:02d}" for n in range(1, 18) if n != 16}
    in_matrix = as_rows & set(parse_requirements("PRD.md"))
    assert in_matrix == as_rows, f"AS rows missing from matrix: {sorted(as_rows - in_matrix)}"
    uncited = sorted(as_rows - set(report["cited_ids"]))
    assert uncited == [], f"AS rows with no citing test: {uncited}"


# ---- FS-22: the PRD<->code reconciliation gate is code-enforced, not just a manual audit -------------
def test_no_orphan_citations_in_the_real_repo():  # [REQ:FS-22]
    # every [REQ:] marker in the suite must resolve to a real PRD row (a typo / deleted row is a stale
    # citation the gate must catch). The real repo must be clean -> the CI gate stays green.
    report = trace("PRD.md", PATHS)
    assert report["unknown_markers"] == [], f"orphan [REQ:] citations (no such PRD row): {report['unknown_markers']}"


def test_orphan_citation_fails_the_gate(tmp_path):  # [REQ:FS-22]
    # a test that cites a non-existent requirement must FAIL the reconciliation gate (exit 1), so a
    # typo'd or stale [REQ:] marker can never silently pass CI. Isolated against a MINIMAL temp PRD whose
    # one row is V=P (so the V=D-citation rule is vacuous here and only the orphan rule is exercised).
    mini_prd = tmp_path / "mini_prd.md"
    mini_prd.write_text("| ID | P | Requirement | I | X | V | Q |\n|---|---|---|---|---|---|---|\n"
                        "| AB-01 | P1 | a real row, not yet V=D | D | D | P | N |\n")
    # build the orphan token by concatenation so THIS file is never itself scanned as citing it
    orphan = "[REQ:" + "ZZ-99]"
    tree = tmp_path / "t"
    os.makedirs(tree)
    (tree / "test_orphan.py").write_text(f"def test_x():  # {orphan}\n    assert True\n")
    assert main(["--prd", str(mini_prd), "--paths", str(tree)]) == 1     # orphan -> fail
    # the SAME PRD cited by a VALID marker (AB-01 exists, V!=D so no V=D-citation requirement) passes
    valid = "[REQ:" + "AB-01]"
    ok = tmp_path / "ok"
    os.makedirs(ok)
    (ok / "test_ok.py").write_text(f"def test_y():  # {valid}\n    assert True\n")
    assert main(["--prd", str(mini_prd), "--paths", str(ok)]) == 0       # resolves to a real row -> pass


def test_understated_rows_are_surfaced_for_review():  # [REQ:FS-22]
    # the reverse-staleness audit: rows that HAVE a citing test but are not yet V=D are reported (a PRD
    # status that may lag the code). Each surfaced row must genuinely be cited AND have V != D.
    reqs = parse_requirements("PRD.md")
    report = trace("PRD.md", PATHS)
    assert isinstance(report["understated"], list)
    for rid, v in report["understated"]:
        assert rid in report["cited_ids"] and reqs[rid]["V"] == v and v != "D"
