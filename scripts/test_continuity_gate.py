"""[REQ:MT-05] the continuity-governance report emits the four maintainability metrics (tracked-payload
size, large-file diff, HTML-sink count, CI test-tier status) and reds on a new large tracked binary. The
metrics are real (measured from the tree/frontend/CI), not defaults. ADRs + a generated-artifact manifest
are the remaining governance follow-ons."""
from scripts import check_tracked_artifacts as ARTIFACTS
from scripts import continuity_gate as GATE


def test_report_carries_all_four_continuity_metrics():
    r = GATE.continuity_report()
    for k in ("tracked_payload_mb", "oversized_count", "html_sink_count", "test_tiers"):
        assert k in r
    assert r["tracked_payload_mb"] > 0
    assert r["oversized_count"] >= 1                      # the known DEM fixtures
    assert r["html_sink_count"] >= 1                      # the frontend has real DOM-write sinks
    assert set(r["test_tiers"]) >= {"lint-type-cov", "test-js", "ui-smoke"}   # the pinned tiers (PO-04)


def test_clean_tree_passes_no_large_file_violations():
    assert GATE.continuity_report()["large_file_violations"] == []
    assert GATE.main() == 0


def test_gate_reds_on_a_new_large_binary(monkeypatch):
    # emptying MT-01's allowlist makes the real oversized DEMs violations -> the continuity gate reds.
    monkeypatch.setattr(ARTIFACTS, "ALLOWLIST", ())
    r = GATE.continuity_report()
    assert r["large_file_violations"], "the gate must surface unlisted large binaries"
    assert GATE.main() == 1


def test_html_sink_count_matches_a_direct_scan():
    # the reported sink count is a real measurement of the served frontend, not a constant.
    assert GATE.html_sink_count() == GATE.continuity_report()["html_sink_count"]
    assert GATE.html_sink_count() > 10                    # the cockpit legitimately uses many DOM writes
