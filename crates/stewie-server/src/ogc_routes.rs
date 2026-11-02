//! The OGC WMS 1.3.0 service over the globe drapes (RW-55b17c; Python `routers.ogc`, ArcGIS-G1 #248): any `QGIS` or
//! `ArcGIS` client can read the layers. `GetCapabilities` advertises the drape kinds and the site's selenographic
//! extent; `GetMap` crops and resamples a drape to the requested `BBOX`, `WIDTH` and `HEIGHT` in `CRS:84` (lon, lat)
//! or `EPSG:4326` / `IAU_2015:30100` (lat, lon). Public and per-IP rate-limited with the globe drapes.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Query, Request, State};
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;

use crate::app::{ApiError, AppState, Head, blocking};
use crate::dem_routes::{Missing, bundle};
use crate::layer_routes::{GLOBE_KINDS, drape, world_bounds};
use crate::operators::py_repr;
use crate::raster::png_rgba;

/// The Moon (2015) ocentric sphere: the drape's geographic CRS.
const LUNAR_GEOG: &str = "IAU_2015:30100";
/// The per-dimension `GetMap` bound and the total pixel budget (#288).
const MAX_PX: i64 = 4096;
const MAX_TOTAL_PX: i64 = 2048 * 2048;

/// A WMS `ServiceExceptionReport`.
fn exception(msg: &str, code: &str, status: StatusCode) -> Response {
    let body = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<ServiceExceptionReport version=\"1.3.0\" \
         xmlns=\"http://www.opengis.net/ogc\">\n  <ServiceException code=\"{}\">{}</ServiceException>\n\
         </ServiceExceptionReport>\n",
        escape(code),
        escape(msg)
    );
    (
        status,
        [(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/vnd.ogc.se_xml"),
        )],
        body,
    )
        .into_response()
}

/// Python `html.escape` (quotes included).
fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&#x27;")
}

/// The request's parameters as the Python's `dict(request.query_params)`: each key at its first position, holding
/// its last value.
fn params(q: &[(String, String)]) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    for (k, v) in q {
        match out.iter_mut().find(|(x, _)| x == k) {
            Some(e) => e.1.clone_from(v),
            None => out.push((k.clone(), v.clone())),
        }
    }
    out
}

/// A case-insensitive key lookup (WMS keys are case-insensitive): the first matching key's value.
fn ci<'a>(p: &'a [(String, String)], key: &str) -> Option<&'a str> {
    p.iter()
        .find(|(k, _)| k.to_lowercase() == key.to_lowercase())
        .map(|(_, v)| v.as_str())
}

/// Python `int(s)` for a decimal string: surrounding whitespace, a sign, digits with single underscores between.
fn py_int(s: &str) -> Option<i64> {
    let t = s.trim();
    let digits = t.strip_prefix(['+', '-']).unwrap_or(t);
    let ok = !digits.is_empty()
        && !digits.starts_with('_')
        && !digits.ends_with('_')
        && !digits.contains("__")
        && digits.chars().all(|c| c.is_ascii_digit() || c == '_');
    ok.then(|| t.replace('_', "").parse().ok()).flatten()
}

/// Python `float(s)`: surrounding whitespace, `inf` / `nan` in any case. shortcut: no `_` digit separators, which no
/// WMS client sends.
fn py_float(s: &str) -> Option<f64> {
    let t = s.trim();
    let bare = t.trim_start_matches(['+', '-']).to_lowercase();
    if matches!(bare.as_str(), "inf" | "infinity" | "nan")
        || t.chars()
            .all(|c| !c.is_alphabetic() || c == 'e' || c == 'E')
    {
        t.parse().ok()
    } else {
        None
    }
}

/// numpy `linspace`: one sample is the start; the last of several exactly the stop.
#[allow(clippy::cast_precision_loss)] // a pixel count
fn linspace(start: f64, stop: f64, n: usize) -> Vec<f64> {
    if n == 1 {
        vec![start]
    } else {
        crate::dem_routes::linspace(start, stop, n)
    }
}

/// The endpoint's own URL for the capabilities' links, through a reverse proxy's forwarded scheme and host.
fn self_url(h: &axum::http::HeaderMap) -> String {
    let get = |k: &str| h.get(k).and_then(|v| v.to_str().ok());
    match (
        get("x-forwarded-proto"),
        get("x-forwarded-host").or_else(|| get("host")),
    ) {
        (Some(proto), Some(host)) => format!("{proto}://{host}/ogc/wms"),
        (_, host) => format!("http://{}/ogc/wms", host.unwrap_or("localhost")),
    }
}

#[allow(clippy::many_single_char_names)] // the Python's w, e, s, n of its box
fn capabilities(
    st: &AppState,
    p: &[(String, String)],
    headers: &axum::http::HeaderMap,
) -> Response {
    let site = ci(p, "site").filter(|s| !s.is_empty()).unwrap_or("haworth");
    let extent = match bundle(st, site)
        .map_err(|m| match m {
            Missing::Unknown(e) | Missing::NotImported(e) => e,
        })
        .and_then(|dir| world_bounds(&dir).map_err(|e| e.1))
    {
        Ok(e) => e,
        Err(e) => {
            return exception(
                &format!("unknown site {}: {e}", py_repr(site)),
                "InvalidParameterValue",
                StatusCode::NOT_FOUND,
            );
        }
    };
    let b = crate::globe::geographic_bbox(&st.terrain.projection(), extent);
    let (w, e, s, n) = (b.west, b.east, b.south, b.north);
    let href = escape(&self_url(headers));
    let layer = |kind: &str| {
        format!(
            "      <Layer queryable=\"0\">\n        <Name>{kind}</Name>\n        <Title>STEWIE {kind} (globe drape)</Title>\n\
             \x20       <CRS>CRS:84</CRS><CRS>EPSG:4326</CRS><CRS>{LUNAR_GEOG}</CRS>\n        <EX_GeographicBoundingBox>\n\
             \x20         <westBoundLongitude>{w:.6}</westBoundLongitude>\n          <eastBoundLongitude>{e:.6}</eastBoundLongitude>\n\
             \x20         <southBoundLatitude>{s:.6}</southBoundLatitude>\n          <northBoundLatitude>{n:.6}</northBoundLatitude>\n\
             \x20       </EX_GeographicBoundingBox>\n        <BoundingBox CRS=\"CRS:84\" minx=\"{w:.6}\" miny=\"{s:.6}\" \
             maxx=\"{e:.6}\" maxy=\"{n:.6}\"/>\n      </Layer>\n"
        )
    };
    let layers: String = GLOBE_KINDS.iter().map(|k| layer(k)).collect();
    let xml = format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<WMS_Capabilities version=\"1.3.0\" xmlns=\"http://www.opengis.net/wms\" \
         xmlns:xlink=\"http://www.w3.org/1999/xlink\">\n  <Service>\n    <Name>WMS</Name>\n    <Title>STEWIE lunar globe layers</Title>\n\
         \x20   <Abstract>Selenographic drape of the STEWIE digital-twin globe layers (south-polar Moon, IAU_2015:30100). \
         Coordinates are SELENOGRAPHIC lat/lon; CRS:84 and the IAU lunar CRS are authoritative. EPSG:4326 is offered only as \
         a numeric (lat/lon-degree) convenience alias for clients that require it -- the datum is the Moon, NOT WGS84 Earth. \
         Base-map data; SIM/analysis products are separate.</Abstract>\n    <OnlineResource xlink:type=\"simple\" xlink:href=\"{href}\"/>\n\
         \x20 </Service>\n  <Capability>\n    <Request>\n      <GetCapabilities><Format>text/xml</Format>\n\
         \x20       <DCPType><HTTP><Get><OnlineResource xlink:type=\"simple\" xlink:href=\"{href}\"/></Get></HTTP></DCPType>\n\
         \x20     </GetCapabilities>\n      <GetMap><Format>image/png</Format>\n\
         \x20       <DCPType><HTTP><Get><OnlineResource xlink:type=\"simple\" xlink:href=\"{href}\"/></Get></HTTP></DCPType>\n\
         \x20     </GetMap>\n    </Request>\n    <Exception><Format>XML</Format></Exception>\n    <Layer>\n\
         \x20     <Title>STEWIE globe layers</Title>\n      <CRS>CRS:84</CRS><CRS>EPSG:4326</CRS><CRS>{LUNAR_GEOG}</CRS>\n\
         \x20     <EX_GeographicBoundingBox>\n        <westBoundLongitude>{w:.6}</westBoundLongitude>\n\
         \x20       <eastBoundLongitude>{e:.6}</eastBoundLongitude>\n        <southBoundLatitude>{s:.6}</southBoundLatitude>\n\
         \x20       <northBoundLatitude>{n:.6}</northBoundLatitude>\n      </EX_GeographicBoundingBox>\n{layers}    </Layer>\n\
         \x20 </Capability>\n</WMS_Capabilities>\n"
    );
    (
        [(
            header::CONTENT_TYPE,
            HeaderValue::from_static("text/xml; charset=utf-8"),
        )],
        xml,
    )
        .into_response()
}

#[allow(
    clippy::too_many_lines,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)] // the Python's checks in its order, then the crop; pixel indices
fn getmap(st: &AppState, p: &[(String, String)]) -> Result<Response, ApiError> {
    let bad = |m: &str| {
        Ok(exception(
            m,
            "InvalidParameterValue",
            StatusCode::BAD_REQUEST,
        ))
    };
    if let Some(ver) = ci(p, "VERSION").filter(|v| !v.is_empty() && *v != "1.3.0") {
        return bad(&format!(
            "version {} not supported; this service is WMS 1.3.0",
            py_repr(ver)
        ));
    }
    let layers: Vec<&str> = ci(p, "LAYERS")
        .unwrap_or("")
        .split(',')
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .collect();
    if layers.len() > 1 {
        return bad("multiple LAYERS not supported; request one layer per GetMap");
    }
    let kind = layers.first().copied().unwrap_or("");
    if !GLOBE_KINDS.contains(&kind) {
        return Ok(exception(
            &format!("layer {} is not defined", py_repr(kind)),
            "LayerNotDefined",
            StatusCode::BAD_REQUEST,
        ));
    }
    let fmt = ci(p, "FORMAT")
        .filter(|f| !f.is_empty())
        .unwrap_or("image/png")
        .to_lowercase();
    if fmt != "image/png" && fmt != "image/png; mode=8bit" {
        return Ok(exception(
            &format!("format {} not supported; only image/png", py_repr(&fmt)),
            "InvalidFormat",
            StatusCode::BAD_REQUEST,
        ));
    }
    let (Some(width), Some(height)) = (
        py_int(ci(p, "WIDTH").unwrap_or("")),
        py_int(ci(p, "HEIGHT").unwrap_or("")),
    ) else {
        return bad("WIDTH and HEIGHT must be integers");
    };
    if !((1..=MAX_PX).contains(&width) && (1..=MAX_PX).contains(&height)) {
        return bad(&format!("WIDTH/HEIGHT must be in [1,{MAX_PX}]"));
    }
    if width * height > MAX_TOTAL_PX {
        return bad(&format!(
            "WIDTH*HEIGHT must be <= {MAX_TOTAL_PX} pixels (got {width}x{height}={})",
            width * height
        ));
    }
    let crs = ci(p, "CRS")
        .filter(|c| !c.is_empty())
        .unwrap_or("CRS:84")
        .to_uppercase()
        .replace("OGC:", "");
    let v: Option<Vec<f64>> = ci(p, "BBOX")
        .unwrap_or("")
        .split(',')
        .map(py_float)
        .collect();
    let Some(v) = v.filter(|v| v.len() == 4) else {
        return bad("BBOX must be four comma-separated numbers");
    };
    // CRS:84 is lon, lat; EPSG:4326 and the lunar geographic CRS are lat, lon in WMS 1.3.0
    let (west, south, east, north) = if crs.replace(':', "").contains("CRS84") {
        (v[0], v[1], v[2], v[3])
    } else if crs.contains("4326") || crs.contains("30100") {
        (v[1], v[0], v[3], v[2])
    } else {
        return Ok(exception(
            &format!(
                "CRS {} not supported; use CRS:84, EPSG:4326, or {LUNAR_GEOG}",
                py_repr(&crs)
            ),
            "InvalidCRS",
            StatusCode::BAD_REQUEST,
        ));
    };
    if !(east > west && north > south) {
        return bad("degenerate BBOX (need west<east and south<north)");
    }
    let site = ci(p, "site").filter(|s| !s.is_empty()).unwrap_or("haworth");
    let unavailable = |e: &str| {
        Ok(exception(
            &format!(
                "layer {} unavailable for site {}: {e}",
                py_repr(kind),
                py_repr(site)
            ),
            "LayerNotDefined",
            StatusCode::NOT_FOUND,
        ))
    };
    let dir = match bundle(st, site) {
        Ok(d) => d,
        Err(Missing::Unknown(e) | Missing::NotImported(e)) => return unavailable(&e),
    };
    let extent = world_bounds(&dir)?;
    // the drape at the route defaults (the Python's `render_globe(kind, site=site)`)
    let src = drape(st, kind, site, (90.0, 6.0), "39ff14", (30.0, 0), extent)?;
    let ((rgba, sw, sh, sb), _) = &*src;
    let (width, height) = (width as usize, height as usize);
    let lons = linspace(west, east, width);
    let lats = linspace(north, south, height);
    let (cmax, rmax) = ((sw - 1) as f64, (sh - 1) as f64);
    let mut out = vec![0u8; width * height * 4];
    for (r, &lat) in lats.iter().enumerate() {
        for (c, &lon) in lons.iter().enumerate() {
            let col = (lon - sb.west) / (sb.east - sb.west) * cmax;
            let row = (sb.north - lat) / (sb.north - sb.south) * rmax;
            if (0.0..=cmax).contains(&col) && (0.0..=rmax).contains(&row) {
                let at = (row.round_ties_even() as usize * sw + col.round_ties_even() as usize) * 4;
                out[(r * width + c) * 4..(r * width + c) * 4 + 4]
                    .copy_from_slice(&rgba[at..at + 4]);
            }
        }
    }
    let png = png_rgba(&out, width, height)
        .map_err(|e| crate::app::err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
    Ok((
        [(header::CONTENT_TYPE, HeaderValue::from_static("image/png"))],
        png,
    )
        .into_response())
}

/// The WMS endpoint (public, per-IP rate-limited with the globe drapes).
async fn wms(
    State(st): State<Arc<AppState>>,
    Query(q): Query<Vec<(String, String)>>,
    req: Request,
) -> Response {
    let h = Head::of(&req);
    let headers = req.headers().clone();
    blocking(st, move |st| {
        st.globe_quota(&h)?;
        let p = params(&q);
        let request = ci(&p, "REQUEST").unwrap_or("").to_lowercase();
        let svc = ci(&p, "SERVICE")
            .filter(|s| !s.is_empty())
            .unwrap_or("WMS")
            .to_uppercase();
        if svc != "WMS" {
            return Ok(exception(
                &format!(
                    "unsupported SERVICE {}; this endpoint is WMS",
                    py_repr(&svc)
                ),
                "InvalidParameterValue",
                StatusCode::BAD_REQUEST,
            ));
        }
        match request.as_str() {
            "getcapabilities" => Ok(capabilities(st, &p, &headers)),
            "getmap" => getmap(st, &p),
            _ => Ok(exception(
                &format!(
                    "unsupported REQUEST {}; expected GetCapabilities or GetMap",
                    ci(&p, "REQUEST").map_or_else(|| "None".to_owned(), py_repr)
                ),
                "OperationNotSupported",
                StatusCode::BAD_REQUEST,
            )),
        }
    })
    .await
}

/// The OGC routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new().route("/ogc/wms", get(wms))
}
