#!/usr/bin/env python3
"""[REQ:PO-19] The §7 plan as an ATOMIC TASK GRAPH: typed dependency edges, a validated DAG, an
ATG-correct ready-set, and DERIVED parallel groups.

WHY THIS EXISTS. The §7 matrix is the project's plan, but until now it was not a graph:

  * **No dependency edges existed at all.** The ~60 `(extends X)` tags in the row prose are a LINEAGE
    tag, not a prerequisite -- verified on the real data: GW-07 is V=D ("Selection + right inspector")
    while GL-02, which it "extends", is V=N. GW-07 shipped fully tested without it. Reading `extends` as
    a dependency would FABRICATE edges and falsely accuse seven delivered rows of standing on unbuilt
    foundations. So `extends` stays what it is (context), and this module introduces the ONE typed edge.
  * **The dispatcher was dependency-blind.** `fanout_plan.classify()` buckets rows by GLYPH and FAMILY
    only, so its "parallel lanes" are family prefixes, not predecessors. It could dispatch a row whose
    prerequisite was unbuilt. ATG's readiness rule is the opposite: a node is executable exactly when
    ALL its predecessors have finished.
  * **The order was hand-written prose and rotted.** The §7.B "Loop pick order" listed 25 rows of which
    18 were already done, and rows added since (RT-06, PX-08..PX-11, GW-13) appeared in NO order at all.
    ATG says the order is DERIVED from the graph, never hand-maintained.

THE EDGE. A row declares a true prerequisite in its own text:

    (requires: GW-00, RT-00)

meaning "this row genuinely needs those rows' OUTPUT" -- the ATG definition. Draw an edge ONLY for that.
An absent `requires:` means "no declared prerequisite", which is honest: it is the absence of a claim, not
a claim of independence. Coverage is reported so the gap stays visible instead of being assumed away.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from req_trace import parse_requirements  # noqa: E402

_PRD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PRD.md")

#: THE EDGE VOCABULARY -- deliberately the PRD's OWN, not a new syntax nobody uses. The matrix already
#: distinguishes a prerequisite from lineage; it was simply never machine-readable. RT-03 proves it in a
#: single row: "(extends BA-07/RS-05; needs RT-00)" -- `extends` is lineage, `needs` is a real edge. And
#: RT-00 states the reverse: "Blocks RS-05, RT-03."
#:
#:   needs X            -> this row requires X            (forward edge)
#:   Blocks X, Y        -> X and Y require this row       (reverse edge)
#:   prerequisite for X -> X requires this row            (reverse edge)
#:   (requires: X, Y)   -> canonical form for new rows    (forward edge)
#:
#: EXPLICITLY NOT EDGES: extends / complements / bounds / reuses / wires / formalizes. Those are LINEAGE.
#: Verified on real data: GW-07 is V=D ("Selection + right inspector") while GL-02, which it "extends", is
#: V=N -- GW-07 shipped fully tested without it. Reading `extends` as a dependency would fabricate ~60
#: edges and falsely accuse seven delivered rows of standing on unbuilt foundations.
_FORWARD = (
    re.compile(r"\(requires:\s*([^)]*)\)", re.I),          # canonical
    re.compile(r"\bneeds\s+((?:[A-Z]{2}-\d{2}[,/ ]*)+)", re.I),
)
_REVERSE = (
    re.compile(r"\bBlocks\s+((?:[A-Z]{2}-\d{2}[,/ ]*)+)", re.I),
    re.compile(r"prerequisite for\s+((?:[A-Z]{2}-\d{2}[,/ ]*)+)", re.I),
)
_ID = re.compile(r"\b([A-Z]{2}-\d{2})\b")

#: A row is DONE (its output exists) exactly when it is verified.
def _done(row: dict) -> bool:
    return row.get("V") == "D"


#: A backticked span is a QUOTATION, not a declaration. Without this, a row that DOCUMENTS the edge
#: vocabulary (PO-19 does exactly that: "RS-05 and RT-03 both declare `needs RT-00`") would be parsed as
#: DECLARING those edges, inventing phantom dependencies from the row that merely explains the syntax.
#: Every real edge in the matrix is written as plain prose ("needs RT-00", "Blocks RS-05, RT-03"), so
#: stripping code spans keeps every true edge and drops every quoted example. (Caught by the PO-19 gate
#: itself the moment the documenting row was added -- the graph is self-referential and must survive it.)
_CODE_SPAN = re.compile(r"`[^`]*`")


def build(prd_path: str = _PRD) -> dict:
    """Parse the §7 matrix into an ATG: {id: {row, requires:set}}. Harvests both directions of the PRD's
    own vocabulary, so a dependency counts whether the row declares it ("needs X") or the prerequisite
    declares it ("Blocks X" / "prerequisite for X"). Quoted examples inside `code spans` are ignored."""
    reqs = parse_requirements(prd_path)
    graph: dict[str, dict] = {rid: {"row": row, "requires": set()} for rid, row in reqs.items()}
    for rid, row in reqs.items():
        text = _CODE_SPAN.sub(" ", row["text"])          # quotations are not declarations
        for pat in _FORWARD:
            for m in pat.finditer(text):
                graph[rid]["requires"] |= set(_ID.findall(m.group(1)))
        for pat in _REVERSE:                    # "this row blocks X" => X requires this row
            for m in pat.finditer(text):
                for x in _ID.findall(m.group(1)):
                    if x in graph:
                        graph[x]["requires"].add(rid)
    for rid in graph:
        graph[rid]["requires"].discard(rid)     # a row cannot require itself
    return graph


def validate(graph: dict) -> list[str]:
    """ATG dependency-validation + consistency. Returns a list of human-readable violations (empty = OK).

    Three checks, each of which corresponds to an ATG failure the plan could otherwise hide:
      * DANGLING   -- an edge points at a row that does not exist (the graph is not closed).
      * CYCLE      -- the plan is not a DAG, so no topological order exists and nothing is ever ready.
      * BUILT-ON-UNBUILT -- a row is V=D while a row it REQUIRES is not. Either the dependency is wrong
        or the row was verified on a foundation that does not exist; both are real defects.
    """
    errs: list[str] = []

    for rid, node in sorted(graph.items()):
        for d in sorted(node["requires"]):
            if d not in graph:
                errs.append(f"DANGLING: {rid} requires {d}, which is not a §7 row")

    # cycle detection (DFS colouring)
    color: dict[str, int] = {}

    def dfs(u: str, stack: list[str]) -> list[str] | None:
        color[u] = 1
        stack.append(u)
        for v in sorted(graph.get(u, {}).get("requires", ())):
            if v not in graph:
                continue
            if color.get(v) == 1:
                return stack[stack.index(v):] + [v]
            if color.get(v, 0) == 0:
                c = dfs(v, stack)
                if c:
                    return c
        color[u] = 2
        stack.pop()
        return None

    for n in sorted(graph):
        if color.get(n, 0) == 0:
            cyc = dfs(n, [])
            if cyc:
                errs.append("CYCLE: " + " -> ".join(cyc))
                break

    for rid, node in sorted(graph.items()):
        if not _done(node["row"]):
            continue
        for d in sorted(node["requires"]):
            if d in graph and not _done(graph[d]["row"]):
                errs.append(
                    f"BUILT-ON-UNBUILT: {rid} is V=D but requires {d} (V={graph[d]['row']['V']}) -- "
                    "either the dependency is wrong or the row was verified on a foundation that does "
                    "not exist")
    return errs


def blocked_by(graph: dict, rid: str) -> list[str]:
    """The UNMET prerequisites of a row -- ATG readiness: ready iff this is empty."""
    return sorted(d for d in graph[rid]["requires"] if d in graph and not _done(graph[d]["row"]))


def levels(graph: dict, ids: list[str] | None = None) -> list[list[str]]:
    """DERIVED parallel groups: topological levels over the given rows (default: everything not done).

    Level 0 = rows with no unmet prerequisite (dispatchable NOW, in parallel). Level k = rows whose
    prerequisites all live in levels < k. This REPLACES the hand-written pick order: ATG says the order
    falls out of the graph, and a hand-maintained order rots (the §7.B one was 72% stale).
    """
    pool = [r for r in (ids if ids is not None else graph) if not _done(graph[r]["row"])]
    placed: set[str] = set()
    out: list[list[str]] = []
    remaining = set(pool)
    while remaining:
        # a row is ready when every prerequisite is either DONE already or placed in an earlier level
        lvl = sorted(
            r for r in remaining
            if all(d not in graph or _done(graph[d]["row"]) or d in placed
                   for d in graph[r]["requires"]))
        if not lvl:                      # only possible under a cycle, which validate() already reports
            out.append(sorted(remaining))
            break
        out.append(lvl)
        placed |= set(lvl)
        remaining -= set(lvl)
    return out


def coverage(graph: dict) -> dict:
    """How much of the plan actually DECLARES its dependencies. An absent edge is the absence of a claim,
    not a claim of independence -- so keep the gap visible rather than assuming the graph is complete."""
    open_rows = [r for r, n in graph.items() if not _done(n["row"])]
    with_deps = [r for r in open_rows if graph[r]["requires"]]
    return {"rows": len(graph), "open": len(open_rows), "open_with_declared_deps": len(with_deps),
            "edges": sum(len(n["requires"]) for n in graph.values())}


def main() -> int:
    g = build()
    errs = validate(g)
    cov = coverage(g)
    print(f"ATG: {cov['rows']} rows · {cov['edges']} declared edges · "
          f"{cov['open_with_declared_deps']}/{cov['open']} open rows declare a prerequisite")
    lv = levels(g)
    print(f"derived parallel groups: {len(lv)} level(s); level-0 (dispatchable now) = {len(lv[0]) if lv else 0} rows")
    if errs:
        print("\nVIOLATIONS:")
        for e in errs:
            print("  " + e)
        return 1
    print("DAG valid: no dangling edges, no cycles, nothing built on an unbuilt prerequisite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
