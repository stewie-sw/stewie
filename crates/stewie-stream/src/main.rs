//! `stewie-stream`: serve the viz2 stream on `STEWIE_STREAM_ADDR` (default `0.0.0.0:8900`, the Python's), from the
//! checkout it was built in unless `STEWIE_REPO_DIR` names another.

use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;

use stewie_stream::app::{Config, Stream, router};

#[tokio::main]
async fn main() {
    let repo = std::env::var("STEWIE_REPO_DIR")
        .ok()
        .filter(|d| !d.is_empty())
        .map_or_else(
            || PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."),
            PathBuf::from,
        );
    let cfg = Config::for_checkout(&repo, Arc::new(|k| std::env::var(k).ok()));
    let st = Arc::new(Stream::new(cfg));
    let addr = std::env::var("STEWIE_STREAM_ADDR").unwrap_or_else(|_| "0.0.0.0:8900".to_owned());
    let listener = match tokio::net::TcpListener::bind(&addr).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("stewie-stream: cannot bind {addr}: {e}");
            std::process::exit(1);
        }
    };
    eprintln!("stewie-stream: serving {} on {addr}", repo.display());
    if let Err(e) = axum::serve(
        listener,
        router(st).into_make_service_with_connect_info::<SocketAddr>(),
    )
    .await
    {
        eprintln!("stewie-stream: {e}");
        std::process::exit(1);
    }
}
