# Project charter

**Artifact ID:** `ART-CHARTER`
**Producer node:** `ORCH-001`
**Consumers:** `RES-010`, `ARCH-010`, `EXP-010`, `INT-010`, `DISS-010`
**Baseline:** `d1056d9deff4e540557b13c8cb78fc799330410e`
**Status:** specified; pending independent Barrier-1 review.

## Purpose

STEWIE will be used as a research apparatus for studying when an autonomous system should promote,
reject, or defer spatial state claims after agents have changed the terrain. The program must retain
what was believed, when it was physically believed valid, when the system learned it, what evidence
caused revision, and which state version informed each decision.

The engineering platform already contains a conserved terrain authority, versioned terrain memory,
an observed-twin event journal, an observation-only reconciliation prototype, action-derived
possible-dependency graphs, baseline implementations, and registered fault probes. The first task is
to join and evaluate those pieces without inflating their current evidence level.

## Candidate scientific contribution

The narrow candidate contribution is a provenance- and time-aware state-promotion mechanism for
self-modifying terrain that:

- constructs accepted values only from admissible observations;
- uses action history to represent possible dependencies between evidence sources;
- lets physical predictions veto but never silently write accepted state;
- removes stale claims using validity time while retaining transaction-time history;
- preserves abstention and unresolved hypotheses as first-class outcomes; and
- exposes the effect on downstream autonomous decisions.

This is a candidate contribution until the novelty and experimental-method reviews accept it.

## Minimal research vertical slice

One deterministic 2.5-D terrain region, two simulated robots, and one physical action are sufficient
for the first coherent slice:

1. ingest a real, content-addressed terrain crop;
2. record its base and current accepted state;
3. plan and apply one conserved excavation/deposition event;
4. generate two partial, asynchronous observations with distinct provenance;
5. retain valid and transaction times and action-derived dependency edges;
6. compare latest-write, timestamp-only, provenance-free, no-physics, physics-fusion, and proposed
   promotion rules;
7. preserve PROMOTE, REJECT, ABSTAIN, and competing-hypothesis outcomes;
8. reconstruct the world as known at an earlier transaction time and as believed valid at an earlier
   physical time; and
9. demonstrate one plan outcome that changes because the selected state/version changes.

## Success criteria

Initial success is Barrier 3, not a complete mission simulator. It requires:

- exact replay of every committed version in the slice;
- no silent overwrite by stale evidence;
- complete queryable lineage for every promoted cell/patch;
- a discrepancy detected and attributed to at least two plausible hypotheses;
- repeatable outputs from fixed inputs and seed;
- a baseline comparison and at least one mechanism ablation; and
- an independent review with all material defects resolved or explicitly accepted as limitations.

Dissertation-level success additionally requires the full Barrier-7 and Barrier-8 evidence described
in `STEWIE_ULTRABUILD_EXECUTION.md`.

## Non-goals

- Flight software, flight certification, or unsupervised physical deployment.
- Proving the physics model is ground truth.
- Claiming novelty for event sourcing, temporal databases, SLAM, scene graphs, GIS, digital twins,
  CRDTs, or provenance standards.
- Replacing every existing STEWIE service before evaluating the central mechanism.
- Treating visual fidelity, code volume, test count, or system complexity as research evidence.
- Quietly depending on LiDAR; the primary sensor condition remains camera/IMU/odometry based.

## Governance

The graph lifecycle, review independence, barrier rules, bounded rework, artifact ownership, and
claim discipline in `STEWIE_ULTRABUILD_EXECUTION.md` are binding. `GRAPH_MANIFEST.yaml` is the
machine-readable source for node state. `TASK_LEDGER.md` records orchestration decisions and defects.

The orchestrator coordinates; specialist nodes own implementation and evaluation. No producer
accepts its own artifact. Any central claim without a baseline, ablation, metric, experiment,
uncertainty statement, and replication command remains unsupported.
