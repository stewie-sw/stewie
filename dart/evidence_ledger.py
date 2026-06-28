"""Navigation evidence ledger writer."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dart.factors import MeasurementFactor


def navigation_evidence_record(*, run_id: str, factors: list[MeasurementFactor], result: dict[str, Any],
                               notes: str = "") -> dict[str, Any]:
    return {
        "schema_version": "stewie_navigation_evidence/1.0",
        "run_id": str(run_id),
        "factor_types": sorted({f.factor_type for f in factors}),
        "evidence_classes": sorted({f.evidence_class for f in factors}),
        "n_factors": len(factors),
        "factors": [f.to_json() for f in factors],
        "result": result,
        "notes": notes,
    }


def write_navigation_evidence(path: str | Path, *, run_id: str, factors: list[MeasurementFactor],
                              result: dict[str, Any], notes: str = "") -> dict[str, Any]:
    record = navigation_evidence_record(run_id=run_id, factors=factors, result=result, notes=notes)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    tmp.replace(p)
    return record
