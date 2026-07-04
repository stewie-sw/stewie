"""[REQ:MT-05] the continuity-governance release gate emits the four maintainability metrics (tracked-payload
size, large-file diff, HTML-sink count, CI test-tier status), REDS on a new large tracked binary OR a new
unlisted HTML sink over baseline, and asserts the governance set is checked in: the ADR-per-boundary set
(docs/adr/) + the generated-artifact manifest (every declared generator on disk). Metrics are real
(measured from the tree/frontend/CI), never defaults."""
import os

from scripts import check_tracked_artifacts as ARTIFACTS
from scripts import continuity_gate as GATE


def test_report_carries_all_four_continuity_metrics_plus_governance_status():
    r = GATE.continuity_report()
    for k in ("tracked_payload_mb", "oversized_count", "html_sink_count", "test_tiers",
              "adr_count", "manifest_missing_generators"):
        assert k in r
    assert r["tracked_payload_mb"] > 0
    assert r["oversized_count"] >= 1                      # the known DEM fixtures
    assert r["html_sink_count"] >= 1                      # the frontend has real DOM-write sinks
    assert set(r["test_tiers"]) >= {"lint-type-cov", "test-js", "ui-smoke"}   # the pinned tiers (PO-04)


def test_clean_tree_passes_no_violations():
    r = GATE.continuity_report()
    assert r["large_file_violations"] == []
    assert r["new_html_sinks"] == 0                       # the frontend is at/under the sink baseline
    assert r["manifest_missing_generators"] == []
    assert GATE.main() == 0


def test_gate_reds_on_a_new_large_binary(monkeypatch):
    # emptying MT-01's allowlist makes the real oversized DEMs violations -> the continuity gate reds.
    monkeypatch.setattr(ARTIFACTS, "ALLOWLIST", ())
    assert GATE.continuity_report()["large_file_violations"], "the gate must surface unlisted large binaries"
    assert GATE.main() == 1


def test_gate_reds_on_a_new_unlisted_html_sink(monkeypatch):
    # a sink count above the ratchet baseline is a new unlisted injection surface -> red.
    monkeypatch.setattr(GATE, "html_sink_count", lambda: GATE._SINK_BASELINE + 1)
    assert GATE.continuity_report()["new_html_sinks"] == 1
    assert GATE.main() == 1


def test_html_sink_count_matches_a_direct_scan_and_is_at_baseline():
    assert GATE.html_sink_count() == GATE.continuity_report()["html_sink_count"]
    assert GATE.html_sink_count() > 10                    # the cockpit legitimately uses many DOM writes
    assert GATE.html_sink_count() <= GATE._SINK_BASELINE  # the ratchet baseline is not already violated


def test_adr_set_present_one_record_per_boundary():
    adrs = GATE.adr_ids()
    assert len(adrs) >= 5, "an ADR per subsystem boundary (DART/LODE/LEAP/FORGE/stewie) must be checked in"
    # the README index references every ADR file (no orphan / missing record)
    with open(os.path.join(GATE._ADR_DIR, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    for a in adrs:
        assert a in readme, f"ADR {a} is not indexed in docs/adr/README.md"


def test_artifact_manifest_present_and_every_generator_exists():
    assert os.path.exists(GATE._MANIFEST), "the generated-artifact manifest must be checked in"
    assert GATE.manifest_missing_generators() == [], "every regenerable artifact must name a generator on disk"
