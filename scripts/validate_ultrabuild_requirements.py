"""Validate UltraBuild requirement ownership and test-citation traceability."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = ROOT / "SYSTEM_REQUIREMENTS.md"
MANIFEST_PATH = ROOT / "GRAPH_MANIFEST.yaml"

ROW = re.compile(
    r"^\|\s*([A-Z]{3}-\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$"
)
MARKER = re.compile(r"\[REQ:([A-Z]{3}-\d{2})\]")

OWNER_BY_PREFIX = {
    "SEM": "WS-010",
    "TMP": "WS-020",
    "PRV": "WS-030",
    "UNC": "WS-050",
    "REC": "WS-040",
    "PHY": "PHY-010",
    "SPA": "WS-010",
    "EVT": "WS-030",
    "SYN": "VERT-030",
    "AUT": "VERT-020",
    "SAF": "INT-010",
    "OBS": "INT-010",
    "EXP": "EXP-010",
    "PER": "PERF-010",
    "GEN": "EXP-020",
}


def parse_requirements() -> dict[str, dict[str, str]]:
    requirements: dict[str, dict[str, str]] = {}
    for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if match is None or match.group(1) == "ID":
            continue
        requirement_id = match.group(1)
        if requirement_id in requirements:
            raise ValueError(f"duplicate requirement ID {requirement_id}")
        requirements[requirement_id] = {
            "requirement": match.group(2),
            "level": match.group(3),
            "baseline": match.group(4),
            "verification": match.group(5),
            "owner": OWNER_BY_PREFIX.get(requirement_id[:3], ""),
        }
    if len(requirements) != 51:
        raise ValueError(f"expected 51 UltraBuild requirements, found {len(requirements)}")
    return requirements


def scan_test_markers() -> dict[str, list[str]]:
    markers: dict[str, list[str]] = defaultdict(list)
    for path in sorted(ROOT.rglob("test_*.py")):
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in MARKER.finditer(line):
                markers[match.group(1)].append(f"{path.relative_to(ROOT)}:{line_number}")
    return dict(markers)


def validate_requirements() -> dict[str, Any]:
    requirements = parse_requirements()
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    node_ids = {node["id"] for node in manifest["nodes"]}
    markers = scan_test_markers()

    for requirement_id, requirement in requirements.items():
        if not requirement["requirement"]:
            raise ValueError(f"{requirement_id}: missing normative text")
        if requirement["level"] not in {"MUST", "SHOULD", "MAY", "MUST for generality"}:
            raise ValueError(f"{requirement_id}: invalid level {requirement['level']}")
        if not requirement["verification"]:
            raise ValueError(f"{requirement_id}: missing verification contract")
        if requirement["owner"] not in node_ids:
            raise ValueError(f"{requirement_id}: missing/unknown owning graph node")

    unknown_markers = sorted(set(markers) - set(requirements))
    if unknown_markers:
        raise ValueError(f"unknown UltraBuild requirement markers: {unknown_markers}")

    cited = sorted(set(requirements) & set(markers))
    uncited = sorted(set(requirements) - set(markers))
    return {
        "total": len(requirements),
        "cited": len(cited),
        "cited_ids": cited,
        "uncited_ids": uncited,
        "owners": {requirement_id: value["owner"] for requirement_id, value in requirements.items()},
        "markers": markers,
    }


def main() -> int:
    result = validate_requirements()
    print(
        f"UltraBuild requirements: {result['total']} · test-cited: {result['cited']} · "
        f"not yet test-cited: {len(result['uncited_ids'])}"
    )
    if result["uncited_ids"]:
        print("Pending implementation evidence: " + ", ".join(result["uncited_ids"]))
    print("Requirement IDs, verification text, prefix owners, and citations are structurally valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
