# Quality rubric

**Artifact ID:** `ART-QUALITY-RUBRIC`
**Producer node:** `ORCH-001`
**Consumers:** all graph nodes, barriers, and `DISS-010`
**Status:** binding scoring rubric; baseline estimates below are unreviewed.

## Scale

| Score | Meaning | Required evidence |
|---:|---|---|
| 0 | Missing | No functional artifact or evidence |
| 1 | Demonstration | Executes in one narrow case; major semantics or evidence absent |
| 2 | Functional prototype | Nominal cases work; limitations and tests exist |
| 3 | Research-grade | Reproducible, documented, linked to an RQ, tested against credible baselines |
| 4 | Strong research artifact | Independent adversarial review, ablations, perturbations, and multi-scenario reliability |
| 5 | Reference-quality evidence | Exceptional reproducibility, generality, independent replication, and precise claim support |

Complexity, code volume, diagrams, visual polish, and test count cannot independently raise a score.
The score is the lowest applicable dimension, not an average that hides a zero.

## Dimensions

Each major subsystem is scored on:

1. semantic correctness;
2. functional correctness and failure containment;
3. temporal/provenance completeness;
4. uncertainty and conflict handling;
5. scientific construct validity;
6. baseline and ablation strength;
7. reproducibility;
8. performance/scaling;
9. integration coherence; and
10. documentation/claim discipline.

## Advancement rules

- `ACCEPTED` requires no dimension below 2 and no unresolved critical defect.
- `INTEGRATED` requires interface, delayed/conflicting-evidence, and rollback tests.
- `REGRESSION_VERIFIED` requires the declared repository gates on the integrated commit.
- `EXPERIMENTALLY_VALIDATED` requires score at least 3 in scientific validity, baselines,
  reproducibility, and claim discipline.
- A score 4 requires a reviewer independent of implementation.
- A score 5 requires an external or separately controlled replication; the producing team cannot
  award it alone.

## Initial inventory estimate

These are triage estimates only and cannot advance lifecycle:

| Subsystem | Estimate | Main reason |
|---|---:|---|
| Conserved simulated terrain transition | 3 | Strong tests/provenance; physical fidelity/generalization bounded |
| Terrain version/history component | 2 | Durable/replayable versions; not bitemporal |
| Observation-only physics-veto component | 3 | Registered probes, credible comparators, mutation tests; not live-integrated |
| Action-derived dependency component | 2 | Pairwise masks and tests; dependency meaning is assumed, not measured |
| Structured end-to-end provenance | 1 | Hash chains exist; full queryable lineage schema absent |
| Bitemporal world state | 0 | Explicit transaction-time model/query absent |
| Competing-hypothesis store | 0 | Decision vocabulary does not persist hypothesis branches |
| Multi-robot closed-loop reconciliation | 1 | Component concurrency scenarios, no integrated closed loop |
| Decision-effect evidence | 0 | Not yet evaluated |
| Visualization/operator platform | 2 | Broad functional surface; scientific uncertainty/time display needs review |

No score in this table is a scientific result.
