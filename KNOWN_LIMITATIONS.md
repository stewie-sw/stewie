# Known limitations

**Artifact ID:** `ART-LIMITATIONS`
**Producer node:** `ORCH-001`
**Consumers:** every reviewer, release, and dissertation node
**Status:** current at baseline `d1056d9d`; update whenever a limitation changes.

## Research and evidence

- The repository contains component regression probes, not the integrated two-domain, multi-robot
  benchmark or a frozen statistical evidence package.
- Existing results use a real Haworth base terrain with controlled simulated excavations, noise,
  biases, delays, coverage, and action-log faults. They are not field validation.
- No current experiment establishes that reconciliation improvements change downstream autonomous
  decisions.
- `NOVELTY_REVIEW.md` covers an initial set of primary bitemporal, provenance, CRDT, multi-robot,
  scene-graph, and changing-map work, but its named temporal GIS, belief-revision, construction,
  mining, digital-twin, and physics-informed search gaps remain open.
- A claimed `dissertation/formal` Lean project is absent from the tracked branch, so no formal
  verification claim is currently admissible.
- Several S3LI result files cited by an existing write-up are absent; the surviving artifacts do not
  reconstruct that complete claimed package.

## State semantics

- The new UltraBuild schemas, semantic validator, and runtime graph are specifications and adversarial
  control fixtures, not an implemented authoritative store or proof of Barrier-2 correctness.
- The draft stored-record schemas require transaction metadata that the temporal model says only the
  store may assign. Submission-versus-stored contracts and final store-side hashing are unresolved.
- The runtime graph does not yet route every immutable candidate, decision, conflict, hypothesis, and
  query record through one typed durable append boundary; its append/projection receipts are not
  machine-readable contracts.
- Candidate-to-revision promotion does not yet bind the complete spatial, valid-time, and aggregate
  uncertainty contract, and the resolver lacks a valid closed golden record graph.
- The system is versioned but not bitemporal. It lacks first-class transaction-time intervals and
  valid-time/transaction-time reference queries.
- `TwinStore` provenance is primarily a string, not the complete structured lineage model.
- A durable store for competing hypotheses does not exist.
- `TerrainMemory.revert_to` truncates later retained history; it is unsuitable as the research
  rollback model.
- `TerrainMemory` chain metadata does not hash the complete sparse spatial delta; summary-chain
  verification can survive spatial-history tampering.
- `WorldStateService` carries global latest identities; an independent probe linked a nondefault site
  transaction to the default Haworth observed twin.
- Simulated run deltas and observed patches can both affect the planner surface without branch-isolated
  reconciliation.
- Planning does not consistently record the exact world version and bitemporal query lens it used.
- Derived-layer and plan invalidation after terrain/state correction are incomplete.

## Reconciliation

- The theorem-facing promotion rule is not the live `POST /twin/resync` write path.
- The current accepted observation value is a plain mean; source-specific/per-cell uncertainty and
  alternative robust aggregates are not integrated.
- Action-derived edges express possible dependence, not measured covariance.
- Relabelled duplicate evidence may be indistinguishable and can defeat the rule.
- The no-physics regime, miscalibrated sensors, fabricated action overlap, partial coverage, and
  worst-covered-cell behavior have documented failure regions.
- The mechanism exposes PROMOTE/REJECT/ABSTAIN but does not yet persist competing hypothesis branches.
- An older reconciliation contract treats a fresh observation as ground truth and conflicts with the
  newer uncertain/stale-evidence semantics; it must not govern the new path.

## Representation and robotics

- The first research slice is 2.5-D and cannot represent overhangs, voids, or arbitrary volumetric
  excavation.
- Dense stereo/COLMAP, GPU render, Godot, ROS/Gazebo, Chrono, and physical-pit tiers are host-gated or
  incomplete; no live robot loop is validated.
- The primary condition must not depend on LiDAR, although an existing synthetic experiment labels a
  second array source “lidar.”
- Numerical mass conservation is exact within the implemented model; prediction of real terrain
  response is not physically exact.
- Localization, illumination, dust, slip, reconstruction, and frame uncertainty are not yet joined to
  the state-promotion path end to end.

## Operations and reproducibility

- The repository license is all-rights-reserved, while some existing text promises an open release or
  calls the repository CC0. A redistributable research package is not yet resolved.
- Dataset and third-party licenses vary; not every external source is bundled.
- README requirement counts conflict with the generated requirements manifest/status.
- The refreshed development lock installs successfully into a new ignored UltraBuild virtual
  environment. This verifies dependency reconstruction for the foundation checks, not a frozen
  experiment/container or cross-platform replication.
- Canonical hashes currently use the Python `json.dumps(sort_keys=True, allow_nan=False)` profile.
  Cross-language numeric/Unicode/negative-zero equivalence is not claimed; an RFC 8785 (or explicitly
  equivalent) profile plus ROS/Godot/database test vectors is required before adapter-generated IDs
  become authoritative.
- Performance budgets are targets; no integrated scaling report exists.
- The root published wheel may omit required workspace packages that CI/Docker install manually.

Nothing in the current repository supports flight certification, mission readiness, unsupervised
physical deployment, or broad cross-domain superiority.
