# Provenance model

**Artifact ID:** `ART-PROVENANCE`
**Producer node:** `WS-030`
**Consumers:** `ARCH-020`, `WS-040`, `WS-050`, `VERT-010`, `EXP-010`, `DISS-010`
**Status:** structured provenance closure implemented for the UltraBuild golden graph and self-tested;
system-wide lineage queries and source attestation remain partial.

## Model

STEWIE specializes the W3C PROV entity/activity/agent model rather than inventing an incompatible
lineage vocabulary. World-state claims and payloads are entities; sensing, transforming,
reconciling, verifying, planning, and executing are activities; robots, sensors, software, operators,
and reviewers are agents.

Hashing has four distinct meanings in the implemented authority boundary:

- a payload SHA-256 identifies immutable bytes in the filesystem content-addressed store;
- `submitted_record_hash` in a provenance subject closes over the domain record before the store adds
  transaction fields;
- `submission_hash` in an append receipt closes over the complete untrusted submission envelope; and
- the stored `content_hash` closes over the completed record, including store-owned transaction time.

These hashes provide content identity, tamper detection, and replay checks. They do not prove source
authenticity, calibrated truth, or that a reported physical event occurred.

## Implemented structured bundle

`provenance_bundle.schema.json` requires:

- one subject naming the domain record ID, schema, record entity, submitted-record hash, generating
  activity, and responsible agent;
- typed agents with qualified attestation, hardware, and firmware fields;
- activities with kind, agent, pipeline identity, algorithm version, package version,
  repository-discovered, build-attested, externally declared, or unavailable Git identity,
  dirty-state status, configuration hash, seed where applicable, and start/end times;
- typed entities with content hash and media type;
- W3C-PROV-aligned relations;
- transform records with source/target frames, transform payload hash, and valid time;
- calibration records with instrument, payload hash, valid time, status, and reason for unknown or
  out-of-domain state; and
- optional payload and coverage entities linked by digest.

Unknown identity fields are represented explicitly with a reason code; the schema does not permit a
silent guessed value.

The repository semantic validator additionally closes a referenced bundle against its subject:

- bundle and subject record IDs and record schemas must match;
- `submitted_record_hash` must match the subject record's canonical submitted form;
- world and site must match across the reference;
- payload and coverage hashes must match;
- evidence source agent and algorithm version must be represented;
- required transform-chain identity must be represented; and
- known calibration identities in source and uncertainty records must be represented;
- every activity pipeline, transform frame, calibration instrument, and source-agent
  hardware/firmware identity must close to a typed entity; and
- provenance must be transactionally earlier than its subject and every bundle subject must link
  back to exactly that bundle.

Reference ordering is enforced by transaction sequence. Provenance may be staged immediately before
its subject in the same atomic append batch, so the combined record graph is complete before commit.

## Required claim lineage

The target lineage for every material state claim includes:

- claim, event, version, world, branch, and region IDs;
- robot, sensor, source, and submitting identity;
- source hardware and firmware where applicable;
- processing pipeline and algorithm build/version;
- calibration artifact/version and validity interval;
- source frame, target frame, transform chain, CRS, axes, units, and resolution;
- observation/valid time, source clock, and uncertainty;
- receipt/transaction time assigned by the store;
- payload and coverage-mask content hashes;
- typed uncertainty model and components;
- input claim/artifact IDs and transformation activity;
- physical model/configuration if physics evidence participates;
- reconciliation policy/version, decision, reason codes, and reviewer;
- human intervention, reason, before/after IDs, and authorization;
- code commit, environment lock, configuration digest, seed, and experiment ID; and
- downstream decisions, derived layers, supersessions, and invalidations.

The implemented schemas distribute these fields across the provenance bundle and subject record.
Not every target field is populated by the golden builder, and not every legacy record type has been
migrated.

## Provenance graph

A material record and its bundle form this shape:

```text
responsible Agent --> generation Activity --> submitted record Entity
                           ^
raw payload Entity --used--+

transform/calibration node IDs --bound by provenance subject--+
coverage Entity and digest ------bound by provenance subject--+--> submitted record Entity
                                                                  |
                                                store sequence/time + final content hash
                                                                  |
                                                                  v
                                                         immutable stored record
```

Reconciliation decisions and accepted revisions each have their own bundle. Their domain contracts
then preserve candidate, evidence, action, policy, and decision links. Query requests and lenses
preserve the temporal/spatial selector and exact result; planner decisions preserve the lens and
revision; autonomous actions preserve the planner decision.

## Mutation protocol

### Ordinary material records

1. Write and verify payload bytes in the content-addressed payload store, if required.
2. Construct the provenance bundle over the submitted domain record.
3. Submit bundle and subject in one `append_batch`.
4. Let the store add transaction sequence/time and final hashes.
5. Validate the complete durable-plus-staged graph and local payload prerequisites.
6. Commit both records and exact idempotency receipts or neither.

### Promotion

1. Submit the decision provenance bundle, revision provenance bundle, PROMOTE decision, and accepted
   revision together to `commit_promotion`.
2. Revalidate their semantic closure and the full candidate/decision/revision graph inside one
   transaction.
3. Atomically append all four records and compare-and-swap the accepted branch head.
4. Return a typed CAS receipt naming the append receipts.

A missing, invalid, late, stale, or semantically disconnected provenance bundle prevents the
authoritative promotion without persisting any of the four records.

## Payload provenance

`ContentAddressedPayloadStore` returns `payload_receipt.schema.json`, including digest, media type,
byte size, relative CAS path, duplicate flag, and file/directory fsync evidence. The record gateway
verifies referenced bytes and declared size before authoritative promotion and authoritative query.
`verify_integrity()` repeats those checks over payload-bearing durable history and fails closed when
no payload verifier is configured.

The payload receipt itself is not currently an immutable domain record in SQLite, and the payload
write is not transactionally atomic with the record append. Orphan payloads are therefore possible;
dangling durable record references fail closed in the configured prototype.

## Queries and integrity checks

The current store supports record lookup and schema/known-at enumeration. `verify_integrity()` checks:

- stored record schema and content hash;
- unique, ordered transaction sequences and nondecreasing receipt timestamps;
- all cross-record references and provenance closure;
- activity-to-pipeline, transform-to-frame, calibration-to-instrument, and source-agent semantic
  closure;
- append and CAS receipt schemas;
- payload availability, size, and digest for payload-bearing history;
- reproducibility of every candidate raster and coverage mask from admitted observation payloads;
- rebuildable branch-head equivalence to immutable history.

The target lineage service must additionally support:

- tracing any claim to raw payload, calibration, transforms, code, configuration, and source;
- listing claims derived from an invalid calibration or algorithm version;
- listing decisions that consumed a superseded claim or revision;
- reconstructing every reconciliation evidence set and policy input;
- identifying all artifacts and seeds used by an experiment result; and
- reporting missing-lineage fields by claim/state kind.

Those indexed lineage queries are not yet implemented as a service.

## Completeness metric

Required fields are weighted by state kind. A promoted claim must not silently omit identity, time,
frame, payload, uncertainty, policy, or decision lineage. Completeness will be reported as:

- complete claims / material claims;
- missing required fields by field and state kind;
- broken graph edges;
- missing or unverifiable payload hashes;
- replayable decisions / decisions; and
- claims relying on explicit unknowns.

The golden graph is a positive closure fixture, not a measured completeness result over STEWIE.

## Implemented evidence

The 18-record golden graph includes structured bundles for the observation, external action,
candidate, promotion decision, accepted revision, planner decision, and planned autonomous action.
The authority test revalidates the complete graph before and after cold restore. Candidate mutation
tests demonstrate that changing its frame, uncertainty components, or valid time breaks the bound
contract rather than silently preserving promotion eligibility. Payload tests detect post-write byte
corruption.

This evidence resolves the prototype provenance-closure construction gap. It does not establish
cryptographic source authenticity, full lineage completeness, experiment reproducibility, or
independent scientific validation.

## Legacy and remaining boundaries

- `TwinStore`, `TerrainMemory`, `TransactionLog`, and `AuditLog` still contain free-text or
  route-level provenance and are not transparently migrated.
- The golden fixture uses deterministic placeholder hashes for some calibration and transform
  artifacts; structural closure is demonstrated, not authenticity of those assets.
- Agent attestation key IDs are data fields, not verified signatures or hardware roots of trust.
- Experiment/environment lock identities and downstream invalidation traversal are not complete
  across all record types.
- No indexed W3C-PROV query engine, retention policy, cross-store payload catalog, or distributed
  provenance synchronization exists.
