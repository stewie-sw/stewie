# Construction-event ledger and accepted-world publication contract

**Status:** target contract, accepted architecture; operational implementation is incomplete  
**Version:** 0.1-draft · 2026-07-28  
**Requirements:** DA-07, DA-08, DA-09, DA-10  
**Decision:** [ADR-0008](adr/0008-construction-event-ledger-and-gis-projections.md)

## 1. Purpose and claim boundary

STEWIE must retain every executed terrain-changing action and every observation used to update the
shared world. It must not represent each action as an independently authoritative GIS layer.

The canonical record is an immutable, spatial-temporal event and evidence ledger. The conserved
physics authority owns simulated physical mutation. The accepted world is a versioned belief
published only by a recorded promotion decision. GIS, PostGIS, QGIS, rasters, vector tiles, and
operator dashboards are derived read models that can be deleted and rebuilt from the ledger and
accepted-world versions.

This contract defines the target operational seam. The existing `stewie/twin/promotion.py` research
rule, `TwinStore`, `TerrainMemory`, and hash-chained `WorldStateService` transaction log supply parts
of it, but `POST /twin/resync` does not yet execute this contract end to end.

## 2. Authority model

| Record or state | Authority | May mutate it | Persistence rule |
|---|---|---|---|
| Conserved simulated terrain | Selected conserving `PhysicsBackend` | Physics verbs following an eligible command | Base snapshot plus immutable executed construction events; before/after hashes and mass balance required |
| Raw sensor artifact | Sensor/ingest source for its emitted bytes only | Nobody after receipt | Content-addressed blob; ledger metadata is append-only |
| Observation evidence | Estimator claim, not terrain truth | Nobody in place; corrections are new records | Immutable record bound to source, time, frame, calibration, coverage, uncertainty, and artifact hashes |
| Possible-dependency graph | Conservative evidence relation, not proof of causation | Nobody in place; revised graphs are new records | Immutable, versioned graph bound to an exact evidence set |
| Promotion decision | Decision service | Nobody after commit | Immutable outcome and reasons, including refusals and abstentions |
| Accepted world | Acceptance service | Only by publishing a new child version | Immutable version plus atomic branch-head compare-and-swap |
| GIS/PostGIS/QGIS layer | Projector | Projector may rebuild or replace it | Disposable read model with source version and ledger high-water mark |

“Observed,” “predicted,” “simulated,” and “accepted” are different epistemic states. A database row,
map layer, or operator edit does not become accepted merely because it is durable or visible.

## 3. Canonical record envelope

Every ledger record carries:

| Field | Contract |
|---|---|
| `schema_version` | Semver-like contract identifier; readers refuse unsupported major versions |
| `record_id` | Globally unique, immutable identifier |
| `record_kind` | Closed enum: `construction_event`, `observation_evidence`, `dependency_graph`, `promotion_candidate`, `promotion_decision`, `accepted_world_version`, `correction`, `tombstone` |
| `site_id`, `mission_id` | Stable identifiers; never inferred from a filename |
| `environment_mode` | DEV, TRAINING, REHEARSAL, LIVE, REPLAY, or ARCHIVE |
| `branch_id` | Actual/conserved, observed, predicted, simulated, design, what-if, or accepted branch identifier |
| `sequence` | Monotonic per-site/per-branch sequence allocated at commit |
| `recorded_at_utc` | Server receive/commit time in UTC |
| `actor` | Authenticated human or service principal plus role |
| `idempotency_key` | Caller-stable key scoped to actor, endpoint, and mission |
| `prev_record_hash` | Hash-chain predecessor for the same ledger stream |
| `payload_sha256` | Hash of canonical payload bytes |
| `record_sha256` | Hash of canonical envelope plus payload |
| `signature` | Optional now; required before LIVE external ingest |

Time is never a single ambiguous field. Records distinguish commanded time, execution start/end,
sensor acquisition time, observation validity interval, receive time, and commit time as applicable.

## 4. Required payloads

### 4.1 `construction_event`

An executed construction event records what the authority says happened, not merely what was
commanded:

- `command_id`, `execution_id`, `task_id`, `asset_id`, and action type;
- commanded parameters separately from executed parameters;
- execution start/end and ordering/causal predecessor identifiers;
- lunar CRS or named local frame, transform identifier, geometry/footprint, and cell-index convention;
- material removed, transported, deposited, lost, and retained, with units;
- authority backend ID/version/configuration and calibration provenance;
- parent conserved-state hash, delta artifact URI/hash, child conserved-state hash, and mass-balance
  residual with tolerance;
- telemetry/raw-artifact references needed to audit execution; and
- completion, partial execution, abort, or fault status.

A command is not a construction event until execution evidence exists. Retries with the same
idempotency key return the original record and cannot apply the terrain delta twice.

### 4.2 `observation_evidence`

Each observation records:

- `observation_id`, `source_id`, `asset_id`, sensor ID/model/serial where available, estimator ID and
  code/configuration hash;
- acquisition time, validity interval, receive time, and clock/timebase quality;
- frame ID, lunar CRS where spatial, transform-chain identifiers and transform covariance;
- calibration identifier/version/status and declared uncertainty with units;
- coverage-mask URI/hash, values URI/hash, nodata semantics, resolution, shape, and spatial extent;
- raw artifact URI/hash and processing lineage;
- the construction-event IDs, localization solution, registration process, preprocessing product, or
  other provenance used to assess possible dependence; and
- authentication and source-identity evidence.

Missing values remain missing. Physics predictions, priors, interpolation, and adjacent observations
cannot fill unobserved cells inside an observation record.

### 4.3 `dependency_graph`

A graph is bound to an exact ordered set of admissible observation IDs and contains:

- pair-specific, per-cell edge-mask artifact references;
- the reason for each possible-dependency edge, such as shared action, clock, localization,
  registration, calibration, preprocessing, or source lineage;
- graph-construction algorithm/version/configuration;
- edge validity interval and coverage domain;
- calibration/evaluation evidence where available; and
- an explicit `relation_semantics = possible_dependency`.

Absence of an edge means independence is permitted only when the configured policy and evidence
justify that interpretation. Shared action is provenance indicating possible dependence; the graph
must not claim that shared action itself caused a sensor error.

### 4.4 `promotion_candidate`

A candidate binds, by identifier and hash:

- parent accepted-world version;
- admissible observations after identity, time, frame, shape, coverage, and finiteness checks;
- dependency graph;
- optional physics prediction offered only to the veto path;
- region and tolerance policy;
- estimator and decision-rule version/configuration; and
- candidate-construction code hash.

Changing any input creates a new candidate. A candidate never points to “latest.”

### 4.5 `promotion_decision`

The decision records:

- candidate ID and all input hashes;
- `promote`, `abstain`, or `reject`;
- machine-readable reason codes and operator-readable explanation;
- accepted mask and accepted-value artifact hash;
- proof-facing diagnostics, including component support, variance proxy \(V\), tolerance \(\tau\),
  residual diagnostics, and assumption/premise checks;
- the exact software version and configuration; and
- reviewer/override identity and rationale if policy permits a manual action.

For the dissertation rule, promoted values are the arithmetic mean of exactly the
metadata-admissible observations present at each cell. Physics may veto but cannot construct, select,
weight, interpolate, or fill the accepted patch. A manual override is a separately typed decision; it
cannot masquerade as an algorithmic promotion.

### 4.6 `accepted_world_version`

Each accepted-world version contains:

- immutable version ID and parent version ID;
- promotion-decision ID;
- accepted delta/mask artifact URI and hash;
- resulting accepted-world content hash and optional snapshot URI/hash;
- validity time, commit time, site, frame/CRS, and units;
- branch-head transaction ID and ledger high-water marks; and
- projection status, which is informative and never gates the canonical commit.

The accepted branch head is a mutable pointer to an immutable version. It is the only mutable datum
in this path and changes by compare-and-swap.

## 5. Transaction and concurrency semantics

### 5.1 Construction mutation

One authority transaction validates the command and mode, checks the expected parent conserved-state
hash, executes exactly once, appends the `construction_event`, persists the resulting conserved-state
version or deterministic delta, and advances the conserved branch head. Failure before commit leaves
neither the event nor the child state visible.

### 5.2 Accepted-world publication

One publication transaction:

1. validates authenticated authority and environment mode;
2. loads immutable candidate inputs by ID and hash;
3. locks or compare-and-swaps the expected accepted parent;
4. evaluates the selected rule;
5. appends the decision, including abstain/reject outcomes;
6. if promoted, appends the accepted-world child version and advances the branch head; and
7. writes an outbox record for projectors before committing.

The decision and accepted version are never split across commits. A projector failure cannot roll
back or alter the accepted version; the outbox retries until all declared projections reach the
version.

### 5.3 Idempotency and conflicts

- Same actor/endpoint/idempotency key and same payload: return the original result.
- Same key and different payload: `409 IDEMPOTENCY_CONFLICT`.
- Stale parent version or branch head: `409 STALE_WORLD_VERSION` with the current version ID.
- Concurrent non-overlapping candidates are still serialized at publication unless a future merge
  policy proves commutativity.
- No last-write-wins behavior is permitted on conserved or accepted terrain.

## 6. API behavior

The target operational endpoints may be composed differently, but they must expose these semantics:

| Operation | Success | Refusal/error behavior |
|---|---|---|
| Append executed action/evidence | `201` first commit; `200` idempotent replay | `400` malformed; `401/403` identity/role; `409` key or parent conflict; `422` invalid frame/time/calibration/coverage |
| Construct candidate | `201` immutable candidate | `422` duplicate source, stale evidence, unknown dependency, incompatible frame/shape, or nonfinite metadata |
| Decide/publish | `200` decision and optional accepted version | Abstain/reject are successful recorded decisions, not server errors; `409` stale parent; `503` only when canonical persistence is unavailable |
| Read accepted state | `200` immutable version or named branch head | Response identifies version/hash; never returns an unlabeled blend of observed, predicted, and accepted |
| Read GIS projection | `200` layer plus provenance | Response identifies accepted version and projector high-water mark; stale projection is labeled or refused by caller policy |

The current direct `POST /twin/resync` mutation must either become candidate construction followed by
this decision path or be restricted to a non-accepted observed branch. It must not remain an unlabeled
accepted-state shortcut.

## 7. GIS projection contract

Every projected layer carries:

- `projection_id`, projector software/configuration hash, generated time;
- source ledger range and accepted-world version/hash;
- source branch and epistemic class;
- lunar CRS/frame, transform, resolution, resampling method, nodata, and units;
- lineage links to events/evidence/decisions;
- planning, release, and execute eligibility; and
- freshness and rebuild status.

Recommended operator layers are stable query products—current accepted terrain, construction-event
footprints by mission/time/action, observation coverage, uncertainty, open candidates, abstentions,
and accepted deltas—not one permanently loaded layer per robot action. Per-action geometry remains
queryable and can be materialized on demand.

Edits made in QGIS or QWC2 create a proposed intent, annotation, or observation record through a
backend route. Direct database or layer edits never mutate conserved or accepted state.

## 8. Replay, recovery, and retention

A cold restore must:

1. verify every blob hash and ledger chain;
2. rebuild conserved terrain from a declared base plus construction events;
3. rebuild every accepted branch from recorded decisions and accepted deltas;
4. reproduce the same branch-head content hashes;
5. regenerate all GIS/read projections from their manifests; and
6. report missing, corrupt, or unsupported records without silently skipping them.

Canonical event, evidence-metadata, decision, and accepted-version records are retained for the
mission/archive lifetime. Raw high-rate data may use a documented tiered-retention policy, but its
content hash, provenance, disposition, and any derived record that depended on it remain. Corrections
append new records; deletion requests use governed tombstones and never rewrite the chain.

## 9. Security and audit

- All writes require authenticated service or human identity and the central environment-mode guard.
- LIVE ingest additionally requires source authentication, anti-replay protection, bounded clock
  skew, schema/version allowlists, and signature verification.
- Blob access follows least privilege; secrets and personal data are not embedded in ledger payloads.
- Operator override, correction, export, retention, and branch-head changes are audit events.
- Hashes detect tampering but do not prove source truth; calibration and identity remain explicit
  empirical/security premises.

## 10. Acceptance gates

DA-07 through DA-10 are complete only when automated tests prove:

1. a two-robot executed construction sequence creates immutable events with commanded/executed
   separation, valid frames, before/after hashes, and conserved mass;
2. observations are durably bound to sensor/source identity, validity, calibration, transform,
   coverage, raw artifacts, construction provenance, and a versioned possible-dependency graph;
3. the live ingest endpoint cannot advance accepted terrain without a recorded decision;
4. physics changes decisions but never promoted bytes or coverage, including missing cells;
5. duplicate, stale, nonfinite, frame-incompatible, or dependency-unknown inputs fail closed;
6. an injected failure cannot leave a decision without its accepted version or vice versa;
7. idempotent retry applies neither a construction delta nor an accepted delta twice;
8. two concurrent publications cannot silently overwrite each other;
9. a complete cold replay reproduces conserved and accepted hashes byte-for-byte;
10. deleting every PostGIS/QGIS projection and rebuilding it changes no canonical hash;
11. every GIS response names its accepted version, ledger high-water mark, CRS, units, and epistemic
    class; and
12. mode/role isolation prevents TRAINING, REPLAY, ARCHIVE, clients, and projectors from writing the
    LIVE accepted branch.

Until those gates pass, this document describes the target architecture, not a shipped capability.
