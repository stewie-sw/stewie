//! Mission-feature edit sessions (RW-55b12; Python `server.edit_session` over `server.db`, routes `routers.editsession`):
//! the server-owned, versioned keep-out and place-object marker set an operator authors in the IDE, with an
//! append-only before/after audit and a linear undo. The durable store is the authority, with the Python's own
//! tables: Postgres (schema `stewie`) when `STEWIE_DATABASE_URL` is set, else the `SQLite` file
//! `data_dir/edit_session.db`. Every mutation is one serialized transaction (load, apply, write the snapshot, append
//! the audit), so concurrent edits serialize and nothing half-applied is ever visible. JSON columns hold the text
//! `SQLAlchemy` writes (`json.dumps`, insertion order; Postgres `JSONB` keeps its own key order, D-R161), so the
//! Python and Rust servers read each other's sessions. The same store mirrors each committed world transaction to
//! the `world_txn` projection when a database URL is configured (PG-01).
//! The routes are keyless: the unguessable session id is the capability (the Python's posture).

use std::path::PathBuf;
use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Request, State};
use axum::http::{Method, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::routing::{delete, get, patch, post};
use serde_json::{Value, json};
use sqlx::any::{AnyConnectOptions, AnyPoolOptions};
use sqlx::{AnyConnection, AnyPool, ConnectOptions as _, Row};

use crate::app::{ApiError, AppState, Head, err, log, no_route_for, parse_body, split};
use crate::operators::py_repr;
use crate::validate::{self, Field, Kind, Model, Ordered};

const MAX_KEEPOUT_VERTS: usize = 256;
const MAX_FEATURES_PER_SESSION: usize = 200;
const MAX_SESSIONS: i64 = 512;
const MAX_MARKERS_PER_SESSION: usize = 200;
const MARKER_TYPES: [&str; 5] = ["antenna", "beacon", "cache", "instrument", "sample"];
const MAX_MARKER_LABEL_LEN: usize = 80;
const AUDIT_TAIL: usize = 50;
/// The Postgres advisory lock that serializes the Rust writers (the `SQLite` path takes `BEGIN IMMEDIATE`).
const WRITE_LOCK: i64 = 0x5354_4557_4945; // "STEWIE"

/// The Python's tables, as `SQLAlchemy` creates them on `SQLite`.
const SQLITE_DDL: [&str; 6] = [
    "CREATE TABLE IF NOT EXISTS edit_session (\n\topaque_id VARCHAR(64) NOT NULL, \n\tplan_id VARCHAR(64), \n\t\
     version INTEGER NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tfid_seq INTEGER NOT NULL, \n\tmarker_seq INTEGER NOT \
     NULL, \n\tfeatures JSON NOT NULL, \n\tmarkers JSON NOT NULL, \n\tPRIMARY KEY (opaque_id)\n)",
    "CREATE TABLE IF NOT EXISTS edit_audit (\n\tid INTEGER NOT NULL, \n\tsession_id VARCHAR(64) NOT NULL, \n\tversion \
     INTEGER NOT NULL, \n\top VARCHAR(32) NOT NULL, \n\tfid VARCHAR(64), \n\tkind VARCHAR(32), \n\t\"before\" JSON, \n\t\
     \"after\" JSON, \n\tts FLOAT NOT NULL, \n\ttarget INTEGER, \n\treverted_op VARCHAR(32), \n\tPRIMARY KEY (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_edit_audit_session_version ON edit_audit (session_id, version)",
    "CREATE TABLE IF NOT EXISTS world_txn (\n\tseq INTEGER NOT NULL, \n\tworld_sha VARCHAR(64) NOT NULL, \n\tchain_hash \
     VARCHAR(64) NOT NULL, \n\tprev_hash VARCHAR(64) NOT NULL, \n\tauthority_sha VARCHAR(64) NOT NULL, \n\ttwin_version \
     INTEGER NOT NULL, \n\ttwin_hash VARCHAR(64) NOT NULL, \n\tplan_id VARCHAR(64) NOT NULL, \n\tmission VARCHAR(160) NOT \
     NULL, \n\tsite VARCHAR(64) NOT NULL, \n\tbody VARCHAR(32) NOT NULL, \n\tmission_t_s FLOAT NOT NULL, \n\tprovenance \
     VARCHAR(240) NOT NULL, \n\tuncertainty_m FLOAT NOT NULL, \n\tlinked JSON NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\t\
     PRIMARY KEY (seq)\n)",
    "CREATE TABLE IF NOT EXISTS release_revision (\n\tcontent_hash VARCHAR(64) NOT NULL, \n\trevision INTEGER NOT NULL, \
     \n\tmission_id VARCHAR(160) NOT NULL, \n\tsigned_by VARCHAR(64) NOT NULL, \n\tsigned_revision JSON NOT NULL, \n\t\
     evidence JSON NOT NULL, \n\ttransitions JSON NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY \
     (content_hash)\n)",
    "CREATE INDEX IF NOT EXISTS ix_release_revision_created ON release_revision (created_at)",
];

/// The Python's tables, as `SQLAlchemy` creates them on Postgres.
const POSTGRES_DDL: [&str; 7] = [
    "CREATE SCHEMA IF NOT EXISTS stewie",
    "CREATE TABLE IF NOT EXISTS stewie.edit_session (\n\topaque_id VARCHAR(64) NOT NULL, \n\tplan_id VARCHAR(64), \n\t\
     version INTEGER NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tfid_seq INTEGER NOT NULL, \n\tmarker_seq INTEGER NOT \
     NULL, \n\tfeatures JSONB NOT NULL, \n\tmarkers JSONB NOT NULL, \n\tPRIMARY KEY (opaque_id)\n)",
    "CREATE TABLE IF NOT EXISTS stewie.edit_audit (\n\tid SERIAL NOT NULL, \n\tsession_id VARCHAR(64) NOT NULL, \n\t\
     version INTEGER NOT NULL, \n\top VARCHAR(32) NOT NULL, \n\tfid VARCHAR(64), \n\tkind VARCHAR(32), \n\tbefore JSONB, \
     \n\tafter JSONB, \n\tts FLOAT NOT NULL, \n\ttarget INTEGER, \n\treverted_op VARCHAR(32), \n\tPRIMARY KEY (id)\n)",
    "CREATE INDEX IF NOT EXISTS ix_edit_audit_session_version ON stewie.edit_audit (session_id, version)",
    "CREATE TABLE IF NOT EXISTS stewie.world_txn (\n\tseq SERIAL NOT NULL, \n\tworld_sha VARCHAR(64) NOT NULL, \n\t\
     chain_hash VARCHAR(64) NOT NULL, \n\tprev_hash VARCHAR(64) NOT NULL, \n\tauthority_sha VARCHAR(64) NOT NULL, \n\t\
     twin_version INTEGER NOT NULL, \n\ttwin_hash VARCHAR(64) NOT NULL, \n\tplan_id VARCHAR(64) NOT NULL, \n\tmission \
     VARCHAR(160) NOT NULL, \n\tsite VARCHAR(64) NOT NULL, \n\tbody VARCHAR(32) NOT NULL, \n\tmission_t_s FLOAT NOT NULL, \
     \n\tprovenance VARCHAR(240) NOT NULL, \n\tuncertainty_m FLOAT NOT NULL, \n\tlinked JSONB NOT NULL, \n\tcreated_at \
     FLOAT NOT NULL, \n\tPRIMARY KEY (seq)\n)",
    "CREATE TABLE IF NOT EXISTS stewie.release_revision (\n\tcontent_hash VARCHAR(64) NOT NULL, \n\trevision INTEGER \
     NOT NULL, \n\tmission_id VARCHAR(160) NOT NULL, \n\tsigned_by VARCHAR(64) NOT NULL, \n\tsigned_revision JSONB NOT \
     NULL, \n\tevidence JSONB NOT NULL, \n\ttransitions JSONB NOT NULL, \n\tcreated_at FLOAT NOT NULL, \n\tPRIMARY KEY \
     (content_hash)\n)",
    "CREATE INDEX IF NOT EXISTS ix_release_revision_created ON stewie.release_revision (created_at)",
];

/// Which database the store talks to; the statements differ only by the schema prefix and the `JSONB` casts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Dialect {
    Sqlite,
    Postgres,
}

/// The edit-session store: a pool on `STEWIE_DATABASE_URL` (Postgres) or `data_dir/edit_session.db`, opened and its
/// schema made on first use, so the server starts before the database is up (as the Python's).
#[derive(Debug, Clone)]
pub struct Store {
    path: PathBuf,
    url: Option<String>,
    pool: Arc<tokio::sync::OnceCell<(AnyPool, Dialect)>>,
}

fn db_error(e: impl std::fmt::Display) -> ApiError {
    err(
        StatusCode::INTERNAL_SERVER_ERROR,
        format!("edit-session store: {e}"),
    )
}

/// The sqlx form of a `SQLAlchemy` Postgres URL: the `+driver` suffix (`postgresql+asyncpg://`) dropped. Anything
/// but a Postgres URL is refused (D-R161).
///
/// # Errors
/// A URL that does not name Postgres. The message never repeats the URL (it carries the password).
pub fn postgres_url(raw: &str) -> Result<String, String> {
    let raw = raw.trim();
    let (scheme, rest) = raw.split_once("://").unwrap_or(("", ""));
    match scheme.split('+').next() {
        Some("postgresql" | "postgres") if !rest.is_empty() => Ok(format!("postgresql://{rest}")),
        _ => Err("STEWIE_DATABASE_URL must be a postgresql:// (or postgresql+<driver>://) URL; the Rust server keeps \
                  the SQLite store in the data directory when it is unset (D-R161)"
            .to_owned()),
    }
}

impl Store {
    /// The store for a data directory, or for the Postgres database `url` (already [`postgres_url`]-normalised).
    /// Nothing is opened yet.
    #[must_use]
    pub fn new(data_dir: &std::path::Path, url: Option<&str>) -> Self {
        Self {
            path: data_dir.join("edit_session.db"),
            url: url.map(str::to_owned),
            pool: Arc::default(),
        }
    }

    async fn pool(&self) -> Result<&(AnyPool, Dialect), ApiError> {
        self.pool
            .get_or_try_init(|| async {
                sqlx::any::install_default_drivers();
                let (opts, dialect, ddl): (AnyConnectOptions, _, &[&str]) =
                    if let Some(u) = &self.url {
                        (
                            u.parse()
                                .map_err(|_| db_error("STEWIE_DATABASE_URL does not parse"))?,
                            Dialect::Postgres,
                            &POSTGRES_DDL,
                        )
                    } else {
                        let url = sqlx::sqlite::SqliteConnectOptions::new()
                            .filename(&self.path)
                            .create_if_missing(true)
                            .to_url_lossy();
                        (
                            AnyConnectOptions::from_url(&url).map_err(db_error)?,
                            Dialect::Sqlite,
                            &SQLITE_DDL,
                        )
                    };
                let mut pool = AnyPoolOptions::new().max_connections(4);
                if dialect == Dialect::Postgres {
                    // an unreachable database answers a request in 5 s, not sqlx's default 30 s
                    pool = pool.acquire_timeout(std::time::Duration::from_secs(5));
                }
                let pool = pool
                    .after_connect(move |c, _| {
                        Box::pin(async move {
                            if dialect == Dialect::Sqlite {
                                sqlx::query("PRAGMA busy_timeout = 30000")
                                    .execute(c)
                                    .await?;
                            }
                            Ok(())
                        })
                    })
                    .connect_with(opts)
                    .await
                    .map_err(db_error)?;
                for q in ddl {
                    sqlx::query(q).execute(&pool).await.map_err(db_error)?;
                }
                Ok((pool, dialect))
            })
            .await
    }

    /// Run `f` inside one serialized transaction (the write lock taken before the first read), committing on `Ok`.
    async fn immediate<T>(
        &self,
        f: impl AsyncFnOnce(&mut AnyConnection, Dialect) -> Result<T, ApiError>,
    ) -> Result<T, ApiError> {
        let (pool, dialect) = self.pool().await?;
        let begin: &[&str] = match dialect {
            Dialect::Sqlite => &["BEGIN IMMEDIATE"],
            Dialect::Postgres => &["BEGIN", "SELECT pg_advisory_xact_lock($1)"],
        };
        Self::transaction(pool, *dialect, begin, f).await
    }

    /// Run `f` inside one read-only snapshot, so a session row and its audit trail are read at one version.
    async fn snapshot<T>(
        &self,
        f: impl AsyncFnOnce(&mut AnyConnection, Dialect) -> Result<T, ApiError>,
    ) -> Result<T, ApiError> {
        let (pool, dialect) = self.pool().await?;
        let begin: &[&str] = match dialect {
            Dialect::Sqlite => &["BEGIN"],
            Dialect::Postgres => &["BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY"],
        };
        Self::transaction(pool, *dialect, begin, f).await
    }

    async fn transaction<T>(
        pool: &AnyPool,
        dialect: Dialect,
        begin: &[&str],
        f: impl AsyncFnOnce(&mut AnyConnection, Dialect) -> Result<T, ApiError>,
    ) -> Result<T, ApiError> {
        let mut conn = pool.acquire().await.map_err(db_error)?;
        for q in begin {
            let q = if q.contains("$1") {
                sqlx::query(q).bind(WRITE_LOCK)
            } else {
                sqlx::query(q)
            };
            q.execute(&mut *conn).await.map_err(db_error)?;
        }
        let out = f(&mut conn, dialect).await;
        let end = if out.is_ok() { "COMMIT" } else { "ROLLBACK" };
        sqlx::query(end)
            .execute(&mut *conn)
            .await
            .map_err(db_error)?;
        out
    }

    /// Upsert one committed world transaction into the `world_txn` projection, keyed by its `seq` (Python
    /// `db._mirror_world_txn`). Not authority: the journal is; the caller logs and drops a failure.
    ///
    /// # Errors
    /// The database unreachable or refusing the row.
    pub async fn mirror_world_txn(&self, txn: &Value, now: f64) -> Result<(), ApiError> {
        let (pool, dialect) = self.pool().await?;
        let s = |k: &str, d: &str| txn.get(k).and_then(Value::as_str).unwrap_or(d).to_owned();
        let f = |k: &str| txn.get(k).and_then(Value::as_f64).unwrap_or(0.0);
        let linked = stewie_twin::pyjson::dumps(txn).map_err(db_error)?;
        sqlx::query(&sql(
            *dialect,
            "INSERT INTO {s}world_txn (seq, world_sha, chain_hash, prev_hash, authority_sha, twin_version, twin_hash, \
             plan_id, mission, site, body, mission_t_s, provenance, uncertainty_m, linked, created_at) VALUES ($1, $2, \
             $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15{j}, $16) ON CONFLICT (seq) DO UPDATE SET \
             world_sha = excluded.world_sha, chain_hash = excluded.chain_hash, prev_hash = excluded.prev_hash, \
             authority_sha = excluded.authority_sha, twin_version = excluded.twin_version, twin_hash = \
             excluded.twin_hash, plan_id = excluded.plan_id, mission = excluded.mission, site = excluded.site, \
             body = excluded.body, mission_t_s = excluded.mission_t_s, provenance = excluded.provenance, \
             uncertainty_m = excluded.uncertainty_m, linked = excluded.linked, created_at = excluded.created_at",
        ))
        .bind(i32::try_from(txn.get("seq").and_then(Value::as_i64).unwrap_or(0)).map_err(db_error)?)
        .bind(s("world_sha", ""))
        .bind(s("chain_hash", ""))
        .bind(s("prev_hash", ""))
        .bind(s("authority_sha", "genesis"))
        .bind(i32::try_from(txn.get("twin_version").and_then(Value::as_i64).unwrap_or(0)).map_err(db_error)?)
        .bind(s("twin_hash", "genesis"))
        .bind(s("plan_id", "none"))
        .bind(s("mission", "none"))
        .bind(s("site", "haworth"))
        .bind(s("body", "moon"))
        .bind(f("mission_t_s"))
        .bind(s("provenance", ""))
        .bind(f("uncertainty_m"))
        .bind(linked)
        .bind(now)
        .execute(pool)
        .await
        .map_err(db_error)?;
        Ok(())
    }
}

impl Store {
    /// Freeze one released revision keyed by its `content_hash` (Python `db.persist_release_revision`):
    /// first write wins, so a signed revision is never mutated; true once the hash is durably present.
    ///
    /// # Errors
    /// The database unreachable or refusing the row.
    pub async fn persist_release_revision(&self, art: &Value, now: f64) -> Result<bool, ApiError> {
        let (pool, dialect) = self.pool().await?;
        let s = |k: &str| art.get(k).and_then(Value::as_str).unwrap_or("").to_owned();
        let doc = |k: &str, d: Value| {
            stewie_twin::pyjson::dumps(&art.get(k).filter(|v| !v.is_null()).cloned().unwrap_or(d))
                .map_err(db_error)
        };
        sqlx::query(&sql(
            *dialect,
            "INSERT INTO {s}release_revision (content_hash, revision, mission_id, signed_by, signed_revision, \
             evidence, transitions, created_at) VALUES ($1, $2, $3, $4, $5{j}, $6{j}, $7{j}, $8) ON CONFLICT \
             (content_hash) DO NOTHING",
        ))
        .bind(s("content_hash"))
        .bind(i32::try_from(art.get("revision").and_then(Value::as_i64).unwrap_or(0)).map_err(db_error)?)
        .bind(s("mission_id"))
        .bind(s("signed_by"))
        .bind(doc("signed_revision", json!({}))?)
        .bind(doc("evidence", json!({}))?)
        .bind(doc("transitions", json!([]))?)
        .bind(now)
        .execute(pool)
        .await
        .map_err(db_error)?;
        Ok(true)
    }

    /// The frozen released revision with `content_hash` (Python `db.read_release_revision`), or `None` when none was
    /// ever released.
    ///
    /// # Errors
    /// The database unreachable, or a stored JSON column that does not parse.
    pub async fn read_release_revision(
        &self,
        content_hash: &str,
    ) -> Result<Option<Value>, ApiError> {
        let (pool, dialect) = self.pool().await?;
        let row = sqlx::query(&sql(
            *dialect,
            "SELECT content_hash, revision, mission_id, signed_by, CAST(signed_revision AS TEXT) AS signed_revision, \
             CAST(evidence AS TEXT) AS evidence, CAST(transitions AS TEXT) AS transitions, created_at FROM \
             {s}release_revision WHERE content_hash = $1",
        ))
        .bind(content_hash.to_owned())
        .fetch_optional(pool)
        .await
        .map_err(db_error)?;
        let Some(r) = row else {
            return Ok(None);
        };
        let doc = |k: &str| -> Result<Value, ApiError> {
            let text: String = r.try_get(k).map_err(db_error)?;
            serde_json::from_str(&text).map_err(db_error)
        };
        Ok(Some(json!({
            "content_hash": r.try_get::<String, _>("content_hash").map_err(db_error)?,
            "revision": r.try_get::<i32, _>("revision").map_err(db_error)?,
            "mission_id": r.try_get::<String, _>("mission_id").map_err(db_error)?,
            "signed_by": r.try_get::<String, _>("signed_by").map_err(db_error)?,
            "signed_revision": doc("signed_revision")?, "evidence": doc("evidence")?,
            "transitions": doc("transitions")?,
            "created_at": r.try_get::<f64, _>("created_at").map_err(db_error)?,
        })))
    }
}

/// A statement for `dialect`: `{s}` is the Postgres schema prefix, `{j}` the cast a text bind needs into `JSONB`.
fn sql(dialect: Dialect, q: &str) -> String {
    let (schema, jsonb) = match dialect {
        Dialect::Sqlite => ("", ""),
        Dialect::Postgres => ("stewie.", "::jsonb"),
    };
    q.replace("{s}", schema).replace("{j}", jsonb)
}

/// One audit record (the Python's dict, an undo adding `target` and `reverted_op`).
#[derive(Debug, Clone)]
struct Audit {
    version: i64,
    op: String,
    fid: Option<String>,
    kind: Option<String>,
    before: Ordered,
    after: Ordered,
    ts: f64,
    target: Option<i64>,
    reverted_op: Option<String>,
}

impl Audit {
    fn to_value(&self) -> Value {
        let mut v = json!({"version": self.version, "op": self.op, "fid": self.fid, "kind": self.kind,
                           "before": self.before.to_value(), "after": self.after.to_value(), "ts": self.ts});
        if self.op == "undo" {
            v["target"] = json!(self.target);
            v["reverted_op"] = json!(self.reverted_op);
        }
        v
    }
}

/// A session as loaded: the live keep-outs and markers in insertion order, and the audit trail.
#[derive(Debug)]
struct Session {
    id: String,
    version: i64,
    fid_seq: i64,
    marker_seq: i64,
    features: Vec<(String, Ordered)>,
    markers: Vec<(String, Ordered)>,
    audit: Vec<Audit>,
    persisted: usize,
}

fn ordered_map(text: &str) -> Result<Vec<(String, Ordered)>, ApiError> {
    match serde_json::from_str::<Ordered>(text).map_err(db_error)? {
        Ordered::Object(m) => Ok(m),
        _ => Err(db_error("a feature set that is not a JSON object")),
    }
}

fn ordered(text: Option<String>) -> Result<Ordered, ApiError> {
    text.map_or(Ok(Ordered::Null), |t| {
        serde_json::from_str(&t).map_err(db_error)
    })
}

fn dumps(v: &Ordered) -> Result<String, ApiError> {
    v.py_dumps().map_err(db_error)
}

/// The live keep-out (or marker) ids in the order the Python's dict holds them, replayed from the audit: Postgres
/// `JSONB` stores keys by length then bytes, so a feature an undo restored would otherwise move back to its mint
/// position and change the planner's keep-out order (D-R161). A create, or an undone delete or modify, inserts a key
/// last; a delete, or an undone create, removes it; a modify keeps its place.
fn insertion_order(audit: &[Audit], markers: bool) -> Vec<String> {
    let mut keys: Vec<String> = Vec::new();
    for a in audit {
        let Some(fid) = &a.fid else { continue };
        let (op, undone) = match (a.op.as_str(), &a.reverted_op) {
            ("undo", Some(r)) => (r.as_str(), true),
            (op, _) => (op, false),
        };
        if op.starts_with("marker.") != markers {
            continue;
        }
        let inserts = matches!(
            (op, undone),
            ("create" | "marker.create", false) | ("delete" | "modify" | "marker.delete", true)
        );
        let removes = matches!(
            (op, undone),
            ("delete" | "marker.delete", false) | ("create" | "marker.create", true)
        );
        match keys.iter().position(|k| k == fid) {
            Some(i) if removes => {
                keys.remove(i);
            }
            None if inserts => keys.push(fid.clone()),
            _ => {}
        }
    }
    keys
}

/// Insert or replace a key in an insertion-ordered map, as a Python dict assignment does (a new key goes last).
fn put(map: &mut Vec<(String, Ordered)>, key: &str, value: Ordered) {
    match map.iter_mut().find(|(k, _)| k == key) {
        Some(slot) => slot.1 = value,
        None => map.push((key.to_owned(), value)),
    }
}

fn take(map: &mut Vec<(String, Ordered)>, key: &str) -> Option<Ordered> {
    let i = map.iter().position(|(k, _)| k == key)?;
    Some(map.remove(i).1)
}

impl Session {
    async fn load(
        conn: &mut AnyConnection,
        d: Dialect,
        sid: &str,
    ) -> Result<Option<Self>, ApiError> {
        let Some(row) = sqlx::query(&sql(
            d,
            "SELECT version, fid_seq, marker_seq, CAST(features AS TEXT) AS features, CAST(markers AS TEXT) AS \
             markers FROM {s}edit_session WHERE opaque_id = $1",
        ))
        .bind(sid)
        .fetch_optional(&mut *conn)
        .await
        .map_err(db_error)?
        else {
            return Ok(None);
        };
        let audit = sqlx::query(&sql(
            d,
            "SELECT version, op, fid, kind, CAST(\"before\" AS TEXT) AS \"before\", CAST(\"after\" AS TEXT) AS \
             \"after\", ts, target, reverted_op FROM {s}edit_audit WHERE session_id = $1 ORDER BY version ASC",
        ))
        .bind(sid)
        .fetch_all(&mut *conn)
        .await
        .map_err(db_error)?
        .into_iter()
        .map(|r| {
            Ok(Audit {
                version: r.get("version"),
                op: r.get("op"),
                fid: r.get("fid"),
                kind: r.get("kind"),
                before: ordered(r.get("before"))?,
                after: ordered(r.get("after"))?,
                ts: r.get("ts"),
                target: r.get("target"),
                reverted_op: r.get("reverted_op"),
            })
        })
        .collect::<Result<Vec<_>, ApiError>>()?;
        let persisted = audit.len();
        let mut features = ordered_map(&row.get::<String, _>("features"))?;
        let mut markers = ordered_map(&row.get::<String, _>("markers"))?;
        for (map, is_marker) in [(&mut features, false), (&mut markers, true)] {
            let keys = insertion_order(&audit, is_marker);
            map.sort_by_key(|(k, _)| keys.iter().position(|x| x == k).unwrap_or(usize::MAX));
        }
        Ok(Some(Self {
            id: sid.to_owned(),
            version: row.get("version"),
            fid_seq: row.get("fid_seq"),
            marker_seq: row.get("marker_seq"),
            features,
            markers,
            audit,
            persisted,
        }))
    }

    /// Write the snapshot and the audit records added since the load.
    async fn save(&self, conn: &mut AnyConnection, d: Dialect) -> Result<(), ApiError> {
        sqlx::query(&sql(
            d,
            "UPDATE {s}edit_session SET version = $1, fid_seq = $2, marker_seq = $3, features = $4{j}, markers = \
             $5{j} WHERE opaque_id = $6",
        ))
        .bind(self.version)
        .bind(self.fid_seq)
        .bind(self.marker_seq)
        .bind(dumps(&Ordered::Object(self.features.clone()))?)
        .bind(dumps(&Ordered::Object(self.markers.clone()))?)
        .bind(&self.id)
        .execute(&mut *conn)
        .await
        .map_err(db_error)?;
        for a in &self.audit[self.persisted..] {
            sqlx::query(&sql(
                d,
                "INSERT INTO {s}edit_audit (session_id, version, op, fid, kind, \"before\", \"after\", ts, target, \
                 reverted_op) VALUES ($1, $2, $3, $4, $5, $6{j}, $7{j}, $8, $9, $10)",
            ))
            .bind(&self.id)
            .bind(a.version)
            .bind(&a.op)
            .bind(&a.fid)
            .bind(&a.kind)
            .bind(dumps(&a.before)?)
            .bind(dumps(&a.after)?)
            .bind(a.ts)
            .bind(a.target)
            .bind(&a.reverted_op)
            .execute(&mut *conn)
            .await
            .map_err(db_error)?;
        }
        Ok(())
    }

    fn record(
        &mut self,
        op: &str,
        fid: &str,
        kind: &str,
        before: Ordered,
        after: Ordered,
        ts: f64,
    ) {
        self.version += 1;
        self.audit.push(Audit {
            version: self.version,
            op: op.to_owned(),
            fid: Some(fid.to_owned()),
            kind: Some(kind.to_owned()),
            before,
            after,
            ts,
            target: None,
            reverted_op: None,
        });
    }

    fn state(&self) -> Value {
        let tail = self.audit.len().saturating_sub(AUDIT_TAIL);
        json!({"session": self.id, "version": self.version,
               "features": self.features.iter().map(|(_, f)| f.to_value()).collect::<Vec<_>>(),
               "markers": self.markers.iter().map(|(_, m)| m.to_value()).collect::<Vec<_>>(),
               "audit": self.audit[tail..].iter().map(Audit::to_value).collect::<Vec<_>>()})
    }

    /// Revert the last live edit not already undone, appending an `undo` record (Python `EditSession.undo`).
    fn undo(&mut self, ts: f64) -> Result<Value, ApiError> {
        const UNDOABLE: [&str; 5] = [
            "create",
            "modify",
            "delete",
            "marker.create",
            "marker.delete",
        ];
        let undone: Vec<i64> = self
            .audit
            .iter()
            .filter(|a| a.op == "undo")
            .filter_map(|a| a.target)
            .collect();
        let Some(target) = self
            .audit
            .iter()
            .rev()
            .find(|a| UNDOABLE.contains(&a.op.as_str()) && !undone.contains(&a.version))
            .cloned()
        else {
            return Err(err(StatusCode::BAD_REQUEST, "nothing to undo"));
        };
        let fid = target.fid.clone().unwrap_or_default();
        match target.op.as_str() {
            "create" => drop(take(&mut self.features, &fid)),
            "delete" | "modify" => put(&mut self.features, &fid, target.before.clone()),
            "marker.create" => drop(take(&mut self.markers, &fid)),
            _ => put(&mut self.markers, &fid, target.before.clone()),
        }
        self.version += 1;
        self.audit.push(Audit {
            version: self.version,
            op: "undo".to_owned(),
            fid: target.fid.clone(),
            kind: target.kind.clone(),
            before: target.after.clone(),
            after: target.before.clone(),
            ts,
            target: Some(target.version),
            reverted_op: Some(target.op.clone()),
        });
        Ok(json!({"undone_version": target.version, "reverted_op": target.op, "fid": fid}))
    }
}

/// Python's `repr` of a float, `inf` and `nan` included.
fn float_repr(x: f64) -> String {
    if x.is_nan() {
        "nan".to_owned()
    } else if x.is_infinite() {
        if x > 0.0 { "inf" } else { "-inf" }.to_owned()
    } else {
        stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
    }
}

/// Python `float(v)` of a client value: a number, a bool, or numeric text (`inf` and `nan` included); `None` where
/// the Python raises `TypeError` or `ValueError`.
fn py_float(v: &Ordered) -> Option<f64> {
    match v {
        Ordered::Number(n) => n.as_f64(),
        Ordered::Bool(b) => Some(f64::from(u8::from(*b))),
        Ordered::String(s) => {
            let t = s.trim();
            let b = t.as_bytes();
            let underscores_ok = b.iter().enumerate().all(|(i, &c)| {
                c != b'_'
                    || (i > 0
                        && i + 1 < b.len()
                        && b[i - 1].is_ascii_digit()
                        && b[i + 1].is_ascii_digit())
            });
            if underscores_ok {
                t.replace('_', "").parse().ok()
            } else {
                None
            }
        }
        _ => None,
    }
}

/// The Python's `_finite`: a finite float, or the 400 naming `what` and the client's value.
fn finite(v: &Ordered, what: &str) -> Result<f64, ApiError> {
    let bad = |m: String| err(StatusCode::BAD_REQUEST, m);
    match py_float(v) {
        None => Err(bad(format!(
            "{what} must be a number (got {})",
            v.py_repr()
        ))),
        Some(x) if !x.is_finite() => {
            Err(bad(format!("{what} must be finite (got {})", v.py_repr())))
        }
        Some(x) => Ok(x),
    }
}

fn num(x: f64) -> Ordered {
    serde_json::Number::from_f64(x).map_or(Ordered::Null, Ordered::Number)
}

/// A keep-out geometry normalised into the stored schema (Python `_normalize_geometry`).
fn geometry(kind: &str, body: &Ordered) -> Result<(String, Vec<(String, Ordered)>), ApiError> {
    let bad = |m: String| err(StatusCode::BAD_REQUEST, m);
    let field = |k: &str| body.get(k).cloned().unwrap_or(Ordered::Null);
    match kind.to_lowercase().as_str() {
        "circle" => {
            let cx = finite(&field("cx"), "circle cx")?;
            let cy = finite(&field("cy"), "circle cy")?;
            let r = finite(&field("r"), "circle r")?;
            if r <= 0.0 {
                return Err(bad(format!("circle r must be > 0 (got {})", float_repr(r))));
            }
            let g = vec![
                ("kind".into(), Ordered::String("circle".into())),
                ("cx".into(), num(cx)),
                ("cy".into(), num(cy)),
                ("r".into(), num(r)),
            ];
            Ok(("circle".to_owned(), g))
        }
        "polygon" => {
            let Ordered::Array(ring) = field("ring") else {
                return Err(bad(
                    "polygon needs a 'ring' list of [x, y] vertices".to_owned()
                ));
            };
            if !(3..=MAX_KEEPOUT_VERTS).contains(&ring.len()) {
                return Err(bad(format!(
                    "polygon needs 3..{MAX_KEEPOUT_VERTS} vertices (got {})",
                    ring.len()
                )));
            }
            let mut pts = Vec::new();
            for (i, p) in ring.iter().enumerate() {
                let Ordered::Array(xy) = p else {
                    return Err(bad(format!("polygon vertex {i} must be [x, y]")));
                };
                if xy.len() != 2 {
                    return Err(bad(format!("polygon vertex {i} must be [x, y]")));
                }
                let x = finite(&xy[0], &format!("polygon vertex {i} x"))?;
                let y = finite(&xy[1], &format!("polygon vertex {i} y"))?;
                pts.push(Ordered::Array(vec![num(x), num(y)]));
            }
            Ok((
                "polygon".to_owned(),
                vec![
                    ("kind".into(), Ordered::String("polygon".into())),
                    ("ring".into(), Ordered::Array(pts)),
                ],
            ))
        }
        _ => Err(bad(format!(
            "unknown keep-out kind {} (want 'circle' or 'polygon')",
            py_repr(kind)
        ))),
    }
}

/// A place-object marker normalised into the stored schema (Python `_normalize_marker`).
fn marker(body: &Ordered) -> Result<Vec<(String, Ordered)>, ApiError> {
    let field = |k: &str| body.get(k).cloned().unwrap_or(Ordered::Null);
    let x = finite(&field("x"), "marker x")?;
    let y = finite(&field("y"), "marker y")?;
    let text = |v: Ordered| match v {
        Ordered::String(s) => s,
        _ => String::new(),
    };
    let otype = text(field("otype")).trim().to_lowercase();
    if !MARKER_TYPES.contains(&otype.as_str()) {
        let want = MARKER_TYPES
            .iter()
            .map(|t| py_repr(t))
            .collect::<Vec<_>>()
            .join(", ");
        return Err(err(
            StatusCode::BAD_REQUEST,
            format!(
                "unknown object type {} (want one of [{want}])",
                py_repr(&otype)
            ),
        ));
    }
    let mut label: String = text(field("label"))
        .trim()
        .chars()
        .take(MAX_MARKER_LABEL_LEN)
        .collect();
    if label.is_empty() {
        let mut c = otype.chars();
        label = c
            .next()
            .map(|f| f.to_uppercase().chain(c).collect())
            .unwrap_or_default();
    }
    Ok(vec![
        ("kind".into(), Ordered::String("marker".into())),
        ("x".into(), num(x)),
        ("y".into(), num(y)),
        ("otype".into(), Ordered::String(otype)),
        ("label".into(), Ordered::String(label)),
    ])
}

const FLOAT: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: None,
};
const TEXT: Kind = Kind::Str {
    min: 0,
    max: usize::MAX,
    nullable: false,
    default: None,
};
const KEEPOUT_IN: Model = Model {
    fields: &[
        Field("kind", TEXT),
        Field("cx", Kind::Opt(&FLOAT)),
        Field("cy", Kind::Opt(&FLOAT)),
        Field("r", Kind::Opt(&FLOAT)),
        Field("ring", Kind::Opt(&Kind::AnyList)),
    ],
    forbid_extra: true,
};
const MARKER_IN: Model = Model {
    fields: &[
        Field("x", FLOAT),
        Field("y", FLOAT),
        Field("otype", TEXT),
        Field("label", Kind::Opt(&TEXT)),
    ],
    forbid_extra: true,
};

/// The request body validated against `model`, kept in the client's key order (with the model's coerced floats).
fn validated(bytes: &[u8], model: Model) -> Result<Ordered, ApiError> {
    let body = parse_body(&bytes.to_vec().into())?;
    let v = validate::model(body.as_ref(), model).map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
    let raw: Ordered =
        serde_json::from_slice(bytes).map_err(|e| err(StatusCode::BAD_REQUEST, e.to_string()))?;
    let Ordered::Object(mut m) = raw else {
        return Err(err(StatusCode::BAD_REQUEST, "body: not an object"));
    };
    // a float field the model coerced (a numeric string, a bool) reads as the Python's `float`
    for (k, x) in &mut m {
        if model.fields.iter().any(|Field(n, kind)| {
            n == k && matches!(kind, Kind::Float { .. } | Kind::Opt(Kind::Float { .. }))
        }) && let Some(f) = v.get(k).and_then(|f| validate::as_float(f).ok())
        {
            *x = num(f);
        }
    }
    Ok(Ordered::Object(m))
}

fn not_found(sid: &str) -> ApiError {
    err(
        StatusCode::NOT_FOUND,
        format!("no edit session {}", py_repr(sid)),
    )
}

fn ok(mut extra: Value, state: Value) -> Response {
    if let (Some(e), Value::Object(s)) = (extra.as_object_mut(), state) {
        e.extend(s);
    }
    axum::Json(extra).into_response()
}

fn reply(r: Result<Response, ApiError>) -> Response {
    r.unwrap_or_else(IntoResponse::into_response)
}

/// A session's keep-outs projected into the planner's order frame (Python `EditSession.to_planner_keepouts`): the
/// y-flipped translation by `anchor` the cockpit applies, rounded to 0.1 m as the Python's `round(v, 1)`.
fn to_planner_keepouts(features: &[(String, Ordered)], (ax, ay): (f64, f64)) -> Vec<Value> {
    let r1 = |v: f64| stewie_twin::numpy::round(v, 1);
    let num = |f: &Ordered, k: &str| match f.get(k) {
        Some(Ordered::Number(n)) => n.as_f64().unwrap_or(0.0),
        _ => 0.0,
    };
    features
        .iter()
        .map(|(_, f)| {
            if matches!(f.get("kind"), Some(Ordered::String(k)) if k == "circle") {
                json!({"x": r1(num(f, "cx") - ax), "y": r1(ay - num(f, "cy")), "r": r1(num(f, "r"))})
            } else {
                let ring = match f.get("ring") {
                    Some(Ordered::Array(r)) => r.clone(),
                    _ => Vec::new(),
                };
                let pts: Vec<Value> = ring
                    .iter()
                    .map(|p| match p {
                        Ordered::Array(xy) if xy.len() == 2 => {
                            let c = |o: &Ordered| match o {
                                Ordered::Number(n) => n.as_f64().unwrap_or(0.0),
                                _ => 0.0,
                            };
                            json!([r1(c(&xy[0]) - ax), r1(ay - c(&xy[1]))])
                        }
                        _ => json!([]),
                    })
                    .collect();
                json!({"points": pts})
            }
        })
        .collect()
}

/// The keep-outs a plan request's edit session adds (Python `routers.plan._merge_session_keepouts`): none without
/// a session id or for a session with nothing drawn; a 400 for an unknown session or, with features, a missing
/// `anchor_xy`.
///
/// # Errors
/// The 400s above, or the store failing.
pub async fn planner_keepouts(
    st: &AppState,
    sid: &str,
    anchor: Option<&Value>,
) -> Result<Vec<Value>, ApiError> {
    if sid.is_empty() {
        return Ok(Vec::new());
    }
    let s = read(st, sid).await.map_err(|e| {
        if e.0 == StatusCode::NOT_FOUND {
            err(
                StatusCode::BAD_REQUEST,
                format!(
                    "edit_session {} is unknown or expired -- its keep-outs cannot be applied; clear the session id to \
                     plan without them",
                    py_repr(sid)
                ),
            )
        } else {
            e
        }
    })?;
    if s.features.is_empty() {
        return Ok(Vec::new());
    }
    let anchor = anchor
        .and_then(Value::as_array)
        .filter(|a| a.len() == 2)
        .and_then(|a| Some((a[0].as_f64()?, a[1].as_f64()?)));
    let Some(anchor) = anchor else {
        return Err(err(
            StatusCode::BAD_REQUEST,
            "edit_session requires anchor_xy [x, y] to project its keep-outs into the order frame",
        ));
    };
    Ok(to_planner_keepouts(&s.features, anchor))
}

/// Mint a session (keyless): a 503 rather than evict a session holding authored work (SR-09).
async fn create_session(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    reply(
        async {
            let mut b = [0_u8; 8];
            st.entropy.fill(&mut b);
            let sid = b.iter().fold(String::new(), |mut s, x| {
                use std::fmt::Write as _;
                let _ = write!(s, "{x:02x}");
                s
            });
            let now = st.clock.now();
            st.edit_sessions
                .immediate(async |c, d| {
                    let count: i64 = sqlx::query(&sql(d, "SELECT count(*) FROM {s}edit_session"))
                        .fetch_one(&mut *c)
                        .await
                        .map_err(db_error)?
                        .get(0);
                    if count >= MAX_SESSIONS {
                        let rows = sqlx::query(&sql(
                            d,
                            "SELECT opaque_id, CAST(features AS TEXT) AS features, CAST(markers AS TEXT) AS markers \
                             FROM {s}edit_session ORDER BY created_at ASC",
                        ))
                        .fetch_all(&mut *c)
                        .await
                        .map_err(db_error)?;
                        let mut victim = None;
                        for r in rows {
                            let (f, m) = (ordered_map(&r.get::<String, _>("features"))?, ordered_map(&r.get::<String, _>("markers"))?);
                            if f.is_empty() && m.is_empty() {
                                victim = Some(r.get::<String, _>("opaque_id"));
                                break;
                            }
                        }
                        let Some(victim) = victim else {
                            return Err(err(
                                StatusCode::SERVICE_UNAVAILABLE,
                                format!(
                                    "edit-session store is full ({count}/{MAX_SESSIONS}) and every session holds \
                                     authored features; refusing to delete an operator's geometry to make room"
                                ),
                            ));
                        };
                        for q in ["DELETE FROM {s}edit_audit WHERE session_id = $1", "DELETE FROM {s}edit_session WHERE opaque_id = $1"] {
                            sqlx::query(&sql(d, q)).bind(&victim).execute(&mut *c).await.map_err(db_error)?;
                        }
                    }
                    sqlx::query(&sql(
                        d,
                        "INSERT INTO {s}edit_session (opaque_id, plan_id, version, created_at, fid_seq, marker_seq, \
                         features, markers) VALUES ($1, NULL, 0, $2, 0, 0, '{}', '{}')",
                    ))
                    .bind(&sid)
                    .bind(now)
                    .execute(&mut *c)
                    .await
                    .map_err(db_error)?;
                    Ok(())
                })
                .await?;
            log(&st, &h, "ide", "edit.session.create", &sid);
            let empty = Session { id: sid, version: 0, fid_seq: 0, marker_seq: 0, features: vec![], markers: vec![],
                                  audit: vec![], persisted: 0 };
            Ok(ok(json!({"ok": true}), empty.state()))
        }
        .await,
    )
}

/// A session read, or its 404.
async fn read(st: &AppState, sid: &str) -> Result<Session, ApiError> {
    st.edit_sessions
        .snapshot(async |c, d| Session::load(c, d, sid).await)
        .await?
        .ok_or_else(|| not_found(sid))
}

/// A session's id, version and audit records (oldest first), or `None` when there is no such session.
///
/// # Errors
/// The store unreadable.
pub(crate) async fn session_audit(
    st: &AppState,
    sid: &str,
) -> Result<Option<(String, Value, Vec<Value>)>, ApiError> {
    let s = st
        .edit_sessions
        .snapshot(async |c, d| Session::load(c, d, sid).await)
        .await?;
    Ok(s.map(|s| {
        (
            s.id.clone(),
            json!(s.version),
            s.audit.iter().map(Audit::to_value).collect(),
        )
    }))
}

async fn get_session(State(st): State<Arc<AppState>>, Path(sid): Path<String>) -> Response {
    if sid.contains('/') {
        return no_route_for(&Method::GET, &format!("/edit/session/{sid}"));
    }
    reply(
        read(&st, &sid)
            .await
            .map(|s| ok(json!({"ok": true}), s.state())),
    )
}

async fn get_audit(State(st): State<Arc<AppState>>, Path(sid): Path<String>) -> Response {
    if sid.contains('/') {
        return no_route_for(&Method::GET, &format!("/edit/session/{sid}/audit"));
    }
    reply(read(&st, &sid).await.map(|s| {
        axum::Json(json!({"ok": true, "session": s.id, "version": s.version,
                          "audit": s.audit.iter().map(Audit::to_value).collect::<Vec<_>>()}))
        .into_response()
    }))
}

/// Apply one edit to a stored session in one transaction; `edit` returns the route's extra fields and the audit
/// target for the log line.
async fn mutate(
    st: &AppState,
    sid: &str,
    edit: impl FnOnce(&mut Session, f64) -> Result<(Value, String), ApiError>,
) -> Result<(Value, String, Value), ApiError> {
    let now = st.clock.now();
    st.edit_sessions
        .immediate(async |c, d| {
            let mut s = Session::load(c, d, sid)
                .await?
                .ok_or_else(|| not_found(sid))?;
            let (extra, target) = edit(&mut s, now)?;
            s.save(c, d).await?;
            Ok((extra, target, s.state()))
        })
        .await
}

async fn create_keepout(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    if sid.contains('/') {
        return no_route_for(&Method::POST, &format!("/edit/session/{sid}/keepout"));
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    reply(
        async {
            let body = validated(&bytes?, KEEPOUT_IN)?;
            let kind = match body.get("kind") {
                Some(Ordered::String(k)) => k.clone(),
                _ => String::new(),
            };
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let (gk, geom) = geometry(&kind, &body)?;
                if s.features.len() >= MAX_FEATURES_PER_SESSION {
                    return Err(err(
                        StatusCode::BAD_REQUEST,
                        format!("session is full ({MAX_FEATURES_PER_SESSION} keep-outs); delete some first"),
                    ));
                }
                s.fid_seq += 1;
                let fid = format!("ko{}", s.fid_seq);
                let mut f = vec![("fid".to_owned(), Ordered::String(fid.clone()))];
                f.extend(geom);
                let feature = Ordered::Object(f);
                put(&mut s.features, &fid, feature.clone());
                s.record("create", &fid, &gk, Ordered::Null, feature.clone(), now);
                Ok((json!({"ok": true, "feature": feature.to_value()}), format!("{}:{fid}", s.id)))
            })
            .await?;
            log(&st, &h, "ide", "edit.keepout.create", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

async fn modify_keepout(
    State(st): State<Arc<AppState>>,
    Path((sid, fid)): Path<(String, String)>,
    req: Request,
) -> Response {
    if sid.contains('/') || fid.contains('/') {
        return no_route_for(
            &Method::PATCH,
            &format!("/edit/session/{sid}/keepout/{fid}"),
        );
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    reply(
        async {
            let body = validated(&bytes?, KEEPOUT_IN)?;
            let kind = match body.get("kind") {
                Some(Ordered::String(k)) => k.clone(),
                _ => String::new(),
            };
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let (gk, geom) = geometry(&kind, &body)?;
                let Some(old) = s
                    .features
                    .iter()
                    .find(|(k, _)| *k == fid)
                    .map(|(_, f)| f.clone())
                else {
                    return Err(err(
                        StatusCode::NOT_FOUND,
                        format!("no keep-out {}", py_repr(&fid)),
                    ));
                };
                let mut f = vec![("fid".to_owned(), Ordered::String(fid.clone()))];
                f.extend(geom);
                let feature = Ordered::Object(f);
                put(&mut s.features, &fid, feature.clone());
                s.record("modify", &fid, &gk, old, feature.clone(), now);
                Ok((
                    json!({"ok": true, "feature": feature.to_value()}),
                    format!("{}:{fid}", s.id),
                ))
            })
            .await?;
            log(&st, &h, "ide", "edit.keepout.modify", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

async fn delete_keepout(
    State(st): State<Arc<AppState>>,
    Path((sid, fid)): Path<(String, String)>,
    req: Request,
) -> Response {
    if sid.contains('/') || fid.contains('/') {
        return no_route_for(
            &Method::DELETE,
            &format!("/edit/session/{sid}/keepout/{fid}"),
        );
    }
    let h = Head::of(&req);
    reply(
        async {
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let Some(old) = take(&mut s.features, &fid) else {
                    return Err(err(
                        StatusCode::NOT_FOUND,
                        format!("no keep-out {}", py_repr(&fid)),
                    ));
                };
                let kind = match old.get("kind") {
                    Some(Ordered::String(k)) => k.clone(),
                    _ => String::new(),
                };
                s.record("delete", &fid, &kind, old, Ordered::Null, now);
                Ok((json!({"ok": true}), format!("{}:{fid}", s.id)))
            })
            .await?;
            log(&st, &h, "ide", "edit.keepout.delete", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

async fn create_marker(
    State(st): State<Arc<AppState>>,
    Path(sid): Path<String>,
    req: Request,
) -> Response {
    if sid.contains('/') {
        return no_route_for(&Method::POST, &format!("/edit/session/{sid}/marker"));
    }
    let (h, bytes) = split(req, st.settings.max_body).await;
    reply(
        async {
            let body = validated(&bytes?, MARKER_IN)?;
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let geom = marker(&body)?;
                if s.markers.len() >= MAX_MARKERS_PER_SESSION {
                    return Err(err(
                        StatusCode::BAD_REQUEST,
                        format!(
                            "session is full ({MAX_MARKERS_PER_SESSION} markers); delete some first"
                        ),
                    ));
                }
                s.marker_seq += 1;
                let fid = format!("mk{}", s.marker_seq);
                let mut f = vec![("fid".to_owned(), Ordered::String(fid.clone()))];
                f.extend(geom);
                let feature = Ordered::Object(f);
                put(&mut s.markers, &fid, feature.clone());
                s.record(
                    "marker.create",
                    &fid,
                    "marker",
                    Ordered::Null,
                    feature.clone(),
                    now,
                );
                Ok((
                    json!({"ok": true, "marker": feature.to_value()}),
                    format!("{}:{fid}", s.id),
                ))
            })
            .await?;
            log(&st, &h, "ide", "edit.marker.create", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

async fn delete_marker(
    State(st): State<Arc<AppState>>,
    Path((sid, fid)): Path<(String, String)>,
    req: Request,
) -> Response {
    if sid.contains('/') || fid.contains('/') {
        return no_route_for(
            &Method::DELETE,
            &format!("/edit/session/{sid}/marker/{fid}"),
        );
    }
    let h = Head::of(&req);
    reply(
        async {
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let Some(old) = take(&mut s.markers, &fid) else {
                    return Err(err(
                        StatusCode::NOT_FOUND,
                        format!("no marker {}", py_repr(&fid)),
                    ));
                };
                s.record("marker.delete", &fid, "marker", old, Ordered::Null, now);
                Ok((json!({"ok": true}), format!("{}:{fid}", s.id)))
            })
            .await?;
            log(&st, &h, "ide", "edit.marker.delete", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

async fn undo(State(st): State<Arc<AppState>>, Path(sid): Path<String>, req: Request) -> Response {
    if sid.contains('/') {
        return no_route_for(&Method::POST, &format!("/edit/session/{sid}/undo"));
    }
    let h = Head::of(&req);
    reply(
        async {
            let (extra, target, state) = mutate(&st, &sid, |s, now| {
                let undone = s.undo(now)?;
                let target = format!("{}:v{}", s.id, undone["undone_version"]);
                Ok((json!({"ok": true, "undone": undone}), target))
            })
            .await?;
            log(&st, &h, "ide", "edit.undo", &target);
            Ok(ok(extra, state))
        }
        .await,
    )
}

/// The edit-session routes (keyless; the session id is the capability).
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/edit/session", post(create_session))
        .route("/edit/session/{sid}", get(get_session))
        .route("/edit/session/{sid}/audit", get(get_audit))
        .route("/edit/session/{sid}/keepout", post(create_keepout))
        .route(
            "/edit/session/{sid}/keepout/{fid}",
            patch(modify_keepout).delete(delete_keepout),
        )
        .route("/edit/session/{sid}/marker", post(create_marker))
        .route("/edit/session/{sid}/marker/{fid}", delete(delete_marker))
        .route("/edit/session/{sid}/undo", post(undo))
}

#[cfg(test)]
mod tests {
    use super::{Ordered, to_planner_keepouts};
    use serde_json::json;

    #[test]
    fn keepouts_project_into_the_order_frame_as_the_python_rounds_them() {
        // SYNTHETIC geometry on rounding ties and near-ties; the expected values are the Python's own
        // (`EditSession.to_planner_keepouts((1000.0, 2000.0))`)
        let f = |v: serde_json::Value| -> (String, Ordered) {
            ("k".into(), serde_json::from_value(v).unwrap())
        };
        let features = [
            f(json!({"fid": "ko1", "kind": "circle", "cx": 1000.25, "cy": 2000.75, "r": 6.05})),
            f(
                json!({"fid": "ko2", "kind": "polygon", "ring": [[990.05, 1990.15], [1010.35, 1990.45],
                                                               [1000.25, 2010.65], [1000.125, 1999.875]]}),
            ),
        ];
        assert_eq!(
            json!(to_planner_keepouts(&features, (1000.0, 2000.0))),
            json!([{"x": 0.2, "y": -0.8, "r": 6.0},
                   {"points": [[-10.0, 9.8], [10.4, 9.5], [0.2, -10.7], [0.1, 0.1]]}])
        );
    }
}
