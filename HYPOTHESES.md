# Hypotheses and falsification criteria

**Artifact ID:** `ART-HYPOTHESES`
**Producer node:** `RES-030`
**Consumers:** `EXP-010`, `WS-040`, `WS-050`, `DISS-010`
**Status:** preregistration draft; numerical thresholds must be frozen before comparative runs.

## H1 — bitemporal correctness and valid-time-aware promotion

For delayed and out-of-order observations:

1. STEWIE and a credible bitemporal/event-sourced comparator will deterministically reproduce the
   reference claim set for both `(valid_at, known_at)` dimensions; and
2. STEWIE's valid-time-aware promotion policy will have a lower stale-overwrite rate than
   latest-write, timestamp-only, version-only, and unconditional-promotion bitemporal comparators.

The first part is a conformance claim, not a novelty claim. H1 is falsified if STEWIE misses any
registered historical-query oracle, if the credible bitemporal comparator is intentionally weakened,
or if the paired stale-overwrite improvement fails to exceed the frozen minimum effect at comparable
input availability.

## H2 — dependency-aware support

When robot actions create possible dependencies between evidence sources, pairwise per-cell
dependency components will reduce harmful acceptance at the fixed registered threshold relative to
independence and global-scalar ablations without exceeding the registered abstention
non-inferiority margin.

Falsified if the paired harmful-acceptance improvement does not exceed the frozen minimum effect, if
its interval includes no improvement, if the result fails on the registered partial-coverage strata,
or if the availability margin is exceeded.

## H3 — observation-only physics veto

Across the registered bounded joint sensor-fault and model-mismatch conditions, an observation-only
promotion rule with contestable physics veto will have lower worst-condition harmful acceptance than
both:

1. a rule that ignores physics; and
2. a rule that fuses physical predictions into accepted values.

Falsified if either baseline matches or improves the frozen harm/availability criterion, if the
availability non-inferiority margin is exceeded, if arbitrary perturbations to physics-predicted
values change candidate or promoted state bytes while the physics decision class is fixed, or if the
result depends on evaluation-reference leakage.

## H4 — provenance-gated reconciliation

Complete queryable provenance and explicit conflict retention will reduce the incorrect-overwrite
rate under delayed, duplicated, or contradictory observations relative to provenance-free single-map
fusion. Automated explanation-edge fidelity, decision replay, and correction latency are mandatory
secondary results; human diagnosis time is exploratory unless its separate protocol is executed.

Falsified if lineage cannot reproduce the decision, if unresolved conflicts are routinely dropped,
or if overwrite/correction metrics do not improve at comparable evidence availability.

## H5 — downstream decision value

Using reconciled, version-identified state will reduce the registered harmful-plan-commitment rate
relative to planning over latest-write state.

Falsified if the paired primary-endpoint improvement does not exceed the frozen minimum effect, if
the proposed method receives information unavailable to a comparator, or if an apparent gain exists
only in a secondary endpoint such as rework or rescan count.

## H6 — bounded operational cost

For the preregistered Barrier-3 and Barrier-5 workloads, reconciliation and historical queries will
remain inside `PERFORMANCE_BUDGET.json` and show no worse than the declared growth class over the
tested scale range.

Falsified if a mandatory budget is exceeded, results cannot be reproduced within the stated resource
envelope, or empirical growth exceeds the declared class without a revised and independently
reviewed architecture.

## H7 — provenance × dependency interaction

In the registered duplicate-identity-by-action-overlap factorial, enabling source-identity provenance
gating will increase the benefit of pairwise dependency reasoning relative to either mechanism alone.
The confirmatory estimand is the difference-in-differences in harmful-acceptance rate:

`(P1D1 - P1D0) - (P0D1 - P0D0)`,

with signs normalized so a positive value favors the hypothesized interaction.

Falsified if the interaction estimate does not exceed the frozen minimum effect, its interval includes
no interaction, the availability margin is exceeded in any required cell, or the dependency oracle
is derived from the same action-report faults that are being evaluated.

## Statistical guardrails

- Freeze terrain crops, seeds, perturbation levels, harm tolerances, minimum effect sizes, and
  multiplicity treatment before comparative execution.
- Report effect sizes and uncertainty intervals, not p-values alone.
- Report harmful acceptance with abstention and accepted-state error.
- A component test can support a mechanism invariant but cannot validate H1–H7 by itself.
- Negative or null results remain part of the evidence package.
