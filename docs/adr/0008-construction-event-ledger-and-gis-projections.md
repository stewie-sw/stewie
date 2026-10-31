# ADR-0008: Construction events are canonical; GIS layers are derived projections

- **Status**: Accepted architecture; implementation incomplete
- **Boundary**: FORGE / execution ↔ DART / observation ↔ world acceptance ↔ GIS
- **Date**: 2026-07-28
- **Contract**: [`construction_event_ledger_contract.md`](../construction_event_ledger_contract.md)

## Context

STEWIE has three related but distinct records:

1. the conserved simulated terrain changed by physics-authority verbs;
2. observations and predictions about terrain; and
3. the shared accepted world used for planning and operations.

The existing system has event-sourced pieces: `TerrainMemory`, the observed `TwinStore`, and a
hash-chained world-transaction log. It also has an atomic compensation path around `POST
/twin/resync`. However, the live resync endpoint writes an observed patch without calling the
dissertation's theorem-facing promotion rule, and `CurrentTerrainView` gives that observation
precedence. The per-cell dependency graph used by the research rule is not durable evidence bound to
the action, observation, decision, and resulting world version.

Saving every action as a separate GIS layer was considered. It preserves visibility but is the wrong
canonical model: layer count grows without bound; layer ordering is not causal ordering; action
geometry alone omits commanded-versus-executed state, calibration, identity, uncertainty, and mass
balance; edits can bypass domain invariants; and replay becomes dependent on GIS implementation
details. A GIS layer is an excellent query/view product and a poor transaction log.

## Decision

Record every executed terrain-changing action as an immutable spatial-temporal
`construction_event`. Record every observation, possible-dependency graph, candidate, promotion
decision, and accepted-world version as immutable, content-addressed ledger records.

The conserved physics authority remains the only simulated-terrain mutation authority. A versioned
acceptance service is the only publisher of accepted belief. It evaluates exact, hash-bound evidence
and atomically appends the decision and accepted-world child version using a parent-version
compare-and-swap. The branch head is a pointer; versions are immutable.

PostgreSQL/PostGIS may durably store the ledger and indexes, but database tables do not acquire
physics or epistemic authority merely by being durable. QGIS, WMS/WMTS, vector tiles, rasters,
dashboards, and analytical tables are disposable projections. Each projection names its source
ledger range, accepted version/hash, epistemic class, CRS, units, and projector version and can be
rebuilt without changing canonical state.

Per-action GIS layers may be generated on demand for inspection. Normal operator views aggregate by
mission, time, action type, asset, or accepted-world delta to avoid unbounded permanent layer
cardinality.

## Consequences

- The platform keeps every action without confusing visibility with authority.
- Commanded and executed action, raw evidence, observation claim, dependency premise, decision, and
  accepted state are independently auditable.
- A live accepted update cannot bypass identity, time/frame, coverage, uncertainty, dependency, and
  promotion checks.
- Projection loss or corruption is recoverable by replay; a projection outage does not corrupt the
  canonical world.
- Concurrency and retry behavior are explicit: idempotency prevents duplicate action application,
  and stale parents fail with conflict rather than last-write-wins.
- Storage and API work increases: canonical schemas, durable blobs, transaction/outbox handling,
  cold replay, projector lag/failure reporting, source authentication, and retention policy are
  required.
- Existing `POST /twin/resync` behavior remains a known gap until it is restricted to an observed
  branch or routed through candidate, decision, and atomic accepted-world publication.
- This decision refines ADR-0003: Terrain Memory remains the conserved shared substrate, while
  observed claims and accepted belief have separate authority and publication semantics.

The decision is accepted; completion is measured only by DA-07 through DA-10 and the acceptance gates
in the contract.
