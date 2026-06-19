#!/usr/bin/env python3
"""Write the reproducible G1/G2 validation reports.

Two dated baselines are regenerated from their generators so a re-freeze (deliberately changed
fixtures) refreshes BOTH in one command and neither goes stale:
  * g1_g2_validation_2026-06-07.json = validate()          -- the conservative NOT_PASSED baseline the
                                                              byte-identity invariant reproduces (indent=2)
  * g1_g2_validation_2026-06-10.json = validate_current()  -- the live G1/G2 PASS evaluation (indent=1)

(The 2026-06-10 artifact previously had no generator, so the 0.05 re-freeze left its displayed
evidence numbers 0.07-stale -- #197. It is now regenerated alongside the frozen baseline.)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from stewie.eval.gates import ROOT, validate, validate_current

DEFAULT_OUTPUT = ROOT / "validation" / "g1_g2_validation_2026-06-07.json"
CURRENT_OUTPUT = ROOT / "validation" / "g1_g2_validation_2026-06-10.json"   # indent=1, preserved format


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-release-gates", action="store_true")
    args = parser.parse_args()
    result = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    # Also refresh the live PASS evaluation baseline so a re-freeze updates both dated artifacts.
    # Gated to the default frozen-baseline path so a custom --output stays side-effect-free.
    if args.output == DEFAULT_OUTPUT:
        CURRENT_OUTPUT.write_text(json.dumps(validate_current(), indent=1) + "\n")
    print(json.dumps(result["release_gate_summary"], indent=2))
    summary = result["release_gate_summary"]
    if args.require_release_gates and (summary["G1"] != "PASSED" or summary["G2"] != "PASSED"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
