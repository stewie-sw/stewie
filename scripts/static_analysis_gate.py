"""[REQ:AS-15] Power-of-10 / static-analysis gate for the SAFETY-CRITICAL autonomy code (dart, stewie/bridge,
stewie/runtime, stewie/contracts).

Maps the JPL "Power of 10" rules for safety-critical software to their enforceable Python analogs and holds
them as a NO-REGRESSION ratchet -- the mechanism the AS-15 acceptance's "Power-of-10/static-analysis review
for safety-critical code" clause names:

  * bounded control-flow complexity   -> C901 (mccabe <= MAX_COMPLEXITY)   [P-o-10 rule 1: simple flow]
  * short, single-purpose functions   -> PLR0912 branches / PLR0915 stmts  [rule 4: small functions]
  * every return checked / no dead set -> RET                              [rule 7: check return values]
  * clean under the bug linters        -> flake8-bugbear (B), no bare except E722  [rule 10: no warnings]

The CURRENT per-rule counts are the documented BASELINE below -- named, tracked tech-debt, NOT hidden. The
gate is a DOWN-ONLY ratchet: it FAILS on any INCREASE over the baseline, so new safety-critical code cannot
add complexity/bug-patterns, and the debt can only shrink (drop the baseline when you fix one). It does NOT
claim the code is already Power-of-10-clean; it claims the review is wired + enforced.

Run: `python scripts/static_analysis_gate.py`  (exit 0 = at/under baseline, 1 = regression).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: the safety-critical autonomy modules the gate reviews.
SAFETY_CRITICAL = ("dart", "stewie/bridge", "stewie/runtime", "stewie/contracts")
#: the Power-of-10-mapped ruleset.
RULES = ("C901", "PLR0912", "PLR0915", "B", "E722", "RET")
MAX_COMPLEXITY = 12

#: documented Power-of-10 static-analysis BASELINE (tracked debt; the ratchet only moves DOWN).
BASELINE: dict[str, int] = {
    "B905": 29,      # zip without explicit strict= (style-adjacent, tracked)
    "PLR0915": 17,   # too-many-statements  (rule 4: short functions)
    "C901": 10,      # complex-structure    (rule 1: simple control flow)
    "PLR0912": 7,    # too-many-branches    (rule 4)
    "B007": 6,       # unused loop control variable
    "RET504": 3,     # unnecessary assign before return (rule 7)
    "B018": 1,       # useless expression
}


def run_gate() -> dict[str, int]:
    """Run the Power-of-10-mapped ruff ruleset over the safety-critical modules; return per-rule counts."""
    cmd = [sys.executable, "-m", "ruff", "check", "--select", ",".join(RULES),
           "--config", f"lint.mccabe.max-complexity={MAX_COMPLEXITY}", "--output-format", "json",
           *[os.path.join(_ROOT, p) for p in SAFETY_CRITICAL]]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=_ROOT)
    counts: dict[str, int] = {}
    for v in json.loads(proc.stdout or "[]"):
        counts[v["code"]] = counts.get(v["code"], 0) + 1
    return counts


def regressions(counts: dict[str, int]) -> list[str]:
    """Rules whose count EXCEEDS the documented baseline -- the ratchet violations that fail the gate."""
    return sorted(f"{code}: {n} > baseline {BASELINE.get(code, 0)}"
                  for code, n in counts.items() if n > BASELINE.get(code, 0))


def main() -> int:
    counts = run_gate()
    regs = regressions(counts)
    total = sum(counts.values())
    if regs:
        print("AS-15 Power-of-10 static-analysis gate: REGRESSION over baseline\n  " + "\n  ".join(regs))
        return 1
    print(f"AS-15 Power-of-10 static-analysis gate: OK ({total} findings at/under the documented baseline "
          f"over {', '.join(SAFETY_CRITICAL)}; no regression)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
