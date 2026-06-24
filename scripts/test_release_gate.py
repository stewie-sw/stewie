"""[REQ:AS-15] §25 autonomy-track release-gate acceptance.

The release gate is the capstone trace over AS-01..17. These tests enforce, mechanically, the
NASA-style rule the PRD states in prose: no AS row is cited-and-claimed without test evidence, the
verification tier each row reports is honest, and the genuinely-deferred capabilities stay named
(the gate can never silently mark them complete). The report itself is read-only -- it must not
mutate the review scorecard.
"""
from scripts.release_gate import AS_ROWS, DEFERRED, TIER, release_report
from scripts.req_trace import parse_requirements


def test_every_as_row_is_in_the_matrix_and_cited():
    rep = release_report()
    assert set(rep["rows"]) == set(AS_ROWS)
    assert rep["summary"]["in_matrix"] == len(AS_ROWS)
    assert rep["summary"]["uncited"] == [], f"uncited AS rows: {rep['summary']['uncited']}"
    for r in AS_ROWS:
        assert rep["rows"][r]["citing_tests"], f"{r} has no citing test"


def test_v_done_rows_are_all_cited():
    # the firewall: anything the PRD already marks V=D must be test-cited (none should slip through)
    rep = release_report()
    for r in rep["summary"]["currently_v_done"]:
        assert rep["rows"][r]["cited"], f"{r} is V=D but uncited"


def test_tier_classification_is_complete_and_honest():
    # every AS row has a tier; the container tier is exactly the ROS2-artifact rows
    assert set(TIER) == set(AS_ROWS)
    rep = release_report()
    assert set(rep["summary"]["container_gated"]) == {"AS-02", "AS-03", "AS-04", "AS-05", "AS-06"}
    # the host-verified rows are everything else
    assert set(rep["summary"]["host_verified"]) == set(AS_ROWS) - set(rep["summary"]["container_gated"])
    # V=D eligibility is STRICTER than host-tier: it also needs I=D (verification never leads
    # implementation). Today only AS-17 is I=D, so it is the sole eligible row.
    eligible = set(rep["summary"]["eligible_for_v_done"])
    assert eligible <= set(rep["summary"]["host_verified"])
    for r in eligible:
        assert rep["rows"][r]["I"] == "D", f"{r} eligible for V=D but I != D"
    assert eligible == {"AS-17"}


def test_container_rows_are_not_auto_eligible_for_v_done():
    # X is gated on a real container smoke -> a container row must NOT be reported V=D-eligible on host alone
    rep = release_report()
    for r in rep["summary"]["container_gated"]:
        assert not rep["rows"][r]["eligible_for_v_done"]
        assert "gated" in rep["rows"][r]["recommendation"].lower()


def test_deferred_capabilities_stay_named():
    # the honesty floor: these stay flagged until each is implemented + executed + verified
    rep = release_report()
    for key in ("live_chrono_producer", "apriltag_12p7mm", "dense_mvs_rmse", "space_ros_profile"):
        assert key in rep["deferred"] and rep["deferred"][key]
    assert rep["deferred"] == DEFERRED


def test_report_is_read_only_does_not_promote_the_scorecard():
    # calling the report must not mutate the PRD V columns (it reads, it does not write)
    before = {r: parse_requirements("PRD.md").get(r, {}).get("V") for r in AS_ROWS}
    release_report()
    after = {r: parse_requirements("PRD.md").get(r, {}).get("V") for r in AS_ROWS}
    assert before == after
    # the human call has been made for AS-17 (the sole eligible row, I=D + host-verified): it is now
    # V=D. The firewall invariant still holds -- every promoted row must be both eligible AND cited, and
    # no container-gated row may be V=D. A promotion that violated that would re-red this assertion.
    rep = release_report()["summary"]
    promoted = set(rep["currently_v_done"])
    assert promoted <= set(rep["eligible_for_v_done"]), "a V=D row that is NOT V=D-eligible slipped through"
    assert promoted.isdisjoint(set(rep["container_gated"])), "a container-gated row was promoted to V=D"
    assert "AS-17" in promoted
