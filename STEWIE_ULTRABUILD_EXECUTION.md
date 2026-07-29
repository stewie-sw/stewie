# STEWIE UltraBuild execution contract

**Artifact ID:** `ART-EXECUTION`
**Source:** normalized from the user-supplied “Graph-Engineered Autonomous World-State System for
Self-Modifying Environments” prompt on 2026-07-28.
**Baseline:** `d1056d9deff4e540557b13c8cb78fc799330410e`
**Producer node:** `ORCH-001`
**Consumers:** every node in `GRAPH_MANIFEST.yaml`
**Status:** binding execution contract; it is not a claim of implementation or validation.

This file makes the task-thread prompt self-contained in the repository. It removes repetition and
subjective “keep going until perfect” language, but preserves the prompt’s requirements, scientific
boundaries, review topology, barriers, and deliverables.

## Mission

Build and evaluate the smallest coherent research artifact that can provide reproducible,
adversarially reviewed evidence for persistent world-state management when autonomous agents
physically change the environment they observe.

The primary validation domain is lunar surface construction. The representation and reconciliation
mechanisms must not depend on lunar-only semantics and must be evaluable in at least one second
domain before a generality claim is made.

STEWIE must keep planned, predicted, simulated, observed, reconciled, verified, authoritative, and
archived state distinct. It must retain history and provenance, represent uncertainty and unresolved
conflict, reject silent stale overwrites, and treat physics as contestable evidence rather than
ground truth.

No artifact may describe STEWIE as flight-certified, mission-ready, production-certified, or safe
for unsupervised physical deployment without separate evidence supporting that exact claim.

## Research contribution boundary

The platform is an experimental vehicle, not itself the contribution. The candidate contribution is
the combination of:

1. action-derived possible-dependency graphs for asynchronous terrain observations;
2. an observation-only accepted state, so a physical model may veto but cannot write accepted values;
3. explicit valid-time and transaction-time semantics;
4. queryable provenance and immutable/superseded history;
5. preservation of disagreement until evidence justifies promotion; and
6. evaluation that reports safety and availability together.

The following are established fields, not novelty claims: SLAM, occupancy/elevation maps, spatial
databases, event sourcing, bitemporal databases, provenance ontologies, CRDTs, scene graphs, change
detection, digital twins, and physics simulation. Any novelty claim must state what the proposed
mechanism adds beyond those foundations and must survive the novelty review node.

## Graph-engineering rules

- Work is represented as bounded nodes with typed inputs and outputs.
- Every artifact has one producer and at least one independent reviewer.
- Independent nodes may run concurrently; dependent nodes wait at named fan-in barriers.
- A subsystem cannot certify its own correctness.
- Every mutation, result, review decision, and rework edge has recorded provenance.
- “Runs successfully” is engineering evidence, not scientific validation.
- Failed experiments create targeted rework edges; they are not hidden or relabelled as success.
- Default rework limits are three local implementation cycles, two integration cycles, two
  experimental-design cycles, and one release-candidate cycle.
- Two consecutive revisions without material metric improvement require escalation or termination.

## Node lifecycle

`UNPLANNED → SPECIFIED → READY → ACTIVE → SELF_TEST → INDEPENDENT_REVIEW → REWORK → ACCEPTED →
INTEGRATED → REGRESSION_VERIFIED → EXPERIMENTALLY_VALIDATED`

States may be skipped only when they are inapplicable and the manifest records why. “Completed” is not
a lifecycle state. Advancement requires the node’s declared artifacts and acceptance evidence.

## Required initial artifacts

The initial research and architecture barrier consists of:

- `PROJECT_CHARTER.md`
- `DISSERTATION_ALIGNMENT.md`
- `PROBLEM_DEFINITION.md`
- `SYSTEM_REQUIREMENTS.md`
- `RESEARCH_QUESTIONS.md`
- `HYPOTHESES.md`
- `SYSTEM_ARCHITECTURE.md`
- `GRAPH_MANIFEST.yaml`
- `DATA_MODEL.md`
- `WORLD_STATE_ONTOLOGY.md`
- `PROVENANCE_MODEL.md`
- `TEMPORAL_MODEL.md`
- `EXPERIMENTAL_DESIGN.md`
- `QUALITY_RUBRIC.md`
- `PERFORMANCE_BUDGET.json`
- `EVALUATION_METRICS.md`
- `RISK_REGISTER.md`
- `TASK_LEDGER.md`
- `ASSUMPTION_REGISTER.md`
- `KNOWN_LIMITATIONS.md`
- `REPRODUCIBILITY_PLAN.md`
- `DATA_AND_ASSET_PROVENANCE.md`

Each artifact identifies its producer and graph consumers. `GRAPH_MANIFEST.yaml` is the
machine-readable registry.

## Required workstreams

The graph must cover independent ownership for research direction and novelty, experimental method,
systems architecture, graph/contracts, world-state representation, bitemporality, event sourcing,
reconciliation, provenance, uncertainty, sensor/perception/localization/reconstruction/change
detection, terrain physics, physics-gated reconciliation, counterfactual simulation, simulation and
digital-twin synchronization, mission/navigation/construction/multi-robot/VOI planning, spatial and
temporal storage, synchronization/catalog, operator/scientific visualization, testing, fault
injection, observability, and safety containment.

These roles may be combined only where independence is not compromised. Implementation and review
roles for the same artifact may not be combined.

## Fan-in barriers

1. **Research definition:** problem, RQs, hypotheses, novelty boundary, falsification criteria,
   baselines, and metrics are independently approved.
2. **Architecture and contracts:** architecture, ontology, temporal/provenance models, graph,
   schemas, coordinate/time/unit conventions, and failure semantics are approved.
3. **Minimal persistent world-state slice:** ingest terrain, record an observation, apply a physical
   change, create a version, query the prior version, trace provenance, and detect a discrepancy.
4. **Single-robot closed loop:** `PLAN → SIMULATE → EXECUTE → OBSERVE → UPDATE → VERIFY → REPLAN`.
5. **Multi-robot reconciliation:** delayed local maps preserve conflict and either converge with
   evidence or expose unresolved disagreement.
6. **Physics as evidence:** a physical constraint changes at least one decision; no-physics and
   physics-fusion baselines plus ablations and failure cases are reported.
7. **Experimental validation:** baselines, ablations, perturbations, statistics, negative results,
   reproducible runs, and threats to validity are complete.
8. **Dissertation evidence lock:** every conclusion claim maps to a frozen artifact and replication
   command; unsupported claims are removed.

## Evaluation contract

Every central result reports:

- geometric/state accuracy;
- temporal and historical-query correctness;
- reconciliation errors, unresolved conflicts, and time to convergence;
- provenance completeness and replayability;
- downstream decision effects;
- latency, throughput, memory, storage, bandwidth, and scaling;
- uncertainty intervals and threats to validity; and
- both harmful-acceptance and abstention/availability rates.

Minimum internal baselines are latest-write/last-write overwrite, timestamp ordering, full map
replacement, provenance-free fusion, one authoritative shared map, no-physics reconciliation,
no-uncertainty reconciliation, centralized synchronization, and local-only mapping. External
baselines must be task-normalized and must not be intentionally weakened.

Required ablations remove bitemporality, provenance gating, physics gating, competing hypotheses,
uncertainty propagation, multi-resolution state, value-of-information reasoning, distributed
synchronization, and historical reconstruction where those mechanisms participate in the tested
claim.

Perturbations vary localization drift, sensing noise, illumination, image loss, wheel slip,
observation delay, bandwidth/partition duration, robot count, map/version count, change magnitude,
observation overlap, conflict density, clock error, model mismatch, and reconstruction error.

## Integration invariants

- Coordinate frames and units are explicit at every boundary.
- Valid time and transaction time are never inferred from one timestamp.
- State kind and authority are explicit; visualization is never authoritative.
- Observations identify robot, sensor, pipeline, calibration, and map/frame version.
- Planned and simulated state are never presented as physical truth.
- Accepted versions are immutable or explicitly superseded.
- Uncertainty and provenance are not discarded at interfaces.
- A decision records the exact map/world version it consumed.
- Terrain mutation invalidates affected derived layers.
- Delayed and conflicting evidence are integration-test cases, not edge-case deferrals.

## Ordered start

1. Inventory the merged repository, documentation, assets, tests, and compute environment.
2. Freeze the problem, semantics, hypotheses, baselines, metrics, risks, and graph contracts.
3. Run independent research, world-state, and platform reviews.
4. Pass Barriers 1 and 2 before adding substantial implementation.
5. Build only the Barrier-3 vertical slice next.

The objective is not the largest codebase or the most polished simulator. It is the least system
that can falsifiably support a genuine Computer Science contribution.
