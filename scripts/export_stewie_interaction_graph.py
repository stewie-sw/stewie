#!/usr/bin/env python3
"""Export the STEWIE interaction map as Graphify extraction and graph JSON."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "stewie_digital_twin_interaction_map_2026-06-28.md"
OUT_DIR = ROOT / "graphify-out"
EXTRACTION_PATH = OUT_DIR / "stewie_interaction_extraction_2026-06-28.json"
GRAPH_PATH = OUT_DIR / "graph.json"
SOURCE_FILE = DOC.relative_to(ROOT).as_posix()

# v2: the 60-entry Phase-1 target taxonomy (the committee-facing coverage graph) -> a SECOND graph. The
# current 51-row graph.json stays the implementation-status view; graph_v2.json is the target taxonomy
# with legacy_current_id crosswalk. Parsed from the "Phase 1 Interaction Coverage Table" in the v2 doc.
V2_DOC = ROOT / "docs" / "stewie_interaction_layer_phase1_v2_current_2026-06-29.md"
V2_EXTRACTION_PATH = OUT_DIR / "stewie_interaction_extraction_v2.json"
V2_GRAPH_PATH = OUT_DIR / "graph_v2.json"
V2_SOURCE_FILE = V2_DOC.relative_to(ROOT).as_posix()
V2_HEADERS = [
    "v2 ID",
    "Family",
    "Current source -> target",
    "Current variables",
    "Governing model",
    "legacy_current_id",
    "Status",
    "Next build",
]

HEADERS = [
    "ID",
    "Trigger / event",
    "Edge",
    "Coupled variables",
    "Governing model",
    "Effect",
    "Observability / topic",
    "STEWIE realization",
    "Status",
    "Needed next",
]


def _ensure_graphify_importable() -> None:
    try:
        import graphify  # noqa: F401
    except ImportError:
        sys.path.insert(0, "/mnt/projects/graphify")


def _clean_cell(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    return value.strip()


def _split_row(line: str) -> list[str]:
    return [_clean_cell(part) for part in line.strip().strip("|").split("|")]


def _slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "unnamed"


def _status_class(status: str) -> str:
    normalized = status.lower().replace("-", "_").replace(" ", "_")
    if "external" in normalized or "gated" in normalized:
        return "external_gated"
    if "sim_only" in normalized or "render" in normalized:
        return "sim_only"
    if "complete" in normalized:
        return "complete"
    if "partial" in normalized:
        return "partial"
    if "started" in normalized:
        return "started"
    if "planned" in normalized:
        return "planned"
    return normalized or "unknown"


def interaction_rows() -> list[dict[str, str]]:
    text = DOC.read_text(encoding="utf-8")
    lines = text.splitlines()
    rows: list[dict[str, str]] = []
    in_table = False

    for line in lines:
        if line.startswith("| ID | Trigger / event | Edge |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        if re.match(r"^\|\s*-", line):
            continue

        cells = _split_row(line)
        if not cells or not cells[0].startswith("INT-"):
            continue
        if len(cells) != len(HEADERS):
            raise ValueError(f"{cells[0]} has {len(cells)} cells, expected {len(HEADERS)}")
        rows.append(dict(zip(HEADERS, cells, strict=True)))

    if not rows:
        raise ValueError(f"No interaction rows found in {DOC}")
    return rows


def _edge_blocks(edge_text: str) -> tuple[str, str]:
    if "->" not in edge_text:
        raise ValueError(f"Interaction edge lacks direction: {edge_text}")
    source, target = edge_text.split("->", 1)
    return source.strip(), target.strip()


def build_extraction(rows: list[dict[str, str]]) -> dict[str, Any]:
    node_by_label: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node_id(label: str) -> str:
        if label in node_by_label:
            return node_by_label[label]
        new_id = f"state_{_slug(label)}"
        node_by_label[label] = new_id
        nodes.append(
            {
                "id": new_id,
                "label": label,
                "file_type": "document",
                "source_file": SOURCE_FILE,
                "source_location": "State Blocks And Variables",
            }
        )
        return new_id

    for row in rows:
        source_label, target_label = _edge_blocks(row["Edge"])
        status = row["Status"]
        status_class = _status_class(status)
        source_id = node_id(source_label)
        target_id = node_id(target_label)
        interaction_id = row["ID"]
        interaction_node_id = f"interaction_{_slug(interaction_id)}"
        interaction_metadata = {
            "interaction_id": interaction_id,
            "trigger_event": row["Trigger / event"],
            "coupled_variables": row["Coupled variables"],
            "governing_model": row["Governing model"],
            "effect": row["Effect"],
            "observability": row["Observability / topic"],
            "stewie_realization": row["STEWIE realization"],
            "status": status,
            "status_class": status_class,
            "needed_next": row["Needed next"],
            "source_block": source_label,
            "target_block": target_label,
        }
        nodes.append(
            {
                "id": interaction_node_id,
                "label": f"{interaction_id}: {row['Trigger / event']}",
                "file_type": "document",
                "source_file": SOURCE_FILE,
                "source_location": interaction_id,
                **interaction_metadata,
            }
        )
        edges.append(
            {
                "source": source_id,
                "target": interaction_node_id,
                "relation": "starts_interaction",
                "confidence": "EXTRACTED",
                "confidence_score": 1.0,
                "source_file": SOURCE_FILE,
                "source_location": interaction_id,
                "weight": 1.0,
                **interaction_metadata,
            }
        )
        edges.append(
            {
                "source": interaction_node_id,
                "target": target_id,
                "relation": "couples_to",
                "confidence": "EXTRACTED",
                "confidence_score": 1.0,
                "source_file": SOURCE_FILE,
                "source_location": interaction_id,
                "weight": 1.0,
                **interaction_metadata,
            }
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "directed": True,
        "source": SOURCE_FILE,
        "description": (
            "STEWIE-native digital twin interaction graph. Interaction rows are "
            "first-class nodes so Graphify's DiGraph export cannot collapse "
            "parallel state-block couplings."
        ),
    }


def write_graphify_graph(extraction: dict[str, Any], *, out_path: Path = GRAPH_PATH,
                         built_at: str = "manual-stewie-interaction-map-2026-06-28") -> None:
    _ensure_graphify_importable()
    from graphify.build import build_from_json
    from graphify.export import to_json
    from graphify.validate import assert_valid

    assert_valid(extraction)
    graph = build_from_json(extraction, directed=True, root=str(ROOT))
    communities: dict[int, list[str]] = defaultdict(list)

    block_groups = {
        "world": {
            "state_lunarsite",
            "state_ephemeris",
            "state_terrainmesh",
            "state_regolithstate",
            "state_thermalenvironment",
            "state_lightingmodel",
            "state_mutableterrainledger",
            "state_surveyedmonuments",
        },
        "robot": {
            "state_roverpose",
            "state_roverbelief",
            "state_wheeldynamics",
            "state_excavatordrum",
            "state_articulationstate",
            "state_camerarig",
            "state_perceptionstate",
            "state_powerthermalstate",
        },
        "planner": {
            "state_missionplan",
            "state_executivestate",
        },
    }
    group_ids = {"world": 0, "robot": 1, "planner": 2, "interaction": 3, "other": 4}
    labels = {
        0: "Lunar World Model",
        1: "Robot And Perception State",
        2: "Mission Planning And Executive",
        3: "Interaction Rows",
        4: "Other",
    }
    for graph_node in graph.nodes:
        assigned = "interaction" if str(graph_node).startswith("interaction_") else "other"
        for group_name, node_ids in block_groups.items():
            if graph_node in node_ids:
                assigned = group_name
                break
        communities[group_ids[assigned]].append(graph_node)

    to_json(
        graph,
        dict(communities),
        out_path,
        force=True,
        built_at_commit=built_at,
        community_labels=labels,
    )


def v2_interaction_rows() -> list[dict[str, str]]:
    """Parse the 60-row 'Phase 1 Interaction Coverage Table' from the v2 taxonomy doc."""
    lines = V2_DOC.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, str]] = []
    in_table = False
    for line in lines:
        if line.startswith("| v2 ID | Family |"):
            in_table = True
            continue
        if not in_table:
            continue
        if line.startswith("## "):
            break
        if not line.startswith("|") or re.match(r"^\|\s*-", line):
            continue
        cells = _split_row(line)
        if not cells or not cells[0].startswith("INT-"):
            continue
        if len(cells) != len(V2_HEADERS):
            raise ValueError(f"{cells[0]} has {len(cells)} cells, expected {len(V2_HEADERS)}")
        rows.append(dict(zip(V2_HEADERS, cells, strict=True)))
    if not rows:
        raise ValueError(f"No v2 interaction rows found in {V2_DOC}")
    return rows


def build_extraction_v2(rows: list[dict[str, str]]) -> dict[str, Any]:
    """Build the v2 target-taxonomy extraction: same interaction-node-as-first-class shape as the current
    graph (so parallel couplings never collapse), with v2 metadata (family, legacy_current_id, status)."""
    node_by_label: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node_id(label: str) -> str:
        if label in node_by_label:
            return node_by_label[label]
        new_id = f"state_{_slug(label)}"
        node_by_label[label] = new_id
        nodes.append({"id": new_id, "label": label, "file_type": "document",
                      "source_file": V2_SOURCE_FILE, "source_location": "State Block Registry"})
        return new_id

    for row in rows:
        source_label, target_label = _edge_blocks(row["Current source -> target"])
        status = row["Status"]
        meta = {
            "interaction_id": row["v2 ID"],
            "family": row["Family"],
            "coupled_variables": row["Current variables"],
            "governing_model": row["Governing model"],
            "legacy_current_id": row["legacy_current_id"],
            "status": status,
            "status_class": _status_class(status),
            "needed_next": row["Next build"],
            "source_block": source_label,
            "target_block": target_label,
        }
        inode = f"interaction_{_slug(row['v2 ID'])}"
        nodes.append({"id": inode, "label": f"{row['v2 ID']}: {row['Family']}", "file_type": "document",
                      "source_file": V2_SOURCE_FILE, "source_location": row["v2 ID"], **meta})
        sid, tid = node_id(source_label), node_id(target_label)
        for src, dst, rel in ((sid, inode, "starts_interaction"), (inode, tid, "couples_to")):
            edges.append({"source": src, "target": dst, "relation": rel, "confidence": "EXTRACTED",
                          "confidence_score": 1.0, "source_file": V2_SOURCE_FILE,
                          "source_location": row["v2 ID"], "weight": 1.0, **meta})

    return {"nodes": nodes, "edges": edges, "hyperedges": [], "input_tokens": 0, "output_tokens": 0,
            "directed": True, "source": V2_SOURCE_FILE,
            "description": ("STEWIE Phase-1 TARGET interaction taxonomy (60-entry v2). Interaction rows are "
                            "first-class nodes (no parallel-coupling collapse); legacy_current_id crosswalks "
                            "to the 51-row implementation graph.")}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / ".graphify_root").write_text(str(ROOT), encoding="utf-8")
    (OUT_DIR / ".graphify_python").write_text(sys.executable, encoding="utf-8")

    extraction = build_extraction(interaction_rows())
    EXTRACTION_PATH.write_text(json.dumps(extraction, indent=2, ensure_ascii=False), encoding="utf-8")
    write_graphify_graph(extraction)
    print(f"Exported {len(extraction['nodes'])} nodes and {len(extraction['edges'])} directed edges "
          f"to {GRAPH_PATH.relative_to(ROOT)}")

    v2 = build_extraction_v2(v2_interaction_rows())
    V2_EXTRACTION_PATH.write_text(json.dumps(v2, indent=2, ensure_ascii=False), encoding="utf-8")
    write_graphify_graph(v2, out_path=V2_GRAPH_PATH, built_at="manual-stewie-interaction-v2-2026-06-29")
    print(f"Exported v2 {len(v2['nodes'])} nodes and {len(v2['edges'])} directed edges "
          f"to {V2_GRAPH_PATH.relative_to(ROOT)}")
    print(f"Extraction JSON: {EXTRACTION_PATH.relative_to(ROOT)} + {V2_EXTRACTION_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
