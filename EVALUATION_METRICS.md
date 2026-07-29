# Evaluation metrics

**Artifact ID:** `ART-METRICS`
**Producer node:** `EXP-010`
**Consumers:** every experiment/review node and `DISS-010`
**Status:** defined; thresholds remain preregistration inputs.

## State accuracy

- **Elevation RMSE/MAE [m]:** over the explicit jointly evaluated coverage mask.
- **Change precision/recall/IoU:** cells or regions correctly identified as changed.
- **Volume error [m³ and %]:** absolute and signed cut/fill difference.
- **Occupancy/voxel error:** precision, recall, IoU, and surface distance when 3-D is evaluated.
- **Semantic accuracy:** per-class precision/recall with an explicit unknown class.
- **Coverage:** observed and promoted fractions; never inferred from finite fills.

## Temporal correctness

- **Stale-overwrite rate:** accepted promotions based on evidence invalid before the last relevant
  physical change, divided by opportunities.
- **Valid-time query accuracy:** exact match of returned claim/version set to a reference oracle.
- **Transaction-time query accuracy:** same, under the knowledge-time lens.
- **Historical reconstruction error:** state error for each requested `(valid_at, known_at)` pair.
- **Ordering accuracy:** pairwise event order correct where causality is known.
- **Revision traceability:** superseded claims with complete cause/evidence links divided by all
  supersessions.

## Reconciliation quality

- **Harmful-acceptance rate:** promoted trials whose accepted error exceeds task tolerance `tau`.
- **Abstention rate:** ABSTAIN/total; always reported beside harmful acceptance.
- **Accepted-state error:** error conditioned on promotion.
- **False merge rate:** incompatible claims collapsed into one accepted claim.
- **Incorrect overwrite rate:** governing state replaced by a claim later shown inadmissible.
- **Unresolved-conflict rate:** retained conflicts / true conflicts, with precision and recall.
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
- **Diagnosis time:** reviewer/operator time to identify the causal source in controlled faults.

## Decision effect

- unsafe/infeasible plan count and rate;
- plans using stale or unidentified versions;
- construction target RMSE/volume error and rework;
- mission completion and partial-completion rate;
- unnecessary rescans and missed necessary rescans;
- energy/time/resource cost;
- task allocation conflicts; and
- decision regret against an evaluation-only oracle.

“Unsafe” is defined per simulated operational constraints and is not a claim of real-world safety.

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
