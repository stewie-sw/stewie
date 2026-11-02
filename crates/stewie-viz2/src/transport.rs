//! The runtime's authenticated loopback seam (Python `Viz2Runtime`'s socket side): an ephemeral 127.0.0.1 port whose
//! boundary is a per-session random token in a 0600 file. The first line a client sends must carry the token
//! (compared in constant time); the server assigns the `drive` role and a fresh epoch, superseding any earlier
//! session. Commands are newline-delimited JSON objects, bounded to 64 KiB a line; frames go back the same way.
//!
//! An actor thread runs [`Runtime::actor_once`] at the fixed rate on the process's monotonic clock. Connection
//! threads only enqueue commands and drain their own epoch's frames; none touches the world.

use std::collections::{HashMap, VecDeque};
use std::io::{ErrorKind, Read as _, Write as _};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, PoisonError};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde_json::{Value, json};

use crate::runtime::Runtime;

/// The bound on one request line (M-03), about a thousand times a real command.
pub const MAX_LINE_BYTES: usize = 65_536;

type Frames = Arc<Mutex<HashMap<u64, VecDeque<Value>>>>;

/// A served runtime: the listening seam, the actor, and the connections.
#[derive(Debug)]
pub struct Served {
    pub port: u16,
    pub token_path: PathBuf,
    pub runtime: Arc<Mutex<Runtime>>,
    stop: Arc<AtomicBool>,
    threads: Vec<JoinHandle<()>>,
    conns: Arc<Mutex<Vec<JoinHandle<()>>>>,
    /// Set when the actor stopped on an error.
    pub failed: Arc<Mutex<Option<String>>>,
}

/// The process's monotonic clock [s].
fn now(origin: Instant) -> f64 {
    origin.elapsed().as_secs_f64()
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(PoisonError::into_inner)
}

/// 32 random bytes as hex (Python `secrets.token_hex(32)`).
fn token_hex() -> Result<String, String> {
    use std::fmt::Write as _;
    let mut b = [0_u8; 32];
    getrandom::fill(&mut b).map_err(|e| e.to_string())?;
    Ok(b.iter().fold(String::new(), |mut out, x| {
        let _ = write!(out, "{x:02x}");
        out
    }))
}

/// `{port, token, start_xy, world_x0, world_y0, base_cell_m, base_w, base_h}` and a newline, born 0600.
fn write_token_file(path: &Path, port: u16, token: &str, rt: &Runtime) -> Result<(), String> {
    use std::os::unix::fs::{OpenOptionsExt as _, PermissionsExt as _};
    let w = rt.ws.world();
    let base = rt.ws.base();
    // the Python's key order, its json.dumps separators
    let text = format!(
        "{{\"port\": {port}, \"token\": \"{token}\", \"start_xy\": [{}, {}], \"world_x0\": {}, \"world_y0\": {}, \
         \"base_cell_m\": {}, \"base_w\": {}, \"base_h\": {}}}\n",
        repr(rt.start_xy.0)?,
        repr(rt.start_xy.1)?,
        repr(w[0])?,
        repr(w[1])?,
        repr(rt.ws.base_cell_m())?,
        base.width(),
        base.height()
    );
    let _ = std::fs::remove_file(path);
    let mut f = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| format!("{}: {e}", path.display()))?;
    f.write_all(text.as_bytes())
        .and_then(|()| f.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|e| e.to_string())
}

fn repr(x: f64) -> Result<String, String> {
    stewie_twin::pyjson::float_repr(x).map_err(|e| format!("{e:?}"))
}

/// A frame or reply on the wire: JSON and a newline.
fn send_line(conn: &mut TcpStream, v: &Value) -> std::io::Result<()> {
    let mut line = v.to_string();
    line.push('\n');
    conn.write_all(line.as_bytes())
}

/// Read one line within the bound; `None` at the end of the stream or past the bound.
fn read_line(conn: &mut TcpStream) -> std::io::Result<Option<Vec<u8>>> {
    let mut buf = Vec::new();
    let mut chunk = [0_u8; 4096];
    while !buf.contains(&b'\n') {
        let n = conn.read(&mut chunk)?;
        if n == 0 {
            return Ok(None);
        }
        buf.extend_from_slice(&chunk[..n]);
        if buf.len() > MAX_LINE_BYTES {
            return Ok(None);
        }
    }
    let end = buf.iter().position(|b| *b == b'\n').unwrap_or(buf.len());
    buf.truncate(end);
    Ok(Some(buf))
}

impl Served {
    /// Bind the seam, write the token file into the session directory, and start the actor and the acceptor.
    ///
    /// # Errors
    /// A port that cannot be bound, or a token file that cannot be written.
    pub fn start(rt: Runtime, host: &str) -> Result<Self, String> {
        let listener = TcpListener::bind((host, 0)).map_err(|e| e.to_string())?;
        listener.set_nonblocking(true).map_err(|e| e.to_string())?;
        let port = listener.local_addr().map_err(|e| e.to_string())?.port();
        let token = token_hex()?;
        let token_path = rt.session_dir.join("viz2_session.json");
        write_token_file(&token_path, port, &token, &rt)?;
        let period = rt.dt;
        let runtime = Arc::new(Mutex::new(rt));
        let stop = Arc::new(AtomicBool::new(false));
        let frames: Frames = Arc::default();
        let failed: Arc<Mutex<Option<String>>> = Arc::default();
        let origin = Instant::now();
        let actor = {
            let (runtime, stop, frames, failed) = (
                Arc::clone(&runtime),
                Arc::clone(&stop),
                Arc::clone(&frames),
                Arc::clone(&failed),
            );
            std::thread::spawn(move || {
                while !stop.load(Ordering::SeqCst) {
                    let t0 = now(origin);
                    let mut rt = lock(&runtime);
                    let outcome = rt.actor_once(t0);
                    let out = rt.take_outbound();
                    drop(rt);
                    let mut q = lock(&frames);
                    for (epoch, frame) in out {
                        q.entry(epoch).or_default().push_back(frame);
                    }
                    drop(q);
                    match outcome {
                        // a trip skips the rate sleep, as the Python's `continue`
                        Ok(false) => {}
                        Ok(true) => {
                            let rest = period - (now(origin) - t0);
                            if rest > 0.0 {
                                std::thread::sleep(Duration::from_secs_f64(rest));
                            }
                        }
                        Err(e) => {
                            // fail closed: the world cannot step, so no session may continue
                            *lock(&failed) = Some(e);
                            stop.store(true, Ordering::SeqCst);
                        }
                    }
                }
            })
        };
        let conns: Arc<Mutex<Vec<JoinHandle<()>>>> = Arc::default();
        let acceptor = {
            let (runtime, stop, frames, conns) = (
                Arc::clone(&runtime),
                Arc::clone(&stop),
                Arc::clone(&frames),
                Arc::clone(&conns),
            );
            std::thread::spawn(move || {
                while !stop.load(Ordering::SeqCst) {
                    match listener.accept() {
                        Ok((conn, _)) => {
                            let (runtime, stop, frames, token) = (
                                Arc::clone(&runtime),
                                Arc::clone(&stop),
                                Arc::clone(&frames),
                                token.clone(),
                            );
                            let h = std::thread::spawn(move || {
                                serve_conn(conn, &token, &runtime, &frames, &stop, origin);
                            });
                            lock(&conns).push(h);
                        }
                        Err(e) if e.kind() == ErrorKind::WouldBlock => {
                            std::thread::sleep(Duration::from_millis(50));
                        }
                        Err(_) => break,
                    }
                }
            })
        };
        Ok(Self {
            port,
            token_path,
            runtime,
            stop,
            threads: vec![actor, acceptor],
            conns,
            failed,
        })
    }

    /// Stop the actor, the acceptor and every connection, and remove the token file.
    pub fn stop(mut self) {
        self.stop.store(true, Ordering::SeqCst);
        for t in self.threads.drain(..) {
            let _ = t.join();
        }
        for t in lock(&self.conns).drain(..) {
            let _ = t.join();
        }
        let _ = std::fs::remove_file(&self.token_path);
    }
}

/// One connection: the token handshake, a fresh session, then a poll loop that sends this epoch's frames and
/// enqueues the client's commands.
fn serve_conn(
    mut conn: TcpStream,
    token: &str,
    runtime: &Mutex<Runtime>,
    frames: &Mutex<HashMap<u64, VecDeque<Value>>>,
    stop: &AtomicBool,
    origin: Instant,
) {
    use subtle::ConstantTimeEq as _;
    let _ = conn.set_nonblocking(false);
    if conn.set_read_timeout(Some(Duration::from_secs(2))).is_err() {
        return;
    }
    let refuse = |conn: &mut TcpStream, why: &str| {
        let _ = send_line(conn, &json!({"ok": false, "error": why}));
    };
    let line = match read_line(&mut conn) {
        Ok(Some(l)) => l,
        Ok(None) => return refuse(&mut conn, "empty handshake"),
        Err(_) => return,
    };
    let Ok(hello) = serde_json::from_slice::<Value>(&line) else {
        return refuse(&mut conn, "handshake not JSON");
    };
    // a handshake that is JSON but not an object: the Python's handler dies on it, closing without a reply
    let Some(hello) = hello.as_object() else {
        return;
    };
    let authorized = hello
        .get("token")
        .and_then(Value::as_str)
        .is_some_and(|t| bool::from(t.as_bytes().ct_eq(token.as_bytes())));
    if !authorized {
        return refuse(&mut conn, "bad or missing token");
    }
    // the server assigns the role; a client-supplied one is ignored
    let Ok(epoch) = lock(runtime).register_session() else {
        return;
    };
    if send_line(
        &mut conn,
        &json!({"ok": true, "role": "drive", "epoch": epoch, "protocol_version": "1.0"}),
    )
    .is_err()
    {
        return;
    }
    if conn
        .set_read_timeout(Some(Duration::from_millis(50)))
        .is_err()
    {
        return;
    }
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0_u8; 4096];
    while !stop.load(Ordering::SeqCst) {
        let mine: Vec<Value> = lock(frames)
            .get_mut(&epoch)
            .map(|q| q.drain(..).collect())
            .unwrap_or_default();
        for f in &mine {
            if send_line(&mut conn, f).is_err() {
                return;
            }
        }
        match conn.read(&mut chunk) {
            Ok(0) => return,
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(e) if matches!(e.kind(), ErrorKind::WouldBlock | ErrorKind::TimedOut) => {}
            Err(_) => return,
        }
        // M-03: an unterminated flood closes the connection
        if buf.len() > MAX_LINE_BYTES && !buf.contains(&b'\n') {
            return;
        }
        drain_lines(&mut buf, epoch, runtime, origin);
    }
}

/// Enqueue every complete line that is a JSON object; a full mailbox leaves the rest for the next read.
fn drain_lines(buf: &mut Vec<u8>, epoch: u64, runtime: &Mutex<Runtime>, origin: Instant) {
    while let Some(i) = buf.iter().position(|b| *b == b'\n') {
        let line: Vec<u8> = buf.drain(..=i).take(i).collect();
        if line.len() > MAX_LINE_BYTES || line.iter().all(u8::is_ascii_whitespace) {
            continue;
        }
        let Ok(Value::Object(msg)) = serde_json::from_slice::<Value>(&line) else {
            continue;
        };
        if !lock(runtime).enqueue(epoch, now(origin), msg) {
            break;
        }
    }
}
