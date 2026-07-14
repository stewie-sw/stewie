"""[REQ:PO-19] The §7 plan is a VALIDATED ATOMIC TASK GRAPH, and the dispatcher obeys its readiness rule.

WHY THIS FILE EXISTS. The §7 matrix is the project's plan, but it was not a graph:

  1. **The dispatcher was dependency-blind.** `fanout_plan.classify()` bucketed rows by GLYPH and FAMILY
     only, so its "parallel lanes" were family prefixes, not predecessors. ATG's readiness rule is the
     opposite -- a node is executable exactly when ALL its predecessors have finished. The consequence was
     not hypothetical: RS-05 and RT-03 both declare `needs RT-00` ("the ROS image carries the stewie python
     stack"), RT-00 is NOT done, and BOTH sat in the buildable ready-set. The fan-out would have sent agents
     to build the Gazebo rehearsal and the live-sensor loop into a container that cannot import `stewie`.
     AD-02/AD-03 likewise sat ready while AD-01 was unbuilt.
  2. **The order was hand-written prose, and it rotted.** The §7.B "Loop pick order" listed 25 rows of which
     18 were already done, and every row added since (RT-06, PX-08..PX-11, GW-13) appeared in NO order at
     all. ATG says the order is DERIVED from the graph; a hand-maintained one drifts from the truth.

THE EDGE SEMANTICS, established from the data rather than assumed. The PRD already had two distinct words
and used them correctly -- RT-03 uses BOTH in one row: "(extends BA-07/RS-05; needs RT-00)".

    needs X / Blocks X / prerequisite for X   ->  a TRUE prerequisite: an ATG edge.
    extends / complements / bounds / reuses   ->  LINEAGE or context: NOT an edge.

Reading `extends` as a dependency would fabricate ~60 edges and falsely accuse seven delivered rows of
standing on unbuilt foundations. The proof it is not an edge: GW-07 is V=D ("Selection + right inspector",
fully tested) while GL-02, which it "extends", is V=N. It shipped without it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atg  # noqa: E402
import fanout_plan as F  # noqa: E402

_PRD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PRD.md")


def test_the_plan_is_a_valid_dag() -> None:
    """[REQ:PO-19] No dangling edges, no cycles, and nothing marked done on an unbuilt prerequisite.

    The third check is the one with teeth: a row that is V=D while something it REQUIRES is not done is
    either mis-wired or was verified against a foundation that does not exist. Both are real defects."""
    violations = atg.validate(atg.build(_PRD))
    assert violations == [], "the §7 plan is not a valid ATG:\n  " + "\n  ".join(violations)


def test_the_dispatcher_never_offers_a_row_whose_prerequisite_is_unbuilt() -> None:
    """[REQ:PO-19] THE READINESS RULE. Every row in the buildable ready-set must have ALL its declared
    prerequisites done. This is the property whose absence would have dispatched RS-05/RT-03 into a ROS
    image that cannot import stewie."""
    graph = atg.build(_PRD)
    p = F.plan(_PRD)
    ready = [r["id"] for lane in p["lanes"].values() for r in lane]
    offenders = {r: atg.blocked_by(graph, r) for r in ready if atg.blocked_by(graph, r)}
    assert offenders == {}, (
        "the fan-out is offering rows whose declared prerequisites are UNBUILT -- an agent dispatched on "
        f"one of these builds on a foundation that does not exist: {offenders}")


def test_blocked_rows_are_reported_with_their_blocker_not_silently_dropped() -> None:
    """[REQ:PO-19] A row held back by ATG readiness must be VISIBLE and must name what blocks it. Silently
    dropping it would hide real work; silently offering it would dispatch it. Neither is acceptable."""
    graph = atg.build(_PRD)
    p = F.plan(_PRD)
    for rid, blockers in p["blocked"].items():
        assert blockers, f"{rid} is blocked but names no blocker"
        assert blockers == atg.blocked_by(graph, rid)
        for b in blockers:
            assert graph[b]["row"]["V"] != "D", f"{rid} is blocked by {b}, which is already done"


def test_every_row_lands_in_exactly_one_bucket() -> None:
    """[REQ:PO-19] The complete-inventory property: done + buildable + gated + blocked + concurrent covers
    every §7 row. A leak here means a row silently fell out of the plan."""
    p = F.plan(_PRD)
    buildable = sum(len(v) for v in p["lanes"].values())
    gated = sum(len(v) for v in p["gated"].values())
    total = p["done"] + buildable + gated + len(p["blocked"]) + len(p["concurrent"])
    assert total == p["total"], (
        f"partition leak: done={p['done']} buildable={buildable} gated={gated} "
        f"blocked={len(p['blocked'])} concurrent={len(p['concurrent'])} != total={p['total']}")


def test_parallel_groups_are_derived_from_the_graph_not_hand_written() -> None:
    """[REQ:PO-19] The order falls out of the DAG. Level 0 is dispatchable NOW in parallel; a row in level
    k>0 must have a prerequisite in an earlier level -- otherwise it belonged in level 0 and the levels are
    not a real topological ordering."""
    graph = atg.build(_PRD)
    lv = atg.levels(graph)
    assert lv, "no levels derived"
    seen: set[str] = set()
    for i, level in enumerate(lv):
        for rid in level:
            unmet = atg.blocked_by(graph, rid)
            if i == 0:
                assert not unmet, f"level-0 row {rid} has unmet prerequisites {unmet}"
            else:
                assert unmet, f"{rid} sits in level {i} but nothing blocks it -- it belongs in level 0"
                assert all(d in seen for d in unmet), (
                    f"{rid} depends on {unmet}, which is not in an earlier level -- not a topological order")
        seen |= set(level)


def test_extends_is_lineage_and_is_not_treated_as_a_dependency() -> None:
    """[REQ:PO-19] Pin the semantics, because getting this wrong silently corrupts the whole plan. `extends`
    must NOT create an edge. The live proof: GW-07 is V=D while GL-02, which it "extends", is V=N -- if
    `extends` were an edge, GW-07 would be a BUILT-ON-UNBUILT violation, and ~60 such phantom edges would
    reorder the entire plan around dependencies that do not exist."""
    graph = atg.build(_PRD)
    assert graph["GW-07"]["row"]["V"] == "D"
    assert graph["GL-02"]["row"]["V"] != "D"
    assert "GL-02" not in graph["GW-07"]["requires"], (
        "`extends` is being read as a dependency edge. It is lineage, not a prerequisite: GW-07 shipped "
        "fully tested while GL-02 is still unbuilt.")
    # ...while the PRD's real prerequisite vocabulary IS an edge, in both directions:
    assert "RT-00" in graph["RT-03"]["requires"], "'needs RT-00' must be an edge (RT-03 declares it)"
    assert "RT-00" in graph["RS-05"]["requires"], "'Blocks RS-05' must be an edge (RT-00 declares it)"
    assert "PX-06" in graph["PO-18"]["requires"], "'prerequisite for PO-18' must be an edge"
