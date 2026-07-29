# Data model

**Artifact ID:** `ART-DATA-MODEL`
**Producer node:** `WS-010`
**Consumers:** `ARCH-020`, `WS-020`, `WS-030`, `WS-040`, `WS-050`, `VERT-010`
**Status:** conceptual v0.1; machine-readable schema is a Barrier-2 output.

## Design rules

- Separate immutable evidence from mutable projections.
- Identify every object, version, branch, frame, unit, and schema.
- Represent missing coverage with a mask, not a numeric sentinel in accepted values.
- Use half-open intervals `[start, end)`; an omitted end means open.
- Store large raster/mesh/voxel payloads by content hash, with metadata and indexes in records.
- Never use one scalar “confidence” as a substitute for typed uncertainty.

The Barrier-2 validator uses a provisional Python canonical-JSON profile: UTF-8, sorted object keys,
no insignificant whitespace, and non-finite numbers forbidden. It is valid only for the single-
language reference slice. Cross-language authority requires a reviewed RFC 8785 (JCS) profile or an
equally explicit alternative with conformance vectors covering Unicode, exponents, and negative zero.

## Core records

### `SpatialExtent`

| Field | Type | Rule |
|---|---|---|
| `extent_id` | UUID/content ID | Stable identity |
| `representation` | enum | `raster_2_5d`, `point_set`, `mesh`, `voxel`, `object`, `region` |
| `crs` | string | Required; e.g. `IAU_2015:30135` |
| `frame_id` | string | Required local/robot transform anchor |
| `axis_order` | array | Explicit axes |
| `units` | object | Per-axis/value SI units |
| `bounds` | geometry/array | Finite, ordered |
| `resolution` | object | Spatial scale or level |

### `EvidenceClaim`

| Field | Type | Rule |
|---|---|---|
| `claim_id` | UUID | Immutable |
| `source_id` | string | Globally unique source identity |
| `source_kind` | enum | `observation`, `physics_prediction`, `action`, `human_assertion` |
| `state_kind` | ontology enum | Usually `observed` or `predicted` |
| `extent_id` | reference | Required |
| `payload_hash` | SHA-256 | Immutable payload |
| `coverage_hash` | SHA-256 | Explicit boolean mask |
| `valid_time` | interval | Physical assertion time |
| `transaction_time` | sequence + instant | Store-maintained append identity; end is derived from a later immutable supersession event |
| `uncertainty` | typed object | Model plus parameters |
| `provenance_bundle_id` | reference | Required |
| `predecessor_claim_ids` | array | Derivation/supersession inputs |

### `ActionEvent`

Adds origin, immutable planning-decision/action linkage where autonomous, actor/robot, command and
execution IDs, planned and executed spatial effects, start/end valid times, receipt transaction
time, capability/tool, material transfer, energy, and evidence for actual execution. Planned
effects and observed effects are separate payloads. External/imported actions explicitly carry a
null decision link rather than pretending STEWIE planned them.

### `DependencyEdge`

`(left_source_id, right_source_id, evaluation_visibility, extent/coverage_hash, valid_interval,
basis, derivation_activity, uncertainty, status)`

`basis` initially permits `shared_action_extent`, `shared_pipeline`, `shared_calibration`,
`shared_localization`, `communication_copy`, and `unknown`. An edge means “errors may be dependent”;
it is not a covariance coefficient. An `independent_error_oracle` edge is evaluator-only and is
rejected from candidate construction.

### `StateCandidate`

Contains a pinned prior version, the admitted observation IDs, excluded evidence with reasons,
observation-only aggregate payload/mask, support/variance fields, physical comparisons, and policy
version. It is proposed state and is never current accepted state by construction.

### `ReconciliationDecision`

| Field | Type |
|---|---|
| `decision_id` | UUID |
| `candidate_id` | reference |
| `decision` | `PROMOTE`, `REJECT`, `ABSTAIN`, `RETAIN_HYPOTHESES` |
| `reason_codes` | non-empty array |
| `policy_id/version` | string |
| `review_status` | enum |
| `valid_time` / `transaction_time` | intervals |
| `resulting_version_id` | nullable reference |
| `retained_hypothesis_ids` | array |
| `metrics` | residual/support/calibration fields |

### `WorldStateVersion`

An immutable branch head:

`version_id, branch_id, parent_version_ids, transaction_seq, valid_extent, region_id,
representation/resolution/frame/units, state_claim_refs, event_refs, provenance_bundle_id,
invalidated_derived_refs, content_hash`.

The version references claims; it does not duplicate all payloads. Merge versions may have multiple
parents but cannot erase unresolved claims.

### `SupersessionEvent`

An immutable event naming the target record, successor where applicable, evidence and provenance,
reason codes, and store-assigned transaction sequence/instant. Transaction interval ends are derived
from these events; old claims and revisions never acquire a mutable `closed_at` field.

### `DecisionRecord`

Records mission/task/robot, exact query lens and `version_id`, alternatives, constraints, chosen
action, expected outcomes, value-of-information result, and approval. It is an immutable
planning-time record. Later dispatch, reported execution, observation, failure, or cancellation
facts are new `ActionEvent` records that refer back to it; they never mutate the decision.

### `ArtifactRecord`

Records content hash, media type, schema, producer graph node, code commit, environment lock,
configuration digest, seed, inputs, command, timestamps, license/source, reviewer decisions, and
retention location.

## Relationships

```text
Agent/Sensor --generated--> EvidenceClaim --used--> StateCandidate
ActionEvent --derived--> DependencyEdge -----------^
PhysicsModel --generated--> EvidenceClaim ----------^
StateCandidate --wasEvaluatedBy--> ReconciliationDecision
ReconciliationDecision --generated--> WorldStateVersion
WorldStateVersion --wasUsedBy--> DecisionRecord
DecisionRecord --generated--> ActionEvent
```

## Representation policy

| State | Primary form | Reason | Conversion loss to declare |
|---|---|---|---|
| Global/regional terrain | Geo-referenced raster pyramid/COG projection | Efficient spatial/multiresolution query | Resampling and vertical datum |
| Local surface | 2.5-D elevation + uncertainty + mask | Current mechanism and grading tasks | Overhangs/voids |
| Excavation/deposition volume | voxel/SDF or sparse volume | Material volume and undercuts | Voxelization resolution |
| Inspection geometry | point set/mesh | Sensor/reconstruction fidelity | Meshing/filtering |
| Objects/work zones | typed vector/semantic entity | Identity and relationships | Geometry simplification |
| Events/provenance | append-only structured records | Audit/replay/query | None permitted |

The Barrier-3 schema implements only the 2.5-D and event/provenance subset. Other rows are target
contracts, not current implementation claims.
