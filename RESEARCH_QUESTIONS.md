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

Does an explicit valid-time/transaction-time model prevent stale overwrites and enable correct
reconstruction of past belief more reliably than latest-state, timestamp-only, or version-only
storage?

Primary metrics: stale-overwrite rate, valid-time query correctness, transaction-time query
correctness, historical reconstruction error, and revision-trace completeness.

## RQ2 — action-derived evidence dependency

Under multi-robot terrain modification, does representing possible source dependencies as per-cell
pairwise action-derived graph edges reduce harmful acceptance relative to treating observations as
independent, using a global overlap scalar, or using provenance-free fusion?

Primary metrics: harmful-acceptance and abstention curves, confidence calibration, false merge rate,
and retained-support error under overlap, missing action records, and partial coverage.

## RQ3 — contestable physics

Can an observation-only accepted state with physics used only as veto evidence remain robust to both
sensor faults and arbitrary physical-model bias more effectively than rules that ignore physics or
fuse physical predictions into accepted values?

Primary metrics: harmful-acceptance and abstention curves under sensor offset and model bias,
accepted-state error, false rejection, and time to correction.

## RQ4 — provenance and conflict preservation

Does provenance-gated admission with explicit competing hypotheses improve reconciliation
auditability and correction under delayed, duplicated, frame-inconsistent, or contradictory evidence
relative to single-map overwrite?

Primary metrics: lineage completeness, incorrect overwrite rate, unresolved-conflict precision,
hypothesis-retention quality, explanation fidelity, and replay success.

## RQ5 — decision effect

Do improvements in state promotion and historical semantics produce measurably better autonomous
choices, rather than only better map metrics?

Primary metrics: unsafe or infeasible plans, plans using stale state, unnecessary rescans,
construction error/rework, completion rate, and decision regret relative to withheld evaluation
reference.

## RQ6 — cost and scaling

What latency, storage, memory, and synchronization costs are introduced as region size, robot count,
evidence density, conflict density, and version count grow, and where does the mechanism cease to be
operationally useful?

Primary metrics: p50/p95/p99 update and query latency, throughput, storage growth, peak memory,
bandwidth, and convergence time.

RQ1–RQ3 define the minimum defensible dissertation core. RQ4–RQ6 are required for the full systems
claim but must not delay the first Barrier-3 slice.
