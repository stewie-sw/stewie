//! Configuration reads (RW-55b7d; Python `routers.config`): the site registry.

use std::sync::Arc;

use axum::Router;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use serde_json::json;

use crate::app::{AppState, Head, blocking, err, require_auth};

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

/// The configuration routes.
pub fn routes() -> Router<Arc<AppState>> {
    Router::new().route("/sites", get(sites))
}
