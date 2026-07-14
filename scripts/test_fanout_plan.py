"""The fan-out planner derives a clean partition of the §7 rows so an orchestrator can dispatch parallel
agents onto the buildable ready-set without colliding with the concurrent lane or picking gated work."""
from __future__ import annotations

import fanout_plan as F  # noqa: E402  (scripts/ sibling import; pytest prepend mode)


def test_every_not_done_row_lands_in_exactly_one_bucket():
    p = F.plan()
    buildable = {r["id"] for lane in p["lanes"].values() for r in lane}
    gated = {i for ids in p["gated"].values() for i in ids}
    concurrent = set(p["concurrent"])
    # [REQ:PO-19] BLOCKED is a fifth bucket: a not-done, not-gated row whose DECLARED prerequisites are
    # unfinished. Under the ATG readiness rule it is not dispatchable (RS-05/RT-03 `needs RT-00`, which is
    # unbuilt), so it must not sit in `buildable` -- but it is still a §7 row, so the partition must count
    # it or this gate goes red. It stays VISIBLE (naming its blocker) rather than being silently dropped.
    blocked = set(p["blocked"])
    # no row appears in two buckets
    assert buildable.isdisjoint(gated) and buildable.isdisjoint(concurrent) and gated.isdisjoint(concurrent)
    assert blocked.isdisjoint(buildable) and blocked.isdisjoint(gated) and blocked.isdisjoint(concurrent)
    # the five buckets account for every §7 row
    assert p["done"] + len(buildable) + len(gated) + len(blocked) + len(concurrent) == p["total"], (
        f"partition leak: done={p['done']} buildable={len(buildable)} gated={len(gated)} "
        f"blocked={len(blocked)} concurrent={len(concurrent)} != total={p['total']}")


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


def test_fanout_specs_briefs_are_real_requirement_rows():
    # every dispatch brief in FANOUT_SPECS.md must name a real §7 requirement ID (no orphan briefs).
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    specs_path = os.path.join(root, "FANOUT_SPECS.md")
    if not os.path.exists(specs_path):
        return  # doc optional; the plan generator stands alone
    spec_ids = set(re.findall(r"^### ([A-Z]{2}-\d{2})", open(specs_path, encoding="utf-8").read(), re.M))
    real_ids = {r["id"] for r in F.parse_rows()}
    orphans = spec_ids - real_ids
    assert not orphans, f"FANOUT_SPECS.md briefs reference non-existent §7 rows: {sorted(orphans)}"
    assert len(spec_ids) >= 40, "FANOUT_SPECS.md lost most of its briefs -- regen the normalization pass"


def test_known_gated_rows_are_routed_to_a_reason():
    p = F.plan()
    by_id = {i: reason for reason, ids in p["gated"].items() for i in ids}
    # the PM depth-source rows are prose-gated (not Q=G) -> the curated map must catch them
    for rid in ("PM-13", "PM-14", "PM-15", "PM-16"):
        assert by_id.get(rid) == "GPU/live depth-source pipeline"
    # the PyChrono-oracle rows too
    assert by_id.get("CP-07") == "PyChrono calibration oracle"
