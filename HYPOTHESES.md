# Hypotheses and falsification criteria

**Artifact ID:** `ART-HYPOTHESES`
**Producer node:** `RES-030`
**Consumers:** `EXP-010`, `WS-040`, `WS-050`, `DISS-010`
**Status:** preregistration draft; numerical thresholds must be frozen before comparative runs.

## H1 — bitemporal correctness

For delayed and out-of-order observations, explicit valid and transaction times will produce fewer
stale overwrites and more correct historical reconstructions than latest-write, timestamp-only, and
version-only baselines.

Falsified if any tested baseline has an equal or lower stale-overwrite rate and equal or higher query
correctness at comparable storage/latency cost, or if the proposed model cannot deterministically
answer both time dimensions.

## H2 — dependency-aware support

When robot actions create possible dependencies between evidence sources, pairwise per-cell
dependency components will reduce harmful acceptance relative to independence and global-scalar
ablations without an operationally unacceptable increase in abstention.

Falsified if the harmful-acceptance curve does not improve with confidence intervals excluding the
predeclared minimum effect, if the improvement disappears under partial coverage, or if it is
explained entirely by higher abstention.

## H3 — observation-only physics veto

Across the registered joint sensor-fault and model-bias conditions, an observation-only promotion rule
with contestable physics veto will have lower worst-condition harmful acceptance than both:

1. a rule that ignores physics; and
2. a rule that fuses physical predictions into accepted values.

Falsified if either baseline matches or improves the worst-condition harm/availability frontier, if
physics values influence promoted values or fill missing cells, or if the result depends on evaluation
reference leakage.

## H4 — provenance-gated reconciliation

Complete queryable provenance and explicit conflict retention will reduce incorrect overwrites and
shorten diagnosis/correction time under delayed, duplicated, or contradictory observations relative
to provenance-free single-map fusion.

Falsified if lineage cannot reproduce the decision, if unresolved conflicts are routinely dropped,
or if overwrite/correction metrics do not improve at comparable evidence availability.

## H5 — downstream decision value

Using reconciled, version-identified state will reduce stale-state plans, unsafe/infeasible plans, or
construction rework relative to planning over latest-write state.

Falsified if map-level improvement causes no material change in any predeclared decision metric, or
if gains depend on giving the proposed method information unavailable to baselines.

## H6 — bounded operational cost

For the preregistered Barrier-3 and Barrier-5 workloads, reconciliation and historical queries will
remain inside `PERFORMANCE_BUDGET.json` and show no worse than the declared growth class over the
tested scale range.

Falsified if a mandatory budget is exceeded, results cannot be reproduced within the stated resource
envelope, or empirical growth exceeds the declared class without a revised and independently
reviewed architecture.

## Statistical guardrails

- Freeze terrain crops, seeds, perturbation levels, harm tolerances, minimum effect sizes, and
  multiplicity treatment before comparative execution.
- Report effect sizes and uncertainty intervals, not p-values alone.
- Report harmful acceptance with abstention and accepted-state error.
- A component test can support a mechanism invariant but cannot validate H1–H6 by itself.
- Negative or null results remain part of the evidence package.
