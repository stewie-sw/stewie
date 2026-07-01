"""The fan-out planner derives a clean partition of the §7 rows so an orchestrator can dispatch parallel
agents onto the buildable ready-set without colliding with the concurrent lane or picking gated work."""
from __future__ import annotations

import fanout_plan as F  # noqa: E402  (scripts/ sibling import; pytest prepend mode)


def test_every_not_done_row_lands_in_exactly_one_bucket():
    p = F.plan()
    buildable = {r["id"] for lane in p["lanes"].values() for r in lane}
    gated = {i for ids in p["gated"].values() for i in ids}
    concurrent = set(p["concurrent"])
    # no row appears in two buckets
    assert buildable.isdisjoint(gated) and buildable.isdisjoint(concurrent) and gated.isdisjoint(concurrent)
    # the four buckets account for every §7 row
    assert p["done"] + len(buildable) + len(gated) + len(concurrent) == p["total"]


def test_ready_set_is_non_empty_and_excludes_the_concurrent_lane():
    p = F.plan()
    buildable_fams = set(p["lanes"])
    assert buildable_fams, "no buildable lanes -- the ready-set is empty"
    assert F.CONCURRENT_FAMILIES.isdisjoint(buildable_fams)   # AS/AM never in the ready-set


def test_cockpit_split_is_not_falsely_gated_as_live_pit():
    # regression: a substring classifier flagged FS-24 (cockpit) as "live pit"; the curated classifier must
    # not. FS-24 is buildable (or done), never gated.
    p = F.plan()
    gated = {i for ids in p["gated"].values() for i in ids}
    assert "FS-24" not in gated


def test_known_gated_rows_are_routed_to_a_reason():
    p = F.plan()
    by_id = {i: reason for reason, ids in p["gated"].items() for i in ids}
    # the GPU dense-stereo PM rows are prose-gated (not Q=G) -> the curated map must catch them
    for rid in ("PM-13", "PM-14", "PM-15", "PM-16"):
        assert by_id.get(rid) == "GPU dense stereo"
    # the PyChrono-oracle rows too
    assert by_id.get("CP-07") == "PyChrono calibration oracle"
