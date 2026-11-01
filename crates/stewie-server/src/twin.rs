//! The twin surface (RW-55b4a; Python `routers.twin`): the live centre-of-gravity and tip margin (`/twin/cg`),
//! an operator's resync of a site's observed twin committed to the world log with a compensating undo when the
//! commit fails (`/twin/resync`), the observed twin's version token and director-only history, and a site's
//! Terrain Memory summary, and (RW-55b4b-2) recording a mission's flat-mantle terrain change into a site's Terrain
//! Memory, committed to the world log with a compensating restore when the commit fails.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Path, Query, Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Value, json};
use stewie_physics::arm::{ARM_TRAVEL_DEG, cg_offset_m};
use stewie_physics::stability::{Axis, Risk, stability};
use stewie_twin::numpy::round;
use stewie_twin::terrain_memory;

use crate::admin::{require_director, require_role};
use crate::app::{
    ApiError, AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::state::{DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE};
use crate::validate::{self, Field, Kind, Model};

/// The rover's dry mass the posture CG is weighted about [kg] (the Python `cg_offset_m` default).
const DRY_MASS_KG: f64 = 30.0;
/// The share of a static stability angle at which the risk band turns to `warn` (the Python default).
const WARN_FRAC: f64 = 0.7;

const NUM: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: Some(0.0),
};
const CG_QUERY: Model = Model {
    fields: &[
        Field("front_deg", NUM),
        Field("back_deg", NUM),
        Field("front_kg", NUM),
        Field("back_kg", NUM),
        Field("pitch_deg", NUM),
        Field("roll_deg", NUM),
    ],
    forbid_extra: false,
};

const RESYNC: Model = Model {
    fields: &[
        Field("heights_m", Kind::AnyList),
        Field("origin_rc", Kind::IntPair),
        Field(
            "provenance",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "site",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some(DEFAULT_TWIN_SITE),
            },
        ),
    ],
    forbid_extra: true,
};

const ANY_INT: Kind = Kind::Int {
    ge: i64::MIN,
    le: i64::MAX,
    default: 0,
};
const ANY_FLOAT: Kind = Kind::Float {
    gt: None,
    ge: None,
    le: None,
    default: None,
};
const TERRAIN_RECORD: Model = Model {
    fields: &[
        Field("mission", Kind::DictRequired),
        Field("rows", Kind::Opt(&ANY_INT)),
        Field("cols", Kind::Opt(&ANY_INT)),
        Field("cell_m", Kind::Opt(&ANY_FLOAT)),
        Field("origin", Kind::Opt(&Kind::FloatPair)),
    ],
    forbid_extra: true,
};

/// The IPEx stability geometry from the fleet registry: (gauge, wheelbase, CG height) [m].
fn ipex_geometry() -> Result<(f64, f64, f64), String> {
    let fleet: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json"))
            .map_err(|e| format!("the fleet registry: {e}"))?;
    let v = &fleet["vehicles"]["ipex"];
    let g = |k: &str| {
        v[k].as_f64()
            .ok_or_else(|| format!("the fleet registry's ipex has no {k}"))
    };
    Ok((g("gauge_m")?, g("wheelbase_m")?, g("cg_height_m")?))
}

/// A float rounded as Python's `round(v, 3)`, as the route rounds every stability float.
fn r3(v: f64) -> Value {
    json!(round(v, 3))
}

async fn cg(Query(q): Query<Vec<(String, String)>>) -> Response {
    let run = || -> Result<Response, ApiError> {
        let obj: serde_json::Map<String, Value> =
            q.iter().map(|(k, v)| (k.clone(), json!(v))).collect();
        let v = validate::model(Some(&Value::Object(obj)), CG_QUERY)
            .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        let f = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let clamp = |d: f64| d.clamp(ARM_TRAVEL_DEG.0, ARM_TRAVEL_DEG.1);
        let (dx, dz) = cg_offset_m(
            clamp(f("front_deg")),
            clamp(f("back_deg")),
            f("front_kg").max(0.0),
            f("back_kg").max(0.0),
            DRY_MASS_KG,
        );
        let (gauge, wheelbase, cg_h) =
            ipex_geometry().map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let st = stability(
            f("pitch_deg"),
            f("roll_deg"),
            gauge,
            wheelbase,
            cg_h + dz,
            dx,
            WARN_FRAC,
        );
        let axis = match st.binding_axis {
            Axis::Pitch => "pitch",
            Axis::Roll => "roll",
            Axis::Unknown => "unknown",
        };
        let risk = match st.risk {
            Risk::Ok => "ok",
            Risk::Warn => "warn",
            Risk::Tip => "tip",
        };
        Ok(axum::Json(json!({"ok": true, "cg_dx_m": round(dx, 4), "cg_dz_m": round(dz, 4),
                              "cg_height_m": round(cg_h + dz, 4), "ssa_pitch_deg": r3(st.ssa_pitch_deg),
                              "ssa_roll_deg": r3(st.ssa_roll_deg), "margin_deg": r3(st.margin_deg),
                              "binding_axis": axis, "risk": risk}))
        .into_response())
    };
    run().unwrap_or_else(IntoResponse::into_response)
}

/// The patch as rows of heights; anything else is not a finite 2-D height array.
fn rows_of(v: &Value) -> Result<Vec<Vec<f64>>, String> {
    let bad = || "patch must be a finite 2-D height array".to_owned();
    v.as_array()
        .ok_or_else(bad)?
        .iter()
        .map(|r| {
            r.as_array()
                .ok_or_else(bad)?
                .iter()
                .map(|x| x.as_f64().ok_or_else(bad))
                .collect()
        })
        .collect()
}

async fn resync(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_role(st, &h, "operator")?;
        let v = body_model(body.as_ref(), RESYNC)?;
        let (site, provenance) = (
            v["site"].as_str().unwrap_or(DEFAULT_TWIN_SITE),
            v["provenance"].as_str().unwrap_or(""),
        );
        let (r0, c0) = (
            v["origin_rc"][0].as_i64().unwrap_or(0),
            v["origin_rc"][1].as_i64().unwrap_or(0),
        );
        let bad = |m: String| err(StatusCode::BAD_REQUEST, m);
        let patch = rows_of(&v["heights_m"]).map_err(bad)?;
        let tw = st
            .terrain
            .twin(site, DEFAULT_TWIN_SOURCE)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        // one critical section: patch, world commit, and the compensating undo if the commit fails
        let mut t = tw.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let (rows, cols) = t.shape();
        let (ph, pw) = (patch.len(), patch.first().map_or(0, Vec::len));
        if r0 < 0 || c0 < 0 {
            return Err(bad(format!(
                "patch ({ph}, {pw}) at ({r0},{c0}) exceeds the twin extent ({rows}, {cols})"
            )));
        }
        let origin = (
            usize::try_from(r0).unwrap_or(usize::MAX),
            usize::try_from(c0).unwrap_or(usize::MAX),
        );
        let version = t
            .apply_patch(&patch, origin, provenance)
            .map_err(|e| bad(e.to_string()))?;
        if let Err(e) = st.world.record_resync(
            &st.terrain,
            &format!("twin.resync: {provenance}"),
            Some(site),
            0.0,
            Some(&t),
        ) {
            let _ = t.undo();
            eprintln!("twin.resync rolled back (world-state commit failed): {e}");
            return Err(err(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("resync rolled back: world-state commit failed: {e}"),
            ));
        }
        drop(t);
        log(st, &h, &identity, "twin.resync", provenance);
        Ok(axum::Json(json!({"ok": true, "twin_version": version})).into_response())
    })
    .await
}

fn default_twin(
    st: &AppState,
) -> Result<Arc<std::sync::Mutex<stewie_twin::twin_store::TwinStore>>, ApiError> {
    st.terrain
        .twin(DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE)
        .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))
}

async fn version(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let tw = default_twin(st)?;
        let t = tw.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        Ok(
            axum::Json(json!({"twin_version": t.version(), "chain_valid": t.verify_chain()}))
                .into_response(),
        )
    })
    .await
}

async fn history(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_director(st, &h)?;
        let tw = default_twin(st)?;
        let t = tw.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        Ok(axum::Json(json!({"twin_version": t.version(), "chain_valid": t.verify_chain(), "events": t.history()}))
            .into_response())
    })
    .await
}

async fn terrain_summary(
    State(st): State<Arc<AppState>>,
    Path(site): Path<String>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        // never a 500: an unrecorded (or unreadable) site is an empty summary
        let out = match terrain_memory::load_site(&st.cfg.data_dir, &site).ok().flatten() {
            None => json!({"ok": true, "site": site, "recorded": false, "version": 0, "cells_changed": 0,
                           "net_volume_m3": 0.0, "max_cut_m": 0.0, "max_fill_m": 0.0, "missions": []}),
            Some(mem) => {
                let s = mem.summary();
                json!({"ok": true, "recorded": true, "chain_valid": mem.verify_chain(), "site": s.site,
                       "version": s.version, "cells_changed": s.cells_changed, "net_volume_m3": s.net_volume_m3,
                       "max_cut_m": s.max_cut_m, "max_fill_m": s.max_fill_m, "missions": s.missions})
            }
        };
        Ok(axum::Json(out).into_response())
    })
    .await
}

fn hex(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut h, b| {
            use std::fmt::Write as _;
            let _ = write!(h, "{b:02x}");
            h
        })
}

/// Fold a completed mission's flat-mantle terrain change into the site's Terrain Memory (a fresh site's grid
/// defaults to the mission's own footprint), persist it, and commit the conserved-authority identity (a sha over
/// the cumulative delta) to the world log; a failed commit restores the prior file.
#[allow(clippy::many_single_char_names)] // the Python's d, m, v
async fn terrain_record(
    State(st): State<Arc<AppState>>,
    Path(site): Path<String>,
    req: Request,
) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_role(st, &h, "operator")?;
        let v = body_model(body.as_ref(), TERRAIN_RECORD)?;
        let bad = |e: String| err(StatusCode::BAD_REQUEST, format!("bad mission: {e}"));
        let mut payload = v["mission"].clone();
        if payload.get("name").is_none() {
            payload["name"] = json!(site);
        }
        let m = st.planning.mission(&payload).map_err(bad)?;
        let inputs = st.planning.inputs(&m).map_err(|(unconfigured, e)| {
            if unconfigured { err(StatusCode::SERVICE_UNAVAILABLE, e) } else { bad(e) }
        })?;
        let d = stewie_build::record::mission_terrain_delta(
            &m,
            None,
            &inputs.acceptance(),
            &stewie_plan::acceptance::AcceptanceParams::default(),
        )
        .map_err(bad)?;
        let internal = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
        let lock = st.terrain.site_lock(&site);
        let _g = lock.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let path = terrain_memory::terrain_path(&st.cfg.data_dir, &site);
        let prior = stewie_twin::snapshot_file(&path).map_err(|e| internal(e.to_string()))?;
        let loaded = terrain_memory::load_site(&st.cfg.data_dir, &site).map_err(|e| internal(e.to_string()))?;
        let mut mem = if let Some(mem) = loaded {
            mem
        } else {
            {
                // the Python's `req.x or default`: an absent (or zero) size falls back to the mission's own
                let pick = |k: &str, dflt: usize| {
                    v[k].as_i64().filter(|n| *n != 0).map_or(Ok(dflt), |n| {
                        usize::try_from(n).map_err(|_| internal(format!("TerrainMemory grid must be positive (got {k}={n})")))
                    })
                };
                let cell = v["cell_m"].as_f64().filter(|c| *c != 0.0).unwrap_or(d.cell_m);
                let origin = v["origin"].as_array().map_or((d.x0, d.y0), |o| {
                    (o[0].as_f64().unwrap_or(0.0), o[1].as_f64().unwrap_or(0.0))
                });
                terrain_memory::TerrainMemory::new(&site, pick("rows", d.rows)?, pick("cols", d.cols)?, cell, origin)
                    .map_err(|e| internal(e.to_string()))?
            }
        };
        let placed = mem
            .apply_subgrid(&d.delta, d.rows, d.cols, (d.x0, d.y0), d.cell_m, &m.name, d.mass_moved_kg)
            .map_err(|e| err(StatusCode::BAD_REQUEST, format!("cannot place mission on site grid: {e}")))?;
        terrain_memory::save_site(&st.cfg.data_dir, &mem).map_err(|e| internal(e.to_string()))?;
        let bytes: Vec<u8> = mem.cumulative_delta().iter().flat_map(|x| x.to_le_bytes()).collect();
        let stamp = crate::world::Stamp { mission: Some(&m.name), site: Some(&site), ..crate::world::Stamp::default() };
        if let Err(e) = st.world.record_terrain(&st.terrain, &hex(&bytes), &format!("terrain.record:{}", m.name), &stamp) {
            let _ = stewie_twin::restore_file(&path, prior.as_deref());
            eprintln!("twin.terrain.record rolled back (world-state commit failed): {e}");
            return Err(internal(format!("terrain record rolled back: world-state commit failed: {e}")));
        }
        log(st, &h, &identity, "twin.terrain.record", &format!("{site}:{}", m.name));
        let s = mem.summary();
        Ok(axum::Json(json!({"ok": true, "recorded": true, "chain_valid": mem.verify_chain(), "site": s.site,
                              "version": placed.version, "cells_changed": s.cells_changed,
                              "net_volume_m3": s.net_volume_m3, "max_cut_m": s.max_cut_m, "max_fill_m": s.max_fill_m,
                              "missions": s.missions, "placed_cells": placed.placed_cells, "clipped": placed.clipped}))
        .into_response())
    })
    .await
}

/// The twin routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/twin/cg", get(cg))
        .route("/twin/resync", post(resync))
        .route("/twin/version", get(version))
        .route("/twin/history", get(history))
        .route(
            "/twin/terrain/{site}",
            get(terrain_summary).post(terrain_record),
        )
}
