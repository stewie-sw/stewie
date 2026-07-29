# Adversarial novelty review

**Artifact ID:** `ART-NOVELTY`
**Producer node:** `RES-020`
**Consumers:** `RES-030`, `EXP-010`, `EXP-020`, `DISS-010`
**Status:** active, incomplete, and not independently accepted; Barrier 1 remains blocked.

## Review rule

No STEWIE component is novel merely because it is difficult, integrated with robotics, or applied to
lunar construction. This review classifies the nearest work found so far and turns overlap into
baseline obligations. “Potentially novel” means a search target, not a conclusion.

## Preliminary nearest-work matrix

| Proposed contribution | Established nearest work | Boundary for STEWIE | Classification | Required next review/baseline |
|---|---|---|---|---|
| Valid-time plus transaction-time world history | Bitemporal databases already model and index both dimensions; see [Nascimento and Dunham, 1998](https://doi.org/10.1109/69.667079). | Spatial/robotic payloads do not make the two-time model novel. | established mechanism; domain integration only | Compare with a credible bitemporal/event-sourced implementation, not only latest-write. |
| Queryable lineage for state claims | [W3C PROV-O](https://www.w3.org/TR/prov-o/) already defines interoperable entities, activities, agents, derivation, revision, invalidation, and qualified relations. | STEWIE may specialize PROV for frames, calibration, robots, and terrain, but cannot claim provenance itself. | established mechanism; systems integration | Validate typed PROV closure and compare with equivalent lineage enabled but admission gating disabled. |
| Replica convergence under partitions | [Preguiça, Baquero, and Shapiro’s CRDT survey](https://arxiv.org/abs/1805.06358) covers deterministic convergence after replicas receive the same updates. | Preserving incompatible spatial hypotheses may intentionally avoid a single merged value; this must be compared with CRDT/event-log designs. | established distributed-systems baseline | Implement a strong convergent replicated-log/map baseline and report semantic conflict loss separately from convergence. |
| Distributed multi-robot metric-semantic mapping | [Kimera-Multi](https://arxiv.org/abs/2106.14386) provides distributed visual-inertial multi-robot localization and globally consistent dense metric-semantic meshes. | STEWIE must not claim multi-robot mapping novelty. Its distinct question is durable state acceptance after agent-induced environmental change. | established robotics capability; nearest external baseline | Normalize sensors, communication, terrain, and observation sequences; compare state-history/conflict behavior, not module count. |
| Multi-resolution spatial world models | [Hydra](https://www.roboticsproceedings.org/rss18/p050.html) incrementally constructs and optimizes layered 3D scene graphs from geometry through semantic places/objects. | A new ontology or graph layout alone is incremental unless temporal/provenance/promotion semantics yield measured effects. | established representation; likely incremental extension | Include scene-graph/map representations with matched perception inputs where the evaluated claim depends on hierarchy. |
| Online mapping in changing environments | [POCD](https://www.roboticsproceedings.org/rss18/p013.html) performs probabilistic object-level change detection and volumetric map maintenance; [LT-mapper](https://arxiv.org/abs/2107.07712) combines multi-session SLAM, change detection, and change management. | “Maps that change” and “historical map versions” are not sufficient novelty claims. | established/incremental | Add strong lifelong/change-aware mapping baselines and test deliberate robot-caused terrain changes rather than generic scene dynamics alone. |
| Persistent competing hypotheses under delayed, contradictory, agent-caused change | Temporal maps, robust SLAM, belief revision, and distributed conflict retention each overlap pieces; this review has not yet identified or excluded a system with the full semantics. | The candidate contribution is the acceptance contract and its measured effect, not storage of multiple maps. | potentially novel but unsupported | Complete belief-revision, temporal GIS, multi-hypothesis mapping, construction/mining autonomy, and digital-twin searches before narrowing the claim. |
| Physics as contestable evidence without allowing predicted values to construct accepted observations | Physics-informed estimation and model-based validation broadly overlap; nearest-work review is incomplete. | A defensible claim requires a noninterference invariant plus no-physics, biased-physics, and prediction-fusion comparisons on identical observations. | potentially methodological; unsupported | Search physics-informed state estimation and construction/mining change verification; register the mechanism interaction contrast. |
| Joint bitemporal, provenance-gated, hypothesis-preserving, physics-contestable state promotion | Every component has established antecedents. Novelty, if any, must be an interaction effect or a systems/methodological contribution demonstrated against credible component baselines. | Integration breadth is not novelty. | integration/systems contribution; interaction unsupported | Add a factorial interaction contrast and show a downstream decision effect beyond abstention or implementation scale. |

## Unsupported claims

The current evidence does **not** support claims that:

- STEWIE invents bitemporal state, provenance, multi-robot mapping, scene graphs, event history, or
  change-aware mapping;
- no prior system combines the proposed mechanisms;
- physics-gated observation-only promotion is novel;
- the mechanism generalizes beyond registered controlled scenarios;
- simulation demonstrates physical, operational, or mission readiness; or
- architectural breadth makes STEWIE superior to an external baseline.

## Baseline obligations created by this review

Barrier 1 requires named owners and reproducible configurations for at least:

1. latest-state overwrite, timestamp-only ordering, and version-only history;
2. a credible bitemporal/event-sourced store;
3. W3C-PROV-equivalent lineage with admission gating ablated;
4. a convergent replicated-log/map approach;
5. change-aware/lifelong mapping with historical reconstruction where supported;
6. multi-robot shared mapping without STEWIE reconciliation;
7. no-physics, biased-physics, and prediction-fused reconciliation; and
8. the full mechanism plus component and interaction ablations.

## Search still required

The review is deliberately incomplete in temporal GIS, belief revision and truth maintenance,
multi-hypothesis mapping, digital-twin synchronization, construction/mining autonomy, terrain
deformation/change attribution, physics-informed state estimation, database event sourcing, and
distributed spatial databases. `FND-001` remains open until primary-source coverage and an
independent novelty reviewer approve a claim-by-claim nearest-work matrix.
