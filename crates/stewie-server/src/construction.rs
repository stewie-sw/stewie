//! The construction surface (RW-55b2; Python `routers.construction`, `routers.siteplan`): the build catalog with
//! the acceptance criteria (`/construction`, operator+) and the validate-and-advise site plan
//! (`/siteplan/analyze`, any auth), over `stewie-build` and the acceptance defaults of `stewie-plan`. Densities
//! are the soil baseline contract's.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use sha2::Digest as _;
use stewie_build::{Densities, Placed, STRUCTURES, analyze_siteplan, decompose, template};
use stewie_plan::acceptance::AcceptanceParams;
use stewie_twin::numpy::round;

use crate::admin::require_role;
use crate::app::{AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split};
use crate::validate::{Field, Kind, Model};

/// The local-frame origin each template is expanded at for the catalog [m].
const PROBE_XY: (f64, f64) = (0.0, 0.0);

const PLACEMENT: Model = Model {
    fields: &[
        Field(
            "name",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: None,
            },
        ),
        Field(
            "x",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            },
        ),
        Field(
            "y",
            Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            },
        ),
        Field("params", Kind::Dict),
    ],
    forbid_extra: false,
};

const SITE_PLAN: Model = Model {
    fields: &[
        Field(
            "placements",
            Kind::List {
                min: 1,
                max: 500,
                item: &PLACEMENT,
            },
        ),
        Field(
            "min_gap_m",
            Kind::Float {
                gt: None,
                ge: Some((0.0, "0")),
                le: None,
                default: Some(2.0),
            },
        ),
    ],
    forbid_extra: false,
};

const VOLUME: Model = Model {
    fields: &[
        Field("orders", Kind::DictList { min: 1, max: 200 }),
        Field(
            "body",
            Kind::Str {
                min: 0,
                max: usize::MAX,
                nullable: false,
                default: Some("moon"),
            },
        ),
        Field(
            "density_kg_m3",
            Kind::Float {
                gt: Some((0.0, "0")),
                ge: None,
                le: None,
                default: None,
            },
        ),
        Field(
            "density_frac",
            Kind::Float {
                gt: None,
                ge: Some((0.0, "0")),
                le: Some((1.0, "1")),
                default: Some(0.0),
            },
        ),
        Field(
            "drum_inferred_kg",
            Kind::Opt(&Kind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            }),
        ),
    ],
    forbid_extra: false,
};

/// The bank and loose densities of the bundled soil baseline.
fn densities() -> Densities {
    let (_, base) = stewie_physics::soil::bundled();
    Densities {
        bank: base.rho_deep.value,
        loose: base.rho_spoil.value,
    }
}

/// One catalog row: the template's defaults and its primitive orders at the probe origin.
fn template_row(name: &str, d: &Densities) -> Result<Value, String> {
    let t = template(name).ok_or_else(|| format!("unknown structure '{name}'"))?;
    let orders = decompose(name, PROBE_XY.0, PROBE_XY.1, &Map::new(), d)?;
    let prim: Vec<Value> = orders
        .iter()
        .map(|o| {
            json!({"action": o["action"], "kind": o["kind"],
                   "footprint_m2": round(o["footprint_m2"].as_f64().unwrap_or(0.0), 3),
                   "depth_m": round(o["depth_m"].as_f64().unwrap_or(0.0), 4),
                   "note": o.get("note").cloned().unwrap_or_else(|| json!(""))})
        })
        .collect();
    let count = |k: &str| prim.iter().filter(|o| o["kind"] == k).count();
    let (n_cut, n_fill) = (count("cut"), count("fill"));
    let defaults: Map<String, Value> = t
        .defaults
        .iter()
        .map(|(k, v)| ((*k).to_owned(), json!(round(*v, 4))))
        .collect();
    Ok(
        json!({"id": name, "doc": t.doc, "defaults": defaults, "n_orders": prim.len(), "orders": prim,
              "n_cut": n_cut, "n_fill": n_fill, "balanced": n_cut > 0 && n_fill > 0}),
    )
}

/// The build catalog and the acceptance criteria (with `validate_plan`'s default tolerances).
fn catalog() -> Result<Value, String> {
    let d = densities();
    let rows = STRUCTURES
        .iter()
        .map(|n| template_row(n, &d))
        .collect::<Result<Vec<_>, _>>()?;
    let p = AcceptanceParams::default();
    let balanced = rows.iter().filter(|r| r["balanced"] == true).count();
    Ok(json!({
        "ok": true, "count": rows.len(), "balanced_count": balanced, "templates": rows,
        "probe_origin_m": [PROBE_XY.0, PROBE_XY.1],
        "acceptance": {
            "checks": [
                {"id": "mass_conservation", "what": "all-cuts-then-all-fills balance on the conserved grid"},
                {"id": "datum_floor_feasibility", "what": "a cut deeper than the regolith mantle is infeasible"},
                {"id": "drum_supply", "what": "every fill can be supplied from the drum it was cut into"},
                {"id": "slope_siting", "what": "no order sited on slope above max_slope_deg",
                 "max_slope_deg": p.max_slope_deg},
                {"id": "off_dem_siting", "what": "no order placed off the loaded DEM tile"},
                {"id": "as_built_flatness", "what": "executed-surface flatness RMSE within tol",
                 "tol_m": p.accept_flatness_tol_m},
                {"id": "berm_profile", "what": "as-built crest rise reaches the ordered depth within tol",
                 "tol_m": p.accept_flatness_tol_m},
                {"id": "repose_stability", "what": "as-built flank slope <= the soil angle of repose (phi)"},
                {"id": "bearing_capacity", "what": "Terzaghi/Vesic allowable bearing of each built pad/berm",
                 "factor_of_safety": p.bearing_fs},
            ],
            "defers_to_totals": ["route_feasibility", "battery_reserve", "sequence_precedence",
                                 "drum_capacity_shuttle_cycles", "time_budget", "energy_budget"],
        },
        "live_acceptance_source": "plan.validation (validate_plan) + plan.ordered_acceptance (IR replay)",
        "note": "Catalog is the real structure-template library (leap/structures.py), each decomposed to \
                 mass-balanced cut/fill primitives. Acceptance criteria are the real validate_plan checks \
                 (lode/planner_acceptance.py) with their default tolerances. The AS-BUILT pass/fail on the real \
                 terrain is a property of a planned mission and is read from the last /plan result (validation + \
                 ordered_acceptance), not stored server-side.",
    }))
}

async fn construction(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_role(st, &h, "operator")?;
        Ok(
            axum::Json(catalog().map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?)
                .into_response(),
        )
    })
    .await
}

async fn siteplan_analyze(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        let identity = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), SITE_PLAN)?;
        let placed: Vec<Placed> = v["placements"]
            .as_array()
            .map(|a| {
                a.iter()
                    .map(|p| Placed {
                        name: p["name"].as_str().unwrap_or("").to_owned(),
                        x: p["x"].as_f64().unwrap_or(0.0),
                        y: p["y"].as_f64().unwrap_or(0.0),
                        params: p["params"].as_object().cloned().unwrap_or_default(),
                    })
                    .collect()
            })
            .unwrap_or_default();
        let report = analyze_siteplan(
            &placed,
            v["min_gap_m"].as_f64().unwrap_or(2.0),
            &densities(),
        )
        .map_err(|e| err(StatusCode::BAD_REQUEST, e))?;
        log(
            st,
            &h,
            &identity,
            "siteplan.analyze",
            &format!("{} structures", placed.len()),
        );
        let mut out = report.to_value();
        out["ok"] = json!(true);
        Ok(axum::Json(out).into_response())
    })
    .await
}

/// The moved-regolith evidence of a mission (FR-13): the flat-mantle terrain change, its conserved mass and the
/// optional drum reading cross-checked, linked to a deterministic plan transaction (`plan:` + the first 12 hex digits
/// of the sha256 of the Python `repr` of the orders as sent).
#[allow(clippy::many_single_char_names)] // the Python's d, m, v
async fn siteplan_volume(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let bytes = bytes?;
        let body = parse_body(&bytes)?;
        let identity = require_auth(st, &h)?;
        let v = body_model(body.as_ref(), VOLUME)?;
        let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
        let payload =
            json!({"name": "volume", "body": v["body"], "charger": [0, 0], "orders": v["orders"]});
        let m = st.planning.mission(&payload).map_err(bad)?;
        let inputs = st.planning.inputs(&m).map_err(|(unconfigured, e)| {
            if unconfigured {
                err(StatusCode::SERVICE_UNAVAILABLE, e)
            } else {
                bad(e)
            }
        })?;
        let d = stewie_build::record::mission_terrain_delta(
            &m,
            None,
            &inputs.acceptance(),
            &AcceptanceParams::default(),
        )
        .map_err(bad)?;
        // the orders' repr in the client's key order (the parsed Value has sorted keys)
        let ordered: crate::validate::Ordered = serde_json::from_slice(&bytes)
            .map_err(|_| bad("bad JSON: JSON decode error".to_owned()))?;
        let repr = ordered
            .get("orders")
            .map(crate::validate::Ordered::py_repr)
            .unwrap_or_default();
        let digest =
            sha2::Sha256::digest(repr.as_bytes())
                .iter()
                .take(6)
                .fold(String::new(), |mut x, b| {
                    use std::fmt::Write as _;
                    let _ = write!(x, "{b:02x}");
                    x
                });
        let est = stewie_build::record::EstimateInputs {
            density_kg_m3: v["density_kg_m3"].as_f64().unwrap_or(0.0),
            spoil_density_kg_m3: None,
            height_rmse_m: 0.0,
            density_frac: v["density_frac"].as_f64().unwrap_or(0.0),
            conserved_mass_kg: Some(d.mass_moved_kg),
            drum_inferred_kg: v["drum_inferred_kg"].as_f64(),
        };
        let ev = stewie_build::record::volume_evidence(
            &d.base,
            &d.as_built,
            d.cell_m,
            &est,
            &stewie_build::record::DrumBand::NTRS_20210022781,
            "siteplan",
            ("conserved-authority:base", "conserved-authority:as_built"),
            &format!("plan:{digest}"),
        )
        .map_err(bad)?;
        let n = v["orders"].as_array().map_or(0, Vec::len);
        log(
            st,
            &h,
            &identity,
            "siteplan.volume",
            &format!("{n} orders -> {}", ev["acceptance"].as_str().unwrap_or("")),
        );
        Ok(axum::Json(json!({"ok": true, "volume": ev})).into_response())
    })
    .await
}

/// The construction routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/construction", get(construction))
        .route("/siteplan/analyze", post(siteplan_analyze))
        .route("/siteplan/volume", post(siteplan_volume))
}
