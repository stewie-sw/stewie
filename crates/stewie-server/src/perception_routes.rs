//! The perception routes (RW-41a; Python `routers.perception`): `POST /localize`, the SN-10 articulation-parallax
//! relocalization wired into the estimator, with the optional #148 shadow-yaw heading fusion in the same graph.
//! The request is observation-only (I3): unknown keys are refused, so no truth field can reach the estimator.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use serde_json::{Map, Value, json};
use stewie_perceive::pose_graph_se2::PoseGraphSe2;
use stewie_perceive::{localize, slam_seam};

use crate::app::{AppState, Head, blocking, body_model, err, log, parse_body, require_auth, split};
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

/// #148: the real lunar est-vs-truth: a reproducible traverse over the real Haworth DEM, dead reckoning drifted by a
/// gyro bias and corrected by real terrain registrations fused in the pose graph, scored against the DEM's own path;
/// 503 when the bundle is absent (never a fabricated run).
async fn localize_traverse(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let Some((dem, _)) = st.terrain.moon_dem("haworth") else {
            return Err(err(
                StatusCode::SERVICE_UNAVAILABLE,
                "Haworth DEM unavailable on this host (bundle absent); the real terrain-fix traverse needs it",
            ));
        };
        let grid = slam_seam::Grid { z: &dem.z, rows: dem.rows, cols: dem.cols, cell_m: dem.cell_m };
        let (t, (r0, c0)) =
            slam_seam::demo_traverse(&grid).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.0))?;
        log(
            st,
            &h,
            "api",
            "localize/traverse",
            &format!(
                "real Haworth DEM-fix: odom {:.1}m -> fused {:.1}m ({} fixes)",
                t.odom.abs_max_err_m, t.fused.abs_max_err_m, t.n_dem_fix
            ),
        );
        Ok(axum::Json(json!({
            "ok": true,
            "ate_fused_m": t.fused.ate_aligned_m, "ate_odom_m": t.odom.ate_aligned_m,
            "abs_max_fused_m": t.fused.abs_max_err_m, "abs_max_odom_m": t.odom.abs_max_err_m,
            "n_dem_fix": t.n_dem_fix, "n_keyframes": t.true_xy.len(), "measured": t.fused.measured,
            "true_xy": t.true_xy, "fused_xy": t.fused.est_xy, "odom_xy": t.odom.est_xy,
            "fix_keyframes": t.fix_keyframes, "start_rc": [r0, c0],
        }))
        .into_response())
    })
    .await
}

/// FR-02: the depth sources the active system profile declares, each with its kind, its declared health status and
/// its output topic, and the selected one (read-only; no health is inferred).
async fn depth_sources(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let profile: Value = serde_json::from_str(st.settings.system_profile)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
        let sensors = &profile["sensors"];
        let sources: Vec<Value> = sensors["depth_sources"]
            .as_array()
            .map(|a| {
                a.iter()
                    .map(|s| {
                        json!({"name": s["name"], "kind": s["kind"], "status": s["status"],
                               "output_topic": s.get("output_topic").cloned().unwrap_or(Value::Null)})
                    })
                    .collect()
            })
            .unwrap_or_default();
        let selected = sensors.get("selected_depth_source").cloned().unwrap_or(Value::Null);
        Ok(axum::Json(json!({"ok": true, "selected": selected, "sources": sources})).into_response())
    })
    .await
}

/// The perception routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/localize", post(localize))
        .route("/localize/traverse", get(localize_traverse))
        .route("/perception/depth-sources", get(depth_sources))
        .route("/sense", post(sense))
        .route("/structure", post(structure))
        .route("/render/parallax", post(render_parallax))
        .route("/localize/render", post(localize_render))
}

/// A float field whose upper bound is optional.
const fn fl(
    gt: crate::validate::Bound,
    ge: crate::validate::Bound,
    le: crate::validate::Bound,
    default: Option<f64>,
) -> Kind {
    Kind::Float {
        gt,
        ge,
        le,
        default,
    }
}

/// The paper's low-error drum fill [kg] (NTRS 20210022781: more than about half full, above 20 kg).
const HALF_FULL_KG: f64 = 20.0;

/// Python `SenseRequest`.
const SENSE: Model = Model {
    fields: &[
        Field(
            "true_mass_kg",
            fl(None, Some((0.0, "0")), Some((1e5, "100000")), None),
        ),
        Field(
            "capacity_kg",
            Kind::Opt(&fl(Some((0.0, "0")), None, Some((1e5, "100000")), None)),
        ),
        Field(
            "noise_frac",
            fl(None, Some((0.0, "0")), Some((1.0, "1")), Some(0.0)),
        ),
        Field(
            "seed",
            Kind::Int {
                ge: 0,
                le: i64::MAX,
                default: 0,
            },
        ),
    ],
    forbid_extra: false,
};

/// Drum-fill sensing (ICE-RASSOR; Python `post_sense`): the true drum mass becomes the free-spinning drum current
/// (with seeded Gaussian noise when `noise_frac > 0`, Python's `random.Random(seed).gauss`), a linear model fitted on
/// seven fills of the drum infers the mass back, and the offload decision fires when the upper uncertainty bound
/// reaches capacity.
async fn sense(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &head)?;
        let v = body_model(body.as_ref(), SENSE)?;
        let cfg = st.planning.config.clone().map_err(|e| err(StatusCode::SERVICE_UNAVAILABLE, e))?;
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let drum = st.planning.fleet.vehicles.get("ipex").map(|v| v.drum_capacity_kg);
        let cap = v["capacity_kg"].as_f64().or(drum).ok_or_else(|| err(StatusCode::SERVICE_UNAVAILABLE,
                                                                          "the fleet registry has no ipex drum"))?;
        let (base, slope) = (cfg.fdc_baseline_a, cfg.fdc_slope_a_per_kg);
        // the calibration: currents synthesised at seven fills, then the least-squares inverse
        let masses: Vec<f64> = [0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0].iter().map(|f| cap * f).collect();
        let currents: Vec<f64> = masses.iter().map(|m| base + slope * m).collect();
        #[allow(clippy::cast_precision_loss)] // seven samples
        let n = masses.len() as f64;
        let sum = |xs: &mut dyn Iterator<Item = f64>| xs.fold(0.0, |a, x| a + x);
        let (mx, my) = (sum(&mut currents.iter().copied()) / n, sum(&mut masses.iter().copied()) / n);
        let sxx = sum(&mut currents.iter().map(|x| (x - mx).powi(2)));
        let sxy = sum(&mut currents.iter().zip(&masses).map(|(x, y)| (x - mx) * (y - my)));
        let (k, b) = (sxy / sxx, my - sxy / sxx * mx);
        let noise = num("noise_frac");
        let mut current = base + slope * num("true_mass_kg");
        if noise > 0.0 {
            let seed = u128::try_from(v["seed"].as_i64().unwrap_or(0)).unwrap_or(0);
            current += stewie_twin::mt19937::Mt19937::new(seed).gauss(0.0, noise * slope * cap);
        }
        let inferred = k * current + b;
        let (lo, hf) = (st.planning.report.fdc_mpe_all, st.planning.report.fdc_mpe_half_full);
        let unc = if inferred >= HALF_FULL_KG { hf } else { lo + inferred.max(0.0) / HALF_FULL_KG * (hf - lo) };
        let (lower, upper) = (inferred * (1.0 - unc), inferred * (1.0 + unc));
        let offload = upper >= cap;
        // the Python audits drum sensing under the literal actor "api"
        log(st, &head, "api", "sense", &format!("inferred {inferred:.1} kg, offload={}", if offload { "True" } else { "False" }));
        Ok(axum::Json(json!({"ok": true, "true_mass_kg": num("true_mass_kg"), "current_a": current, "inferred_kg": inferred,
                             "uncertainty_frac": unc, "lower_kg": lower, "upper_kg": upper, "capacity_kg": cap,
                             "offload": offload, "noise_frac": noise}))
        .into_response())
    })
    .await
}

const NAME: Kind = Kind::Str {
    min: 0,
    max: 80,
    nullable: true,
    default: None,
};

/// Python `StructureRequest` (`extra="allow"`).
const STRUCTURE: Model = Model {
    fields: &[
        Field("name", NAME),
        Field("x", fl(None, None, None, Some(0.0))),
        Field("y", fl(None, None, None, Some(0.0))),
        Field("params", Kind::Dict),
        Field("site", NAME),
        Field(
            "lat",
            Kind::Opt(&fl(None, Some((-90.0, "-90")), Some((90.0, "90")), None)),
        ),
        Field(
            "lon",
            Kind::Opt(&fl(
                None,
                Some((-360.0, "-360")),
                Some((360.0, "360")),
                None,
            )),
        ),
    ],
    forbid_extra: false,
};

/// The median slope [deg] of a 400 x 400 window of the site's DEM around the placement (or the centre), with the
/// DEM cell and what it was measured at (Python `constructability.site_slope_deg`); no slope without a DEM.
fn site_slope(
    st: &AppState,
    site: Option<&str>,
    lat: Option<f64>,
    lon: Option<f64>,
) -> (Option<f64>, Option<f64>, &'static str) {
    let Some(site) = site.filter(|s| !s.is_empty()) else {
        return (None, None, "no-site");
    };
    let Some((dem, _)) = st.terrain.moon_dem(site) else {
        return (None, None, "site-dem-unavailable");
    };
    let (h, w, cell) = (dem.rows, dem.cols, dem.cell_m);
    let (mut rc, mut cc, mut source) = (h / 2, w / 2, "site-median");
    if let (Some(lat), Some(lon)) = (lat, lon)
        && let Ok((ox, oy)) = st.terrain.latlon_to_order(&dem, (0.0, 0.0), lon, lat)
    {
        #[allow(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            clippy::cast_precision_loss
        )] // grid indices
        let clamp = |v: f64, n: usize| (v.round_ties_even().max(0.0) as usize).min(n - 1);
        (rc, cc, source) = (clamp(oy / cell, h), clamp(ox / cell, w), "placement");
    }
    let half = 200;
    let r0 = rc.saturating_sub(half).min(h.saturating_sub(2 * half));
    let c0 = cc.saturating_sub(half).min(w.saturating_sub(2 * half));
    let (rows, cols) = ((r0 + 2 * half).min(h) - r0, (c0 + 2 * half).min(w) - c0);
    if rows * cols < 4 {
        return (None, None, "dem-window-empty");
    }
    let win: Vec<f64> = (r0..r0 + rows)
        .flat_map(|r| dem.z[r * w + c0..r * w + c0 + cols].iter().copied())
        .collect();
    let mut slope = lunar_dem::slope_deg_grid(&win, cols, rows, cell);
    slope.sort_by(f64::total_cmp);
    let n = slope.len();
    let median = if n % 2 == 1 {
        slope[n / 2]
    } else {
        f64::midpoint(slope[n / 2 - 1], slope[n / 2])
    };
    (Some(median), Some(cell), source)
}

/// Python's builtin `round(x, n)` (the evidence's rounding).
fn round(x: f64, n: usize) -> f64 {
    stewie_traverse::nav::py_round(x, n)
}

/// SD-01 (Python `constructability.structure_evidence`): the orders' volume and mass at the bank (cut) and loose
/// (fill) densities; at the site slope, the applied wheel contact pressure against the allowable bearing, the
/// slip-sinkage equilibrium on the canonical constants (as the Python's spine) and the derived verdict.
#[allow(clippy::too_many_lines)] // the Python's evidence block, field by field
fn structure_evidence(
    st: &AppState,
    name: &Value,
    orders: &[Value],
    site: &Value,
    slope: (Option<f64>, Option<f64>, &str),
) -> Result<Value, String> {
    let (_, base) = stewie_physics::soil::bundled();
    let (bank, loose) = (base.rho_deep.value, base.rho_spoil.value);
    let (mut per, mut cv, mut fv, mut cm, mut fm) = (Vec::new(), 0.0, 0.0, 0.0, 0.0);
    for o in orders {
        let (fp, depth) = (
            o["footprint_m2"].as_f64().unwrap_or(0.0),
            o["depth_m"].as_f64().unwrap_or(0.0),
        );
        let vol = fp * depth;
        let cut = o["kind"] == "cut";
        let rho = if cut { bank } else { loose };
        let mass = vol * rho;
        per.push(json!({"action": o.get("action").cloned().unwrap_or(json!("")), "kind": o["kind"],
                        "footprint_m2": round(fp, 3), "depth_m": round(depth, 4), "volume_m3": round(vol, 4),
                        "mass_kg": round(mass, 1), "density_kg_m3": rho}));
        if cut {
            cv += vol;
            cm += mass;
        } else {
            fv += vol;
            fm += mass;
        }
    }
    let balanced = cm > 0.0 && fm > 0.0 && (cm - fm).abs() <= 1e-6 * cm.max(fm);
    let earthwork = json!({"orders": per, "cut_volume_m3": round(cv, 4), "fill_volume_m3": round(fv, 4),
                           "cut_mass_kg": round(cm, 1), "fill_mass_kg": round(fm, 1), "excavated_volume_m3": round(cv, 4),
                           "excavated_mass_kg": round(cm, 1), "mass_balanced": balanced});
    let (mut terra, mut verdict) = (Value::Null, Value::Null);
    if let Some(deg) = slope.0 {
        let cfg = st.planning.config.as_ref().map_err(Clone::clone)?;
        let soil = crate::nav_routes::constants_soil()?;
        let ipex = st
            .planning
            .fleet
            .vehicles
            .get("ipex")
            .ok_or("the fleet registry has no ipex")?;
        let g = st
            .planning
            .bodies
            .get("moon")
            .map(|b| b.g)
            .ok_or("no moon in the body registry")?;
        let weight = ipex.dry_mass_kg * g;
        let th = deg.to_radians();
        let (len, width) = (cfg.slip.contact_len_m, cfg.slip.contact_width_m);
        #[allow(clippy::cast_precision_loss)] // a wheel count
        let applied = weight * th.cos() / ipex.n_wheels.get() as f64 / (width * len);
        let case = stewie_physics::terra::DriveCase {
            total_weight_n: weight,
            slope_rad: th,
            n_wheels: cfg.slip.n_wheels,
            contact_len_m: len,
            contact_width_m: width,
            density: None,
            demand_frac: 1.0,
            extra_demand_n: 0.0,
            s_entrap: 0.95,
            z_entrap_m: cfg.slip.z_entrap_m,
        };
        let eq = stewie_physics::terra::slip_sinkage_equilibrium(&case, &soil)
            .map_err(|e| e.to_string())?;
        let allowable = stewie_physics::bearing::allowable_pa(
            soil.cohesion_pa,
            soil.phi_rad,
            loose * g,
            width,
            0.0,
            3.0,
        );
        let (pa, cap) = (round(applied, 1), round(allowable, 1));
        let sink = round(eq.sinkage_m, 4);
        terra = json!({"slope_deg": round(deg, 2), "contact_pressure_pa": pa, "bearing_capacity_pa": cap,
                       "bearing_fs": 3.0, "bearing_ok": applied <= allowable, "sinkage_m": sink,
                       "static_sinkage_m": round(eq.static_sinkage_m, 4), "slip": round(eq.slip, 4),
                       "entrapped": eq.entrapped});
        let limit = ipex.wheel_radius_m;
        let within = sink <= limit;
        let bearing_ok = applied <= allowable;
        let status = if eq.entrapped {
            format!(
                "NOT constructable — sinkage runaway (entrapment) at {:.0}° (slip {:.2})",
                round(deg, 2),
                round(eq.slip, 4)
            )
        } else if !within {
            format!(
                "NOT constructable — sinkage {sink:.3} m exceeds the {limit:.3} m wheel-radius mobility limit"
            )
        } else if !bearing_ok {
            format!(
                "NOT constructable — contact pressure {pa:.0} Pa exceeds allowable bearing {cap:.0} Pa"
            )
        } else {
            format!(
                "bearing OK ({pa:.0} ≤ {cap:.0} Pa) · sinkage within limit ({sink:.3} ≤ {limit:.3} m)"
            )
        };
        verdict = json!({"constructable": !eq.entrapped && within && bearing_ok, "status": status,
                         "bearing_ok": bearing_ok, "sinkage_within_limit": within, "sinkage_limit_m": round(limit, 4),
                         "sinkage_limit_basis": "wheel radius (IPEx WHEEL_RADIUS_M) — sinkage past it buries the hub"});
    }
    let spine = crate::model_routes::reg("terra_spine");
    let cal = |id: &str, d: &str| {
        spine
            .as_array()
            .and_then(|a| a.iter().find(|t| t["id"] == id))
            .map_or_else(|| json!(d), |t| t["calibration"].clone())
    };
    Ok(
        json!({"name": name, "site": site, "site_slope_deg": slope.0.map(|s| round(s, 2)), "slope_source": slope.2,
              "earthwork": earthwork, "terramechanics": terra, "verdict": verdict,
              "material": {"cut_density_kg_m3": bank, "fill_density_kg_m3": loose,
                           "assumption": "conserved Apollo-profile bank(cut)/loose(fill) regolith density; mass = volume × density",
                           "provenance": "stewie.specs.constants RHO_DEEP / RHO_SPOIL"},
              "uncertainty": {"dem_resolution_m": slope.1.map(|c| round(c, 3)), "slope_calibration": cal("slope", "measured"),
                              "density_calibration": cal("regolith_density", "calibrated"),
                              "sinkage_calibration": cal("sinkage", "calibrated"),
                              "bearing_calibration": cal("contact_pressure", "calibrated"),
                              "note": "volume = footprint × depth (exact from the decomposed order); mass uses the calibrated \
                                       bank/loose density profile; bearing/sinkage are calibrated Tier-2 spine terms (not \
                                       oracle-fit); site slope is measured on the real DEM at the resolution above."}}),
    )
}

/// SD-01: decompose a named structure at (x, y) into mass-balanced cut and fill orders, with its constructability
/// evidence at the site's real slope.
async fn structure(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &head)?;
        let v = body_model(body.as_ref(), STRUCTURE)?;
        let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
        let params = v["params"].as_object().cloned().unwrap_or_default();
        if params.len() > 32 {
            return Err(bad("too many structure params (max 32)".to_owned()));
        }
        let (_, base) = stewie_physics::soil::bundled();
        let d = stewie_build::Densities {
            bank: base.rho_deep.value,
            loose: base.rho_spoil.value,
        };
        let num = |k: &str| v[k].as_f64().unwrap_or(0.0);
        let Some(name) = v["name"].as_str() else {
            let mut known: Vec<&str> = stewie_build::STRUCTURES.to_vec();
            known.sort_unstable();
            return Err(bad(format!(
                "unknown structure None; known: {}",
                stewie_twin::pyjson::repr_list(&known)
            )));
        };
        let orders = stewie_build::decompose(name, num("x"), num("y"), &params, &d).map_err(bad)?;
        let slope = site_slope(st, v["site"].as_str(), v["lat"].as_f64(), v["lon"].as_f64());
        let evidence = structure_evidence(st, &v["name"], &orders, &v["site"], slope)
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        let name = v["name"].as_str().unwrap_or("None");
        log(
            st,
            &head,
            "api",
            "structure",
            &format!("{name}: {} orders", orders.len()),
        );
        Ok(axum::Json(
            json!({"ok": true, "name": v["name"], "orders": orders, "evidence": evidence}),
        )
        .into_response())
    })
    .await
}

/// Python `ParallaxPlanRequest` (`extra="forbid"`).
const PARALLAX: Model = Model {
    fields: &[
        Field(
            "scene",
            Kind::Regex {
                pattern: r"^[A-Za-z0-9_\-]+$",
                max: 64,
                default: Some("crater_boulders"),
            },
        ),
        Field(
            "sun_az_deg",
            fl(None, Some((0.0, "0")), Some((360.0, "360")), None),
        ),
        Field(
            "sun_el_deg",
            fl(None, Some((0.0, "0")), Some((90.0, "90")), None),
        ),
        Field(
            "posture_from",
            Kind::Regex {
                pattern: "^[A-Z_]+$",
                max: 32,
                default: Some("TRANSIT"),
            },
        ),
        Field(
            "posture_to",
            Kind::Regex {
                pattern: "^[A-Z_]+$",
                max: 32,
                default: Some("MEERKAT"),
            },
        ),
        Field(
            "size",
            Kind::Regex {
                pattern: r"^\d{2,5}x\d{2,5}$",
                max: 12,
                default: Some("1024x768"),
            },
        ),
    ],
    forbid_extra: true,
};

/// Python `LocalizeRenderRequest` (`extra="forbid"`).
const LOCALIZE_RENDER: Model = Model {
    fields: &[
        Field(
            "camera",
            Kind::Regex {
                pattern: "^[a-z_]+$",
                max: 32,
                default: Some("front_left"),
            },
        ),
        Field(
            "drift_m",
            fl(Some((0.0, "0")), None, Some((50.0, "50")), Some(1.41)),
        ),
    ],
    forbid_extra: true,
};

/// This checkout, resolved, as the Python names its files (`stewie/godot/...`, `samples/...`).
fn checkout() -> std::path::PathBuf {
    let repo = crate::content_routes::repo();
    std::fs::canonicalize(&repo).unwrap_or(repo)
}

/// SN-10: the two-posture standstill capture plan: the known baseline `dh = lift_B - lift_A` and the two Godot render
/// commands (same scene and sun, the eight-camera rig, each posture's chassis lift) a GPU host runs for the pair.
async fn render_parallax(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &h)?;
        let v = body_model(body.as_ref(), PARALLAX)?;
        let text = |k: &str| v[k].as_str().unwrap_or_default().to_owned();
        let num = |k: &str| crate::executive_routes::float_repr(v[k].as_f64().unwrap_or(0.0));
        let (scene, from, to) = (text("scene"), text("posture_from"), text("posture_to"));
        let unknown = |e: String| err(StatusCode::BAD_REQUEST, format!("unknown posture: {e}"));
        let (lift_a, lift_b) = (
            crate::spec_routes::chassis_lift(&from).map_err(unknown)?,
            crate::spec_routes::chassis_lift(&to).map_err(unknown)?,
        );
        let render = checkout()
            .join("stewie/godot/render_layers.sh")
            .display()
            .to_string();
        let argv = |lift: f64| {
            json!([
                render,
                "--",
                "--scene",
                scene,
                "--cameras",
                "--rover-rc",
                "1000,1000",
                "--chassis-lift",
                format!("{lift:.4}"),
                "--sun-elev",
                num("sun_el_deg"),
                "--sun-azim",
                num("sun_az_deg"),
                "--size",
                text("size")
            ])
        };
        log(st, &h, "api", "render/parallax", &scene);
        Ok(axum::Json(json!({
            "ok": true, "scene": scene, "dh_m": lift_b - lift_a,
            "frames": [{"posture": from, "chassis_lift_m": lift_a, "argv": argv(lift_a)},
                       {"posture": to, "chassis_lift_m": lift_b, "argv": argv(lift_b)}],
        }))
        .into_response())
    })
    .await
}

/// A sensor-metadata number, refused as the Python's `KeyError` when absent.
fn meta_f64(v: &Value, path: &[&str]) -> Result<f64, String> {
    let mut at = v;
    for k in path {
        at = at.get(*k).ok_or_else(|| format!("'{k}'"))?;
    }
    at.as_f64()
        .ok_or_else(|| format!("{}: not a number", path.join(".")))
}

/// The rendered frame as PIL's `convert("L")`: ITU-R 601-2 luma in 16-bit fixed point, rounded.
fn gray(path: &std::path::Path) -> Result<stewie_perceive::parallax::Gray, String> {
    let (w, h, rgb) = crate::render_routes::read_rgb(path)?;
    Ok(stewie_perceive::parallax::Gray {
        px: rgb
            .chunks_exact(3)
            .map(|p| {
                f64::from(
                    (u32::from(p[0]) * 19595
                        + u32::from(p[1]) * 38470
                        + u32::from(p[2]) * 7471
                        + 0x8000)
                        >> 16,
                )
            })
            .collect(),
        width: w as usize,
        height: h as usize,
    })
}

/// The scene heightfield (`heightmap.rf32`, little-endian float32, its grid in `metadata.json`).
fn heightfield(scene: &std::path::Path) -> Result<stewie_perceive::parallax::Heightfield, String> {
    let meta: Value = serde_json::from_slice(
        &std::fs::read(scene.join("metadata.json")).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let g = &meta["grid"];
    let dim = |k: &str| {
        g[k].as_u64()
            .and_then(|x| usize::try_from(x).ok())
            .ok_or_else(|| format!("'{k}'"))
    };
    let (width, height) = (dim("width")?, dim("height")?);
    let raw = std::fs::read(scene.join("heightmap.rf32")).map_err(|e| e.to_string())?;
    if raw.len() != width * height * 4 {
        return Err(format!(
            "cannot reshape array of size {} into shape ({height},{width})",
            raw.len() / 4
        ));
    }
    Ok(stewie_perceive::parallax::Heightfield {
        z: raw
            .chunks_exact(4)
            .map(|b| f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]])))
            .collect(),
        width,
        height,
        cell_m: meta_f64(&meta, &["grid", "cell_m"])?,
    })
}

/// SN-10: the measured articulation-parallax fix from the committed two-posture render pair (a truth-free confidence
/// gate and a RANSAC over the measured ranges); 503 when the pair is absent, never a fabricated fix.
async fn localize_render(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (h, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &h)?;
        let v = body_model(body.as_ref(), LOCALIZE_RENDER)?;
        let camera = v["camera"].as_str().unwrap_or_default().to_owned();
        let drift = v["drift_m"].as_f64().unwrap_or(1.41);
        let (render_dir, scene_dir) = (checkout().join("stewie/godot/out/parallax"), checkout().join("samples/crater_boulders"));
        if !render_dir.join("A").join(format!("{camera}.png")).exists() {
            return Err(err(
                StatusCode::SERVICE_UNAVAILABLE,
                "two-posture render-pair unavailable (stewie/godot/out/parallax); render it with the Godot sidecar first",
            ));
        }
        let internal = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, e);
        let read = |name: &str| -> Result<Value, String> {
            serde_json::from_slice(&std::fs::read(render_dir.join(name)).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())
        };
        let (sa, sb) = (read("A_sensors.json").map_err(internal)?, read("B_sensors.json").map_err(internal)?);
        let bad = |e: String| err(StatusCode::BAD_REQUEST, e);
        let ca = sa["cameras"]
            .as_array()
            .and_then(|cs| cs.iter().find(|c| c["name"] == camera.as_str()))
            .ok_or_else(|| internal(format!("camera {camera} is not in the render pair's sensor metadata")))?;
        let pos = |r: &Value, i: usize| {
            r["position_m"].get(i).and_then(Value::as_f64).ok_or_else(|| "'position_m'".to_owned())
        };
        let triple = |k: &str, n: usize| -> Result<Vec<f64>, String> {
            (0..n)
                .map(|i| ca["pose_in_world"][k].get(i).and_then(Value::as_f64).ok_or_else(|| format!("'{k}'")))
                .collect()
        };
        let (cpos, cquat) = (triple("position_m", 3).map_err(bad)?, triple("quaternion_xyzw", 4).map_err(bad)?);
        let cam = stewie_perceive::parallax::Camera {
            fx: meta_f64(ca, &["intrinsics", "fx"]).map_err(bad)?,
            fy: meta_f64(ca, &["intrinsics", "fy"]).map_err(bad)?,
            cx: meta_f64(ca, &["intrinsics", "cx"]).map_err(bad)?,
            cy: meta_f64(ca, &["intrinsics", "cy"]).map_err(bad)?,
            position: [cpos[0], cpos[1], cpos[2]],
            quat_xyzw: [cquat[0], cquat[1], cquat[2], cquat[3]],
        };
        let dh = pos(&sb["rover"], 1).map_err(bad)? - pos(&sa["rover"], 1).map_err(bad)?;
        if dh <= 0.0 {
            return Err(bad("the B posture must lift the chassis above A (dh > 0)".to_owned()));
        }
        let true_xy = [pos(&sa["rover"], 0).map_err(bad)?, pos(&sa["rover"], 2).map_err(bad)?];
        let frame = |side: &str| gray(&render_dir.join(side).join(format!("{camera}.png"))).map_err(internal);
        let (ga, gb) = (frame("A")?, frame("B")?);
        let terrain = heightfield(&scene_dir).map_err(bad)?;
        let fix = stewie_perceive::parallax::localize_on_render_pair(&ga, &gb, &terrain, &cam, dh, true_xy, drift)
            .map_err(bad)?;
        let r = |x: f64, n: usize| stewie_traverse::nav::py_round(x, n);
        let error_m = r((fix.fix_xy[0] - true_xy[0]).hypot(fix.fix_xy[1] - true_xy[1]), 3);
        let n_inliers = fix.inlier_ranges.len();
        let (lo, hi) = fix
            .inlier_ranges
            .iter()
            .fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), &x| (lo.min(x), hi.max(x)));
        log(
            st,
            &h,
            "api",
            "localize/render",
            &format!("{camera}: fix err {} m, {n_inliers} inliers", crate::executive_routes::float_repr(error_m)),
        );
        Ok(axum::Json(json!({
            "ok": true, "fix_xy": fix.fix_xy, "true_xy": true_xy, "seed_xy": fix.seed_xy, "error_m": error_m,
            "fix_sigma_m": r(fix.fix_sigma_m, 3), "drift_m": r(drift, 3), "n_features": fix.n_features,
            "n_inliers": n_inliers, "dh_m": r(dh, 4), "camera": camera, "range_span_m": [r(lo, 2), r(hi, 2)],
            "landmarks_xy": fix.inlier_landmarks.iter().take(60).map(|l| [r(l[0], 2), r(l[1], 2)]).collect::<Vec<_>>(),
        }))
        .into_response())
    })
    .await
}
