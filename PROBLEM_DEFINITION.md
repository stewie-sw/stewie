# Problem definition

**Artifact ID:** `ART-PROBLEM`
**Producer node:** `RES-010`
**Consumers:** `RES-020`, `RES-030`, `ARCH-010`, `WS-010`, `EXP-010`
**Status:** specified; pending Barrier-1 review.

## Problem

An autonomous construction system maintains spatial claims while its own actions change the physical
state those claims describe. Observations arrive from different robots and pipelines with partial
coverage, uncertain frames, delayed delivery, and possible shared failure causes. A last-write or
timestamp rule can therefore replace a newer physical state with stale evidence, count correlated
readings as independent corroboration, or incorporate a biased physical prediction into accepted
terrain.

The research problem is to decide, for each spatial claim, whether to:

- promote a new accepted state;
- reject inadmissible evidence;
- abstain pending more evidence; or
- preserve multiple live hypotheses;

while retaining enough time and provenance information to reconstruct what the system believed and
why a past decision used that belief.

## Formal object

A state claim is:

`C = (claim_id, region, representation, value, state_kind, valid_interval, transaction_interval,
frame, units, uncertainty, provenance_graph, predecessor, status)`

where:

- `valid_interval` is when the condition is asserted to hold in the physical environment;
- `transaction_interval` is when STEWIE stored that assertion as current knowledge;
- `state_kind` distinguishes planned, predicted, simulated, observed, proposed, reconciled, verified,
  authoritative, superseded, and archived state;
- `provenance_graph` links source observations, sensors, agents, transforms, algorithms,
  calibrations, actions, reviewers, and derived artifacts; and
- `status` permits unresolved competing claims over the same region and valid time.

An acceptance procedure receives a prior accepted state `S`, observations `O`, physical predictions
`P`, action history `A`, and policy `G`:

`decision, candidate, evidence = reconcile(S, O, P, A, G)`

For the candidate mechanism, `candidate` is a function of admissible observations only. `P` may
change the decision but may not supply values, weights, missing-cell fills, or a source subset.

## Primary outcome

For a task-declared harm tolerance `tau`, the primary safety outcome is the harmful-acceptance rate:

`Pr(decision = PROMOTE and error(candidate, withheld_reference) > tau)`.

It must always be paired with abstention rate and accepted-state error. A mechanism that achieves zero
harm by never accepting state has failed operationally, even if its safety number appears perfect.

## Required query semantics

The system must eventually answer:

- What did robot A believe at valid time `T`, as recorded by transaction time `K`?
- What does the system now believe was valid at `T`?
- When was a modification first observed, verified, superseded, and archived?
- Which evidence and transformations produced a claim?
- Which state version informed a plan or action?
- Which past decisions depended on a claim now known to be superseded?
- Which regions retain unresolved hypotheses, and what measurement could distinguish them?

## Failure classes

1. stale or out-of-order evidence;
2. partial and non-overlapping coverage;
3. localization/frame disagreement;
4. sensor fault or miscalibrated uncertainty;
5. correlated or duplicated evidence;
6. missing, incomplete, or fabricated action history;
7. physics-model bias or unavailable physics;
8. planned/simulated/observed state conflation;
9. communication partition and replica divergence;
10. history/provenance loss or non-auditable mutation;
11. threshold choices that trade hidden availability loss for safety; and
12. downstream planning over the wrong or unidentified world version.

## Scope and boundaries

The first representation is a bounded 2.5-D elevation patch with masks and scalar-per-source height
uncertainty because that is what the current promotion mechanism supports. 3-D meshes, voxels,
semantic objects, per-cell covariance, distributed storage, and live robots remain downstream
extensions. They may not be claimed as part of the validated contribution until evaluated.

The withheld simulated/conserved state is evaluation reference only. It is structurally unavailable
to the system under test. Simulation is not physical ground truth, and success on injected faults is
not evidence of deployment safety.

## Existing implementation gap

The repository has the component mechanisms, but `docs/BENCHMARK_SPEC.md` explicitly states that the
integrated two-domain multi-robot benchmark is incomplete and that live `POST /twin/resync` bypasses
the theorem-facing promotion rule. Valid-time filtering exists, while true transaction-time
semantics and bitemporal queries do not. Closing those seams is the minimal research build, not a
wholesale platform rewrite.
