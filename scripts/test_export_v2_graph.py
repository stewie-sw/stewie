"""Graphify-v2 export: the 60-entry Phase-1 target taxonomy parses + builds a structurally-valid
extraction (interaction rows as first-class nodes; no dangling/duplicate edges; legacy_current_id
crosswalk). The parser + extraction builder are graphify-free (networkx only enters write_graphify_graph),
so this runs in the plain venv; the graph.json build itself is exercised by running the script."""
from __future__ import annotations

import export_stewie_interaction_graph as EX  # noqa: E402  (scripts/ sibling import; pytest prepend mode)


def test_v2_taxonomy_has_sixty_rows():
    rows = EX.v2_interaction_rows()
    assert len(rows) == 60
    assert all(r["v2 ID"].startswith("INT-") for r in rows)
    assert all("->" in r["Current source -> target"] for r in rows)   # every row is a directed coupling


def test_v2_extraction_is_structurally_valid():
    ext = EX.build_extraction_v2(EX.v2_interaction_rows())
    assert ext["directed"] is True
    node_ids = {n["id"] for n in ext["nodes"]}
    inter = [n for n in ext["nodes"] if n["id"].startswith("interaction_")]
    assert len(inter) == 60                                   # one first-class interaction node per row
    # no dangling: every edge endpoint resolves to a node (the assert graphify's assert_valid enforces)
    for e in ext["edges"]:
        assert e["source"] in node_ids and e["target"] in node_ids
    # no exact-duplicate directed edges
    keyed = {(e["source"], e["target"], e["relation"]) for e in ext["edges"]}
    assert len(keyed) == len(ext["edges"])
    # each row emits exactly two edges (source -> interaction -> target)
    assert len(ext["edges"]) == 2 * 60
    # the crosswalk to the 51-row implementation graph is carried on every interaction node
    assert all("legacy_current_id" in n and "family" in n and "status_class" in n for n in inter)


def test_v2_status_classes_are_recognized():
    ext = EX.build_extraction_v2(EX.v2_interaction_rows())
    classes = {n["status_class"] for n in ext["nodes"] if n["id"].startswith("interaction_")}
    assert classes <= {"complete", "partial", "started", "planned", "sim_only", "external_gated"}
