"""[ops] Rebuild the AST-only codebase knowledge graph into graphify-out/graph.json.

Deterministic, no LLM / no Gemini: STRUCTURAL (AST) extraction only, so it runs unattended in CI with
just `pip install graphifyy` and no API key. The weekly workflow (.github/workflows/graphify-rebuild.yml)
runs this, then `graphify export html`, then copies graphify-out/graph.html -> docs/knowledge-graph.html
so the hosted Pages graph stays fresh. Run locally the same way, or via `/graphify` for the full
(doc-semantic) build when a Gemini key is available.
"""
from __future__ import annotations

from pathlib import Path

from graphify.build import build_from_json
from graphify.cluster import cluster
from graphify.detect import detect
from graphify.export import to_json
from graphify.extract import collect_files, extract

ROOT = Path(".")
OUT = Path("graphify-out")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    det = detect(ROOT)
    code_files: list[Path] = []
    for f in det["files"].get("code", []):
        p = Path(f)
        code_files.extend(collect_files(p) if p.is_dir() else [p])
    if not code_files:
        print("no code files detected -- nothing to graph")
        return 1
    ast = extract(code_files, cache_root=ROOT)
    extraction = {
        "nodes": ast["nodes"], "edges": ast["edges"], "hyperedges": [],
        "input_tokens": 0, "output_tokens": 0,
    }
    G = build_from_json(extraction, root=".", directed=False)
    if G.number_of_nodes() == 0:
        print("ERROR: graph is empty -- extraction produced no nodes")
        return 1
    communities = cluster(G)
    to_json(G, communities, str(OUT / "graph.json"))
    print(f"graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
