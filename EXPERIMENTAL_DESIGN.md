# Experimental design

**Artifact ID:** `ART-EXPERIMENT-DESIGN`
**Producer node:** `EXP-010`
**Consumers:** `WS-040`, `WS-050`, `PHY-010`, `VERT-010`, `EXP-020`, `EXP-030`, `PERF-010`,
`DISS-010`
**Status:** preregistration draft; comparative runs are prohibited until Barrier-1 approval.

## Experimental unit

An experimental unit is one content-addressed scenario, evidence sequence, policy configuration, and
seed evaluated by one system under test. Repeated rows must differ in injected noise or scenario
state; rerunning identical input is replay evidence, not a new trial.

## Reference firewall

The reference terrain and executed-action truth are withheld evaluation inputs. System outputs are
frozen before reference access. The existing displacement/poison attestation is retained and extended
to the integrated path: changing only the reference must leave every candidate and decision
bit-identical.

## Domains and scenario sets

### D1 — lunar construction

A fixed crop from the real Haworth LOLA-derived terrain bundle, with controlled conserved cuts,
deposits, and grading. Sensing failures may be injected, but the underlying terrain is not replaced by
a synthetic flat surface.

### D2 — terrestrial earthwork

A publicly licensed terrestrial elevation crop and documented soil parameters. This domain is
required before any cross-domain generality claim, but not before Barrier 3.

### Scenario families

1. nominal excavation and verification;
2. partial/failed execution;
3. stale and out-of-order observations;
4. conflicting robot observations;
5. partial/non-overlapping coverage;
6. localization/frame error;
7. physical-model bias or absence;
8. sensor fault/miscalibration/duplication;
9. incomplete or fabricated action history;
10. communication partition/rejoin; and
11. terrain collapse or unexplained change.

Each scenario declares harm tolerance from the downstream operation and records whether that
tolerance is sourced, calibrated, or an assumption.

## Systems under test

| ID | System | Purpose |
|---|---|---|
| B-LWW | Latest/last-write overwrite | Common overwrite baseline |
| B-TS | Timestamp-only ordering | Tests whether one time axis is sufficient |
| B-REPLACE | Full map replacement, no history | Historical-retention baseline |
| B-NOPROV | Provenance-free confidence fusion | Provenance-gating baseline |
| B-SINGLE | One centralized authoritative map | Conflict-preservation baseline |
| B-IVF | Inverse-variance fusion with physics pseudo-measurement | Honest physics-using comparator |
| B-CI | Covariance intersection with declared weight policy | Unknown-correlation comparator |
| A-NOPHYS | Proposed observation aggregate without physics | Physics ablation |
| A-INDEP | Proposed rule treating sources independent | Dependency ablation |
| A-GLOBAL | Global overlap scalar dependency | Graph-structure ablation |
| P-STEWIE | Full candidate mechanism for the tested slice | Proposed system |

External systems may be added only through the same evidence/result interface. They receive identical
terrain, evidence, times, masks, frames, seeds, and compute accounting.

## Experiment series

### E1 — temporal correctness

Permute delay, order, clock offset, and retroactive correction. Compare B-LWW, B-TS, B-REPLACE, and
P-STEWIE on stale overwrites and bitemporal reference queries.

### E2 — model bias × sensor fault

Run the existing two-condition design over a preregistered grid of physical-model bias and sensor
offset. Compare B-LWW, B-IVF, B-CI, A-NOPHYS, and P-STEWIE. Report the harm/abstention frontier and
accepted-state error.

### E3 — dependency and coverage

Cross robot count, action-overlap graph, partial coverage, and missing/fabricated action-log rates.
Compare A-INDEP, A-GLOBAL, and P-STEWIE. Evaluate support estimation, harmful acceptance, and
availability.

### E4 — provenance/conflict

Inject duplicate identities, relabelled duplicates, calibration invalidation, frame conflicts, and
delayed contradictory claims. Compare B-NOPROV/B-SINGLE with P-STEWIE on overwrites, hypothesis
retention, replay, and diagnosis time.

### E5 — downstream decision effect

Run the same construction/route/verification decisions over state produced by each accepted system.
Measure stale-state plan rate, infeasible/unsafe plan rate, rescan count, completion error, and rework.

### E6 — scaling

Vary region cells, observations, robots, dependency edges, versions, payload size, and partition
duration. Report latency distributions, throughput, memory, storage, and bandwidth against
`PERFORMANCE_BUDGET.json`.

## Ablations

One mechanism is removed at a time: transaction time, valid time, provenance gating, physics veto,
dependency graph, competing hypotheses, uncertainty propagation, multi-resolution representation,
VOI, distributed synchronization, and historical reconstruction. An ablation is included only in an
experiment where the mechanism participates; a nonfunctional stripped system is not a valid control.

## Perturbation grid

The frozen run manifest will enumerate levels for localization drift, observation noise,
miscalibration, illumination, image dropout, wheel slip, delay, bandwidth, partition duration, robot
count, region/version count, terrain-change magnitude, observation overlap, conflict density, clock
error, model mismatch, reconstruction error, action-log recall/precision, and source duplication.

Pilot runs may determine feasible ranges but may not contribute comparative results. Final levels,
seeds, tolerances, and stopping rules are frozen before the first comparative run.

## Randomization and blocking

- Block by terrain crop, operation, and fault level.
- Use common random numbers across systems for paired comparisons.
- Randomize system evaluation order within a block.
- Keep calibration/pilot seeds disjoint from evaluation seeds.
- Record deterministic seeds and library/runtime versions.

## Statistical treatment

- Report paired effect sizes with bootstrap or model-appropriate confidence intervals.
- Use binomial intervals for harmful acceptance/abstention and calibration curves for uncertainty.
- Correct families of planned comparisons; exploratory analyses are labelled.
- Predeclare the minimum operationally relevant effect for each hypothesis.
- Report null and negative results and all excluded trials with reasons.
- Distinguish statistical significance from operational relevance.

## Threat controls

- Reference-displacement test for leakage.
- Mutation tests proving critical gates fail on the defect they target.
- Source/order permutation invariance where semantics are order-independent.
- Independent reviewers for scenario generation and statistical scripts.
- Same hardware/resource caps for comparable systems.
- Both full result data and summary tables retained.

## Barrier mapping

Barrier 3 runs a minimal E1/E2/E3 subset. Barrier 5 completes multi-robot E3/E4. Barrier 6 completes
physics E2 with ablation. Barrier 7 completes all required series, statistics, negative results, and
reproducibility review.
