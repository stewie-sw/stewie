# Evaluation metrics

**Artifact ID:** `ART-METRICS`
**Producer node:** `EXP-010`
**Consumers:** every experiment/review node and `DISS-010`
**Status:** executable definitions drafted; scenario-specific thresholds remain blocked until the
pilot/freeze packet is independently accepted.

## Common notation and denominator rules

- A trial is one system run for one registered terrain/action unit, perturbation cell, and seed.
- `N_opportunity` contains every registered trial in which the event could occur, including crashes,
  invalid outputs, and abstentions unless the metric explicitly conditions on promotion.
- `N_promoted` contains only valid durable promotions. A crash or invalid output is not an abstention.
- A `true conflict`, `stale claim`, `harmful state`, and `harmful plan` are labelled only by the
  evaluator process from withheld reference inputs after candidate-output freeze.
- Terrain-window estimates are computed first. Confidence intervals resample `terrain_window`
  units; actions, cells, sources, and seeds are nested repeated measures.
- Missing required output is scored as failure for correctness/replay metrics and reported separately
  as an execution-failure rate. It is never silently excluded.

## State accuracy

- **Elevation RMSE/MAE [m]:** over the explicit jointly evaluated coverage mask.
- **Change precision/recall/IoU:** cells or regions correctly identified as changed.
- **Volume error [m³ and %]:** absolute and signed cut/fill difference.
- **Occupancy/voxel error:** precision, recall, IoU, and surface distance when 3-D is evaluated.
- **Semantic accuracy:** per-class precision/recall with an explicit unknown class.
- **Coverage:** observed and promoted fractions; never inferred from finite fills.

## Temporal correctness

- **Stale-overwrite rate:** `N_stale_promotions / N_promotion_opportunities`. A promotion is stale when
  every observation supporting at least one changed promoted cell has a valid interval ending before
  the most recent evaluator-labelled physical change for that cell, or when its exact query lens
  already marks its prior revision superseded.
- **Valid-time query accuracy:** exact-set matches of returned claim/revision IDs to the oracle divided
  by registered `(valid_at, known_at=latest)` queries.
- **Transaction-time query accuracy:** exact-set matches for registered `(valid_at, known_at)` queries
  that precede and follow retroactive corrections.
- **Historical reconstruction error:** state error for each requested `(valid_at, known_at)` pair.
- **Ordering accuracy:** pairwise event order correct where causality is known.
- **Revision traceability:** superseded claims with complete cause/evidence links divided by all
  supersessions.

## Reconciliation quality

- **Harmful-acceptance rate:** `N_harmful_promotions / N_promotion_opportunities`. A promotion is
  harmful when its registered primary state-error metric exceeds `tau` on more than the allowed
  promoted coverage; this unconditional denominator prevents abstention from hiding harm.
- **Abstention rate:** ABSTAIN/total; always reported beside harmful acceptance.
- **Availability:** `N_valid_promotions / N_promotion_opportunities`; reported with abstention and
  execution-failure rates so they sum to one.
- **Accepted-state error:** error conditioned on valid promotion; its denominator is always printed.
- **False merge rate:** evaluator-labelled incompatible claim pairs collapsed into one accepted claim
  divided by true incompatible pairs presented to the system.
- **Incorrect-overwrite rate:** accepted-head advances later shown inadmissible by the frozen
  evaluator oracle divided by accepted-head advance opportunities.
- **Conflict-retention recall/precision:** true conflicts represented by a durable unresolved conflict
  record divided by true conflicts; and true conflicts retained divided by all retained conflicts.
  “Unresolved-conflict rate” is not used because it confuses retention with prevalence.
- **Time/evidence to convergence:** elapsed transaction time and number of new claims until resolution.
- **Hypothesis-retention quality:** precision/recall of plausible reference hypotheses retained.
- **Support error:** estimated effective support versus the injected/independently estimated
  dependency structure.

## Uncertainty

- **Coverage of declared intervals:** empirical frequency that the reference falls within intervals.
- **Calibration error:** expected calibration error/Brier-style score appropriate to output.
- **Sharpness:** interval width or predictive variance, reported with coverage.
- **Unknown rate:** claims that explicitly retain unknown uncertainty components.
- **Cross-source dependency diagnostics:** residual association by declared component/edge class.

## Provenance

- **Claim completeness:** material claims with every required lineage field / material claims.
- **Broken-edge rate:** missing referenced entity/activity/agent edges.
- **Hash verifiability:** referenced payloads whose digest verifies / referenced payloads.
- **Decision replay rate:** decisions reproduced from stored provenance / attempted decisions.
- **Invalidation recall:** dependents correctly found after source/calibration/claim invalidation.
- **Explanation-edge precision/recall:** predicted causal provenance edges compared as exact typed
  triples `(subject, relation, object)` with the independently generated evaluator graph.
- **Automated correction latency:** transaction-sequence and wall-clock difference from first
  admissible corrective evidence to durable corrected head.
- **Human diagnosis time:** exploratory only under the blinded multi-reviewer protocol in
  `EXPERIMENTAL_DESIGN.md`; otherwise omitted rather than simulated.

## Decision effect

- **Harmful-plan-commitment rate (primary):** committed plans that either reference no exact accepted
  revision/query lens, reference a revision already superseded at their recorded lens, or violate a
  registered evaluator-only simulation constraint, divided by plan-commit opportunities.
- stale or unidentified-version plan counts, reported as components of the primary;
- construction target RMSE/volume error and rework;
- mission completion and partial-completion rate;
- unnecessary rescans and missed necessary rescans;
- energy/time/resource cost;
- task allocation conflicts; and
- decision regret against an evaluation-only oracle.

“Unsafe” is defined per simulated operational constraints and is not a claim of real-world safety.

## Interaction estimand

For E7, let `Y_pd` be unit-level harmful-acceptance rate with provenance gating `p` and dependency
reasoning `d`. The reported normalized interaction is
`-((Y_11 - Y_10) - (Y_01 - Y_00))`, so positive values favor the registered hypothesis. The paired
interval resamples terrain/action units and keeps all four cells together. Cell-wise availability and
execution failures are mandatory; the interaction is rejected if any availability margin fails.

## Computational performance

- p50/p95/p99 ingest, reconcile, append, current-query, historical-query, and provenance-query latency;
- evidence/claims/versions processed per second;
- peak resident memory and GPU memory where used;
- authoritative metadata and payload storage growth;
- synchronization bytes and convergence time;
- simulation real-time factor; and
- empirical growth with cells, robots, observations, dependency edges, and versions.

## Reporting rules

- Record units, masks, sample counts, excluded trials, hardware, software versions, and confidence
  intervals.
- Report curves over `tau`, not one favorable threshold.
- State whether reference is simulated/conserved, surveyed, or otherwise measured.
- A zero-harm result with 100% abstention is not operational success.
- Means never replace latency tails, failure distributions, or per-scenario results.
- Every table names its denominator, conditioning set, unit count, repeated-measure count, and missing
  outcome treatment.
