# System architecture

**Artifact ID:** `ART-ARCHITECTURE`
**Producer node:** `ARCH-010`
**Consumers:** `ARCH-020`, all `WS-*`, `VERT-*`, `EXP-*`, `INT-010`
**Status:** target architecture grounded in the merged baseline; pending Barrier-2 review.

## Architectural position

STEWIE remains a modular monorepo. Logical service boundaries are enforced in code and contracts
before they are split into deployment processes. The authoritative scientific record is an
append-only event/evidence store; spatial, temporal, GIS, and UI projections are rebuildable views.

“Authority” is scoped:

- in simulation, the conserved physics state is authoritative for the simulated material transition;
- observations are authoritative only as immutable evidence that a source reported a value;
- reconciled state is authoritative for a named policy, world branch, valid-time lens, and transaction
  time;
- planned and predicted states are never authoritative descriptions of the physical world; and
- evaluation reference is authoritative only for scoring, never available to the evaluated system.

## Existing reusable components

| Concern | Existing implementation | Honest boundary |
|---|---|---|
| Conserved terrain transition | `stewie/physics/`, ADRs 0001–0003 | Simulation/model authority, not physical truth |
| Accumulated worked terrain | `stewie/twin/terrain_memory.py` | Version history exists; no valid/transaction intervals |
| Observed patch journal | `stewie/twin/versioned.py` | Provenance is currently a string; patch events lack full bitemporal fields |
| Linked world transaction | `stewie/twin/envelope.py`, `stewie/server/world_state.py` | Runtime adoption is partial; projection is non-authoritative |
| Multi-robot action overlap | `stewie/twin/shared_terrain.py` | Possible dependency, not measured covariance |
| Promotion mechanism | `stewie/twin/promotion.py` | Component path; live resync is not yet gated by it |
| Comparators and fault probes | `stewie/twin/baselines.py`, `veto_experiment.py`, tests | Mostly injected faults on a real terrain crop |
| Audit/governance | `stewie/contracts/audit.py`, server governance/routers | Governance evidence is distinct from scientific provenance |
| Planning/execution | `lode/`, `leap/`, `stewie/server/routers/` | Must begin recording the exact query lens/version |
| Sensor/perception/localization | `dart/`, `stewie/sensors/`, `stewie/runtime/` | Dense GPU and live-pit tiers remain gated |
| GIS/operator surfaces | `gis/`, `frontend/`, server web assets | Visualization is a consumer, never authority |
| Deployment | FastAPI, QGIS Server/QWC2, Docker compose, optional ROS/Godot | Public/runtime claims remain simulation-only |

## Target logical topology

```text
 Sensors / robot logs / operator imports / simulation
                         |
                         v
                Evidence Ingest Gateway
       validate frame, units, time, identity, schema
                         |
                         v
              Immutable Evidence + Event Store
       entities, activities, agents, payload hashes, clocks
             |                 |                 |
             v                 v                 v
      Spatial projection   Temporal index   Artifact catalog
             \                 |                 /
              \                |                /
               v               v               v
                  Reconciliation Engine
      admissibility -> observation aggregate -> dependency
        support -> contestable physics -> promote/reject/
                 abstain/retain hypotheses
                         |
           +-------------+---------------+
           |                             |
           v                             v
  Versioned accepted branch      Unresolved hypothesis set
           |                             |
           +-------------+---------------+
                         |
                         v
              World-State Query Service
       region + valid_time + transaction_time + branch
                         |
        +----------------+-------------------+
        |                |                   |
        v                v                   v
    Planner/VOI      Simulation/twin       GIS/operator UI
        |                |                   |
        +----------------+-------------------+
                         |
              Decision and mutation events
                         |
                         +----> immutable store
```

## Bounded contexts

### Evidence and provenance

Owns immutable observations, actions, physical predictions, transformations, identities, calibrations,
and payload hashes. It validates but does not reconcile.

### World-state reconciliation

Owns admissibility, temporal filtering, dependency graphs, uncertainty propagation, promotion policy,
competing hypotheses, and supersession. It does not fabricate sensor data or mutate simulation.

### Terrain authority and simulation

Owns conserved simulated material state and counterfactual predictions. It emits evidence with
model/calibration identity. Its outputs never bypass reconciliation into physical belief.

### World-state storage and query

Owns event append, transaction ordering, branch/version identity, bitemporal and spatial indexes,
historical reconstruction, and rebuildable projections.

### Planning and autonomy

Consumes a complete query lens and records it with each decision. It owns goals, constraints, route,
construction sequencing, resource policy, and value-of-information decisions.

### Integration and presentation

ROS 2, GIS/QGIS, Godot/Gazebo, API, synchronization, and UI translate contracts. They may cache and
project state but cannot become an untracked source of authority.

## Write path

1. Ingest validates schema, frame, units, time source, identity, and payload hash.
2. The immutable evidence/event record is durably appended before acknowledgement.
3. Reconciliation queries a pinned prior version and admissible evidence set.
4. The candidate is produced only from admissible observations.
5. Dependency, uncertainty, and physics evidence affect the decision.
6. PROMOTE appends a new accepted claim/version only through compare-and-swap against the pinned
   `prior_head_revision_id`; a stale head produces ABSTAIN/retry, never overwrite. The revision must
   name the matching durable promotion decision. ABSTAIN or conflict appends unresolved hypotheses;
   REJECT appends the decision without mutating accepted state.
7. Derived-layer and plan invalidations are emitted as events.
8. Read projections update after the authoritative append; failed projection updates are replayable.

## Read path

All reads specify:

`region, representation, state_kind/branch, valid_at, known_at, resolution, frame, units`.

Defaults are allowed only for operator convenience and are returned explicitly in the response. A
planner may not use an implicit “latest” lens.

## Consistency and failure semantics

- Append and accepted-version creation are atomic at the event-store boundary.
- Payload blobs are content-addressed and immutable.
- Spatial/temporal projections may be eventually consistent but expose their projected transaction
  head.
- Unknown frame, time, identity, dependency, or required uncertainty fails closed to REJECT/ABSTAIN.
- Communication partitions retain local evidence and metadata; synchronization does not use
  last-write-wins for accepted terrain.
- Audit/provenance write failure prevents the corresponding authoritative mutation.
- Corrupt interior history refuses startup/query; a documented tail-recovery policy may recover only
  a proven incomplete final record.

## Integration contracts

Machine-readable schemas live under `schemas/`. Interfaces must include schema version, content type,
units, CRS/frame, valid time, transaction receipt time, producer identity, calibration and algorithm
versions, uncertainty model, payload hash, and prior/version references.

The Barrier-2 subset separately contracts branches, evidence claims, action events, possible-
dependency edges, provenance bundles, state candidates, reconciliation decisions, conflict and
hypothesis records, world revisions, supersession events, query lenses, and experiment scenarios.
Cross-record validation enforces common `world_id`/`site_id`, reference type, branch/policy identity,
and observation-versus-physics roles; JSON Schema alone cannot enforce those joins.

ROS REP-103/local robot frames and lunar `IAU_2015:30135` are translated through explicit transforms.
RFC 7946 GeoJSON export is an interchange representation and does not redefine lunar authority.

## Observability

Every request/run carries `trace_id`, `graph_node_id`, `experiment_id` when applicable, code commit,
configuration digest, and actor. Logs and metrics reference immutable event/claim IDs. A replay
records whether results are byte-identical, numerically equivalent within a declared tolerance, or
non-reproducible.

## Deployment sequence

Barrier 3 uses an in-process Python slice and file-backed immutable artifacts to reduce moving parts.
Postgres/PostGIS or another spatial/temporal projection is introduced only after the semantics and
reference queries pass. ROS, QGIS, Godot/Gazebo, and distributed synchronization remain adapters to
that core rather than prerequisites for proving it.
