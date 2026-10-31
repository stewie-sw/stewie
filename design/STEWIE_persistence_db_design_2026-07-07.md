# STEWIE Persistence + Backend DB — Design (2026-07-07)

> Grounds Aaron's ask: save/load plans, import/export missions, save/load world states, edit the DEM in
> 3D from actual construction, a real backend DB + schemas, and "set QWC2 up correctly for fidelity."
> Synthesized from an evidence-grounded research pass (QWC2 docs `docs.qwc.app/master` + STEWIE code at
> `file:line`). Companion to the mission-workflow design (`STEWIE_workflow_design_2026-07-07.md`).

> **Historical-state warning, reconciled 2026-07-28.** The “no database” and in-memory-only edit-session
> findings below were true at this document's audit date and are no longer current: DA-04 now persists
> edit sessions through SQLAlchemy with SQLite fallback/PostgreSQL support, and PG-01 mirrors
> world-transaction projections when configured. Those pieces are not the complete operational
> evidence path. DA-07--DA-10 and `../docs/construction_event_ledger_contract.md` define the still-unbuilt
> immutable construction/evidence ledger, atomic accepted-world publication, cold replay, and
> version-attributed GIS projections. PostGIS remains a store/projection surface, not terrain authority.

## The two findings that drive everything

1. **Historical finding (superseded): STEWIE had no database at this audit.** Grep for `sqlalchemy|psycopg|sqlite3|duckdb|create_engine` across the
   codebase → zero hits. Persistence today is 100% filesystem (JSON docs + numpy `.npz`/`.rf32` + append-only
   hash-chained journals) plus **process-memory dicts**. Data root = `$STEWIE_DATA_DIR` (`stewie/specs/config.py:148`).
2. **STEWIE uses QWC2 as an OpenLayers render shell only.** The plan authoring adds raw OL vector layers
   (`planAuthor.js:167-205`) and writes through STEWIE's own FastAPI edit-session (`/api/edit/session/*`,
   `stewie/server/edit_session.py`), **not** QWC2's `qwc-data-service` / WFS-T. So we forgo QWC2's free WFS-T
   editing, permissions model, and DB-backed permalinks/bookmarks.

## What STEWIE persists today (all file / journal / in-memory)

| Concern | Mechanism | Durability |
|---|---|---|
| Plans / missions | one JSON doc per slug (`objects.py`); live/sandbox namespaces, soft-delete, publish | **File** |
| **GW-08 keep-out edit session** | process-wide `_SESSIONS` dict; versioned before/after audit + undo | **IN-MEMORY — lost on restart** ⚠ |
| World-transaction log (DT-01/03) | append-only, hash-chained, fsync-per-commit journal (`world.journal`) | File-journal (durable) |
| As-built DEM / Terrain Memory (DT-04) | per-site `.npz` mass-conserving delta grid + version + provenance chain | File (durable) |
| Observed twin (DT-04) | base map + append-only hash-chained edit journal | File-journal |
| Executive audit (EG-07) / evidence (EV-01) | tamper-evident chain / derived reproduction bundle (`bundle_sha`) | File / derived |
| DEM tiles | real LOLA/SfS rasters (`.rf32`) | File |

The single clearest defect at the audit date was the in-memory GW-08 edit session. **That defect is
now closed by DA-04; it is retained here only as design provenance.**

**"Edit the DEM in 3D from construction" already half-exists:** `state.as_built_dem()` composes OBSERVED >
AS-BUILT > pristine (`state.py:54-105`); `POST /dem/asbuilt` returns the mass-conserving deformed surface for
a set of orders (`routers/dem.py:156-209`). But that's a **re-derivable view, not a stored edit** — Terrain
Memory only gains a persisted delta when a mission is executed and folded in. There is no first-class *manual*
3D DEM edit saved as an editable delta yet.

## What QWC2 gives free (only if adopted)

WFS-T feature editing UI (Editing plugin) → **qwc-data-service** persisting to **PostGIS** (datasources MUST be
PostGIS; every editable layer needs a PK); a roles/resources permission model + admin GUI; **DB-backed
permalinks + bookmarks** (`qwc-permalink-service`, Postgres — directly satisfies "save/load view state");
GeoJSON/DXF/GeoPDF export; QGIS print. **What it cannot represent:** conserved mass-balanced terrain, as-built
DEM deltas, ordered plans with precedence, hash-chained world transactions, reproducible evidence bundles —
qwc-data-service edits *flat PostGIS feature tables* only.

## Recommendation — ONE Postgres + PostGIS, hybrid

1. **Route the genuinely map-feature-shaped editable layers through qwc-data-service + WFS-T + PostGIS** —
   keep-outs, landmarks, site markers, structure footprints, placed order points. This is exactly where STEWIE
   is reinventing QWC2 today (and losing fidelity); adopting it gives WFS-T persistence + permissions +
   **permalinks/bookmarks for free**. This is the concrete answer to "set QWC2 up correctly for fidelity."
2. **Add a STEWIE-owned `stewie` schema (same Postgres)** for the rich model QWC2 can't hold: plans (ordered
   orders + precedence + Plan IR), missions (the import/export unit), world-states, DEM-edit provenance, the
   world-transaction chain, evidence bundles.
3. **Arrays never go in DB rows.** The DEM deltas (`.npz`), twin journals, and rasters (`.rf32`) stay on the
   filesystem/object store, **referenced by content-hash + version** from the DB. The DB is the **index +
   provenance graph** over those artifacts, not their container. (This is already how STEWIE stores them —
   correct — so the DB layers *on top*, it doesn't replace the conserved authority.)

**DB choice: Postgres + PostGIS**, not SQLite/DuckDB. The store's job is concurrent multi-user metadata CRUD
with roles/namespaces — Postgres's wheelhouse, not DuckDB's (columnar OLAP, single-writer) or SQLite's (weak
multi-writer concurrency). Adopting *any* QWC2 service makes PostGIS mandatory anyway (one engine for
`qwc_config` + qwc-data-service edit tables + the `stewie` schema). DuckDB can be an optional analytics sidecar
later (querying evidence/telemetry over the file artifacts), not the operational store.

## Schema sketch (`stewie` schema; PostGIS geometry in the lunar CRS)

```
plan            (id, slug, title, owner, namespace, site, plan_ir jsonb, mission_t0_s, created_at, updated_at)
order_item      (id, plan_id→plan, seq, kind, order_kind, geom(Point,<lunar_crs>), footprint_m2, depth_m)
order_precedence(plan_id, before_order→order_item, after_order→order_item)      -- the precedence DAG
mission         (id, slug, owner, namespace, site, plan_id→plan, vehicle jsonb, lander jsonb, vehicles, exported_at)
mission_package (id, mission_id→mission, manifest jsonb, geojson jsonb, dem_origin jsonb, bundle_sha)
edit_session    (id, opaque_id, plan_id→plan, version, created_at)              -- GW-08, was in-memory → durable
edit_audit      (id, session_id→edit_session, version, op, fid, before jsonb, after jsonb, ts)
world_state     (id, slug, site, wtxn_id→world_txn, terrain_memory_version, terrain_memory_sha,               \
                 twin_version, twin_hash, world_sha, created_at)                -- a PIN over on-disk artifacts
world_txn       (id, seq, mission, authority_sha, twin_version, twin_hash, world_sha, chain_hash, prev_hash, ts)
dem_edit        (id, site, world_state_id→world_state, source['mission'|'manual'], delta_ref, cell_m,          \
                 origin jsonb, mass_moved_kg, net_volume_m3, provenance jsonb, chain_hash, ts)
exec_audit      (id, seq, who, what, when_ts, where_loc, mode, reason, before jsonb, after jsonb, chain_hash, prev_hash)
evidence_bundle (id, mission, site, world_state_id→world_state, bundle_sha, reproduced jsonb, built_at)
```
Editable map features (keepout/landmark/site_marker/structure_footprint) live in **qwc-data-service PostGIS
tables** (WFS-T), *not* here — unless we keep STEWIE's before/after-undo semantics (see fidelity #5).

## Fidelity (load-bearing)

1. **Don't let the DB become a second source of truth for terrain.** The conserved authority
   (`physics/column_state.py`) + Terrain-Memory `.npz` + `world.journal` stay authoritative; the DB stores
   *versions + content-hashes* (`terrain_memory_sha`, `world_sha`, `twin_hash`), never the arrays. A naive
   "put world state in Postgres" would reintroduce exactly the four-source skew DT-01 (`envelope.py`) exists to stop.
2. **World state round-trips by reference, not value.** "Load world state N" = restore the `.npz` at that
   version (Terrain Memory already supports versioned snapshot/restore, `terrain_memory.py:285-314`) + replay
   the twin journal to that hash. The DB names the pin; mass conservation is never re-serialized through SQL.
3. **Manual 3D DEM edits go through the conserved delta path.** A hand edit must push through the same
   rasterize→delta path as `/dem/asbuilt` (`routers/dem.py:197`, `mission_terrain_delta`) so it's mass-checked,
   then persisted as a Terrain-Memory delta with `source='manual'` — not a cosmetic displacement.
4. **Reproducibility already has an anchor — index it, don't duplicate it.** EV-01's `bundle_sha`
   (`routers/evidence.py:189-220`) + DT-01's `world_sha` are the repro keys; the DB stores them, it doesn't
   compete with the existing reproducibility machinery.
5. **WFS-T tradeoff for keep-outs.** qwc-data-service logs create/edit user+timestamp but **not** full
   before/after + undo. GW-08 gives versioned before/after + linear undo (its biggest gap = in-memory). If
   undo/audit fidelity matters (it's a named GW-08 requirement), **persist STEWIE's edit-session to
   `edit_session`/`edit_audit`** rather than moving keep-outs to WFS-T; use WFS-T for the simpler
   landmark/marker layers.

## Phased migration path (files → DB, without breaking the conserved core)

- **Phase 0 — persist GW-08 (the must-fix).** Move the in-memory `_SESSIONS` dict to `edit_session`/`edit_audit`
  rows (or, interim, a durable journal like the twin). Smallest change, highest value: keep-out edits survive
  restart. *No QWC2 dependency; no conserved-core change.*
- **Phase 1 — stand up Postgres + the `stewie` schema** for the index/provenance model (plan / order_item /
  mission / world_state / world_txn / dem_edit / evidence_bundle). Dual-write from the current file writers,
  then read from the DB; keep the files/journals as the durable artifact store the DB references by hash.
- **Phase 2 — adopt qwc-data-service/WFS-T + permalinks** for the simple editable features + save/load view
  state. Requires the lunar CRS (IAU_2015:30135) wired into QGIS Server + qwc-data-service (the QWC2-IDE spike
  reportedly proved the lunar CRS — confirm before committing).
- **Phase 3 — manual 3D DEM edit** (through the conserved delta path) + the portable **mission import/export
  unit** (plan + world-state pin + provenance in one package).

## Open decisions for Aaron

1. **Adopt qwc-data-service/WFS-T for simple features, or keep STEWIE's own edit path + just make it durable?**
   (WFS-T buys permalinks/permissions free; STEWIE's path keeps before/after-undo. Recommend: WFS-T for
   landmarks/markers, STEWIE-durable for keep-outs where undo matters.)
2. **Deployment weight** — a full qwc-services stack (config-service, config-generator, data-service, QGIS
   Server, PostGIS, admin-gui) is much heavier than today's single FastAPI + cloudflared origin. OK to take on
   for Phase 2, or stay STEWIE-only-on-Postgres?
3. **Priority** — Phase 0 (fix the restart-loss) first is my recommendation regardless of the QWC2 decision.

---
*Not committed pending review. The conserved authority + Terrain-Memory + world.journal remain the source of
truth throughout; the DB is an index + provenance graph over them, never a replacement.*
