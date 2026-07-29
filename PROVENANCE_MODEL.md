# Provenance model

**Artifact ID:** `ART-PROVENANCE`
**Producer node:** `WS-030`
**Consumers:** `ARCH-020`, `WS-040`, `WS-050`, `VERT-010`, `EXP-010`, `DISS-010`
**Status:** specified v0.1; current implementation is partial.

## Model

STEWIE specializes the W3C PROV entity/activity/agent model rather than inventing an incompatible
lineage vocabulary. World-state claims and payloads are entities; sensing, transforming,
reconciling, verifying, planning, and executing are activities; robots, sensors, software, operators,
and reviewers are agents.

Hash chains provide tamper evidence and ordering. They do not by themselves provide semantic
provenance, source authenticity, calibrated uncertainty, or proof that an event happened physically.

## Required claim lineage

Every material state claim records:

- claim, event, version, world, branch, and region IDs;
- robot, sensor, source, and submitting identity;
- source hardware/firmware where applicable;
- processing pipeline and algorithm build/version;
- calibration artifact/version and validity interval;
- source frame, target frame, transform chain, CRS, axes, units, and resolution;
- observation/valid time, source clock and uncertainty;
- receipt/transaction time assigned by the store;
- payload and coverage-mask content hashes;
- uncertainty model and parameters;
- input claim/artifact IDs and transformation activity;
- physical model/configuration if physics evidence participates;
- reconciliation policy/version, decision, reason codes, and reviewer;
- human intervention, reason, before/after IDs, and authorization;
- code commit, environment lock, configuration digest, seed, and experiment ID; and
- downstream decisions, derived layers, and invalidations.

Unknown fields are explicit `unknown` values with reason codes. Required unknowns may force ABSTAIN;
they are never replaced with guessed metadata.

## Source identity and authenticity

`source_id` identifies a provenance root, not a caller-provided display name. A source credential
binds robot/sensor/pipeline identity to submissions. Duplicate IDs are rejected. Relabelled duplicate
payloads are detected where content hashes or upstream attestations expose them; otherwise they remain
an explicit source-integrity assumption and fault condition.

## Provenance bundle

A bundle is an immutable graph:

```text
sensor-frame Entity
  --wasGeneratedBy--> observation Activity
  --wasAttributedTo--> sensor/robot Agent
  --wasDerivedFrom--> raw payload Entity
  --wasDerivedFrom--> calibration Entity
  --wasDerivedFrom--> transform Entity
  --usedBy--> reconciliation Activity
  --generated--> candidate/decision/version Entities
```

Bundles are addressable by canonical serialization hash. Large payloads remain in content-addressed
storage and are referenced by digest.

## Mutation protocol

1. Validate identity, schema, time, frame, unit, and hashes.
2. Append mutation intent and provenance inputs durably.
3. Perform the authoritative event/version append.
4. Append result referencing the new version or failure.
5. Update projections asynchronously/replayably.

If steps 1–3 cannot be made atomic in one store, use a durable outbox/intent protocol. An audit or
provenance failure must not leave authoritative state ahead of its record.

## Queries

- trace a claim to raw payload, calibration, transforms, code, and source;
- list claims derived from an invalid calibration or algorithm version;
- list decisions that consumed a superseded claim/version;
- reconstruct the evidence set and policy inputs for a decision;
- identify all artifacts and seeds used by an experiment result;
- compute missing-lineage fields by claim/state kind; and
- verify every content hash and journal chain involved in replay.

## Completeness metric

Required fields are weighted by state kind. A promoted/authoritative claim has no optional identity,
time, frame, payload, uncertainty, or policy fields. Completeness is reported as:

- complete claims / material claims;
- missing required fields by field;
- broken graph edges;
- unverifiable payload hashes;
- replayable decisions / decisions; and
- claims relying on explicit unknowns.

## Current baseline boundary

`TwinStore`, `TerrainMemory`, `TransactionLog`, and `AuditLog` provide useful durable hash-chained
records, but much provenance is a free-text string or route-level metadata. The Barrier-3 work must
add structured bundles without claiming that existing hash chains already satisfy this model.
