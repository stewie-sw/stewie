//! RW-55a1 against the Python oracle (`auth_cases`): the same scripted scenario through the account store and the
//! session layer, with the oracle's pinned clock and seeded byte stream, must give every step's result or error,
//! the final account and revocation stores, and byte-identical session tokens (so live Python sessions verify in
//! Rust after the cutover). The clock, the byte stream, the emails, passwords and keys are SYNTHETIC test inputs.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_server::auth::{Auth, AuthConfig, peer_trusted};
use stewie_server::operators::{Store, validate_email};
use stewie_server::services::{AUDIT_DEFAULT_MAX_BYTES, Ledger};
use stewie_server::{Clock, Entropy};

/// SYNTHETIC: a settable clock.
struct PinnedClock(Mutex<f64>);

impl Clock for PinnedClock {
    fn now(&self) -> f64 {
        *self.0.lock().unwrap()
    }
}

impl PinnedClock {
    fn advance(&self, s: f64) {
        *self.0.lock().unwrap() += s;
    }
}

/// SYNTHETIC: the oracle's deterministic stream, sha256(seed || counter) blocks, the tail of the last block dropped.
struct SeededBytes {
    seed: [u8; 32],
    n: Mutex<u64>,
}

impl Entropy for SeededBytes {
    fn fill(&self, buf: &mut [u8]) {
        let mut out = Vec::new();
        let mut n = self.n.lock().unwrap();
        while out.len() < buf.len() {
            let mut h = Sha256::new();
            h.update(self.seed);
            h.update(n.to_be_bytes());
            out.extend_from_slice(&h.finalize());
            *n += 1;
        }
        buf.copy_from_slice(&out[..buf.len()]);
    }
}

fn step<T: Into<Value>, E: ToString>(
    steps: &mut Vec<Value>,
    op: &str,
    args: Value,
    r: Result<T, E>,
) {
    let mut out = match r {
        Ok(v) => json!({"ok": v.into()}),
        Err(e) => json!({"error": e.to_string()}),
    };
    out["op"] = json!(op);
    out["args"] = args;
    steps.push(out);
}

fn opt(s: Option<String>) -> Value {
    s.map_or(Value::Null, Value::from)
}

#[test]
#[allow(clippy::too_many_lines, clippy::many_single_char_names)] // one scenario, step for step as the oracle's; the tokens keep its keys a/z/o/d
fn the_python_auth_scenario_replays_exactly() {
    let fx = stewie_oracle::load("auth_cases").unwrap().payload;
    let dir: PathBuf =
        std::env::temp_dir().join(format!("stewie-auth-oracle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let mut env: HashMap<String, String> = fx["env"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().unwrap().to_owned()))
        .collect();
    env.insert("STEWIE_DATA_DIR".into(), dir.display().to_string());
    let cfg_of =
        |env: &HashMap<String, String>| AuthConfig::from_env(&|k| env.get(k).cloned()).unwrap();
    let cfg = cfg_of(&env);
    let clock = PinnedClock(Mutex::new(fx["clock0"].as_f64().unwrap()));
    let bytes = SeededBytes {
        seed: Sha256::digest(b"stewie-auth-oracle").into(),
        n: Mutex::new(0),
    };
    let store = Store::new(dir.clone(), &clock, &bytes);
    let ledger = Ledger::new(dir.clone(), AUDIT_DEFAULT_MAX_BYTES, &clock);
    let auth = Auth {
        cfg: &cfg,
        store: &store,
        clock: &clock,
        entropy: &bytes,
        ledger: &ledger,
    };
    let mut s = Vec::new();
    let s = &mut s;

    // the account store
    step(
        s,
        "register",
        json!(["Alice@Example.org", "correct horse battery"]),
        store.register(
            "Alice@Example.org",
            "correct horse battery",
            "operator",
            "pending",
            None,
        ),
    );
    step(
        s,
        "register",
        json!(["bob@example.org", "short"]),
        store.register("bob@example.org", "short", "operator", "pending", None),
    );
    step(
        s,
        "register",
        json!(["<img src=x>@x.co", "long enough pw"]),
        store.register(
            "<img src=x>@x.co",
            "long enough pw",
            "operator",
            "pending",
            None,
        ),
    );
    step(
        s,
        "register",
        json!(["alice@example.org", "another password"]),
        store.register(
            "alice@example.org",
            "another password",
            "operator",
            "pending",
            None,
        ),
    );
    let vc = |e: &str, p: &str, ip: &str| store.verify_credentials(e, p, Some(ip)).map(opt);
    step(
        s,
        "verify_credentials",
        json!(["alice@example.org", "correct horse battery", "1.2.3.4"]),
        vc("alice@example.org", "correct horse battery", "1.2.3.4"),
    );
    step(
        s,
        "approve",
        json!(["alice@example.org", "boot", "director"]),
        store.approve("alice@example.org", "boot", "director"),
    );
    for k in 0..6 {
        clock.advance(1.0);
        let pw = format!("wrong {k}");
        step(
            s,
            "verify_credentials",
            json!(["alice@example.org", pw, "6.6.6.6"]),
            vc("alice@example.org", &pw, "6.6.6.6"),
        );
        // the lock engages at exactly the fifth failure
        step(
            s,
            "is_locked",
            json!(["alice@example.org", "6.6.6.6"]),
            store.is_locked("alice@example.org", Some("6.6.6.6")),
        );
    }
    step(
        s,
        "is_locked",
        json!(["alice@example.org", "6.6.6.6"]),
        store.is_locked("alice@example.org", Some("6.6.6.6")),
    );
    step(
        s,
        "is_locked",
        json!(["alice@example.org", "1.2.3.4"]),
        store.is_locked("alice@example.org", Some("1.2.3.4")),
    );
    step(
        s,
        "verify_credentials",
        json!(["alice@example.org", "correct horse battery", "1.2.3.4"]),
        vc("alice@example.org", "correct horse battery", "1.2.3.4"),
    );
    step(
        s,
        "verify_credentials",
        json!(["alice@example.org", "correct horse battery", "6.6.6.6"]),
        vc("alice@example.org", "correct horse battery", "6.6.6.6"),
    );
    clock.advance(15.0 * 60.0 + 1.0);
    step(
        s,
        "verify_credentials",
        json!(["alice@example.org", "correct horse battery", "6.6.6.6"]),
        vc("alice@example.org", "correct horse battery", "6.6.6.6"),
    );
    step(
        s,
        "create_active",
        json!(["carol@example.org", "carol password 1", "trainee"]),
        store.create_active(
            "carol@example.org",
            "carol password 1",
            "trainee",
            Some("alice@example.org"),
        ),
    );
    step(
        s,
        "set_password",
        json!(["carol@example.org", "carol password 2"]),
        store.set_password("carol@example.org", "carol password 2"),
    );
    step(
        s,
        "verify_old_password",
        json!(["carol@example.org", "carol password 1"]),
        store.verify_old_password("carol@example.org", "carol password 1"),
    );
    step(
        s,
        "verify_old_password",
        json!(["carol@example.org", "carol password 2"]),
        store.verify_old_password("carol@example.org", "carol password 2"),
    );
    step(
        s,
        "set_role",
        json!(["carol@example.org", "pilot", "alice@example.org"]),
        store.set_role("carol@example.org", "pilot", "alice@example.org"),
    );
    let invite = store.create_invite("alice@example.org", "operator", 3600.0, 1);
    step(
        s,
        "create_invite",
        json!(["alice@example.org", "operator", 3600, 1]),
        invite.clone(),
    );
    let invite = invite.unwrap();
    step(
        s,
        "redeem_invite",
        json!(["<invite>", "dave@example.org", "weak"]),
        store.redeem_invite(&invite, "dave@example.org", "weak"),
    );
    step(
        s,
        "redeem_invite",
        json!(["<invite>", "dave@example.org", "dave password 1"]),
        store.redeem_invite(&invite, "dave@example.org", "dave password 1"),
    );
    step(
        s,
        "redeem_invite",
        json!(["<invite>", "erin@example.org", "erin password 1"]),
        store.redeem_invite(&invite, "erin@example.org", "erin password 1"),
    );
    step(
        s,
        "revoke",
        json!(["bob@example.org", "alice@example.org"]),
        store.revoke("bob@example.org", "alice@example.org"),
    );
    step(
        s,
        "revoke",
        json!(["dave@example.org", "alice@example.org"]),
        store.revoke("dave@example.org", "alice@example.org"),
    );
    for who in [
        "api-key",
        "desktop-local",
        "gis-anon",
        "alice@example.org",
        "carol@example.org",
        "dave@example.org",
        "bob@example.org",
        "zed@example.org",
    ] {
        step(s, "role_of", json!([who]), auth.role_of(who));
    }
    step(s, "list_all", json!([]), store.list_all());
    let account_store: Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("operators.json")).unwrap())
            .unwrap();

    // session tokens: issued, verified, revoked
    let a = auth.issue_token("alice@example.org", None);
    step::<_, String>(
        s,
        "issue_token",
        json!(["alice@example.org"]),
        Ok(a.clone()),
    );
    step::<_, String>(
        s,
        "verify_token",
        json!(["<alice>"]),
        Ok(opt(auth.verify_token(&a, None))),
    );
    step::<_, String>(
        s,
        "decode_claims",
        json!(["<alice>"]),
        Ok(auth.decode_claims(&a).unwrap_or(Value::Null)),
    );
    step::<_, String>(
        s,
        "verify_token",
        json!(["<alice>", "expired"]),
        Ok(opt(
            auth.verify_token(&a, Some(clock.now() + 12.0 * 3600.0 + 1.0))
        )),
    );
    let (head, tail) = a.split_at(a.len() - 2);
    let tampered = format!(
        "{}{}{}",
        head,
        if tail.starts_with('A') { 'B' } else { 'A' },
        &tail[1..]
    );
    step::<_, String>(
        s,
        "verify_token",
        json!(["<alice tampered>"]),
        Ok(opt(auth.verify_token(&tampered, None))),
    );
    let z = auth.issue_token("zed@example.org", None);
    step::<_, String>(s, "issue_token", json!(["zed@example.org"]), Ok(z.clone()));
    step::<_, String>(
        s,
        "verify_token",
        json!(["<zed, not allowlisted>"]),
        Ok(opt(auth.verify_token(&z, None))),
    );
    let mut other_env = env.clone();
    other_env.insert("STEWIE_TOKEN_AUD".into(), "other-audience".into());
    let other_cfg = cfg_of(&other_env);
    let o = Auth {
        cfg: &other_cfg,
        ..auth
    }
    .issue_token("alice@example.org", None);
    step::<_, String>(
        s,
        "issue_token",
        json!(["alice@example.org", "other-audience"]),
        Ok(o.clone()),
    );
    step::<_, String>(
        s,
        "verify_token",
        json!(["<other audience>"]),
        Ok(opt(auth.verify_token(&o, None))),
    );
    let jti = auth.decode_claims(&a).unwrap()["jti"]
        .as_str()
        .unwrap()
        .to_owned();
    step(
        s,
        "revoke_jti",
        json!(["<alice jti>"]),
        auth.revoke_jti(&jti).map(|()| Value::Null),
    );
    step::<_, String>(
        s,
        "verify_token",
        json!(["<alice revoked>"]),
        Ok(opt(auth.verify_token(&a, None))),
    );
    let revoked: Value =
        serde_json::from_str(&std::fs::read_to_string(dir.join("revoked_jti.json")).unwrap())
            .unwrap();
    std::fs::write(dir.join("revoked_jti.json"), "{not json").unwrap();
    step::<_, String>(
        s,
        "is_revoked",
        json!(["<anything>", "corrupt store"]),
        Ok(auth.is_revoked(&"0".repeat(32))),
    );
    let mut derived_env = env.clone();
    derived_env.remove("STEWIE_SESSION_SECRET");
    let derived_cfg = cfg_of(&derived_env);
    let d = Auth {
        cfg: &derived_cfg,
        ..auth
    }
    .issue_token("alice@example.org", None);
    step::<_, String>(
        s,
        "issue_token",
        json!(["alice@example.org", "derived secret"]),
        Ok(d.clone()),
    );

    // proxy trust and the Tailscale identity
    for peer in [
        Some("100.64.0.1"),
        Some("10.9.8.7"),
        Some("11.0.0.1"),
        Some("testclient"),
        None,
        Some("not-an-ip"),
    ] {
        step::<_, String>(
            s,
            "peer_trusted",
            json!([peer]),
            Ok(peer_trusted(peer, &cfg.trusted_proxies)),
        );
    }
    for (peer, login) in [
        ("100.64.0.1", "Alice@Example.org"),
        ("11.0.0.1", "alice@example.org"),
        ("10.1.1.1", "zed@example.org"),
    ] {
        step::<_, String>(
            s,
            "tailscale_identity",
            json!([peer, login]),
            Ok(opt(auth.tailscale_identity(login, Some(peer)))),
        );
    }
    let long = format!("{}@x.co", "x".repeat(65));
    for addr in [
        "user.name+tag@host.tld",
        "a..b@x.co",
        ".a@x.co",
        "a@x",
        "a@-x.co",
        "a@x.c0",
        "a b@x.co",
        &long,
        "ok@sub.domain.museum",
    ] {
        step(s, "validate_email", json!([addr]), validate_email(addr));
    }

    let want = fx["steps"].as_array().unwrap();
    assert_eq!(s.len(), want.len(), "step count");
    for (i, (got, want)) in s.iter().zip(want).enumerate() {
        assert_eq!(got, want, "step {i}");
    }
    assert_eq!(account_store, fx["store"], "the account store");
    assert_eq!(revoked, fx["revoked"], "the revocation store");
    assert_eq!(
        json!({"a": a, "z": z, "o": o, "d": d}),
        fx["tokens"],
        "the tokens, byte for byte"
    );
    let hex: String = derived_cfg
        .signing_secret()
        .iter()
        .fold(String::new(), |mut h, b| {
            use std::fmt::Write as _;
            let _ = write!(h, "{b:02x}");
            h
        });
    assert_eq!(hex, fx["derived_secret_hex"]);
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn startup_refuses_an_open_or_fail_open_configuration() {
    // SYNTHETIC environments, one guard each (D-R106: no open mode)
    let base = [("STEWIE_API_KEY", "k"), ("STEWIE_DATA_DIR", "/nonexistent")];
    let cfg = |extra: &[(&str, &str)], drop: &str| {
        let env: HashMap<&str, &str> = base
            .iter()
            .chain(extra)
            .copied()
            .filter(|(k, _)| *k != drop)
            .collect();
        AuthConfig::from_env(&|k| env.get(k).map(|v| (*v).to_owned()))
    };
    assert!(
        cfg(&[], "STEWIE_API_KEY")
            .unwrap_err()
            .contains("no open mode")
    );
    assert!(
        cfg(&[("STEWIE_TLS_TERMINATED", "1")], "")
            .unwrap_err()
            .contains("STEWIE_SESSION_SECRET")
    );
    assert!(
        cfg(&[("STEWIE_TRUST_TAILSCALE", "1")], "")
            .unwrap_err()
            .contains("STEWIE_TRUSTED_PROXIES")
    );
    assert!(
        cfg(&[], "STEWIE_DATA_DIR")
            .unwrap_err()
            .contains("STEWIE_DATA_DIR")
    );
    let ok = cfg(&[], "").unwrap();
    assert!(ok.allowed.is_empty(), "no compiled-in operator");
}
