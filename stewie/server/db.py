"""[GW-08 persistence, Phase 0] The durable backing store for the mission-feature EDIT SESSION.

Before this module the keep-out / marker edit session lived only in the process-wide ``_SESSIONS``
dict in ``edit_session.py`` -- versioned before/after audit + linear undo, all IN MEMORY, LOST on every
server restart (the single clearest persistence defect in the design pass,
``design/STEWIE_persistence_db_design_2026-07-07.md`` §"two findings"). This is the first brick of the
hybrid Postgres+PostGIS architecture: it makes the edit session survive a restart WITHOUT changing the
public API in ``edit_session.py`` (the routes + tests are untouched).

DESIGN (per the design doc, Phase 0 = ``edit_session`` + ``edit_audit`` only; no geometry arrays -- the
edit session holds small JSON before/after, so it needs no PostGIS geometry column):

  * ``edit_session`` -- one row per session: the opaque id, the monotonic version, the fid sequences,
    and the LIVE keep-out + marker snapshot (small JSON, no arrays) so a session round-trips exactly.
  * ``edit_audit``   -- the append-only versioned before/after trail (the durable provenance the design
    doc's fidelity #5 requires: GW-08's before/after + linear undo persist, they are not lost).

BACKEND (the CI test strategy, design doc + task): the SQLAlchemy URL is CONFIGURABLE via
``$STEWIE_DATABASE_URL``. Production points it at Postgres/PostGIS over asyncpg
(``postgresql+asyncpg://...``); with the var UNSET the store falls back to a per-``$STEWIE_DATA_DIR``
SQLite file over aiosqlite -- so CI (which has no Postgres) and local dev work with ZERO setup, and the
conftest per-test data-dir isolation gives every test its own clean database file. edit_session/edit_audit
carry only JSON (no geometry), so SQLite is a faithful test backend for them.

SCHEMA: the tables live in a logical ``stewie`` schema (the design doc's STEWIE-owned schema). On Postgres
that is a real ``CREATE SCHEMA IF NOT EXISTS stewie``; on SQLite (which has no schemas) a
``schema_translate_map`` folds ``stewie`` -> the default schema, so the SAME models serve both backends.

SYNC-OVER-ASYNC: ``edit_session.py`` exposes a synchronous API (the FastAPI routes are sync ``def`` and
the tests call it synchronously), so this module drives the async SQLAlchemy engine from a single
dedicated background event loop and blocks for the result. The engine + its pooled connections live on
that one loop (asyncpg connections are loop-bound), so pooling stays valid regardless of whether the
caller sits in a running loop or not -- the standard, robust sync-facade-over-async-DB pattern.

NO SECRET IN GIT: the connection string (with any password) comes from the environment only; nothing here
embeds a credential, and the default SQLite path holds no secret.
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    delete,
    func,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from stewie.specs.config import data_dir

# The logical schema all STEWIE-owned tables belong to (design doc). Folded to the default schema on
# SQLite via schema_translate_map; a real schema on Postgres.
_SCHEMA = "stewie"


def _json():
    """A JSON column that is JSONB on Postgres (binary, indexable) and JSON (TEXT) on SQLite. One fresh
    type per column (TypeEngine instances are cheap; a fresh one avoids any shared-state surprises)."""
    return JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    # Bind every table to the logical ``stewie`` schema (translated away on SQLite).
    metadata = MetaData(schema=_SCHEMA)


class EditSessionRow(Base):
    """One operator edit session (GW-08). ``opaque_id`` is the unguessable capability id the client holds;
    it is the primary key (already unique + unenumerable). ``features`` / ``markers`` are the LIVE snapshot
    (fid -> feature dict, insertion-ordered) so ``current_features`` / ``current_markers`` reload exactly;
    ``fid_seq`` / ``marker_seq`` are the id counters so a reloaded session keeps minting non-colliding fids.
    ``plan_id`` is a nullable forward-compat slot for the Phase-1 plan link (no FK yet -- the ``plan`` table
    lands in Phase 1); nothing populates it today, it is stored NULL."""

    __tablename__ = "edit_session"

    opaque_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # Phase-1 plan link (unwired)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)            # time.time() epoch seconds
    fid_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    marker_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    features: Mapped[dict[str, Any]] = mapped_column(_json(), nullable=False, default=dict)
    markers: Mapped[dict[str, Any]] = mapped_column(_json(), nullable=False, default=dict)


class EditAuditRow(Base):
    """One versioned audit record (append-only). Mirrors the in-memory audit dict field-for-field so
    ``audit()`` round-trips exactly after a reload: every create/modify/delete/marker.*/undo carries its
    version, op, fid, kind, and before/after JSON; ``target`` + ``reverted_op`` are the two extra fields an
    ``undo`` record adds. ``session_id`` is an indexed plain column (not a DB FK in Phase 0 -- the FK to
    ``plan``/cascade lands with the Phase-1 schema; integrity is code-enforced here on session delete)."""

    __tablename__ = "edit_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    op: Mapped[str] = mapped_column(String(32), nullable=False)
    fid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    before: Mapped[Optional[dict]] = mapped_column(_json(), nullable=True)
    after: Mapped[Optional[dict]] = mapped_column(_json(), nullable=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)       # undo: the reverted version
    reverted_op: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # undo: the reverted op


# index for the per-session load + delete (audit rows are read/deleted by session_id + version order)
Index("ix_edit_audit_session_version", EditAuditRow.session_id, EditAuditRow.version)


class WorldTxnRow(Base):
    """[PG-01] The DURABLE PROJECTION of a linked world-state transaction (DT-01). NOT authority: the
    conserved TransactionLog (its journal) remains the source of truth; this is a queryable read-model that
    mirrors each committed WorldTransaction so a durable store (Postgres/PostGIS in prod, the SQLite fallback
    in dev/CI) holds the provenance chain for querying. ``seq`` is the monotonic transaction sequence (primary
    key -> idempotent re-mirror). The mirror is best-effort: a projection write NEVER breaks the authoritative
    commit (WorldStateService catches + logs a mirror failure). The full linked identity body is kept in
    ``linked`` (JSON) so a consumer reads the exact DT-01 stamp; the flat columns are for indexed queries."""

    __tablename__ = "world_txn"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)                 # monotonic txn sequence
    world_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    authority_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="genesis")
    twin_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    twin_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="genesis")
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False, default="none")
    mission: Mapped[str] = mapped_column(String(160), nullable=False, default="none")
    site: Mapped[str] = mapped_column(String(64), nullable=False, default="haworth")
    body: Mapped[str] = mapped_column(String(32), nullable=False, default="moon")
    mission_t_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provenance: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    uncertainty_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    linked: Mapped[dict[str, Any]] = mapped_column(_json(), nullable=False, default=dict)   # the full DT-01 stamp
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)             # mirror wall-clock


class ReleaseRevisionRow(Base):
    """[dispatch-audit R1] The DURABLE, IMMUTABLE store of a canonical released mission revision. When the
    executive enters RELEASED it signs an MO-02 ``SignedRevision`` (the frozen intent + a deterministic
    ``content_hash`` + the director sign-off); before R1 that artifact lived only in the release HTTP
    response and was discarded with the in-process executive, so no later run/RC could BIND what was signed.
    This freezes it: one row per ``content_hash`` (the primary key), holding the whole frozen artifact --
    the signed revision (JSON, incl. the full intent), the analyze/rehearse ``evidence`` (the plan_ir
    content-hash + forward_compare), and the ordered approval ``transitions`` (the authority evidence).

    IMMUTABLE by construction: ``content_hash`` is a pure SHA-256 of the intent, so the same plan always
    freezes to the same hash; the store is FIRST-WRITE-WINS (a re-persist of an existing hash is a no-op),
    so a released revision can never be mutated in place. Same backend story as the rest of db.py (Postgres/
    PostGIS in prod via ``$STEWIE_DATABASE_URL``, per-data-dir SQLite in CI/dev)."""

    __tablename__ = "release_revision"

    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)   # SHA-256 of the frozen intent
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mission_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    signed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signed_revision: Mapped[dict[str, Any]] = mapped_column(_json(), nullable=False, default=dict)  # full SignedRevision
    evidence: Mapped[dict[str, Any]] = mapped_column(_json(), nullable=False, default=dict)          # plan_id + forward_compare
    transitions: Mapped[list] = mapped_column(_json(), nullable=False, default=list)                 # approval evidence
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)                     # first-persist wall-clock


# index for the newest-first index scan (R2/UI listing of released revisions)
Index("ix_release_revision_created", ReleaseRevisionRow.created_at)


# ---- the dedicated background event loop (sync facade over the async engine) ----------------------
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """The single background event loop the async engine + all its connections live on. Started lazily,
    daemon so it never blocks process exit."""
    global _loop
    lp = _loop
    if lp is not None and lp.is_running():
        return lp
    with _loop_lock:
        lp = _loop
        if lp is not None and lp.is_running():
            return lp
        lp = asyncio.new_event_loop()
        threading.Thread(target=lp.run_forever, name="stewie-editsession-db", daemon=True).start()
        _loop = lp
        return lp


def _run(coro) -> Any:
    """Submit a coroutine to the background loop and block for its result (the sync bridge)."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result()


# ---- engine / schema lifecycle (lazy, URL-aware so a per-test data-dir change rebinds) ------------
_engine: Optional[AsyncEngine] = None
_engine_url: Optional[str] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None
_ready: bool = False
_ready_lock: Optional[asyncio.Lock] = None


def _resolve_url() -> str:
    """The SQLAlchemy URL: ``$STEWIE_DATABASE_URL`` (normalized to an async driver) if set, else a
    per-``$STEWIE_DATA_DIR`` SQLite file over aiosqlite. NO secret is embedded here -- a password only ever
    arrives inside ``$STEWIE_DATABASE_URL`` from the environment."""
    raw = os.environ.get("STEWIE_DATABASE_URL")
    if raw:
        if raw.startswith("postgresql+"):
            return raw
        if raw.startswith("postgresql://"):
            return "postgresql+asyncpg://" + raw[len("postgresql://"):]
        if raw.startswith("postgres://"):
            return "postgresql+asyncpg://" + raw[len("postgres://"):]
        if raw.startswith("sqlite://") and "+" not in raw.split("://", 1)[0]:
            return "sqlite+aiosqlite://" + raw[len("sqlite://"):]
        return raw
    d = data_dir()
    os.makedirs(d, exist_ok=True)
    return "sqlite+aiosqlite:///" + os.path.join(d, "edit_session.db")


def _get_lock() -> asyncio.Lock:
    global _ready_lock
    if _ready_lock is None:
        _ready_lock = asyncio.Lock()
    return _ready_lock


async def _ensure_ready() -> async_sessionmaker[AsyncSession]:
    """Build (or rebuild, on URL change) the async engine + session factory and create the schema/tables
    idempotently. Runs on the background loop; serialized by an asyncio lock so concurrent callers race-free."""
    global _engine, _engine_url, _sessionmaker, _ready
    url = _resolve_url()
    if _engine is not None and _engine_url == url and _ready and _sessionmaker is not None:
        return _sessionmaker
    async with _get_lock():
        if _engine is not None and _engine_url == url and _ready and _sessionmaker is not None:
            return _sessionmaker
        if _engine is not None and _engine_url != url:           # a different DB (per-test data dir) -> rebind
            await _engine.dispose()
            _engine, _sessionmaker, _ready = None, None, False
        if _engine is None:
            is_sqlite = url.startswith("sqlite")
            kwargs: dict[str, Any] = {"echo": False}
            if is_sqlite:
                # SQLite has no schemas -> fold the logical ``stewie`` schema onto the default; and a busy
                # timeout so a brief concurrent-writer contention waits rather than raising "database is locked".
                kwargs["execution_options"] = {"schema_translate_map": {_SCHEMA: None}}
                kwargs["connect_args"] = {"timeout": 30}
            _engine = create_async_engine(url, **kwargs)
            _engine_url = url
            _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
        if not _ready:
            async with _engine.begin() as conn:
                if not url.startswith("sqlite"):
                    await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
                await conn.run_sync(Base.metadata.create_all)
            _ready = True
        if _sessionmaker is None:   # set in the block above; an explicit raise, never a bare assert (CT-06:
            raise RuntimeError("edit-session store: sessionmaker was not initialized")  # -O strips asserts)
        return _sessionmaker


async def _dispose_engine() -> None:
    """Drop the engine + its pooled connections (simulates a process restart for the durability test, and
    lets the next call rebuild against the current URL). The durable rows are untouched."""
    global _engine, _sessionmaker, _ready, _engine_url
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker, _ready, _engine_url = None, None, False, None


# ---- audit record <-> row mapping -----------------------------------------------------------------
def _row_from_audit(sid: str, rec: dict) -> EditAuditRow:
    return EditAuditRow(
        session_id=sid,
        version=rec["version"],
        op=rec["op"],
        fid=rec.get("fid"),
        kind=rec.get("kind"),
        before=rec.get("before"),
        after=rec.get("after"),
        ts=rec["ts"],
        target=rec.get("target"),
        reverted_op=rec.get("reverted_op"),
    )


def _audit_from_row(row: EditAuditRow) -> dict:
    """Reconstruct the in-memory audit dict EXACTLY (an undo record carries target + reverted_op; a normal
    record does not), so ``audit()`` is byte-identical after a reload."""
    if row.op == "undo":
        return {"version": row.version, "op": "undo", "target": row.target,
                "reverted_op": row.reverted_op, "fid": row.fid, "kind": row.kind,
                "before": row.before, "after": row.after, "ts": row.ts}
    return {"version": row.version, "op": row.op, "fid": row.fid, "kind": row.kind,
            "before": row.before, "after": row.after, "ts": row.ts}


# ---- async operations -----------------------------------------------------------------------------
async def _create_session_row(sid: str, created_at: float, max_sessions: int) -> Optional[str]:
    """Insert a fresh (empty, version-0) session row, enforcing the global bound the in-memory store had:
    if the store is at ``max_sessions``, delete the OLDEST session (its audit + row) first. Returns the
    evicted opaque id (so the caller can drop it from the in-memory cache) or None."""
    sm = await _ensure_ready()
    evicted: Optional[str] = None
    async with sm() as s:
        async with s.begin():
            count = (await s.execute(select(func.count()).select_from(EditSessionRow))).scalar_one()
            if count >= max_sessions:
                oldest = (await s.execute(
                    select(EditSessionRow.opaque_id).order_by(EditSessionRow.created_at.asc()).limit(1)
                )).scalar_one_or_none()
                if oldest is not None:
                    await s.execute(delete(EditAuditRow).where(EditAuditRow.session_id == oldest))
                    await s.execute(delete(EditSessionRow).where(EditSessionRow.opaque_id == oldest))
                    evicted = oldest
            s.add(EditSessionRow(opaque_id=sid, plan_id=None, version=0, created_at=created_at,
                                 fid_seq=0, marker_seq=0, features={}, markers={}))
    return evicted


async def _persist_session(sid: str, version: int, fid_seq: int, marker_seq: int,
                           features: dict, markers: dict, new_audit: list[dict]) -> None:
    """Write-through one mutation: upsert the live session snapshot + append the not-yet-persisted audit
    records, in a single transaction."""
    sm = await _ensure_ready()
    async with sm() as s:
        async with s.begin():
            row = await s.get(EditSessionRow, sid)
            if row is None:                              # first write after a reload/eviction edge -> recreate
                row = EditSessionRow(opaque_id=sid, created_at=0.0)
                s.add(row)
            row.version = version
            row.fid_seq = fid_seq
            row.marker_seq = marker_seq
            row.features = features
            row.markers = markers
            for rec in new_audit:
                s.add(_row_from_audit(sid, rec))


async def _load_session(sid: str) -> Optional[dict]:
    """Load a full session snapshot (row + ordered audit trail) for reconstruction, or None if unknown."""
    sm = await _ensure_ready()
    async with sm() as s:
        row = await s.get(EditSessionRow, sid)
        if row is None:
            return None
        audit_rows = (await s.execute(
            select(EditAuditRow).where(EditAuditRow.session_id == sid).order_by(EditAuditRow.version.asc())
        )).scalars().all()
        return {
            "opaque_id": row.opaque_id,
            "version": row.version,
            "created_at": row.created_at,
            "fid_seq": row.fid_seq,
            "marker_seq": row.marker_seq,
            "features": dict(row.features or {}),
            "markers": dict(row.markers or {}),
            "audit": [_audit_from_row(r) for r in audit_rows],
        }


async def _reset_store() -> None:
    """Truncate both tables (test isolation). ``_ensure_ready`` first so it also rebinds to the current
    per-test data-dir URL before wiping."""
    sm = await _ensure_ready()
    async with sm() as s:
        async with s.begin():
            await s.execute(delete(EditAuditRow))
            await s.execute(delete(EditSessionRow))
            await s.execute(delete(WorldTxnRow))
            await s.execute(delete(ReleaseRevisionRow))


async def _mirror_world_txn(txn: dict) -> None:
    """[PG-01] Upsert one linked world-state transaction into the durable projection, idempotent by ``seq``
    (a re-mirror of the same seq updates in place). NOT authority -- the caller's TransactionLog journal is
    the source of truth; this is the queryable read-model."""
    import time
    sm = await _ensure_ready()
    async with sm() as s:
        async with s.begin():
            seq = int(txn.get("seq", 0))
            row = await s.get(WorldTxnRow, seq)
            if row is None:
                row = WorldTxnRow(seq=seq)
                s.add(row)
            row.world_sha = str(txn.get("world_sha", ""))
            row.chain_hash = str(txn.get("chain_hash", ""))
            row.prev_hash = str(txn.get("prev_hash", ""))
            row.authority_sha = str(txn.get("authority_sha", "genesis"))
            row.twin_version = int(txn.get("twin_version", 0) or 0)
            row.twin_hash = str(txn.get("twin_hash", "genesis"))
            row.plan_id = str(txn.get("plan_id", "none"))
            row.mission = str(txn.get("mission", "none"))
            row.site = str(txn.get("site", "haworth"))
            row.body = str(txn.get("body", "moon"))
            row.mission_t_s = float(txn.get("mission_t_s", 0.0) or 0.0)
            row.provenance = str(txn.get("provenance", ""))
            row.uncertainty_m = float(txn.get("uncertainty_m", 0.0) or 0.0)
            row.linked = dict(txn)
            row.created_at = time.time()


async def _persist_release_revision(art: dict) -> bool:
    """[dispatch-audit R1] Freeze one released revision into the durable store, keyed by ``content_hash``.
    FIRST-WRITE-WINS: if a row already exists for this hash the write is a NO-OP (the signed revision is
    immutable -- a re-release of the same plan, or any later write under an existing hash, must never mutate
    what was signed). Returns True once the hash is durably present (freshly inserted OR already there)."""
    import time
    ch = str(art["content_hash"])
    sm = await _ensure_ready()
    async with sm() as s:
        async with s.begin():
            existing = await s.get(ReleaseRevisionRow, ch)
            if existing is not None:
                return True                                   # immutable: never overwrite the frozen artifact
            s.add(ReleaseRevisionRow(
                content_hash=ch,
                revision=int(art.get("revision", 0) or 0),
                mission_id=str(art.get("mission_id", "")),
                signed_by=str(art.get("signed_by", "")),
                signed_revision=dict(art.get("signed_revision", {}) or {}),
                evidence=dict(art.get("evidence", {}) or {}),
                transitions=list(art.get("transitions", []) or []),
                created_at=time.time(),
            ))
    return True


async def _read_release_revision(content_hash: str) -> Optional[dict]:
    """[dispatch-audit R1] Fetch the frozen released revision for ``content_hash`` (the whole immutable
    artifact), or None if no such revision was ever released."""
    sm = await _ensure_ready()
    async with sm() as s:
        row = await s.get(ReleaseRevisionRow, str(content_hash))
        if row is None:
            return None
        return {
            "content_hash": row.content_hash, "revision": row.revision, "mission_id": row.mission_id,
            "signed_by": row.signed_by, "signed_revision": dict(row.signed_revision or {}),
            "evidence": dict(row.evidence or {}), "transitions": list(row.transitions or []),
            "created_at": row.created_at,
        }


async def _read_world_txns(limit: int) -> list[dict]:
    """[PG-01] Read the durable world-txn projection, newest first (a queryable provenance chain)."""
    sm = await _ensure_ready()
    async with sm() as s:
        rows = (await s.execute(
            select(WorldTxnRow).order_by(WorldTxnRow.seq.desc()).limit(int(limit))
        )).scalars().all()
        return [{
            "seq": r.seq, "world_sha": r.world_sha, "chain_hash": r.chain_hash,
            "authority_sha": r.authority_sha, "twin_version": r.twin_version, "twin_hash": r.twin_hash,
            "plan_id": r.plan_id, "mission": r.mission, "site": r.site, "body": r.body,
            "provenance": r.provenance, "linked": dict(r.linked or {}),
        } for r in rows]


# ---- public sync API (called by edit_session.py; all block on the background loop) ----------------
def init_db() -> None:
    """Create the schema + tables idempotently. The MAIN THREAD calls this once against the live Postgres
    (after standing up the container); dev/tests get it lazily on first use."""
    _run(_ensure_ready())


def create_session_row(sid: str, created_at: float, max_sessions: int) -> Optional[str]:
    return _run(_create_session_row(sid, created_at, max_sessions))


def persist_session(sid: str, version: int, fid_seq: int, marker_seq: int,
                    features: dict, markers: dict, new_audit: list[dict]) -> None:
    _run(_persist_session(sid, version, fid_seq, marker_seq, features, markers, new_audit))


def load_session(sid: str) -> Optional[dict]:
    return _run(_load_session(sid))


def reset_store() -> None:
    _run(_reset_store())


def dispose() -> None:
    """Drop the in-process engine + connection pool WITHOUT touching the durable rows -- the truest
    simulation of a process restart for the survives-restart proof."""
    _run(_dispose_engine())


def mirror_world_txn(txn: dict) -> None:
    """[PG-01] Mirror one committed WorldTransaction (its ``linked_body()`` dict) into the durable
    projection. Wire this as the WorldStateService projection_sink; it is NON-AUTHORITATIVE and blocks
    only briefly on the DB write (SQLite/Postgres)."""
    _run(_mirror_world_txn(txn))


def read_world_txns(limit: int = 100) -> list[dict]:
    """[PG-01] Read the durable world-txn projection (newest first)."""
    return _run(_read_world_txns(limit))


def persist_release_revision(art: dict) -> bool:
    """[dispatch-audit R1] Durably freeze a released revision (immutable, first-write-wins by content_hash).
    ``art`` = {content_hash, revision, mission_id, signed_by, signed_revision, evidence, transitions}."""
    return _run(_persist_release_revision(art))


def read_release_revision(content_hash: str) -> Optional[dict]:
    """[dispatch-audit R1] Fetch the frozen released revision by content_hash (None if never released)."""
    return _run(_read_release_revision(content_hash))


if __name__ == "__main__":       # convenience: `python -m stewie.server.db` runs the idempotent schema-init
    init_db()
    print(f"stewie edit-session store ready at {_resolve_url().split('@')[-1]}")
