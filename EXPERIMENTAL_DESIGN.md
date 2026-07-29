# Experimental design

**Artifact ID:** `ART-EXPERIMENT-DESIGN`
**Producer node:** `EXP-010`
**Consumers:** `WS-040`, `WS-050`, `PHY-010`, `VERT-010`, `EXP-020`, `EXP-030`, `PERF-010`,
`DISS-010`
**Status:** preregistration draft; comparative runs are prohibited until Barrier-1 approval.

## Experimental unit and repeated measures

The independent experimental unit is a `terrain_action_pair`: one non-overlapping terrain window and
one action geometry generated without using any candidate output. System, mechanism cell, fault
level, observation realization, and seed are repeated measures within that unit. Cells, observations,
and reruns are never counted as independent units. Rerunning identical input is replay evidence, not
a new trial.

The evaluation design uses 24 units formed from eight disjoint Haworth windows crossed with three
registered action geometries. Eight evaluation seeds are repeated within each unit. Four disjoint
terrain/action units and seeds `1001..1008` are reserved for calibration only; evaluation uses seeds
`3001..3008`. Calibration outputs cannot enter confirmatory estimates. These values become frozen
only when the content-addressed scenario manifests and pilot report are committed and independently
accepted.

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
| B-VERSION | Immutable integer versions without valid/transaction-time semantics | Version-only history baseline |
| B-REPLACE | Full map replacement, no history | Historical-retention baseline |
| B-BITEMP | Same immutable inputs in a valid/transaction-time event store with unconditional valid-latest promotion | Credible temporal-storage comparator |
| B-NOPROV | Provenance-free confidence fusion | Provenance-gating baseline |
| B-PROV | W3C-PROV-equivalent lineage retained but not used for admission | Separates lineage storage from gating |
| B-SINGLE | One centralized authoritative map with overwrite conflict policy | Conflict-preservation baseline |
| B-CRDT | Content-addressed convergent replicated event set plus deterministic LWW projection | Convergence baseline |
| B-CENTRAL | Centralized metadata/payload synchronization | Distributed-sync baseline |
| B-LOCAL | Robot-local mapping without shared reconciliation | Shared-state baseline |
| B-LIFELONG | Change-aware multi-session map adapter with historical output where supported | Changing-map baseline |
| B-MRMAP | Shared multi-robot map adapter without STEWIE promotion | Multi-robot mapping baseline |
| B-IVF | Inverse-variance fusion with physics pseudo-measurement | Honest physics-using comparator |
| B-CI | Covariance intersection with declared weight policy | Unknown-correlation comparator |
| A-NOPHYS | Proposed observation aggregate without physics | Physics ablation |
| A-INDEP | Proposed rule treating sources independent | Dependency ablation |
| A-GLOBAL | Global overlap scalar dependency | Graph-structure ablation |
| A-NOUNC | Proposed rule with uncertainty replaced by fixed threshold | Uncertainty ablation |
| A-NOPROVGATE | Complete lineage recorded but provenance admission disabled | Provenance-gating ablation |
| P-STEWIE | Full candidate mechanism for the tested slice | Proposed system |

External systems may be added only through the same evidence/result interface. They receive identical
terrain, evidence, times, masks, frames, seeds, and compute accounting.

## Experiment series

### E1 — temporal correctness

Permute delay, order, clock offset, and retroactive correction. Compare B-LWW, B-TS, B-VERSION,
B-REPLACE, B-BITEMP, and P-STEWIE. The primary empirical endpoint is stale-overwrite rate at the
frozen promotion threshold. Exact valid-time/transaction-time oracle agreement is a pass/fail
conformance result for B-BITEMP and P-STEWIE and is reported separately from the effect estimate.

### E2 — model bias × sensor fault

Run the existing two-condition design over the registered bounded grid of physical-model mismatch and
sensor offset. Compare B-LWW, B-IVF, B-CI, A-NOPHYS, and P-STEWIE. The primary endpoint is the maximum
harmful-acceptance rate over required grid cells at the fixed threshold. Availability must remain
within the frozen non-inferiority margin. Report the complete harm/abstention frontier and
accepted-state error as secondary results.

### E3 — dependency and coverage

Cross robot count, action-overlap graph, partial coverage, and missing/fabricated action-log rates.
Compare B-CI, A-INDEP, A-GLOBAL, A-NOUNC, and P-STEWIE. The primary endpoint is
harmful-acceptance rate at the frozen threshold, blocked by terrain/action unit; availability is a
mandatory non-inferiority result. The evaluator dependency graph is generated independently from
candidate-visible action reports.

### E4 — provenance/conflict

Inject duplicate identities, relabelled duplicates, calibration invalidation, frame conflicts, and
delayed contradictory claims. Compare B-NOPROV, B-PROV, B-SINGLE, A-NOPROVGATE, and P-STEWIE. The
primary endpoint is incorrect-overwrite rate. Automated explanation-edge precision/recall, hypothesis
retention, replay, and correction latency are mandatory secondary results.

### E5 — downstream decision effect

Run the same construction/route/verification decisions over state produced by each system. The
primary endpoint is harmful-plan-commitment rate under the withheld evaluator oracle. Rescan count,
completion error, rework, resource use, and regret are secondary. A plan without an exact revision and
query lens is counted as harmful, not excluded.

### E6 — scaling

Vary region cells, observations, robots, dependency edges, versions, payload size, and partition
duration. Report latency distributions, throughput, memory, storage, and bandwidth against
`PERFORMANCE_BUDGET.json`.

### E7 — provenance × dependency interaction

Run the `P0D0`, `P1D0`, `P0D1`, and `P1D1` cells over duplicate/relabel rates crossed with
action-overlap density. `P` enables source-identity provenance admission; `D` enables pairwise
action-derived dependency components. The confirmatory estimand is the paired
difference-in-differences in harmful-acceptance rate. Availability is a mandatory co-endpoint. No
four-way synergy or novelty claim is inferred from this experiment.

## Endpoint hierarchy and frozen decision rules

| Family | Primary endpoint | Direction | Frozen minimum effect | Mandatory guard |
|---|---|---|---|---|
| E1/H1 | stale-overwrite rate | lower | 0.10 absolute paired reduction | exact two-time oracle agreement |
| E2/H3 | worst-grid-cell harmful-acceptance rate | lower | 0.10 absolute paired reduction | availability no more than 0.10 lower |
| E3/H2 | harmful-acceptance rate | lower | 0.10 absolute paired reduction | availability no more than 0.10 lower |
| E4/H4 | incorrect-overwrite rate | lower | 0.10 absolute paired reduction | decision replay rate at least 0.99 |
| E5/H5 | harmful-plan-commitment rate | lower | 0.10 absolute paired reduction | identical planner and information inputs |
| E7/H7 | normalized provenance × dependency interaction | higher | 0.05 absolute | availability no more than 0.10 lower in any cell |

The minimum effects are operational assumptions for the controlled research artifact, not sourced
mission-safety thresholds. Calibration must show that 24 independent units can resolve the stated
effect under a paired design; otherwise the design is revised before freeze or the hypothesis remains
underpowered and unsupported. Secondary endpoints cannot rescue a failed primary endpoint.

## Ablations

One mechanism is removed at a time: transaction time, valid time, provenance gating, physics veto,
dependency graph, competing hypotheses, uncertainty propagation, multi-resolution representation,
VOI, distributed synchronization, and historical reconstruction. E7 additionally identifies the one
claimed provenance-by-dependency interaction. An ablation is included only in an experiment where the
mechanism participates; a nonfunctional stripped system is not a valid control.

## Perturbation grid

The frozen run manifest will enumerate levels for localization drift, observation noise,
miscalibration, illumination, image dropout, wheel slip, delay, bandwidth, partition duration, robot
count, region/version count, terrain-change magnitude, observation overlap, conflict density, clock
error, model mismatch, reconstruction error, action-log recall/precision, and source duplication.

Pilot runs may determine feasible ranges and paired-unit variance but may not contribute comparative
results. Pilot scenarios use disjoint windows, unit IDs, and seeds. Final levels, seeds, tolerances,
minimum effects, sample size, exclusions, and stopping rules are frozen before the first comparative
run.

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
- Bootstrap and permutation resampling operate at the `terrain_action_pair` level; per-cell and
  per-seed rows remain nested repeated measures.

## Exclusions and stopping

The only pre-execution exclusions are: source bundle fails checksum/schema validation, registered
terrain crop is unreadable, or required evaluator reference is unavailable before any candidate is
run. Post-run crashes, timeouts, numerical failures, abstentions, missing outputs, and invalid
candidate records remain outcomes and count against the relevant metric. Every family uses a fixed
trial count; there is no efficacy, futility, or result-dependent stopping. Infrastructure-wide
failure may pause execution, but completed trials remain registered and the restart is recorded.

## Human evaluation boundary

No central hypothesis depends on subjective review. If diagnosis time is reported, a separate
exploratory protocol uses at least three reviewers who did not implement the injected fault,
randomized and blinded system labels, identical fault packets, a frozen answer key, median time to
the first correct causal source, accuracy, inter-rater agreement, and all timeouts. Without that
protocol, only automated explanation-edge fidelity and correction latency are reported.

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
