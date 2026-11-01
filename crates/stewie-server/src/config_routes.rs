//! Configuration reads (RW-55b7d/e; Python `routers.config`): the site registry, the configuration overlay state
//! and the Config pane's one-call summary. The N15 overlay is never applied here: the Rust compiles its constants in
//! and refuses to start when one is configured (D-R135), so `applied` is empty and `config_file` null.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::{Map, Value, json};

use crate::app::{ApiError, AppState, Head, blocking, err, require_auth};

/// The site registry, in its own order (any authenticated caller).
async fn sites(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let rows = st
            .terrain
            .site_rows()
            .map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        Ok(axum::Json(json!({"ok": true, "sites": rows})).into_response())
    })
    .await
}

/// Python `int(s)` then `float(s)` digits: `_` only between two digits.
fn py_digits_ok(s: &str) -> bool {
    let b = s.as_bytes();
    b.iter().enumerate().all(|(i, &c)| {
        c != b'_'
            || (i > 0 && i + 1 < b.len() && b[i - 1].is_ascii_digit() && b[i + 1].is_ascii_digit())
    })
}

/// An overlay value as the Python's `_coerce` reads it: `true`/`false`, else `int`, else `float`, else the stripped
/// text. A non-finite float is an error, as the Python's JSON response refuses it.
fn py_coerce(v: &str) -> Result<Value, String> {
    let s = v.trim();
    match s.to_lowercase().as_str() {
        "true" => return Ok(Value::Bool(true)),
        "false" => return Ok(Value::Bool(false)),
        _ => {}
    }
    if !s.is_empty() && py_digits_ok(s) {
        let plain = s.replace('_', "");
        let body = plain.strip_prefix(['+', '-']).unwrap_or(&plain);
        if !body.is_empty() && body.bytes().all(|c| c.is_ascii_digit()) {
            // shortcut: an integer beyond 64 bits reads as a float, where the Python keeps it exact; widen if one appears
            if let Ok(i) = plain.parse::<i64>() {
                return Ok(json!(i));
            }
            if let Ok(u) = plain.trim_start_matches('+').parse::<u64>() {
                return Ok(json!(u));
            }
        }
        if let Ok(x) = plain.parse::<f64>() {
            return serde_json::Number::from_f64(x)
                .map(Value::Number)
                .ok_or_else(|| format!("a non-finite override value {s:?}"));
        }
    }
    Ok(Value::String(s.to_owned()))
}

/// A secret-bearing name (the Python's tests on the upper-cased key).
fn secret_name(k: &str, words: &[&str]) -> bool {
    let up = k.to_uppercase();
    words.iter().any(|w| up.contains(w))
}

/// The Python's `_redact_secrets`: a secret-named key's value, or any text holding the automation key, is redacted.
fn redact(v: Value, key: &str) -> Value {
    match v {
        Value::Object(m) => Value::Object(
            m.into_iter()
                .map(|(k, x)| {
                    let x = if secret_name(&k, &["KEY", "TOKEN", "SECRET"]) {
                        json!("[REDACTED]")
                    } else {
                        redact(x, key)
                    };
                    (k, x)
                })
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.into_iter().map(|x| redact(x, key)).collect()),
        Value::String(t) if !key.is_empty() && t.contains(key) => json!("[REDACTED]"),
        other => other,
    }
}

/// The Python's `config.describe()` after `_redact_secrets`: the overrides are the `STEWIE_*` environment (redacted
/// by name at the source), nothing is applied and no overlay file is read (D-R135).
fn describe(st: &AppState) -> Result<Value, ApiError> {
    let mut overrides = Map::new();
    for (k, v) in &st.environment {
        let name = &k["STEWIE_".len()..];
        let value = if secret_name(name, &["KEY", "TOKEN", "SECRET", "PASSWORD"]) {
            json!("[REDACTED]")
        } else {
            py_coerce(v).map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?
        };
        overrides.insert(name.to_owned(), value);
    }
    let doc = json!({"config_file": null, "overrides": overrides, "applied": {},
                     "data_dir": st.cfg.data_dir.display().to_string()});
    Ok(redact(doc, &st.cfg.api_key))
}

/// The runtime configuration overlay state (any authenticated caller).
async fn config(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let mut body =
            json!({"ok": true, "identity": {"on_builtin_defaults": on_builtin_defaults(st)}});
        if let (Some(b), Value::Object(d)) = (body.as_object_mut(), describe(st)?) {
            b.extend(d);
        }
        Ok(axum::Json(body).into_response())
    })
    .await
}

/// Identity running on built-in defaults: no operator allowlist and no director list (BP-04).
fn on_builtin_defaults(st: &AppState) -> bool {
    st.cfg.allowed.is_empty() && st.cfg.directors.is_none()
}

/// The Config pane's one-call state: server, auth flags (never the key), data holdings and the overlay (any
/// authenticated caller). SPICE is not available: the Rust sun is the bundled DE440 pack (D-R131).
async fn config_full(State(st): State<Arc<AppState>>, req: Request) -> Response {
    let h = Head::of(&req);
    blocking(st, move |st| {
        require_auth(st, &h)?;
        let rows = st.terrain.site_rows().map_err(|e| err(StatusCode::INTERNAL_SERVER_ERROR, e))?;
        #[allow(clippy::case_sensitive_file_extension_comparisons)] // the Python's `endswith(".npz")`
        let snapshots = std::fs::read_dir(st.cfg.data_dir.join("snapshots")).map_or(0, |rd| {
            rd.filter_map(Result::ok)
                .filter(|e| e.file_name().to_str().is_some_and(|n| n.ends_with(".npz")))
                .count()
        });
        Ok(axum::Json(json!({
            "ok": true,
            "server": {"version": env!("CARGO_PKG_VERSION"), "data_dir": st.cfg.data_dir.display().to_string(),
                       "backup_dir": st.settings.backup_dir.clone().unwrap_or_else(|| "(data_dir)/replica".to_owned())},
            "auth": {"api_key_set": !st.cfg.api_key.is_empty(), "operator_login": st.settings.operator_login,
                     "trust_tailscale": st.cfg.trust_tailscale},
            "data": {"sites_total": rows.len(), "sites_imported": rows.iter().filter(|r| r["imported"] == true).count(),
                     "spice_available": false, "twin_snapshots": snapshots},
            "overlay": describe(st)?,
        }))
        .into_response())
    })
    .await
}

/// The configuration routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new()
        .route("/sites", get(sites))
        .route("/config", get(config))
        .route("/config/full", get(config_full))
}

#[cfg(test)]
mod tests {
    use super::py_coerce;
    use serde_json::json;

    #[test]
    fn overlay_values_coerce_as_the_python_reads_them() {
        // SYNTHETIC values, each against Python's `_coerce` (bool, then int, then float, else stripped text)
        for (v, want) in [
            (" True ", json!(true)),
            ("false", json!(false)),
            ("1_000", json!(1000)),
            ("+5", json!(5)),
            ("-007", json!(-7)),
            ("1e3", json!(1000.0)),
            ("1_0.5", json!(10.5)),
            (".5", json!(0.5)),
            (
                "18446744073709551615",
                json!(18_446_744_073_709_551_615_u64),
            ),
            ("1__0", json!("1__0")),
            ("_1", json!("_1")),
            ("1_", json!("1_")),
            ("0x10", json!("0x10")),
            ("  plain text ", json!("plain text")),
            ("", json!("")),
        ] {
            assert_eq!(py_coerce(v).unwrap(), want, "{v:?}");
        }
        for v in ["nan", "inf", "-Infinity"] {
            assert!(py_coerce(v).is_err(), "{v:?}");
        }
    }
}
