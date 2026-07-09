# STEWIE — Multi-user GIS Data Architecture + Lab Deployment Topology (2026-07-08)

> Folds in Aaron's 2026-07-08 directive: for a research lab, install QGIS locally on every workstation and
> keep all shared project data on a central file server, with a PostGIS spatial database for the vector +
> world-state layers that multiple people edit at once. This document reconciles that guidance with STEWIE's
> actual code and stages it as a TRL-phased progression. Companion to `STEWIE_persistence_db_design_2026-07-07.md`
> (the backend-DB/schema design) and `STEWIE_qgis_platform_architecture_2026-07-07.md`.

## Why this matters (the workflow it enables)

STEWIE is a lunar mission-control GIS platform. As it grows from one researcher to a lab/robotics team, the
binding question stops being "does the map render" and becomes "where does the shared truth live, and how do
several people (and the rover, via ROS2) read and write it without clobbering each other." The maintainable
answer for a GIS shop is the standard one: **local QGIS per workstation for interactive performance + a central
file server for the heavy shared artifacts + a PostGIS database for the concurrently-edited vector/world-state
layers.** Each user gets local render speed; everyone works from one dataset; the world model has one home.

## Topology

```
   Workstation (QGIS + STEWIE cockpit/IDE)
   Workstation (QGIS + STEWIE cockpit/IDE)          each: local QGIS install, local render,
   Workstation (QGIS + STEWIE cockpit/IDE)          no per-machine copies of shared data
            │
     1–10 Gbps LAN
            │
   ┌────────┴─────────────────────────────────────────────┐
   │  Central server (NAS or Linux host)                   │
   │                                                       │
   │  File store (heavy, read-mostly)   PostGIS (concurrent edits)
   │  ├── rasters: DEMs, imagery,       ├── vector layers (features, keep-outs,
   │  │   orthophotos, COGs             │   mission features, site polygons)
   │  ├── QGIS projects (.qgz)          ├── world-state (authoritative terrain-memory
   │  ├── GeoPackages (.gpkg)           │   index, transactions, versions)
   │  ├── sim assets (Godot), ROS       └── permissions, permalinks, edit sessions
   │  │   exports, mission recordings
   │  └── backups
   └───────────────────────────────────────────────────────┘
```

**Split rule.** Large rasters (DEMs, imagery) stay as files on the server; vectors and world-state go in
PostGIS. Rasters are big, read-mostly, and cheap to serve as files/COGs; vectors and world-state are small,
concurrently edited, and need transactions + versioning + conflict avoidance — exactly what a spatial DB gives.

## What lives where

| Artifact | Home | STEWIE anchor today |
|---|---|---|
| Raster DEMs (`.rf32`, LOLA/SfS), imagery, orthophotos, COGs | File server | `samples/lunar_dem/<site>_10km_5m/`, the global LDEM mount, `/dem/heightfield_full` |
| Global LDEM (plan-anywhere source) | File server (read-only mount) | `STEWIE_GLOBAL_LDEM` (`compose.yml`), the request-time crop resolver (#30) |
| QGIS projects (`.qgz`) | File server | `gis/stewie_south_pole.qgz` |
| GeoPackages (`.gpkg`) — interchange + Phase-1 shared vectors | File server | interchange with the QGIS Processing provider (#46) |
| Site vectors / pins (GeoJSON) | File server (read-only) → PostGIS (Phase 2) | `/io/vectors/artemis_sites.geojson` mount → keyless `/world/site-markers` |
| Mission/plan documents | File → PostGIS | `objects.py` JSON docs (live/sandbox); `STEWIE_DATABASE_URL` optional Postgres store |
| Keep-out / mission-feature edit sessions | **PostGIS** (fixes the in-memory defect) | GW-08 `_SESSIONS` (in-memory today — lost on restart) |
| World transactions (DT-01/03) | File-journal → PostGIS index | append-only hash-chained `world.journal` (durable) |
| As-built DEM / Terrain Memory (DT-04) | File (`.npz` delta) + PostGIS version index | per-site mass-conserving delta grid + provenance chain |
| Godot sim assets, ROS2 exports, mission recordings | File server | Godot sidecar outputs, ROS bag exports, SIM run artifacts |
| Backups | File server (+ off-host) | new (Phase 2) |

## Server folder taxonomy (Aaron's layout)

Organize the shared server with stable top-level folders so the structure scales from one researcher to a team
and maps cleanly onto ROS2, Godot, and the mutable world model:

```
/maps         QGIS projects (.qgz), styled map bundles, print layouts
/dem          raster DEMs (per-site .rf32 bundles + global LDEM)
/imagery      orthophotos, LROC/Kaguya basemaps, COGs
/missions     plans, executed paths, mission documents, recordings
/telemetry    ROS2 telemetry captures, bags, health logs
/world_model  authoritative terrain-memory deltas + world-transaction journal snapshots
/planning     candidate plans, cost maps, keep-outs, forward-compare artifacts
/simulation   Godot assets, SIM run outputs, sensor-bridge captures
/exports      GeoPackages, GeoTIFF/COG exports, mission packages, report PDFs
/training     RL curricula, datasets, checkpoints
/archive      superseded artifacts (dated, reversible)
/backups      automated snapshots (DB dumps + file-store deltas)
```

These map onto STEWIE's existing `$STEWIE_DATA_DIR`, `samples/lunar_dem/`, `/io/vectors`, the SIM-run output
tree, and the world-transaction journal; adopting them is a *reorganization + mount convention*, not new code.

## TRL-phased progression (adopt in order; each phase is shippable)

**Phase 1 — TRL 3–5 (single researcher → small team): files + Git.**
Shared NAS/Linux file server with the taxonomy above; **shared GeoPackages** for vector interchange; **Git** for
scripts + configuration (the STEWIE repo). No database yet — matches STEWIE today (100% filesystem + in-memory).
Deliverable: the folder taxonomy + a `.gpkg` interchange convention + documented mounts.

**Phase 2 — TRL 5–6 (concurrent editing): PostGIS.**
Stand up **PostGIS** for vectors + world-state (the `postgres`/`db`-profile service already in `compose.yml`;
set `STEWIE_DATABASE_URL=postgresql+asyncpg://…`). Move the **GW-08 edit session** off the in-memory dict into
PostGIS (its clearest defect — lost on restart). Keep large rasters on the file server. Add **automated backups**
(DB dumps + file-store snapshots → `/backups`) and **user permissions** (per-role read/write, mission sign-off
gated). Deliverable: durable edit sessions + concurrent vector editing + backups + roles.

**Phase 3 — TRL 6+ (live world model): ROS2 writes, near-real-time QGIS.**
A **central world-model database** is the authoritative mutable terrain/operational state. **ROS2 writes mission
updates** through the gated ingest bridge (see the AUTODIG/ingest fold, §7.F); **STEWIE updates the terrain after
every mission** (the SIM execute→remember loop + Terrain Memory, already built); **QGIS/QWC2 visualizes the
latest world state in near real time** off the same PostGIS/file store. Deliverable: the closed loop
robot → ROS2 → world model → QGIS, with the world model as the single source of truth.

## Reconciliation with STEWIE's code (no contradictions)

- STEWIE already ships a **`postgres`/PostGIS** service (`compose.yml`, `db` profile) and an optional
  `STEWIE_DATABASE_URL` async store — Phase 2 is a *deploy*, not a rewrite.
- The **world-transaction journal** (durable, hash-chained) + **Terrain Memory** (per-site mass-conserving
  deltas) are the world-model substrate Phase 3 indexes in the DB; the **SIM execute→remember loop** already
  updates terrain after a run.
- The **plan-anywhere resolver** (#30) already reads the global LDEM from a read-only mount — the file-server
  raster split is the shape STEWIE is already built for.
- The **QGIS Processing provider** (#46) + GeoPackage export are the Phase-1 `.gpkg` interchange path.
- The one concrete defect this formalizes: **GW-08 edit sessions are in-memory** (lost on restart) →
  Phase 2 moves them to PostGIS.

## Non-goals / guardrails

- Do NOT put large rasters in PostGIS (files/COGs on the server; the DB indexes/points at them).
- Do NOT copy shared data per-workstation (one dataset on the server; QGIS opens it over the LAN).
- Phase 2/3 are opt-in deploys; the file-only Phase-1 path (STEWIE today) stays fully functional with no DB.
- Backups + permissions are prerequisites before multi-user write (Phase 2), not afterthoughts.
