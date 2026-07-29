# Temporal and bitemporal model

**Artifact ID:** `ART-TEMPORAL`
**Producer node:** `WS-020`
**Consumers:** `ARCH-020`, `WS-040`, `WS-050`, `VERT-010`, `EXP-010`
**Status:** specified v0.1; transaction-time implementation is missing.

## Time dimensions

### Valid time

When a claim is asserted to describe the modeled physical or simulated world. It is supplied or
derived from source evidence and carries clock identity and uncertainty.

### Transaction time

When STEWIE recorded the claim in the authoritative evidence store. It is assigned monotonically by
the store and cannot be supplied by the source. An immutable record stores only its transaction
sequence and `recorded_at`. A later immutable supersession event causes the temporal projection to
derive the earlier record's `tx_end`; the earlier record itself is never edited.

### Event/mission time

Elapsed time within a run. It is useful for simulation and ordering but does not replace either valid
or transaction time.

### Source and receipt clocks

Raw source timestamps and receipt timestamps are retained with clock identity, offset estimate,
uncertainty, and synchronization status. Converting them to valid time is a provenance activity.

## Interval rules

- Intervals are half-open `[start, end)`.
- An omitted end means open-ended.
- Point observations use a validity instant plus declared temporal uncertainty or a minimal interval.
- Transaction time is append-only; past records are not edited in place.
- Valid time may be retroactively corrected, but the correction creates a new transaction-time record.
- Non-finite times, inverted intervals, or unknown clocks fail schema validation.
- Clock ordering alone never proves physical causality.

## Query lens

Every state query resolves:

`state(region, valid_at=T, known_at=K, branch=B, policy=P, representation=R)`.

- “What robot A believed at T as of K” filters claims attributed/available to A and both time axes.
- “What STEWIE now believes was true at T” uses current transaction time with historical valid time.
- “What did the planner use” reads the immutable query lens stored in `DecisionRecord`.
- “When was change first observed/verified” finds the earliest transaction interval for the relevant
  valid-time claim and verification state.

## Stale evidence

An observation is stale for a region when its valid interval ends before the latest accepted action or
state transition affecting that region. Unknown validity after a modification produces ABSTAIN, not
implicit freshness. Stale evidence remains queryable and may still inform historical reconstruction.

## Corrections and supersession

Suppose claim `C1` was stored at transaction time `K1` as valid at `T`. At `K2`, evidence shows `C1`
was wrong.

1. append correction `C2` with its own valid interval and transaction sequence;
2. append `SupersessionEvent S1` targeting `C1`, naming `C2`, evidence, activity, and `K2`;
3. derive `C1.tx_end = S1.recorded_at` in the temporal projection;
4. retain decisions that used `C1`; and
5. append invalidation/re-evaluation events for dependents according to policy.

The record at query `known_at < K2` still returns `C1`; the current query returns `C2`.
`C1`'s canonical bytes and content hash remain identical before and after `K2`.

## Action ordering

Actions carry planned and executed valid intervals separately. Action-derived possible-dependency
edges apply only on spatial and temporal overlap. Touching half-open endpoints are sequential, not
concurrent. Delayed action records may retroactively change dependency analysis, producing a new
transaction-time reconciliation result rather than rewriting the old one.

## Storage/index model

The authoritative append log assigns a transaction sequence and timestamp. A temporal projection
indexes `(world, site, branch, valid_start, valid_end, tx_start, derived_tx_end, region_id, claim_id)`.
`derived_tx_end` is the first valid supersession/invalidation event for the record on that branch.
Spatial payloads stay content-addressed; the temporal index references them. Query results expose the
projection head so stale projections are visible.

## Revision validity

A `WorldRevision` is a branch snapshot resolved for one declared query lens and spatial extent. Its
`valid_time` describes that resolved snapshot, while referenced claims retain their own possibly
heterogeneous valid intervals. A revision may not broaden a claim's validity. Historical queries
must filter each claim as well as the snapshot and report any partial coverage.

## Current baseline mapping

- `Evidence.observed_at` and `last_modified_at` implement a limited valid-time freshness check.
- `TerrainMemory.cumulative_delta_at(version)` reconstructs version order, not valid time.
- hash-chained journals preserve append order but do not expose transaction-time intervals.
- `mission_t_s` is mission elapsed time, not a bitemporal axis.

Accordingly, STEWIE does not currently implement bitemporal state. Barrier 3 requires the first
end-to-end valid/transaction-time record and reference queries before any bitemporal claim is made.
