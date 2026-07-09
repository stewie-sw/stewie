# STEWIE backend + database integration — as-built analysis (2026-07-09)

Grounds the current backend/persistence integration against the design of record
(`STEWIE_persistence_db_design_2026-07-07.md`). This is an AS-BUILT + GAP audit, run-verified against the
live deploy (`stewie-backend-1` + `stewie-postgres`), not a re-design.

## The two-tier reality (verified)

STEWIE deliberately splits **authority** (truth) from **durable projection** (queryable metadata). The
design's load-bearing fidelity rule holds in code: *the DB must never become a second source of truth for
terrain* — that would reintroduce the four-source skew DT-01 (`stewie/twin/envelope.py`) exists to stop.

### Tier 1 — AUTHORITY = files / journal / in-memory (the conserved core)
- **Terrain Memory** — `<STEWIE_DATA_DIR>/terrain_memory/<site>.npz` (`stewie/twin/terrain_memory.py`):
  `np.savez(delta, meta=json)`, hash-chain verified (`verify_chain`), atomic tmp-rename, fsync-per-edit.
- **Event-sourced twin** — `stewie/twin/versioned.py` `TwinStore` + `backup.py` (`np.savez(base=…)`), the
  conserved `column_state` authority (`stewie/physics/column_state.py`).
- **DT-01 world-transaction envelope** — `stewie/twin/envelope.py` (authority_sha / twin / world hashes).
- **In-memory handles** — `stewie/server/state.py` holds the process-wide per-site DEM cache + the lazy
  durable `TwinStore`; the planner/twin/session/perception routers read it without importing the app module.
- **Verdict:** correct + conserved. This tier is NOT in Postgres and should not be (design fidelity #1).

### Tier 2 — DURABLE PROJECTION = Postgres + PostGIS (metadata/index on top)
- **Built + LIVE (Phase 0):** `stewie.edit_session` + `stewie.edit_audit` (GW-08), via `stewie/server/db.py`
  — async SQLAlchemy over **asyncpg** (prod) / **aiosqlite** (CI + local, zero-setup fallback), gated on
  `STEWIE_DATABASE_URL`, a sync-facade-over-async engine on one dedicated loop. **Run-verified:** the live
  backend has `STEWIE_DATABASE_URL=postgresql+asyncpg://…@postgres:5432/stewie` and `stewie.edit_session`
  holds **186 rows** — the edit-session survives restarts (the design's "single clearest persistence defect"
  is closed). The image is `postgis/postgis:16-3.4` (PostGIS + tiger geocoder present; only `edit_session`
  / `edit_audit` are STEWIE-owned so far).

## Gap map vs the design's phased path

| Phase | Design intent | Status |
|---|---|---|
| **0** | Persist GW-08 edit session/audit to the `stewie` schema | ✅ **DONE + LIVE** (186 sessions) |
| **1 (= PG-01, §7.B N)** | STEWIE `stewie` schema for the rich index model — `plan` / `order_item` / **`world_txn`** (id, seq, mission, authority_sha, twin_version, twin_hash, world_sha, chain_hash, prev_hash, ts) mirroring `TwinStore` events as a queryable **provenance projection** (not the terrain arrays) | ❌ **UNBUILT** — the twin touches no Postgres (grep-confirmed); world history is only in the file journal + in-memory |
| **2** | Adopt `qwc-data-service` + WFS-T + PostGIS for simple editable map features + `qwc-permalink-service` (DB-backed permalinks/bookmarks) | ❌ **UNBUILT** — and the QWC2 `config.json` service URLs were **emptied 2026-07-09** (they pointed at an undeployed `localhost:8088`, breaking the public map — P0-1). Adopting Phase 2 is what would fill them back in with same-origin `/api/...` qwc-service routes. |
| **3** | Manual 3D DEM edit through the conserved delta path + portable mission import/export | ❌ **UNBUILT** |

## The highest-value next brick — PG-01 / Phase 1 `world_txn` projection

A durable, queryable `world_txn` (+ `plan`/`order_item`) projection in the `stewie` schema is the single
biggest lever, and it compounds with already-tracked work:
- **Dispatch-audit R1/R6 (#82/#87):** a canonical, immutable **release artifact** + **recoverable
  (prepare/commit) transactions with honest reproducible playback** both want a durable transaction index
  with prev/chain hashes — exactly the `world_txn` row shape. Building PG-01 gives R1/R6 their storage spine.
- **Asset Library / EV-01 (#36/#37, done):** currently reconstruct provenance from files; a `world_txn`
  index makes "what ran, in what order, from which authority hash" a query instead of a scan.
- **Mission-snapshot lineage (BR-02, §7.B N):** the branchable replay/ML unit needs an immutable snapshot
  row per completed mission — a natural extension of `world_txn`.

**Design guardrail (must hold):** `world_txn` stores **hashes + metadata only**, never terrain arrays. The
`np.savez` files stay the truth; Postgres is the index that points at them. A mirror writer hangs off the
existing `TwinStore` commit path (`versioned.py`) + the DT-01 envelope, append-only, best-effort (a Postgres
outage must not block a conserved commit — the file journal remains the durable authority).

## Operational notes (verified)
- Postgres is **opt-in** in compose (`--profile db`); the live deploy runs it and sets `STEWIE_DATABASE_URL`
  (no host port; internal compose network only; password from `deploy/.env`, gitignored — no secret in git).
- **CI/local run with zero DB setup** (aiosqlite fallback + per-test data-dir isolation) — so PG-01 work must
  keep the SQLite fallback faithful for the index tables (JSON/text columns; PostGIS geometry only where a
  Phase-2 editable feature needs it, which SQLite can skip).
- The 38-router / ~140-route API is the app layer over Tier-1 authority; only `edit_session` writes reach
  Tier-2 today.

## Open decisions for Aaron (unchanged from the 2026-07-07 design)
1. **Adopt `qwc-data-service`/WFS-T (Phase 2)?** It makes PostGIS mandatory + adds a heavier ops surface
   (qwc-data-service, admin-gui) vs today's single FastAPI + cloudflared origin. If yes, it also restores
   DB-backed permalinks/bookmarks (the emptied `config.json` services). If no, stay STEWIE-only-on-Postgres
   and keep permalinks a STEWIE `/api` route.
2. **Build PG-01 / Phase 1 next?** Recommended — it is independent of the Phase-2 decision, unblocks the
   dispatch-audit R1/R6 storage spine, and does not touch the conserved authority.
