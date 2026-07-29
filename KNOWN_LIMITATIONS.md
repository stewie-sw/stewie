# Known limitations

**Artifact ID:** `ART-LIMITATIONS`
**Producer node:** `ORCH-001`
**Consumers:** every reviewer, release, and dissertation node
**Status:** current for baseline `d1056d9d` plus the unreviewed UltraBuild working-tree prototype of
2026-07-29; update whenever a limitation changes.

## Research and evidence

- The repository contains component regression probes and one deterministic 18-record UltraBuild
  golden graph, not the integrated two-domain, multi-robot benchmark or a frozen statistical evidence
  package.
- Existing results use a real Haworth base terrain with controlled simulated excavations, noise,
  biases, delays, coverage, and action-log faults. They are not field validation.
- No current experiment establishes that better persistent state management changes downstream
  autonomous decisions.
- `NOVELTY_REVIEW.md` covers an initial set of primary bitemporal, provenance, CRDT, multi-robot,
  scene-graph, and changing-map work, but its named temporal GIS, belief-revision, construction,
  mining, digital-twin, and physics-informed search gaps remain open.
- A claimed `dissertation/formal` Lean project is absent from the tracked branch, so no formal
  verification claim is currently admissible.
- Several S3LI result files cited by an existing write-up are absent; the surviving artifacts do not
  reconstruct that complete claimed package.
- The focused UltraBuild test suite is producer self-test evidence. No independent reviewer has
  accepted Barrier 2 or Barrier 3 against the implementation.

## Authority-store prototype

- `stewie/ultrabuild/` is an implemented in-process research prototype, not a production service. It
  is not wired into legacy FastAPI, ROS 2, GIS/QGIS, Godot/Gazebo, planner, resynchronization, or robot
  command paths.
- SQLite is a single-node semantic authority. Concurrency was tested with two connections and threads
  on one host, not multiple processes, hosts, replicas, communication partitions, or Byzantine
  sources.
- WAL plus `synchronous=FULL` and SQLite backup are configured and cold restore is tested, but
  kill-at-every-instruction crash recovery, disk-full behavior, filesystem-specific durability, and
  backup rotation are not tested.
- `snapshot_to()` copies the SQLite database and every payload referenced by its immutable history
  into a sibling content-addressed store. A signed cross-store backup manifest, remote replication,
  incremental backup, and retention/rotation policy are not implemented.
- `verify_integrity()` is explicit. The store does not automatically quarantine a corrupt database on
  startup, distinguish a torn tail from interior corruption, or implement a recovery policy.
- Append-only behavior is enforced by the Python gateway and checked by hashes; SQLite does not yet
  use immutable-record triggers, restricted database roles, signatures, or an external transparency
  log against direct administrative writes.
- Store schema version 1 fails closed when another version is found. There is no forward migration,
  downgrade, retention, compaction, archival, or schema-evolution procedure.
- Branch heads rebuild from immutable Branch and accepted WorldRevision records. Spatial, temporal,
  artifact-catalog, dependency, and GIS projections do not yet have equivalent replay workers.
- Projection receipts and watermarks are typed, but no asynchronous projector or read-your-write
  coordination service is implemented.
- Payload bytes and SQLite records use separate durability transactions. A failed record append may
  leave an orphan payload. Promotion provenance, decision, revision, and branch-head CAS now share
  one SQLite transaction, so stale or invalid promotions do not leave provenance records.
- A store may ingest non-authoritative payload-bearing material without a configured local payload
  verifier for synchronization use, but integrity verification, promotion, and authoritative query
  fail closed until the verifier is present.
- Payload receipts are returned by the filesystem CAS but are not themselves immutable records in
  the SQLite authority or a replicated catalog.

## Temporal and state semantics

- The prototype assigns store-owned transaction sequence/time and supports revision selection by
  valid time and known-at sequence. It does not yet implement complete claim-level bitemporal state.
- There is no transaction wall-clock query, derived transaction interval table, general temporal
  join, heterogeneous claim-validity resolver, or first-observed/first-verified query service.
- The immutable QueryRequest and QueryLens bind region, policy, representation, resolution, frame,
  units, valid time, known-at sequence, and exact result, but current `query_revision` SQL evaluates
  only world/site/branch, revision valid interval, known-at sequence, state kinds, and durable
  supersession/invalidation.
- Structured provenance closes the golden material-record graph, but legacy `TwinStore`,
  `TerrainMemory`, `TransactionLog`, and route-level audit paths remain incomplete or free-text.
- Golden provenance uses deterministic placeholder hashes for some calibration and transform
  artifacts. Structural closure is demonstrated; asset authenticity is not.
- Attestation key IDs are stored metadata, not verified signatures or hardware roots of trust.
- Hypothesis and conflict records are appendable through the authority gateway, but no integrated
  scenario yet demonstrates durable competing-hypothesis evolution and later resolution.
- `TerrainMemory.revert_to` truncates later retained history; it remains unsuitable as the research
  rollback model.
- `TerrainMemory` chain metadata does not hash the complete sparse spatial delta; summary-chain
  verification can survive spatial-history tampering. The UltraBuild payload CAS does not
  retroactively repair that legacy history.
- `WorldStateService` carries global latest identities; an independent probe linked a nondefault site
  transaction to the default Haworth observed twin. That service is not yet isolated behind the new
  gateway.
- Simulated run deltas and observed patches can still both affect the legacy planner surface without
  branch-isolated reconciliation.
- The golden planner decision records its exact revision and query lens; existing live planners do
  not consistently do so.
- Derived-layer and dependent-plan invalidation after terrain correction remain incomplete.

## Reconciliation

- The UltraBuild `commit_promotion` path atomically gates PROMOTE decisions and accepted revisions,
  but the legacy `POST /twin/resync` path is not wired through it.
- The golden candidate uses a plain mean of one admissible observation. Source-specific/per-cell
  uncertainty and alternative robust aggregates are not integrated into a live reconciliation
  engine.
- Action-derived edges express possible dependence, not measured covariance.
- Relabelled duplicate evidence may be indistinguishable without verified source attestation.
- The no-physics regime, miscalibrated sensors, fabricated action overlap, partial coverage, and
  worst-covered-cell behavior have documented failure regions.
- The schemas permit PROMOTE/REJECT/ABSTAIN and durable conflicts/hypotheses, but the golden graph
  exercises only one successful PROMOTE and a few invalid/stale promotion failures.
- An older reconciliation contract treats a fresh observation as ground truth and conflicts with the
  newer uncertain/stale-evidence semantics; it must not govern the new path.
- Physics evidence is represented in contracts but the golden promotion does not provide a
  physics-gating ablation or validate Barrier 6.

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
  the UltraBuild promotion path end to end.
- No communication-loss or multi-robot map-synchronization workflow uses the authoritative store.

## Operations and reproducibility

- The repository license is all-rights-reserved, while some existing text promises an open release or
  calls the repository CC0. A redistributable research package is not yet resolved.
- Dataset and third-party licenses vary; not every external source is bundled.
- README requirement counts conflict with the generated requirements manifest/status.
- The refreshed development lock installs successfully into a new ignored UltraBuild virtual
  environment. This verifies dependency reconstruction for foundation checks, not a frozen
  experiment container or cross-platform replication.
- Canonical hashes use the Python `json.dumps(sort_keys=True, allow_nan=False)` profile.
  Cross-language numeric, Unicode, and negative-zero equivalence is not claimed; an RFC 8785 or
  explicitly equivalent profile plus ROS/Godot/database test vectors is required before
  adapter-generated IDs become authoritative.
- Receipt timestamps use a supplied process clock; production monotonicity across clock rollback is
  not guaranteed by the timestamp, although the SQLite sequence remains authoritative.
- Performance budgets are targets; no integrated latency, storage-growth, map-scale, robot-scale, or
  version-scale report exists.
- The root package now declares the required `stewie-bodies` distribution. A clean-wheel smoke test
  covers dependency resolution from a local wheelhouse, but publication to an external package index
  and installation on other operating systems remain unverified.
- The new implementation and documentation are working-tree artifacts until committed, frozen, and
  independently reproduced.

Nothing in the current repository supports flight certification, mission readiness, unsupervised
physical deployment, or broad cross-domain superiority.
