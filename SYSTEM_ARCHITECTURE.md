# System architecture

**Artifact ID:** `ART-ARCHITECTURE`
**Producer node:** `ARCH-010`
**Consumers:** `ARCH-020`, all `WS-*`, `VERT-*`, `EXP-*`, `INT-010`
**Status:** authoritative-store prototype implemented and self-tested; pending independent
Barrier-2 and Barrier-3 review.

## Architectural position

STEWIE remains a modular monorepo. The new `stewie/ultrabuild/` package establishes the first
executable authority boundary without requiring a premature service split:

- `AuthoritativeStore` is the only immutable-record append gateway;
- SQLite is the prototype transaction authority, configured for WAL journaling and `FULL`
  synchronization;
- callers submit `stewie.record_submission/1.0` records without transaction or content-identity
  fields;
- the store assigns the monotonic transaction sequence, receipt timestamp, and final record hash;
- accepted-head promotion is a single SQLite transaction containing the promotion decision,
  accepted revision, and compare-and-swap of the rebuildable branch head; and
- spatial payload bytes live in a separate, immutable filesystem content-addressed store.

The append log is authoritative. `branch_heads` and projection watermarks are mutable conveniences,
not independent sources of truth. A head can be reconstructed from immutable branch and accepted
revision records.

“Authority” remains scoped:

- simulation physics is authoritative only for the simulated material transition;
- an observation record is authoritative only as evidence that a named source reported a value;
- a reconciled revision is authoritative only for its world, site, branch, policy, valid interval,
  and known-at sequence;
- planned and predicted states are never observations of physical truth; and
- evaluation reference is authoritative only for scoring and is unavailable to the evaluated path.

## Implemented prototype topology

```text
 Payload bytes ----------------------> Filesystem SHA-256 CAS
                                              |
                                      payload receipt + verification
                                              |
 Domain record draft                           v
        |                             untrusted record submission
        +--------------------------------------+
                                               |
                                               v
                                  Authoritative SQLite gateway
                         schema + full record-graph + payload checks
                         store sequence/time + final canonical hash
                                  |                     |
                         ordinary append         atomic promotion CAS
                                  |                     |
                                  +----------+----------+
                                             |
                              immutable records + typed receipts
                                             |
                  +--------------------------+----------------------+
                  |                          |                      |
          rebuildable branch head     revision query         integrity/replay
                  |               valid_at + known_at seq     and cold snapshot
                  +--------------------------+----------------------+
                                             |
                          query request -> query lens -> plan -> action
                              (each durable record returns through append)
```

The deterministic golden graph contains two branches, observation/action/candidate evidence and
their required provenance bundles, an atomically promoted revision, an immutable query request and
resolved lens, a planning decision bound to that lens/revision, and a resulting autonomous action.
It contains 18 immutable records in one continuous store sequence.

## Bounded contexts and ownership

### Payload authority

`ContentAddressedPayloadStore` owns payload-byte identity and durability. It writes a temporary file,
fsyncs it, atomically replaces the SHA-256 target, fsyncs the containing directory, and returns a
typed payload receipt. With `require_local_payloads=True`, the SQLite gateway rejects records whose
referenced payload or coverage bytes are missing, corrupt, or the wrong declared size.

Payload persistence and SQLite append are separate transactions. A failed record append may leave an
unreferenced payload, but a committed record cannot reference a missing or corrupt required local
payload in the enforced prototype configuration.

### Immutable record authority

`AuthoritativeStore` owns:

- canonical record completion and hashing;
- a gap-free monotonic sequence across reopen;
- exact idempotency-key comparison against the canonical submission hash;
- immutable record insertion and durable append receipts;
- full cross-record semantic validation before commit;
- promotion-operation idempotency and typed CAS receipts; and
- the branch-head and projection-watermark tables.

Callers cannot submit `transaction_time`, `recorded_at`, or `content_hash`. Ordinary `append` and
`append_batch` also reject PROMOTE decisions and accepted-state revisions, so those records cannot
bypass `commit_promotion`.

### Reconciliation and promotion

Reconciliation owns candidate and decision construction but has no accepted-state mutation
authority. A candidate binds its spatial contract, valid time, uncertainty, payload, and coverage
through `state_contract_hash`. Cross-record validation requires the promotion decision and revision
to preserve that contract.

`commit_promotion` requires an approved or explicitly not-required PROMOTE review, matching
decision/revision links, matching world/site/branch/policy, the pinned prior head, and a contiguous
branch revision sequence. A stale or invalid request returns a typed non-applied CAS receipt and
leaves neither decision nor revision partially appended.

### Query, planning, and action

The implemented revision resolver accepts explicit `world_id`, `site_id`, `branch_id`, `valid_at`,
`known_at_sequence`, and requested state kinds. Supersession or invalidation affects only queries
whose known-at sequence includes the durable event. The golden path then stores:

1. the full `QueryRequest`, including region, representation, resolution, frame, units, policy,
   valid time, and known-at sequence;
2. the resolved `QueryLens`, including exact revision, state kind, payload, coverage, and projection
   sequence;
3. the planner `DecisionRecord`, including exact lens and revision IDs; and
4. the linked autonomous `ActionEvent`.

The richer spatial lens is therefore durable in the record graph, although the current
`query_revision` SQL selector does not yet evaluate every request field.

### Integration and presentation

Legacy ROS 2, GIS/QGIS, Godot/Gazebo, FastAPI, planner, and UI paths remain adapters and consumers.
They are not yet wired through this gateway and must not be described as sharing the new authority
boundary. Visualization remains non-authoritative.

## Write protocols

### Ordinary append

1. Persist referenced payload bytes and retain the typed payload receipt when applicable.
2. Normalize a domain draft into `record_submission.schema.json`; omit store-owned fields.
3. Validate the submission schema, selected record schema/version, and record identity.
4. Within `BEGIN IMMEDIATE`, assign the next sequence and timestamp, calculate the final hash, verify
   payload prerequisites, and validate the combined durable-plus-staged record graph.
5. Insert canonical record bytes and the exact-idempotency mapping.
6. Commit before returning `append_receipt.schema.json`.

Provenance and its subject may be submitted in one batch. The full graph is checked before any
member of that batch becomes durable.

### Accepted-head promotion

1. Pin expected revision ID and branch sequence.
2. Submit exactly one PROMOTE decision and one accepted revision to `commit_promotion`.
3. Recheck review status, cross-links, state contract, policy, world/site, branch, prior head, and
   contiguous revision sequence inside the write transaction.
4. Append both completed records through the same private append primitive.
5. Update `branch_heads` with a conditional compare-and-swap.
6. Commit the records, head, append receipts, and operation receipt together.

Two concurrent store instances targeting one head were tested: exactly one promotion was durable and
the loser received `stale_head`.

## Projection, restore, and integrity semantics

- `branch_heads` is synchronously maintained but derived exclusively from immutable branch and
  accepted-revision records.
- `rebuild_projections()` currently rebuilds branch heads and clears projection watermarks; it is not
  yet a general spatial/temporal/catalog projector.
- `projection_receipt.schema.json` exposes requested sequence, projected sequence, lag, and freshness
  status.
- `snapshot_to()` uses SQLite backup to produce a consistent cold-restorable database.
- `verify_integrity()` revalidates canonical records, hashes, transaction ordering, full graph
  semantics, append/CAS receipts, local payloads, sequence metadata, and derived branch heads.
- Integrity verification is explicit; automatic startup quarantine or recovery after detected
  corruption is not implemented.

## Typed integration contracts

The authority boundary adds five registered contracts:

| Contract | Purpose |
|---|---|
| `record_submission.schema.json` | Untrusted domain record plus producer and exact idempotency identity; forbids store-owned fields |
| `append_receipt.schema.json` | Durable immutable-record identity, sequence, hash, and SQLite durability mode |
| `cas_receipt.schema.json` | Applied, stale, invalid, or replayed accepted-head operation with expected/observed/proposed heads |
| `projection_receipt.schema.json` | Explicit projection sequence, lag, and freshness |
| `payload_receipt.schema.json` | SHA-256 payload identity, byte size, location, and fsync result |

The existing domain contracts cover branches, observations, actions, dependencies, provenance,
candidates, decisions, conflicts, hypotheses, revisions, supersession, query lenses, and experiment
scenarios. Repository semantic validation enforces joins that JSON Schema cannot express, including
world/site/reference consistency, ordering, provenance closure, observation-only candidate
construction, promotion contract preservation, and query/plan/action linkage.

## Evidence and nonclaims

`stewie/ultrabuild/test_store.py` currently exercises:

- a valid 18-record golden graph and cold SQLite restore;
- payload deduplication and corruption detection;
- store-owned transaction fields and exact idempotency;
- monotonic transaction sequence after reopen;
- concurrent promotion with exactly one winner;
- no partial records from a pending-review promotion;
- historical known-at behavior across durable invalidation;
- deterministic branch-head rebuild after deliberate projection corruption; and
- rejection of spatial, uncertainty, and valid-time candidate mutations.

These tests support an implemented, self-tested, single-node research prototype. They do not accept
Barrier 2 or Barrier 3, demonstrate distributed synchronization, validate a live robot path, prove
full bitemporal query semantics, establish performance budgets, or support a scientific-effectiveness
claim.
