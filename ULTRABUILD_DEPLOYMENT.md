# UltraBuild deployment

**Artifact ID:** `ART-DEPLOYMENT`
**Producer node:** `INT-010`
**Consumers:** `ORCH-001`, `VERT-010`, `DISS-010`
**Status:** `simulation_only`

The implemented artifact is an in-process, single-host research service boundary. Deploy it only as
a simulation, test, or rehearsal component.

- Place the SQLite authority database and payload CAS on durable local storage.
- Keep `PRAGMA journal_mode=WAL` and `synchronous=FULL`.
- Back up with `AuthoritativeStore.snapshot_to`; it copies the database and referenced payloads.
- Run `stewie-ultrabuild verify --database ... --payloads ...` after restore and before accepting
  new authoritative work.
- Treat branch heads and projection watermarks as rebuildable caches.
- Preserve database, payload directory, exact code commit, policy configuration, and schemas
  together.
- Reject promotion and authoritative query when a payload verifier is unavailable.

There is no supported multi-process service API, authentication layer, Postgres migration,
distributed replication, ROS command dispatcher, QGIS/Gazebo adapter, automatic schema migration, or
flight-safety boundary. Physical robot deployment is explicitly unsupported.
