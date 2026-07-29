# Dissertation alignment

**Artifact ID:** `ART-DISSERTATION-ALIGNMENT`
**Producer node:** `RES-010`
**Consumers:** `RES-020`, `EXP-010`, `DISS-010`
**Status:** candidate framing; pending novelty and method review.

## One-sentence thesis candidate

In spatial environments changed by autonomous agents, state promotion can be made more auditable and
less prone to harmful acceptance by combining bitemporal evidence semantics, action-derived
possible-dependency graphs, and an observation-only acceptance rule in which physics is contestable
veto evidence rather than a value-producing source.

This sentence is a hypothesis-bearing target, not a conclusion.

## Selected center

Existing documentation presents two other possible dissertation centers: conserved dynamics plus
learned perception (`docs/related_work.md`) and articulated-rover state estimation
(`docs/ARCHITECTURE.md`). This restart selects persistent state acceptance under agent-induced change
as the primary thesis. Conserved physics is contestable evidence and experimental apparatus;
perception/localization supplies observations and perturbation conditions. Neither is bundled into
the novelty claim unless separately evaluated.

## Contribution decomposition

| Candidate contribution | Type | Current repository evidence | Current support |
|---|---|---|---|
| Observation-only accepted state with contestable physics veto | Methodological | `stewie/twin/promotion.py`, `stewie/twin/veto_experiment.py`, focused tests | Component-level, simulated fault probes |
| Action-derived pairwise possible-dependency graph for multi-robot terrain evidence | Methodological/integration | `stewie/twin/shared_terrain.py`, `stewie/twin/effective_support.py`, partial-coverage and overlap tests | Component-level; covariance meaning remains an assumption |
| Persistent historical terrain reconstruction | Systems | `stewie/twin/terrain_memory.py`, `stewie/twin/versioned.py`, point-in-time and journal tests | Engineering-validated, not bitemporal |
| Valid-time plus transaction-time state semantics | Integration | Valid-time filtering exists as `Evidence.observed_at`; transaction-time query model does not | Partial/unvalidated |
| Queryable end-to-end provenance for state claims | Systems/integration | Hash-chained journals and route audit exist; per-cell W3C-style lineage does not | Partial |
| Better autonomous decisions due to better state management | Empirical | Existing planners and world-state routes are reusable | Unsupported until decision experiments run |
| Generality beyond lunar construction | External-validity | Terrestrial domain is specified but no integrated two-domain run is frozen | Unsupported |

## Novelty boundary

The following nearby results narrow the claim:

- Hydra builds and optimizes real-time layered 3-D scene graphs; STEWIE must not claim that a layered
  spatial world graph is new: <https://www.roboticsproceedings.org/rss18/p050.pdf>.
- Kimera-Multi performs distributed multi-robot metric-semantic mapping; multi-robot map fusion and
  distributed mesh consistency are established: <https://arxiv.org/abs/2106.14386>.
- Lifelong SLAM and spatiotemporal occupancy maps explicitly model changing environments; “maps
  change over time” is not novel: <https://doi.org/10.1109/IROS.2016.7759671>.
- Bitemporal valid/transaction-time semantics predate this work; applying the terms without a new
  mechanism is integration, not novelty: <https://doi.org/10.1109/69.667079>.
- W3C PROV already defines interoperable entity/activity/agent provenance; STEWIE should specialize,
  not rename, that model: <https://www.w3.org/TR/prov-o/>.
- CRDTs already provide deterministic convergence for compatible replicated data types; preserving
  scientifically meaningful competing terrain hypotheses is a different requirement and must be
  compared explicitly: <https://arxiv.org/abs/1805.06358>.

The potentially novel unit is therefore not any one representation. It is the testable interaction
between action-derived evidence dependency, observation-only accepted values, bitemporal
admissibility, and contestable physics in agent-modified terrain.

## Dissertation question-to-chapter map

| Chapter | Purpose | Governing artifacts |
|---|---|---|
| 1. Problem and scope | Define self-modifying world state and harmful promotion | `PROBLEM_DEFINITION.md`, `PROJECT_CHARTER.md` |
| 2. Related work and novelty | Establish what is already known and bound the claim | this file, `docs/related_work.md`, novelty review output |
| 3. Semantics and architecture | Define ontology, time, provenance, uncertainty, and authority | `WORLD_STATE_ONTOLOGY.md`, `TEMPORAL_MODEL.md`, `PROVENANCE_MODEL.md`, `SYSTEM_ARCHITECTURE.md` |
| 4. Mechanism | Specify dependency graph and observation-only physics-veto rule | `DATA_MODEL.md`, code and contract nodes `WS-040`/`WS-050` |
| 5. Experimental method | Baselines, ablations, perturbations, statistics, and preregistration | `EXPERIMENTAL_DESIGN.md`, `EVALUATION_METRICS.md` |
| 6. Results | Report state, temporal, reconciliation, decision, and performance results | frozen experiment artifacts |
| 7. Threats and limits | State failure regions, negative results, and generality limits | `RISK_REGISTER.md`, `KNOWN_LIMITATIONS.md` |
| 8. Conclusions | Include only claims in the locked evidence matrix | node `DISS-010` |

## Claim admission rule

A conclusion claim is admissible only when the final claim-evidence matrix supplies: claim, RQ,
hypothesis, mechanism, implementation, baseline, ablation, metric, experiment, result, uncertainty,
threats, evidence artifact, replication command, and support level. “Demonstrated,” “engineering
verified,” and “experimentally validated” remain separate labels.
