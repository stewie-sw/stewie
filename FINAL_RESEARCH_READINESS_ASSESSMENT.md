# Final research-readiness assessment

**Artifact ID:** `ART-FINAL-READINESS`
**Producer node:** `DISS-010`
**Consumers:** `ORCH-001`, `REV-010`
**Source commit:** `608c6881e9be5754ac801a7833ee1f8217c238a0`
**Assessment date:** 2026-07-29
**Status:** `functional_prototype_research_blocked`
**Overall quality level:** **2 — Functional Prototype**

The bounded UltraBuild software build is complete and reproducible. The dissertation research
program is not experimentally validated.

## Barrier state

| Barrier | Decision | Basis |
|---|---|---|
| 1 — Research definition | **BLOCK** | independent scientific review: replacement allocation, power/MDE, executable isolation/oracle controls, baseline attestations, and confirmatory packet are absent |
| 2 — Architecture and contracts | **ACCEPT** | independent systems and database reviews accepted the typed authority, temporal, provenance, receipt, snapshot, and failure contracts at the pinned source commit |
| 3 — Minimal persistent world state | **BLOCK** | controlled synthetic implementation runs, but real-terrain ingest, a prior immutable revision, and integrated discrepancy evidence are absent; Barrier 1 is also upstream |
| 4 — Single-robot loop | **BLOCKED** | Barrier 3 not accepted; no live closed robot loop |
| 5 — Multi-robot reconciliation | **BLOCKED** | controlled promotion/conflict demos are not partition/rejoin synchronization evidence |
| 6 — Physics as evidence | **BLOCKED** | noninterference is demonstrated, but the registered outcome ablation is neutral and no accepted Barrier-3 slice exists |
| 7 — Experimental validation | **BLOCKED** | retained evaluation is exposed exploratory synthetic evidence, not a confirmatory two-domain packet |
| 8 — Dissertation evidence lock | **BLOCKED** | no central H1–H7 conclusion currently has accepted confirmatory evidence |

## Implemented

- typed world, branch, evidence, provenance, candidate, conflict, decision, revision, query, receipt,
  scenario, and barrier contracts;
- store-owned transaction sequence/time and immutable content identities;
- revision-level valid-time/known-at querying with supersession and invalidation;
- content-addressed payload storage, exact-cut cold snapshot, and restored-bundle verification;
- observation-only candidate reconstruction with physics used as contestable evidence rather than
  accepted state bytes;
- atomic provenance/decision/revision promotion and accepted-head compare-and-swap;
- complete checked shadows for indexed immutable-record metadata;
- append-receipt and applied-promotion-receipt closure, canonical receipt hashing, idempotent replay,
  projection integrity, and deterministic projection rebuild;
- controlled 18-record single promotion, 31-record multi-source promotion, and 12-record
  competing-hypothesis retention demonstrations;
- exploratory baseline/ablation, perturbation, fault-injection, and host-local performance harnesses;
  and
- installation, deployment, reproduction, test, limitation, claim-matrix, and review history
  documentation.

## Evidence level

| Subsystem | Score | Evidence boundary |
|---|---:|---|
| Architecture and typed contracts | 3 | independently reviewed and Barrier-2 accepted |
| Authority store, provenance, and temporal revision query | 3 | adversarially tested, reproducible, bounded single-host semantics |
| Reconciliation and physics noninterference | 2 | controlled synthetic demonstration; outcome benefit unsupported |
| Multi-robot conflict retention | 2 | durable controlled graph; no communication partition/convergence study |
| Packaging and command-line reproduction | 3 | clean-wheel smoke and runnable installed entry point |
| Fault/performance evidence | 2 | eight in-process faults and six measured host-local targets; scaling families remain open |
| Confirmatory experimental method | 1 | contracts exist, but the exposed allocation is permanently exploratory |
| Real terrain modification vertical slice | 1 | existing fixture is generated and lacks prior/new discrepancy evidence |
| Physical robot or mission integration | 0 | not implemented or validated |

## Experimentally observed, but not validated

The exploratory diagnostic retains 1,728 repeated-measure rows over eight generated 12×12 terrain
windows. The constructed STEWIE-minus-latest-overwrite harmful-plan difference is `−0.667` with a
descriptive, degenerate interval `[-0.667, -0.667]`. The physics ablation difference is `0.000`.
Those results diagnose the current generator and implementation only; they do not establish
generality, novelty, safety, or a dissertation effect.

The final 200-run microbenchmark passes all six measured targets. Eight registered budget families,
including cold cache, storage growth, 1,000-version replay, concurrency, scaling, and distributed
synchronization, remain unmeasured.

## Deferred or blocked

- evaluator-controlled confirmatory terrain/action allocation;
- pilot calibration, power analysis, MDEs, and frozen analysis packet;
- strong external baselines and executable same-input/reference-firewall attestations;
- real terrain prior/modified reconstruction and discrepancy measurement;
- single-robot closed loop, network partition/rejoin, and distributed synchronization;
- ROS 2, GIS/QGIS, Gazebo/Godot, legacy API, and physical robot integration;
- physics-gating benefit under model bias and real terrain response;
- two-domain validation, scaling, independent replication, and defense-ready accepted claims; and
- deployment security, authentication, migration, automatic recovery/quarantine, and
  flight/mission assurance.

Nothing in this package supports mission readiness, flight certification, unsupervised physical
deployment, broad planetary generality, or superiority to existing world-model systems.
