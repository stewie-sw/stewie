"""[REQ:AS-15] the Power-of-10 / static-analysis review gate for the safety-critical autonomy code is wired
and enforced: it runs the Power-of-10-mapped ruleset (bounded complexity, short functions, checked returns,
bug-linter cleanliness) over dart/bridge/runtime/contracts and holds a DOWN-ONLY ratchet against a documented
baseline -- new safety-critical code cannot add complexity/bug-patterns. This is the AS-15 acceptance clause
'Power-of-10/static-analysis review for safety-critical code' the release-gate traceability half did not cover."""
from scripts.static_analysis_gate import (
    BASELINE,
    RULES,
    SAFETY_CRITICAL,
    regressions,
    run_gate,
)


def test_power_of_10_gate_reviews_the_safety_critical_code_with_no_regression():  # [REQ:AS-15]
    # the gate actually reviews the safety-critical autonomy modules with the Power-of-10-mapped ruleset.
    assert {"dart", "stewie/bridge", "stewie/runtime", "stewie/contracts"} <= set(SAFETY_CRITICAL)
    assert {"C901", "PLR0912", "PLR0915", "RET"} <= set(RULES)   # complexity + short-fn + checked-return analogs
    counts = run_gate()
    # NON-VACUOUS: the gate genuinely ran ruff over real code (it finds the documented baseline debt).
    assert sum(counts.values()) > 0
    # the safety-critical code stays at/under the documented Power-of-10 baseline -- the ratchet holds.
    assert regressions(counts) == [], f"Power-of-10 static-analysis regression: {regressions(counts)}"


def test_the_ratchet_is_real_a_seeded_increase_regresses():  # [REQ:AS-15]
    # tamper trial: bump one rule's count above baseline in a copy -> the ratchet MUST flag it (proves the
    # gate is not a rubber stamp -- a real regression fails).
    counts = dict(run_gate())
    worst = next(iter(BASELINE))
    counts[worst] = BASELINE[worst] + 1
    assert regressions(counts), "the ratchet did not catch a seeded over-baseline increase"
