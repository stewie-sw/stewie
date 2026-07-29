# Temporal and bitemporal model

**Artifact ID:** `ART-TEMPORAL`
**Producer node:** `WS-020`
**Consumers:** `ARCH-020`, `WS-040`, `WS-050`, `VERT-010`, `EXP-010`
**Status:** transaction-time and revision-level known-at prototype implemented and self-tested;
full bitemporal semantics remain partial and independently unreviewed.

## Time dimensions

### Valid time

When a claim is asserted to describe the modeled physical or simulated world. It is supplied or
derived from source evidence and carries clock identity and uncertainty.

### Transaction time

When STEWIE recorded a claim in the authoritative evidence store. It is assigned monotonically by
the SQLite authority and cannot be supplied by the source. Every stored record contains a positive
store sequence and `recorded_at`; those fields participate in the final content hash. A later
immutable supersession or invalidation event changes resolution at later known-at sequences without
editing the earlier record.

The implemented ordering authority is the integer sequence. `recorded_at` is retained evidence about
receipt time but is not currently a separate wall-clock query axis.

### Event/mission time

Elapsed time within a run. It is useful for simulation and ordering but does not replace either valid
or transaction time.

### Source and receipt clocks

Raw source timestamps and receipt timestamps are retained with clock identity and uncertainty where
the record contract provides them. Converting a source timestamp into valid time is a provenance
activity. Clock-offset estimation and distributed synchronization status remain target semantics.

## Interval rules

- Intervals are half-open `[start, end)`.
- An omitted end means open-ended.
- Point observations use a validity instant plus declared temporal uncertainty or a minimal interval.
- Transaction time is append-only; past records are not edited in place.
- Valid time may be retroactively corrected, but the correction creates a new transaction-time record.
- Non-finite times, inverted intervals, or unknown clocks fail schema or semantic validation.
- Clock ordering alone never proves physical causality.
- A submitted record may not contain `transaction_time`, `recorded_at`, or `content_hash`; only the
  authority gateway completes those fields.
- Store sequences remain monotonic after closing and reopening the database.

## Query lens

Every target state query resolves:

`state(region, valid_at=T, known_at=K, branch=B, policy=P, representation=R)`.

- “What robot A believed at T as of K” filters claims attributed or available to A and both time
  axes.
- “What STEWIE now believes was true at T” uses current transaction time with historical valid time.
- “What did the planner use” reads the immutable query lens stored in `DecisionRecord`.
- “When was change first observed or verified” finds the earliest transaction interval for the
  relevant valid-time claim and verification state.

The durable `QueryRequest` and `QueryLens` schemas already carry the full requested lens: world,
site, region, branch, policy, state kinds, valid-time instant and clock uncertainty, known-at sequence
and timestamp, representation, resolution, frame, units, requesting agent, exact resolved revision,
payload, coverage, and projection sequence.

The implemented `AuthoritativeStore.query_revision` evaluates a narrower reference subset:

`world_id, site_id, branch_id, valid_at, known_at_sequence, state_kinds`.

It selects only revisions stored by the requested known-at sequence, applies half-open revision valid
intervals, and excludes targets of supersession or invalidation events durable by that sequence. The
remaining request fields are bound and audited by the immutable lens but are not yet all evaluated by
the SQL resolver.

## Stale evidence

An observation is stale for a region when its valid interval ends before the latest accepted action
or state transition affecting that region. Unknown validity after a modification should produce
ABSTAIN, not implicit freshness. Stale evidence remains queryable and may still inform historical
reconstruction.

The current resolver implements durable supersession/invalidation filtering for revisions. It does
not yet calculate action-relative staleness for all evidence claims.

## Corrections and supersession

Suppose claim `C1` was stored at transaction sequence `K1` as valid at `T`. At `K2`, evidence shows
`C1` was wrong.

1. append correction `C2` with its own valid interval and transaction sequence;
2. append `SupersessionEvent S1` targeting `C1`, naming replacement evidence where applicable;
3. derive `C1` as inactive for queries with `known_at_sequence >= S1.sequence`;
4. retain decisions that used `C1`; and
5. append invalidation or re-evaluation records for dependents according to policy.

The record at query `known_at < K2` still returns `C1`; the current query returns `C2`, another
eligible revision, or an explicit no-result state. `C1`'s canonical bytes and content hash remain
identical before and after `K2`.

The current test slice exercises the no-result case: the accepted revision is returned immediately
before its durable invalidation and omitted immediately after it, while direct retrieval of the
immutable revision still succeeds.

## Action ordering

Actions carry planned and executed valid intervals separately. Action-derived possible-dependency
edges apply only on spatial and temporal overlap. Touching half-open endpoints are sequential, not
concurrent. Delayed action records may retroactively change dependency analysis, producing a new
transaction-time reconciliation result rather than rewriting the old one.

## Storage and index model

The prototype `records` table stores immutable canonical JSON plus indexed columns for:

`sequence, record_id, record_schema, world_id, site_id, branch_id, valid_start, valid_end,
recorded_at, content_hash`.

`store_meta.next_sequence` persists ordering across reopen. `branch_heads` and
`projection_watermarks` are mutable projections. A typed projection receipt exposes requested
sequence, projected sequence, lag, and status. Branch heads can be deleted and deterministically
rebuilt from immutable Branch and accepted WorldRevision history.

The target temporal projection still needs:

`(world, site, branch, valid_start, valid_end, tx_start, derived_tx_end, region_id, claim_id)`.

`derived_tx_end` remains a query or projection result, not a field written back into the immutable
record. Spatial payloads remain content-addressed and are referenced by digest.

## Revision validity

A `WorldRevision` is a branch snapshot resolved for one declared spatial extent. Its `valid_time`
describes that resolved snapshot, while referenced claims retain their own possibly heterogeneous
valid intervals. A revision may not broaden an admitted observation's validity; the cross-record
validator enforces this for the current candidate and promotion graph. A complete historical query
must eventually filter each constituent claim as well as the revision and report partial coverage.

## Implemented evidence

The focused authoritative-store suite demonstrates:

- rejection of caller-owned transaction fields;
- exact idempotent replay without allocating another sequence;
- monotonic sequence allocation after database reopen;
- a cold-restored 18-record history with byte-identical canonical records;
- historical revision resolution before and after a durable invalidation; and
- accepted-head reconstruction from immutable history after deliberate projection corruption.

This is implementation and self-test evidence, not independent validation of RQ1 or Barrier
acceptance.

## Remaining semantic gaps

- There is no query by transaction wall-clock timestamp, derived transaction-time interval table, or
  general temporal join.
- `query_revision` resolves revision records, not every constituent claim independently;
  heterogeneous claim validity and partial spatial or temporal coverage are not yet calculated.
- Supersession and invalidation are filtered by transaction sequence, but replacement selection,
  dependent-plan re-evaluation, and first-observed or first-verified queries are not implemented as
  services.
- Projection freshness receipts and watermarks exist, but there is no asynchronous spatial or
  temporal projection worker.
- Multi-robot clock offset, clock disagreement, intermittent synchronization, and distributed
  transaction ordering remain unimplemented.
- Store schema version 1 fails closed on an unsupported version; forward migration and retention
  policy are absent.

## Legacy baseline mapping

- `Evidence.observed_at` and `last_modified_at` implement a limited valid-time freshness check.
- `TerrainMemory.cumulative_delta_at(version)` reconstructs version order, not valid time.
- hash-chained journals preserve append order but do not expose transaction-time intervals.
- `mission_t_s` is mission elapsed time, not a bitemporal axis.

Those legacy paths are not automatically upgraded by the UltraBuild store. The new prototype
supports dual-axis revision queries by valid time and known-at sequence, but STEWIE must not claim a
complete bitemporal world-state system until claim-level projection, all reference queries,
integration, and independent review are complete.
