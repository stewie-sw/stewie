//! RW-51e2: the runtime's loopback seam, live. Its token file and its answer to every handshake equal the Python's
//! (`viz2_transport_cases`, SYNTHETIC handshakes labelled there), and in real time it closes an unterminated flood,
//! counts a superseded session's commands as stale, ignores junk lines, and trips the terminal safe-stop on a
//! stalled link and on an expired command.

use std::io::{BufRead as _, BufReader, Read as _, Write as _};
use std::net::{Shutdown, TcpStream};
use std::os::unix::fs::PermissionsExt as _;
use std::time::{Duration, Instant};

use serde_json::{Value, json};
use stewie_viz2::config::{production_calib, production_setup};
use stewie_viz2::runtime::{Options, Runtime};
use stewie_viz2::transport::Served;

fn serve(tag: &str) -> (Served, std::path::PathBuf) {
    let dir = std::env::temp_dir().join(format!(
        "stewie-viz2-transport-{tag}-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let repo = stewie_oracle::repo_root();
    let rt = Runtime::new(
        &repo.join("samples/lunar_dem/haworth_sfs_2km_1m"),
        &dir,
        Options::default(),
        production_setup("moon").unwrap(),
        production_calib("small", &repo.join("deploy/planner.json")).unwrap(),
    )
    .unwrap();
    (Served::start(rt, "127.0.0.1").unwrap(), dir)
}

fn token(s: &Served) -> String {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&s.token_path).unwrap()).unwrap();
    v["token"].as_str().unwrap().to_owned()
}

/// Send `payload` (closing the write side when asked) and read the first reply line ("" when closed without one).
fn exchange(port: u16, payload: &[u8], close_write: bool) -> (String, Option<Value>) {
    let mut c = TcpStream::connect(("127.0.0.1", port)).unwrap();
    c.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    c.write_all(payload).unwrap();
    if close_write {
        c.shutdown(Shutdown::Write).unwrap();
    }
    let mut r = BufReader::new(c);
    let mut line = String::new();
    r.read_line(&mut line).unwrap();
    let first = if line.contains("\"ok\":true") {
        let mut next = String::new();
        r.read_line(&mut next).unwrap();
        Some(serde_json::from_str(&next).unwrap())
    } else {
        None
    };
    (line.trim_end().to_owned(), first)
}

#[test]
fn the_token_file_and_every_handshake_answer_equal_the_pythons() {
    let fx = stewie_oracle::load("viz2_transport_cases").unwrap().payload;
    let (s, dir) = serve("handshake");
    let meta = std::fs::metadata(&s.token_path).unwrap();
    assert_eq!(
        u64::from(meta.permissions().mode() & 0o777),
        fx["token_file"]["mode"].as_u64().unwrap()
    );
    let text = std::fs::read_to_string(&s.token_path).unwrap();
    assert!(text.ends_with('\n') && fx["token_file"]["ends_with_newline"] == true);
    // the Python's key order, read off the text
    let keys: Vec<&str> = fx["token_file"]["keys"]
        .as_array()
        .unwrap()
        .iter()
        .map(|k| k.as_str().unwrap())
        .collect();
    let positions: Vec<usize> = keys
        .iter()
        .map(|k| text.find(&format!("\"{k}\":")).unwrap())
        .collect();
    assert!(positions.windows(2).all(|w| w[0] < w[1]), "{text}");
    let tok: Value = serde_json::from_str(&text).unwrap();
    assert_eq!(tok.as_object().unwrap().len(), keys.len());
    for (k, v) in fx["token_file"]["values"].as_object().unwrap() {
        assert_eq!(&tok[k], v, "{k}");
    }
    let t = token(&s);
    assert_eq!(
        t.len() as u64,
        fx["token_file"]["token_hex_len"].as_u64().unwrap()
    );
    assert!(t.bytes().all(|b| b.is_ascii_hexdigit()) && tok["port"] == json!(s.port));
    for c in fx["replies"].as_array().unwrap() {
        let case = c["case"].as_str().unwrap();
        let payload: Vec<u8> = match case {
            "eof" => vec![],
            "not_json" => b"not json\n".to_vec(),
            "wrong_token" => b"{\"token\": \"wrong\"}\n".to_vec(),
            "no_token" => b"{\"role\": \"admin\"}\n".to_vec(),
            "json_list" => b"[1]\n".to_vec(),
            _ => format!("{}\n", json!({"token": t, "role": "admin"})).into_bytes(),
        };
        let (line, first) = exchange(s.port, &payload, case == "eof");
        let want = c["line"].as_str().unwrap();
        if want.is_empty() {
            assert_eq!(line, "", "{case}: closed without a reply");
        } else {
            let got: Value = serde_json::from_str(&line).unwrap();
            assert_eq!(got, serde_json::from_str::<Value>(want).unwrap(), "{case}");
        }
        if let Some(w) = c["first_frame"].as_object() {
            let f = first.unwrap();
            let sorted = |v: &Value| {
                let mut k: Vec<String> = v.as_object().unwrap().keys().cloned().collect();
                k.sort();
                json!(k)
            };
            assert_eq!(sorted(&f), w["keys"]);
            assert_eq!(sorted(&f["payload"]), w["payload_keys"]);
            assert_eq!(
                (&f["payload"]["type"], &f["payload"]["keyframe"]),
                (&w["type"], &w["keyframe"])
            );
            assert_eq!((&f["seq"], &f["v"]), (&w["seq"], &w["v"]));
        }
    }
    let path = s.token_path.clone();
    s.stop();
    assert!(!path.exists(), "the token file is removed on stop");
    std::fs::remove_dir_all(&dir).unwrap();
}

/// A driving client: handshake, then frames read line by line.
struct Client {
    w: TcpStream,
    r: BufReader<TcpStream>,
    epoch: u64,
}

impl Client {
    fn connect(s: &Served) -> Self {
        let mut w = TcpStream::connect(("127.0.0.1", s.port)).unwrap();
        w.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
        writeln!(w, "{}", json!({"token": token(s)})).unwrap();
        let mut r = BufReader::new(w.try_clone().unwrap());
        let mut hello = String::new();
        r.read_line(&mut hello).unwrap();
        let hello: Value = serde_json::from_str(&hello).unwrap();
        Self {
            w,
            r,
            epoch: hello["epoch"].as_u64().unwrap(),
        }
    }

    fn send(&mut self, v: &Value) {
        writeln!(self.w, "{v}").unwrap();
    }

    /// The next frame, acking telemetry when asked; `None` when the connection closed.
    fn frame(&mut self, ack: bool) -> Option<Value> {
        let mut line = String::new();
        if self.r.read_line(&mut line).ok()? == 0 {
            return None;
        }
        let f: Value = serde_json::from_str(&line).unwrap();
        if ack && f.get("payload").is_some() {
            let seq = f["seq"].clone();
            self.send(&json!({"cmd": "ack", "seq": seq}));
        }
        Some(f)
    }

    /// Read until a safe-stop notice; the reason, within `limit`.
    fn until_safe_stop(&mut self, ack: bool, limit: Duration) -> String {
        let t0 = Instant::now();
        while t0.elapsed() < limit {
            let f = self.frame(ack).expect("connection open");
            if f["type"] == "safe_stop" {
                assert_eq!(f["epoch"], json!(self.epoch));
                return f["reason"].as_str().unwrap().to_owned();
            }
        }
        panic!("no safe-stop within {limit:?}");
    }
}

#[test]
fn the_seam_holds_its_bounds_in_real_time() {
    let (s, dir) = serve("live");
    // an unterminated flood past the line bound closes the connection
    let mut a = Client::connect(&s);
    a.w.write_all(&vec![b'x'; 70_000]).unwrap();
    // the server closes it: an end of stream, or a reset when the unread flood was still in its buffer; never a
    // read timeout (a connection left open)
    let mut rest = Vec::new();
    match a.r.read_to_end(&mut rest) {
        Ok(_) => {}
        Err(e) => assert_eq!(e.kind(), std::io::ErrorKind::ConnectionReset, "{e}"),
    }
    let stale_before = s.runtime.lock().unwrap().rejected_stale;
    // a newer session supersedes an older one: the old one's commands are counted stale, never applied
    let mut old = Client::connect(&s);
    let mut new = Client::connect(&s);
    assert_eq!(new.epoch, old.epoch + 1);
    old.send(&json!({"cmd": "twist", "v": 0.3, "omega": 0.0}));
    // junk, blank and non-object lines are ignored
    new.w
        .write_all(b"\n   \nnot json\n[1, 2]\n\"twist\"\n")
        .unwrap();
    new.send(&json!({"cmd": "twist", "v": 0.2, "omega": 0.0}));
    for _ in 0..10 {
        new.frame(true).unwrap();
    }
    let rt = s.runtime.lock().unwrap();
    assert_eq!(
        rt.rejected_stale,
        stale_before + 1,
        "the superseded session's twist"
    );
    assert_eq!(rt.rejected_bounds, 0);
    drop(rt);
    // the twist is not refreshed: it expires after the 2 s deadline and holds the rover
    assert_eq!(
        new.until_safe_stop(true, Duration::from_secs(4)),
        "command_expired"
    );
    // a fresh session that stops acking: the link-stall deadman trips
    let mut stall = Client::connect(&s);
    assert_eq!(
        stall.until_safe_stop(false, Duration::from_secs(4)),
        "deadman_link_stall"
    );
    assert!(s.runtime.lock().unwrap().safe_stopped());
    assert!(s.failed.lock().unwrap().is_none());
    s.stop();
    std::fs::remove_dir_all(&dir).unwrap();
}
