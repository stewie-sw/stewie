"""[REQ:AS-15] §25 autonomy-track release-gate acceptance.

The release gate is the capstone trace over AS-01..17. These tests enforce, mechanically, the
NASA-style rule the PRD states in prose: no AS row is cited-and-claimed without test evidence, the
verification tier each row reports is honest, and the genuinely-deferred capabilities stay named
(the gate can never silently mark them complete). The report itself is read-only -- it must not
mutate the review scorecard.
"""
from scripts.release_gate import (
    AS04_TIERS,
    AS_ROWS,
    CONTAINER_EVIDENCE_VERIFIED,
    CONTAINER_TIER_GAPS,
    DEFERRED,
    DETECTION_CAPABILITY_GAPS,
    TIER,
    release_report,
)
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
    # V=D eligibility is STRICTER than tier: it also needs I=D (verification never leads
    # implementation). Container rows become eligible only after recorded container evidence exists.
    eligible = set(rep["summary"]["eligible_for_v_done"])
    for r in eligible:
        assert rep["rows"][r]["I"] == "D", f"{r} eligible for V=D but I != D"
    assert eligible == {"AS-02", "AS-03", "AS-05", "AS-06", "AS-17"}


def test_container_rows_are_not_auto_eligible_for_v_done():
    # X is gated on a real container smoke -> a container row must not be reported V=D-eligible on host alone.
    # The fully promoted rows below have current deploy/ros2/evidence records.
    rep = release_report()
    for r in rep["summary"]["container_gated"]:
        if r in CONTAINER_EVIDENCE_VERIFIED:
            assert rep["rows"][r]["eligible_for_v_done"]
            assert "recorded container evidence" in rep["rows"][r]["recommendation"].lower()
        else:
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
    # the human call has been made for AS-02, AS-03, AS-05, AS-06, and AS-17. The firewall invariant still holds:
    # every promoted row must be both eligible AND cited; container rows need recorded container evidence.
    rep = release_report()["summary"]
    promoted = set(rep["currently_v_done"])
    assert promoted <= set(rep["eligible_for_v_done"]), "a V=D row that is NOT V=D-eligible slipped through"
    assert (promoted & set(rep["container_gated"])) <= CONTAINER_EVIDENCE_VERIFIED
    assert {"AS-02", "AS-03", "AS-05", "AS-06", "AS-17"} <= promoted


def test_gated_container_tiers_and_detection_capabilities():
    # The FANOUT expansion: document, mechanically, that the deferred set the gate carries is
    # partitioned into the *3 deferred container tiers* and the *2 deferred detection capabilities*
    # the PRD names -- and that the gate can never silently promote either category to complete.
    rep = release_report()
    cats = rep["deferred_categories"]

    # AS-04 tier accounting is honest: 6 named tiers, exactly 3 shipped, exactly 3 deferred (the
    # PRD's own "3 of the 6 named tiers ship" claim -- asserted against the tier ledger, not prose).
    shipped = {t for t, built in AS04_TIERS.items() if built}
    deferred_tiers = {t for t, built in AS04_TIERS.items() if not built}
    assert len(AS04_TIERS) == 6
    assert shipped == {"base", "rviz", "gazebo"}
    assert deferred_tiers == {"perception_slam", "bridge_runtime", "space_ros"}, deferred_tiers
    assert len(deferred_tiers) == 3, "the '3 deferred container tiers' must stay named"

    # The container-tier gaps map to the 3 deferred AS-04 tiers (space_ros_profile alone, plus the
    # combined perception+bridge key), and the detection-capability gaps to the 2 perception outputs.
    assert set(cats["container_tier_gaps"]) == set(CONTAINER_TIER_GAPS) == {
        "space_ros_profile", "perception_bridge_tiers",
    }
    assert set(cats["detection_capability_gaps"]) == set(DETECTION_CAPABILITY_GAPS) == {
        "apriltag_12p7mm", "dense_mvs_rmse",
    }, "the '2 deferred detection capabilities' must stay named"

    # The two named categories plus the standalone host-side stub (live Chrono producer) partition
    # DEFERRED exactly -- every deferred key is accounted for, none double-counted, none orphaned.
    categorised = set(CONTAINER_TIER_GAPS) | set(DETECTION_CAPABILITY_GAPS) | {"live_chrono_producer"}
    assert categorised == set(DEFERRED), categorised ^ set(DEFERRED)
    assert not (set(CONTAINER_TIER_GAPS) & set(DETECTION_CAPABILITY_GAPS)), "categories must not overlap"

    # Neither category may silently empty: emptying one is exactly "the gate marked those gaps done".
    assert cats["container_tier_gaps"], "container-tier gaps went empty without recorded evidence"
    assert cats["detection_capability_gaps"], "detection-capability gaps went empty without recorded evidence"

    # And each categorised key carries a live, non-empty rationale (it stays *documented* as gated).
    for key in set(CONTAINER_TIER_GAPS) | set(DETECTION_CAPABILITY_GAPS):
        assert rep["deferred"][key], f"{key} lost its deferral rationale"
