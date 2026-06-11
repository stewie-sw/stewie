"""#NASA-standards: the requirements tracer -- PRD section-7 IDs must trace to tests.

A requirement may only claim V=D if at least one test cites it with a [REQ:<ID>] marker."""
from scripts.req_trace import parse_requirements, scan_markers, trace


def test_parses_the_prd_matrix():
    reqs = parse_requirements("PRD.md")
    assert len(reqs) >= 110                                # the 2026-06-10 census found 112
    assert "CT-01" in reqs and reqs["CT-01"]["pri"] == "P0"
    assert "SN-01" in reqs                                 # the research track family


def test_markers_are_found_and_traced():
    markers = scan_markers(["stewie", "dart", "lode", "scripts"])
    assert isinstance(markers, dict)
    report = trace("PRD.md", ["stewie", "dart", "lode", "scripts"])
    assert report["total"] >= 110
    assert report["cited"] == len(report["cited_ids"])
    # the seeded markers exist (CT-01 cites its real input-validation tests)
    assert "CT-01" in report["cited_ids"]


def test_v_done_requires_a_citation():
    report = trace("PRD.md", ["stewie", "dart", "lode", "scripts"])
    # the ENFORCED rule: every requirement whose V column is D must be cited by a test
    assert report["v_done_uncited"] == []
