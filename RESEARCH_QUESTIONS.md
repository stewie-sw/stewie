# Research questions

**Artifact ID:** `ART-RQ`
**Producer node:** `RES-030`
**Consumers:** `RES-020`, `EXP-010`, `WS-040`, `WS-050`, `DISS-010`
**Status:** proposed; not accepted until Barrier 1.

## Central question

How should an autonomous system promote and retain spatial state when multiple agents both modify and
observe the environment, and the available observations, action histories, and physical models may
each be delayed, incomplete, dependent, or wrong?

## RQ1 — temporal and historical correctness

Which correctness properties are provided by explicit valid-time/transaction-time history, and does
STEWIE's valid-time-aware promotion rule prevent stale overwrites beyond what is obtained by merely
storing the same records in a credible bitemporal/event-sourced store?

Primary empirical endpoint: stale-overwrite rate at the registered promotion threshold. Exact
valid-time and transaction-time query results are structural conformance gates, not novelty metrics.
Latest-state, timestamp-only, version-only, and bitemporal/event-sourced comparators are required.

## RQ2 — action-derived evidence dependency

Under multi-robot terrain modification, does representing possible source dependencies as per-cell
pairwise action-derived graph edges reduce harmful acceptance relative to treating observations as
independent, using a global overlap scalar, or using provenance-free fusion?

Primary metrics: harmful-acceptance and abstention curves, confidence calibration, false merge rate,
and retained-support error under overlap, missing action records, and partial coverage.

## RQ3 — contestable physics

Across a bounded, registered grid of sensor faults and physical-model mismatch, can an
observation-only accepted state with physics used only as contestable veto evidence achieve a better
harm/availability tradeoff than rules that ignore physics or fuse physical predictions into accepted
values? Separately, does the implementation satisfy the structural invariant that arbitrary changes
to physics-predicted values cannot change candidate or promoted state bytes when the physics decision
class is held fixed?

Primary empirical endpoint: worst-condition harmful-acceptance rate at the registered threshold,
subject to the registered availability non-inferiority margin. The byte-level noninterference check
is a structural gate; accepted-state error, false rejection, and time to correction are secondary.

## RQ4 — provenance and conflict preservation

Does provenance-gated admission with explicit competing hypotheses improve reconciliation
auditability and correction under delayed, duplicated, frame-inconsistent, or contradictory evidence
relative to single-map overwrite?

Primary metrics: lineage completeness, incorrect overwrite rate, unresolved-conflict precision,
hypothesis-retention quality, explanation fidelity, and replay success.

## RQ5 — decision effect

Do improvements in state promotion and historical semantics reduce harmful autonomous plan
commitments, rather than only improving map metrics?

Primary endpoint: harmful-plan-commitment rate, where a committed plan either uses a revision that
was already superseded under the plan's recorded `(valid_at, known_at)` lens or violates a registered
simulation constraint under the withheld reference. Rescans, construction error/rework, completion,
resource cost, and oracle regret are secondary and cannot substitute post hoc for the primary.

## RQ6 — cost and scaling

What latency, storage, memory, and synchronization costs are introduced as region size, robot count,
evidence density, conflict density, and version count grow, and where does the mechanism cease to be
operationally useful?

Primary metrics: p50/p95/p99 update and query latency, throughput, storage growth, peak memory,
bandwidth, and convergence time.

## RQ7 — provenance × dependency interaction

When duplicated or relabelled observations overlap action histories, does source-identity provenance
gating materially change the effect of pairwise action-derived dependency reasoning, rather than the
two mechanisms acting as interchangeable filters?

Primary endpoint: the preregistered provenance-by-dependency interaction contrast in
harmful-acceptance rate at the fixed promotion threshold, with availability reported as a mandatory
co-endpoint.

RQ1–RQ3 define the minimum defensible dissertation core. RQ4–RQ7 are required for the full systems
claim but must not delay the first Barrier-3 slice. RQ7 is the only confirmatory interaction claim;
STEWIE does not claim that integration breadth or a four-way mechanism interaction is itself novel.
