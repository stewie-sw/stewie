//! The perception routes (RW-41a; Python `routers.perception`): `POST /localize`, the SN-10 articulation-parallax
//! relocalization wired into the estimator, with the optional #148 shadow-yaw heading fusion in the same graph.
//! The request is observation-only (I3): unknown keys are refused, so no truth field can reach the estimator.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use serde_json::{Map, Value, json};
use stewie_perceive::localize;
use stewie_perceive::pose_graph_se2::PoseGraphSe2;

use crate::app::{AppState, blocking, body_model, err, log, parse_body, require_auth, split};
use crate::validate::{Field, Kind, Model};

const fn float(
    gt: Option<(f64, &'static str)>,
    ge: Option<(f64, &'static str)>,
    le: (f64, &'static str),
    default: Option<f64>,
) -> Kind {
    Kind::Float {
        gt,
        ge,
        le: Some(le),
        default,
    }
}

const SHADOW_LIST: Kind = Kind::FloatList { max: 256 };
const ANTI_SOLAR: Kind = Kind::FloatLt {
    ge: Some((0.0, "0")),
    lt: Some((360.0, "360")),
};

/// Python `LocalizeRequest` (`extra="forbid"`).
const LOCALIZE: Model = Model {
    fields: &[
        Field("landmarks_xy", Kind::FloatPairList { max: 256 }),
        Field("pixel_shifts", Kind::FloatList { max: 256 }),
        Field("dh_m", float(Some((0.0, "0")), None, (10.0, "10"), None)),
        Field(
            "fx_px",
            float(Some((0.0, "0")), None, (1e5, "100000"), None),
        ),
        Field(
            "sigma_px",
            float(Some((0.0, "0")), None, (100.0, "100"), Some(0.3)),
        ),
        Field("prior_xy", Kind::FloatPairDefault(0.0, 0.0)),
        Field(
            "prior_yaw",
            float(None, Some((-7.0, "-7")), (7.0, "7"), Some(0.0)),
        ),
        Field(
            "prior_sigma_xy",
            float(Some((0.0, "0")), None, (1e6, "1000000"), Some(50.0)),
        ),
        Field(
            "prior_sigma_yaw",
            float(Some((0.0, "0")), None, (1e3, "1000"), Some(1.0)),
        ),
        Field("shadow_bearings_deg", Kind::Opt(&SHADOW_LIST)),
        Field("shadow_contrasts", Kind::Opt(&SHADOW_LIST)),
        Field("anti_solar_az_deg", Kind::Opt(&ANTI_SOLAR)),
        Field(
            "shadow_sigma_deg",
            float(Some((0.0, "0")), None, (90.0, "90"), Some(8.0)),
        ),
        Field(
            "shadow_min_contrast",
            float(None, Some((0.0, "0")), (255.0, "255"), Some(20.0)),
        ),
    ],
    forbid_extra: true,
};

fn floats(v: &Value) -> Vec<f64> {
    v.as_array()
        .map(|a| a.iter().filter_map(Value::as_f64).collect())
        .unwrap_or_default()
}

fn by_node<T>(m: &std::collections::BTreeMap<i64, T>, f: impl Fn(&T) -> Value) -> Value {
    Value::Object(
        m.iter()
            .map(|(k, v)| (k.to_string(), f(v)))
            .collect::<Map<_, _>>(),
    )
}

/// SN-10: fix the rover position heading-free from the shadow-tip pixel shifts under a commanded lift, fuse it
/// into a one-node pose graph with its geometry-derived covariance, and return the re-optimized fix.
async fn localize(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &h)?;
        let v = body_model(body.as_ref(), LOCALIZE)?;
        let bad = |m: &str| err(StatusCode::BAD_REQUEST, m.to_owned());
        let landmarks: Vec<[f64; 2]> = v["landmarks_xy"]
            .as_array()
            .map(|a| a.iter().map(|p| [p[0].as_f64().unwrap_or(0.0), p[1].as_f64().unwrap_or(0.0)]).collect())
            .unwrap_or_default();
        let shifts = floats(&v["pixel_shifts"]);
        let n = landmarks.len();
        if n < 2 {
            return Err(bad("need >= 2 landmarks for a heading-free fix"));
        }
        if shifts.len() != n {
            return Err(bad("pixel_shifts must match landmarks_xy in length"));
        }
        // #148: the shadow-nav heading needs the ephemeris anti-solar azimuth to turn a body bearing into a heading
        let bearings = floats(&v["shadow_bearings_deg"]);
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        if !bearings.is_empty() {
            if v["anti_solar_az_deg"].is_null() {
                return Err(bad("shadow_bearings_deg requires anti_solar_az_deg (the ephemeris anti-solar azimuth)"));
            }
            if !v["shadow_contrasts"].is_null() && floats(&v["shadow_contrasts"]).len() != bearings.len() {
                return Err(bad("shadow_contrasts must match shadow_bearings_deg in length"));
            }
        }
        let refused = |e: stewie_perceive::pose_graph_se2::GraphError| err(StatusCode::BAD_REQUEST, e.0);
        let mut graph = PoseGraphSe2::default();
        graph
            .add_prior(
                0,
                [v["prior_xy"][0].as_f64().unwrap_or(0.0), v["prior_xy"][1].as_f64().unwrap_or(0.0), num("prior_yaw")],
                num("prior_sigma_xy"),
                num("prior_sigma_yaw"),
            )
            .map_err(refused)?;
        let mut shadow_added = 0;
        if !bearings.is_empty() {
            // the shadow headings go in before the parallax solve, so the final optimize fuses both
            let contrasts = if v["shadow_contrasts"].is_null() {
                vec![num("shadow_min_contrast"); bearings.len()]
            } else {
                floats(&v["shadow_contrasts"])
            };
            let facs = localize::shadow_yaw_factors(
                &contrasts,
                &bearings,
                num("anti_solar_az_deg"),
                num("shadow_sigma_deg"),
                num("shadow_min_contrast"),
            );
            shadow_added = localize::add_shadow_yaw_factors(&mut graph, 0, &facs, localize::min_heading_information())
                .map_err(refused)?;
        }
        let out = localize::articulation_localize(
            &mut graph,
            0,
            &landmarks,
            &shifts,
            num("dh_m"),
            num("fx_px"),
            num("sigma_px"),
        )
        .map_err(refused)?;
        let [fx, fy] = out.fix_xy;
        let shadow = if shadow_added > 0 { format!(" + {shadow_added} shadow-yaw") } else { String::new() };
        let msg = format!("{n} landmarks -> fix ({fx:.2},{fy:.2}) sigma {:.3}m{shadow}", out.fix_sigma_m);
        log(st, &h, "api", "localize", &msg);
        Ok(axum::Json(json!({
            "ok": true,
            "fix_xy": [fx, fy],
            "fix_sigma_m": out.fix_sigma_m,
            "shadow_yaw_factors_added": shadow_added,
            // H-14: a mirror-ambiguous fix carries both hypotheses rather than passing as unique
            "ambiguous": out.ambiguous,
            "hypotheses": out.hypotheses,
            "pose": by_node(&out.pose, |p| json!(p)),
            "xy_sigma": by_node(&out.xy_sigma, |s| json!(s)),
            "yaw_sigma": by_node(&out.yaw_sigma, |s| json!(s)),
        }))
        .into_response())
    })
    .await
}

/// The perception routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new().route("/localize", post(localize))
}
