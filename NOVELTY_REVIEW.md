# Adversarial novelty review

**Artifact ID:** `ART-NOVELTY`
**Producer node:** `RES-020`
**Consumers:** `RES-030`, `EXP-010`, `EXP-020`, `DISS-010`
**Status:** bounded primary-source review complete for the registered claims; independent acceptance
and experiment freeze remain required before Barrier 1 can advance.

## Review rule

No STEWIE component is novel merely because it is difficult, integrated with robotics, or applied to
lunar construction. This review classifies the nearest work found so far and turns overlap into
baseline obligations. “Potentially novel” means a search target, not a conclusion.

## Search boundary

The review searched the mechanism families that could invalidate the registered contribution:
bitemporal/spatiotemporal databases, event logs, provenance, truth maintenance and model-based
diagnosis, CRDT/replication, lifelong and multi-robot mapping, scene graphs, change-aware maps,
earthwork digital twins, and physics/model consistency checks. It is a claim-directed engineering
review, not an exhaustive systematic literature review. Absence from this bounded search is never
evidence that no prior work exists.

## Nearest-work matrix

| Proposed contribution | Established nearest work | Boundary for STEWIE | Classification | Required next review/baseline |
|---|---|---|---|---|
| Spatial state and valid-time plus transaction-time history | Spatial types, indexes, joins, and system architecture were surveyed by [Güting, 1994](https://sigmod.org/publications/dblp/db/journals/vldb/Guting94.html); bitemporal data and indexing already model both dimensions, including [Bliujutė, Jensen, Šaltenis, and Slivinskas, 1998](https://www.vldb.org/conf/1998/p345.pdf). | Spatial/robotic payloads do not make either spatial databases or the two-time model novel. | established mechanisms; domain integration only | Compare with a credible bitemporal/event-sourced implementation, not only latest-write. |
| Immutable change log and replayable projections | Event-sourced systems retain immutable changes and reconstruct projections; the literature also documents their observability problem, e.g. [Lima et al., 2021](https://doi.org/10.1016/j.jss.2021.111015). | Append-only events and replay are implementation obligations, not dissertation novelty. | established architecture pattern | Implement a typed append boundary and compare semantics, cost, and failure recovery rather than claiming the log. |
| Queryable lineage for state claims | [W3C PROV-O](https://www.w3.org/TR/prov-o/) already defines interoperable entities, activities, agents, derivation, revision, invalidation, and qualified relations. | STEWIE may specialize PROV for frames, calibration, robots, and terrain, but cannot claim provenance itself. | established mechanism; systems integration | Validate typed PROV closure and compare with equivalent lineage enabled but admission gating disabled. |
| Dependency-directed belief revision and competing contexts | [Doyle's TMS](https://doi.org/10.1016/0004-3702(79)90008-0) records reasons for beliefs and revises them after contradictions; [de Kleer's ATMS](https://doi.org/10.1016/0004-3702(86)90080-9) retains assumption sets and supports multiple inconsistent solution contexts. | Storing justifications or competing hypotheses is established. STEWIE's claim must concern typed spatial admission behavior and measured decision effects. | established knowledge-representation mechanisms; application/integration | Include provenance and competing-hypothesis ablations and test durable spatial/temporal closure. |
| Model consistency as evidence and alternative diagnoses | [Reiter, 1987](https://doi.org/10.1016/0004-3702(87)90062-2) formalizes diagnoses from discrepancy between observation and a system model and computes competing explanations. | A physics discrepancy check or candidate diagnoses are not novel alone. The narrower test is whether predicted values are prevented from constructing accepted observation state while veto evidence remains useful. | established diagnostic principle; proposed noninterference method unsupported until tested | Require biased-model, no-model, fusion, and byte-level noninterference conditions. |
| Replica convergence under partitions | [Preguiça, Baquero, and Shapiro’s CRDT survey](https://arxiv.org/abs/1805.06358) covers deterministic convergence after replicas receive the same updates. | Preserving incompatible spatial hypotheses may intentionally avoid a single merged value; this must be compared with CRDT/event-log designs. | established distributed-systems baseline | Implement a strong convergent replicated-log/map baseline and report semantic conflict loss separately from convergence. |
| Distributed multi-robot metric-semantic mapping | [Kimera-Multi](https://arxiv.org/abs/2106.14386) provides distributed visual-inertial multi-robot localization and globally consistent dense metric-semantic meshes. | STEWIE must not claim multi-robot mapping novelty. Its distinct question is durable state acceptance after agent-induced environmental change. | established robotics capability; nearest external baseline | Normalize sensors, communication, terrain, and observation sequences; compare state-history/conflict behavior, not module count. |
| Multi-resolution spatial world models | [Hydra](https://www.roboticsproceedings.org/rss18/p050.html) incrementally constructs and optimizes layered 3D scene graphs from geometry through semantic places/objects. | A new ontology or graph layout alone is incremental unless temporal/provenance/promotion semantics yield measured effects. | established representation; likely incremental extension | Include scene-graph/map representations with matched perception inputs where the evaluated claim depends on hierarchy. |
| Online mapping in changing environments | [Biber and Duckett, 2005](https://doi.org/10.15607/RSS.2005.I.003) represent maps over multiple timescales; [POCD](https://www.roboticsproceedings.org/rss18/p013.html) performs probabilistic object-level change detection and volumetric maintenance; [LT-mapper](https://arxiv.org/abs/2107.07712) combines multi-session SLAM, change detection, and management. | “Maps that change,” multi-session storage, and historical versions are not sufficient novelty claims. | established/incremental | Add strong lifelong/change-aware mapping baselines and test deliberate robot-caused terrain changes rather than generic scene dynamics alone. |
| Persistent competing spatial hypotheses under delayed, contradictory, agent-caused change | TMS/ATMS retain alternative belief contexts; dynamic and lifelong maps retain change at multiple timescales; distributed mapping retains multiple local estimates. | The candidate contribution is a typed acceptance contract joining action-derived dependencies to immutable spatial/temporal/provenance records, not storage of multiple maps. | systems/methodological candidate; novelty unsupported until comparative evidence and wider peer review | Compare TMS-like retention, change-aware maps, and shared-map projections; report conflict loss and decision effect. |
| Planned/as-built volumetric earthwork twin | Voxel earthwork representation and dynamic as-planned/as-built progress are explicit in [Khan, Cho, and Seo, 2025](https://doi.org/10.3390/app15147899), with earlier voxel earthwork modeling in [Khan and Seo, 2021](https://doi.org/10.1061/(ASCE)CO.1943-7862.0002137). | Voxel terrain, excavation/deposition visualization, and progress tracking are established construction/digital-twin work. | established domain representation; integration only | Use as a representation comparator where possible; do not claim the digital twin or volumetric terrain itself. |
| Physics as contestable evidence without allowing predicted values to construct accepted observations | Model-based diagnosis and sensor-fault isolation already use model/observation residuals; Reiter is the closest general principle found. | A defensible narrower claim requires a noninterference invariant plus no-physics, biased-physics, and prediction-fusion comparisons on identical observations. | potentially methodological; unsupported until H3 evidence | Execute bounded mismatch and arbitrary-value noninterference tests; classify novelty no higher than methodological. |
| Provenance-gated action-dependency interaction | Provenance and dependency reasoning are established independently; the bounded search found no direct comparator using action-overlap provenance to discount terrain evidence in a bitemporal promotion contract. | “Not found” is not novelty. The registered P×D interaction, credible ablations, and downstream effect are required before even a potentially novel classification. | potentially methodological; unsupported | Execute E7 and seek independent domain review; a null interaction narrows the contribution to systems integration. |
| Joint bitemporal, provenance-gated, hypothesis-preserving, physics-contestable state promotion | Every component has established antecedents. | Integration breadth is not novelty, and STEWIE no longer claims an unspecified four-way synergy. | systems integration contribution; scientific value contingent on mechanism and decision evidence | Show conformance, component effects, the one registered P×D interaction, costs, and downstream decision effect. |

## Unsupported claims

The current evidence does **not** support claims that:

- STEWIE invents bitemporal state, provenance, multi-robot mapping, scene graphs, event history, or
  change-aware mapping;
- no prior system combines the proposed mechanisms;
- physics-gated observation-only promotion is novel;
- an action-dependency/provenance interaction exists;
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
8. the full mechanism plus component and the registered P×D interaction ablations.

## Disposition

The bounded search closes the missing-family inventory but cannot establish novelty. `FND-001` may
close only when an independent novelty reviewer confirms that every registered claim is no broader
than this matrix. Any later literature match reopens the relevant claim and baseline obligation.
