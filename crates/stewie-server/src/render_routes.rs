//! The select-area render (RW-51b; Python `routers/perception.post_render` over `scripts/plan_render_pipeline`):
//! `POST /render` crops a window of the real Haworth bundle at the picked (u, v), flattens its central pad to the
//! median level on the conserved column state, writes the BEFORE and AFTER scene bundles, renders both through the
//! Godot renderer plugin (RW-51a), and answers the composed figure with the earthwork. No renderer configured is a
//! 503; a render that fails is a 500 naming why. The earthwork is the Python's to 1e-9 (`render_earthwork_cases`);
//! the figure is the two real renders side by side (the Python's is a matplotlib composite, D-R180).

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::post;
use serde_json::{Value, json};
use stewie_physics::column::{ColumnState, Fields, Regolith};
use stewie_plugins::{Kind, Registry, Session};

use crate::app::{
    ApiError, AppState, blocking, body_model, err, log, parse_body, require_auth, split,
};
use crate::validate::{Field, Kind as VKind, Model};

/// The window's side in bundle cells and its resampling factor (the pipeline's defaults).
const WIN_CELLS: usize = 10;
const ZOOM: usize = 10;

/// `scipy.ndimage.zoom` of a row-major `rows x cols` grid by `z` (order 1: bilinear, order 0: nearest), with its
/// `grid_mode=False` mapping: output index `i` samples input coordinate `i (n - 1) / (m - 1)`.
#[allow(clippy::many_single_char_names)] // scipy's n, m, x, y and the zoom z
fn ndzoom(src: &[f64], rows: usize, cols: usize, z: usize, nearest: bool) -> Vec<f64> {
    let (mr, mc) = (rows * z, cols * z);
    #[allow(clippy::cast_precision_loss)] // grid sizes
    let coord = |i: usize, n: usize, m: usize| {
        if m > 1 {
            i as f64 * ((n - 1) as f64 / (m - 1) as f64)
        } else {
            0.0
        }
    };
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // non-negative coordinates
    let split = |c: f64, n: usize| {
        let i0 = (c.floor() as usize).min(n - 1);
        (i0, (i0 + 1).min(n - 1), c - c.floor())
    };
    let mut out = Vec::with_capacity(mr * mc);
    for i in 0..mr {
        let y = coord(i, rows, mr);
        for j in 0..mc {
            let x = coord(j, cols, mc);
            if nearest {
                #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
                // non-negative coordinates
                let (r, c) = (
                    ((y + 0.5).floor() as usize).min(rows - 1),
                    ((x + 0.5).floor() as usize).min(cols - 1),
                );
                out.push(src[r * cols + c]);
            } else {
                let ((y0, y1, wy), (x0, x1, wx)) = (split(y, rows), split(x, cols));
                let at = |r: usize, c: usize| src[r * cols + c];
                out.push(
                    (at(y0, x0) * (1.0 - wx) + at(y0, x1) * wx) * (1.0 - wy)
                        + (at(y1, x0) * (1.0 - wx) + at(y1, x1) * wx) * wy,
                );
            }
        }
    }
    out
}

/// Python `crop_window_columnstate`: the `WIN_CELLS` window at the (u, v) fraction of `full`, resampled by `ZOOM`
/// (the state label nearest, the rest bilinear), its datum zero-based so the sidecar frames a relative patch.
///
/// # Errors
/// A resampled field outside the column state's domain.
#[allow(clippy::many_single_char_names)] // the Python's h, w, f, u, v, r
pub fn crop_window(
    full: &ColumnState,
    u: f64,
    v: f64,
    r: &Regolith,
) -> Result<ColumnState, String> {
    let (h, w) = (full.height(), full.width());
    let win = WIN_CELLS.min(h).min(w);
    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )] // grid indices
    let (cr, cc) = (
        (v.clamp(0.0, 1.0) * (h - 1) as f64) as usize,
        (u.clamp(0.0, 1.0) * (w - 1) as f64) as usize,
    );
    let half = win / 2;
    let (r0, c0) = (
        cr.saturating_sub(half).min(h - win),
        cc.saturating_sub(half).min(w - win),
    );
    let f = full.fields();
    let take = |v: &[f64]| -> Vec<f64> {
        (r0..r0 + win)
            .flat_map(|row| v[row * w + c0..row * w + c0 + win].to_vec())
            .collect()
    };
    let mut datum = ndzoom(&take(&f.datum), win, win, ZOOM, false);
    let low = datum.iter().copied().fold(f64::INFINITY, f64::min);
    for d in &mut datum {
        *d -= low;
    }
    let labels: Vec<f64> = f.state_label.iter().map(|&l| f64::from(l)).collect();
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // labels are small codes
    let state_label = ndzoom(&take(&labels), win, win, ZOOM, true)
        .iter()
        .map(|&l| l as u8)
        .collect();
    #[allow(clippy::cast_precision_loss)] // the zoom factor
    let cell = full.cell_m() / ZOOM as f64;
    ColumnState::new(
        win * ZOOM,
        win * ZOOM,
        cell,
        Fields {
            mass_areal: ndzoom(&take(&f.mass_areal), win, win, ZOOM, false),
            density: ndzoom(&take(&f.density), win, win, ZOOM, false),
            state_label,
            disturbance: ndzoom(&take(&f.disturbance), win, win, ZOOM, false),
            datum,
            ice: None,
        },
        0.0,
        r,
    )
    .map_err(|e| e.to_string())
}

/// The flatten's earthwork (Python `plan_flatten`'s numbers).
#[derive(Debug, Clone, PartialEq)]
pub struct Flatten {
    pub target: f64,
    pub cut_kg: f64,
    pub fill_kg: f64,
    pub cut_vol_m3: f64,
    pub fill_vol_m3: f64,
}

/// Python `plan_flatten`: the central `pad_frac` square flattened to its median height on the conserved state --
/// what stands above is cut into the drum, what lies below is filled toward the level from it.
///
/// # Errors
/// The column state refusing the cut or the fill.
pub fn plan_flatten(cs: &mut ColumnState, pad_frac: f64, r: &Regolith) -> Result<Flatten, String> {
    let h0 = cs.derive_height();
    let (h, w) = (cs.height(), cs.width());
    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )] // Python's int()
    let bound = |n: usize, s: f64| (n as f64 * (0.5 + s * pad_frac / 2.0)) as usize;
    let (r0, r1, c0, c1) = (bound(h, -1.0), bound(h, 1.0), bound(w, -1.0), bound(w, 1.0));
    let pad: Vec<bool> = (0..h * w)
        .map(|i| (r0..r1).contains(&(i / w)) && (c0..c1).contains(&(i % w)))
        .collect();
    let mut inside: Vec<f64> = h0
        .iter()
        .zip(&pad)
        .filter(|(_, p)| **p)
        .map(|(x, _)| *x)
        .collect();
    if inside.is_empty() {
        return Err("the pad holds no cells".to_owned());
    }
    inside.sort_by(f64::total_cmp);
    let n = inside.len();
    let target = if n % 2 == 1 {
        inside[n / 2]
    } else {
        f64::midpoint(inside[n / 2 - 1], inside[n / 2])
    };
    let above: Vec<bool> = pad
        .iter()
        .zip(&h0)
        .map(|(p, x)| *p && *x > target)
        .collect();
    let below: Vec<bool> = pad
        .iter()
        .zip(&h0)
        .map(|(p, x)| *p && *x < target)
        .collect();
    let dens = cs.fields().density.clone();
    let cut_areal: Vec<f64> = (0..h0.len())
        .map(|i| {
            if above[i] {
                (h0[i] - target) * dens[i]
            } else {
                0.0
            }
        })
        .collect();
    let cut_kg = cs
        .cut_to_inventory(&above, &cut_areal)
        .map_err(|e| e.to_string())?;
    let fill_kg = cs
        .fill_toward(&below, &vec![target; h0.len()], None, r.rho_spoil)
        .map_err(|e| e.to_string())?;
    let area = cs.cell_m() * cs.cell_m();
    let cut: Vec<f64> = (0..h0.len())
        .map(|i| if above[i] { h0[i] - target } else { 0.0 })
        .collect();
    let fill: Vec<f64> = (0..h0.len())
        .map(|i| if below[i] { target - h0[i] } else { 0.0 })
        .collect();
    Ok(Flatten {
        target,
        cut_kg,
        fill_kg,
        cut_vol_m3: stewie_twin::numpy::sum(&cut) * area,
        fill_vol_m3: stewie_twin::numpy::sum(&fill) * area,
    })
}

/// Write `cs` as an INTERFACE.md scene bundle (Python `write_bundle` / `save_scene`): the five rasters row-major
/// little-endian, then `metadata.json` (the bundle's, re-gridded to the window) last as the commit marker.
fn write_bundle(cs: &ColumnState, meta: &Value, dir: &Path) -> Result<(), String> {
    std::fs::create_dir_all(dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    let f = cs.fields();
    #[allow(clippy::cast_possible_truncation)] // the scene contract is float32
    let f32s =
        |v: &[f64]| -> Vec<u8> { v.iter().flat_map(|x| (*x as f32).to_le_bytes()).collect() };
    let rasters: [(&str, Vec<u8>); 5] = [
        ("heightmap", f32s(&cs.derive_height())),
        ("mass_areal", f32s(&f.mass_areal)),
        ("density", f32s(&f.density)),
        ("disturbance", f32s(&f.disturbance)),
        ("state_label", f.state_label.clone()),
    ];
    for (name, bytes) in rasters {
        let file = meta["fields"][name]["file"]
            .as_str()
            .ok_or_else(|| format!("the bundle names no {name} file"))?;
        crate::atomic_write(&dir.join(file), &bytes)?;
    }
    let text = serde_json::to_string_pretty(meta).map_err(|e| e.to_string())?;
    crate::atomic_write(&dir.join("metadata.json"), text.as_bytes())
}

/// The window's metadata: the bundle's, renamed `map_window` and re-gridded.
fn window_meta(bundle_meta: &Value, cs: &ColumnState) -> Value {
    let mut m = bundle_meta.clone();
    #[allow(clippy::cast_precision_loss)] // grid sizes
    let (x1, y1) = (
        cs.width() as f64 * cs.cell_m(),
        cs.height() as f64 * cs.cell_m(),
    );
    m["scene_name"] = json!("map_window");
    m["grid"] = json!({"width": cs.width(), "height": cs.height(), "cell_m": cs.cell_m(), "order": "row-major-C"});
    m["world_bounds_m"] = json!({"x0": 0.0, "y0": 0.0, "x1": x1, "y1": y1});
    m
}

/// Decode an RGB(A) PNG to RGB rows.
fn read_rgb(path: &Path) -> Result<(u32, u32, Vec<u8>), String> {
    let file = std::fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let mut reader = png::Decoder::new(std::io::BufReader::new(file))
        .read_info()
        .map_err(|e| e.to_string())?;
    let mut buf = vec![0; reader.output_buffer_size().ok_or("an oversized image")?];
    let info = reader.next_frame(&mut buf).map_err(|e| e.to_string())?;
    let px = &buf[..info.buffer_size()];
    let rgb = match info.color_type {
        png::ColorType::Rgb => px.to_vec(),
        png::ColorType::Rgba => px
            .chunks_exact(4)
            .flat_map(|p| [p[0], p[1], p[2]])
            .collect(),
        other => {
            return Err(format!(
                "{}: unexpected colour type {other:?}",
                path.display()
            ));
        }
    };
    Ok((info.width, info.height, rgb))
}

/// The figure: the BEFORE and AFTER renders side by side.
fn compose(before: &Path, after: &Path, out: &Path) -> Result<(), String> {
    let (w0, h0, a) = read_rgb(before)?;
    let (w1, h1, b) = read_rgb(after)?;
    if (w0, h0) != (w1, h1) {
        return Err("the two renders differ in size".to_owned());
    }
    let row = w0 as usize * 3;
    let mut px = Vec::with_capacity(a.len() * 2);
    for y in 0..h0 as usize {
        px.extend_from_slice(&a[y * row..(y + 1) * row]);
        px.extend_from_slice(&b[y * row..(y + 1) * row]);
    }
    let mut bytes = Vec::new();
    {
        let mut enc = png::Encoder::new(&mut bytes, w0 * 2, h0);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        enc.write_header()
            .and_then(|mut w| w.write_image_data(&px))
            .map_err(|e| e.to_string())?;
    }
    crate::atomic_write(out, &bytes)
}

/// Python `RenderRequest`.
const RENDER: Model = Model {
    fields: &[
        Field(
            "u",
            VKind::Float {
                gt: None,
                ge: Some((0.0, "0")),
                le: Some((1.0, "1")),
                default: Some(0.5),
            },
        ),
        Field(
            "v",
            VKind::Float {
                gt: None,
                ge: Some((0.0, "0")),
                le: Some((1.0, "1")),
                default: Some(0.5),
            },
        ),
        Field(
            "pad_frac",
            VKind::Float {
                gt: Some((0.0, "0")),
                ge: None,
                le: Some((1.0, "1")),
                default: Some(0.5),
            },
        ),
        Field(
            "mission_t_s",
            VKind::Opt(&VKind::Float {
                gt: None,
                ge: None,
                le: None,
                default: None,
            }),
        ),
    ],
    forbid_extra: false,
};

/// Python's `round(x)`: the nearest integer, ties to even.
#[allow(clippy::cast_possible_truncation)] // a mass in kg
fn round_int(x: f64) -> i64 {
    x.round_ties_even() as i64
}

fn unavailable(why: &str) -> ApiError {
    err(
        StatusCode::SERVICE_UNAVAILABLE,
        format!("render pipeline unavailable ({why})"),
    )
}

/// The Godot renderer, started and handshaken, offering `render`.
fn renderer(st: &AppState) -> Result<Session, ApiError> {
    let reg = Registry::discover(&st.settings.plugin_path);
    let plugin = reg
        .require(Kind::Renderer)
        .map_err(|u| unavailable(&u.to_string()))?;
    let s =
        Session::start(plugin, Duration::from_mins(5)).map_err(|u| unavailable(&u.to_string()))?;
    if !s.capabilities.iter().any(|c| c == "render") {
        return Err(unavailable(
            "the renderer plugin has no Godot binary configured",
        ));
    }
    Ok(s)
}

#[allow(clippy::too_many_lines)] // the Python's route, step by step
async fn render(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let (head, bytes) = split(req, st.settings.max_body).await;
    blocking(st, move |st| {
        let body = parse_body(&bytes?)?;
        require_auth(st, &head)?;
        let v = body_model(body.as_ref(), RENDER)?;
        let num = |k: &str| v[k].as_f64().unwrap_or(0.5);
        let (u, vv, pad) = (num("u"), num("v"), num("pad_frac"));
        let mut session = renderer(st)?;
        crate::plan_routes::prune_reports(st);
        let reports = st.cfg.data_dir.join("reports");
        let stem = {
            use sha1::Digest as _;
            let digest = sha1::Sha1::digest(format!("{u:.4}_{vv:.4}_{pad:.2}").as_bytes());
            let hex = digest.iter().fold(String::new(), |mut out, b| {
                use std::fmt::Write as _;
                let _ = write!(out, "{b:02x}");
                out
            });
            format!("render_{}", &hex[..10])
        };
        let failed = |e: String| err(StatusCode::INTERNAL_SERVER_ERROR, format!("render failed: {e}"));
        let bundle = st.terrain.bundle_for_site("haworth").map_err(failed)?;
        let soil_base = &st.planning.soil_base;
        let rho = st.planning.bodies.get("moon").and_then(|b| b.bulk_density).ok_or_else(|| failed("no moon density".into()))?;
        let regolith = Regolith::new(rho, soil_base);
        let (full, _) = stewie_physics::worksite::coarse_base_from_bundle(&bundle, &regolith).map_err(|e| failed(e.to_string()))?;
        let bundle_meta: Value = serde_json::from_str(
            &std::fs::read_to_string(bundle.join("metadata.json")).map_err(|e| failed(e.to_string()))?,
        )
        .map_err(|e| failed(e.to_string()))?;
        let mut cs = crop_window(&full, u, vv, &regolith).map_err(failed)?;
        let meta = window_meta(&bundle_meta, &cs);
        let out_dir: PathBuf = reports.join(&stem);
        write_bundle(&cs, &meta, &out_dir.join("before_bundle")).map_err(failed)?;
        let plan = plan_flatten(&mut cs, pad, &regolith).map_err(failed)?;
        write_bundle(&cs, &meta, &out_dir.join("after_bundle")).map_err(failed)?;
        #[allow(clippy::cast_precision_loss)] // grid size
        let ext = cs.width() as f64 * cs.cell_m();
        let c = ext / 2.0;
        // the oblique bird's-eye pose, as the Python's two-decimal string
        let r2 = |x: f64| stewie_traverse::nav::py_round(x, 2);
        let pose = json!([r2(c), r2(ext * 0.85), r2(c + ext * 0.6), r2(c), 0.0, r2(c)]);
        let (az, el) = match v["mission_t_s"].as_f64() {
            // one solar authority: the planner's sun at the mission time, kept visible at a grazing elevation
            Some(t) => {
                let (az, el, _) = crate::spec_routes::sun_az_el(-87.45, t, 0.0);
                (Value::from(az), el.max(3.0))
            }
            None => (Value::Null, 25.0),
        };
        let mut shoot = |scene: &str, png: &str| -> Result<PathBuf, ApiError> {
            let out = out_dir.join(png);
            session
                .call("render", &json!({"scene": out_dir.join(scene).display().to_string(), "out": out.display().to_string(),
                                         "layers": "terrain", "size": "1024x768", "pose": pose, "sun_elev": el,
                                         "sun_azim": az}))
                .map_err(|e| failed(e.to_string()))?;
            Ok(out)
        };
        let before = shoot("before_bundle", "win_before.png")?;
        let after = shoot("after_bundle", "win_after.png")?;
        let fig_name = format!("{stem}.png");
        compose(&before, &after, &reports.join(&fig_name)).map_err(failed)?;
        log(st, &head, "api", "render", &fig_name);
        let r = |x: f64, n: usize| stewie_traverse::nav::py_round(x, n);
        Ok(axum::Json(json!({"ok": true, "figure": format!("/reports/{fig_name}"), "cut_vol_m3": r(plan.cut_vol_m3, 2),
                             "fill_vol_m3": r(plan.fill_vol_m3, 2), "cut_kg": round_int(plan.cut_kg),
                             "extent_m": r(ext, 1), "cell_m": r(cs.cell_m(), 2)}))
        .into_response())
    })
    .await
}

/// The render route.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new().route("/render", post(render))
}
