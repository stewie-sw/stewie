//! `stewie-server`: the Rust STEWIE server (RW-55). Configuration is the environment (`STEWIE_*`); the server
//! refuses to start without an automation key or a data directory, and refuses a non-loopback bind unless TLS is
//! terminated in front of it (`STEWIE_TLS_TERMINATED=1`), as the Python's S-04 guard.
//!
//! Usage: `stewie-server [--host 127.0.0.1] [--port 8770]`

use std::net::SocketAddr;
use std::sync::Arc;

use stewie_server::app::{AppState, router};
use stewie_server::{OsEntropy, SystemClock};

static CLOCK: SystemClock = SystemClock;
static ENTROPY: OsEntropy = OsEntropy;

fn args() -> Result<(String, u16), String> {
    let (mut host, mut port) = ("127.0.0.1".to_owned(), 8770_u16);
    let mut it = std::env::args().skip(1);
    while let Some(a) = it.next() {
        match a.as_str() {
            "--host" => host = it.next().ok_or("--host needs a value")?,
            "--port" => {
                port = it
                    .next()
                    .ok_or("--port needs a value")?
                    .parse()
                    .map_err(|e| format!("--port: {e}"))?;
            }
            "--version" => {
                println!("stewie-server {}", env!("CARGO_PKG_VERSION"));
                std::process::exit(0);
            }
            other => {
                return Err(format!(
                    "unknown argument {other:?} (usage: stewie-server [--host H] [--port P])"
                ));
            }
        }
    }
    Ok((host, port))
}

#[tokio::main]
async fn main() {
    let fail = |m: String| -> ! {
        eprintln!("stewie-server: {m}");
        std::process::exit(2)
    };
    let (host, port) = args().unwrap_or_else(|e| fail(e));
    let state = AppState::from_env(&|k| std::env::var(k).ok(), &CLOCK, &ENTROPY)
        .unwrap_or_else(|e| fail(e))
        .with_environment(std::env::vars());
    let loopback = matches!(
        host.trim().to_lowercase().as_str(),
        "127.0.0.1" | "::1" | "localhost"
    );
    if !loopback && !state.cfg.tls_terminated {
        fail(format!(
            "refusing public bind {host:?} without TLS: set STEWIE_TLS_TERMINATED=1 once HTTPS is terminated in front \
             of the server, or bind 127.0.0.1"
        ));
    }
    let addr = format!("{host}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr)
        .await
        .unwrap_or_else(|e| fail(format!("bind {addr}: {e}")));
    eprintln!(
        "stewie-server {} listening on http://{addr}/",
        env!("CARGO_PKG_VERSION")
    );
    let app = router(Arc::new(state)).into_make_service_with_connect_info::<SocketAddr>();
    if let Err(e) = axum::serve(listener, app).await {
        fail(format!("serve: {e}"));
    }
}
