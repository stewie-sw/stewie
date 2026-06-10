#!/usr/bin/env python3
"""Write the reproducible G1/G2 validation report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dissertation.eval.gates import ROOT, validate

DEFAULT_OUTPUT = ROOT / "validation" / "g1_g2_validation_2026-06-07.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-release-gates", action="store_true")
    args = parser.parse_args()
    result = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["release_gate_summary"], indent=2))
    summary = result["release_gate_summary"]
    if args.require_release_gates and (summary["G1"] != "PASSED" or summary["G2"] != "PASSED"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
