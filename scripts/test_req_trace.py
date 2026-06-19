"""#NASA-standards: the requirements tracer -- PRD section-7 IDs must trace to tests.

A requirement may only claim V=D if at least one test cites it with a [REQ:<ID>] marker."""
from scripts.req_trace import parse_requirements, scan_markers, trace

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
    # the §25 release gate: every AS-01..17 row exists in the matrix AND is cited by >=1 test
    # (the ros2_ws scan is what makes AS-02/03/04/05/06 visible)
    report = trace("PRD.md", PATHS)
    as_rows = {f"AS-{n:02d}" for n in range(1, 18)}
    in_matrix = as_rows & set(parse_requirements("PRD.md"))
    assert in_matrix == as_rows, f"AS rows missing from matrix: {sorted(as_rows - in_matrix)}"
    uncited = sorted(as_rows - set(report["cited_ids"]))
    assert uncited == [], f"AS rows with no citing test: {uncited}"
