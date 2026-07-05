#!/usr/bin/env python3
"""[REQ:LY-01] Generate the layer catalog registry (stewie/server/layer_catalog.json) from the SINGLE SOURCE OF
TRUTH — the PRD2 explicit layer catalog table (design/STEWIE_PRD2_gis_mission_workbench_2026-07-04.md). Each of
the ~65 named layers (`base.*`…`evidence.*`) declares type / purpose / source_class / planning-eligibility /
release-execute-eligibility. This is CONFIG (like bodies.json), not synthetic data — the backend serves it and
`test_ly01_layer_catalog.py` asserts the committed JSON is in sync with the table (regen-when-drift)."""
import json
import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_DOC = os.path.join(_ROOT, "design", "STEWIE_PRD2_gis_mission_workbench_2026-07-04.md")
_OUT = os.path.join(_ROOT, "stewie", "server", "layer_catalog.json")


def parse_catalog(doc_path: str = _DOC) -> list[dict]:
    """Parse the PRD2 catalog markdown table into typed layer records."""
    layers: list[dict] = []
    in_table = False
    with open(doc_path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("| Layer ID |"):
                in_table = True
                continue
            if not in_table:
                continue
            if re.match(r"^\|\s*`", line):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                lid, ltype, purpose, source_class, planning, rel_exec = cells[:6]
                layers.append({
                    "id": lid.strip("`"),
                    "domain": lid.strip("`").split(".", 1)[0],
                    "type": ltype,
                    "purpose": purpose,
                    "source_class": source_class,
                    "planning_eligible": planning.lower().startswith("yes"),
                    "planning_note": planning,
                    "release_execute_eligible": rel_exec.lower().startswith("yes"),
                    "release_execute_note": rel_exec,
                })
            elif not line.strip().startswith("|"):
                break
    return layers


def build() -> dict:
    layers = parse_catalog()
    return {"schema_version": "1.0", "source": "PRD2 explicit layer catalog", "count": len(layers),
            "domains": sorted({ly["domain"] for ly in layers}), "layers": layers}


def main() -> None:
    catalog = build()
    with open(_OUT, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {_OUT}: {catalog['count']} layers across {len(catalog['domains'])} domains "
          f"({', '.join(catalog['domains'])})")


if __name__ == "__main__":
    main()
