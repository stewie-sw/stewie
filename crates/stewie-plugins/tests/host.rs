//! The plugin host: with zero plugins every kind is "not available"; refused manifests are reported with
//! why; and against SYNTHETIC test plugins (small Python scripts written here, labelled) the host
//! handshakes, calls, surfaces a plugin's own error, and reports a silent, crashing or wrong-protocol
//! plugin as not available, killing what it started.

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::json;
use stewie_plugins::{Kind, PluginError, Registry, Session};

fn scratch(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("stewie-plugins-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d
}

/// Install a SYNTHETIC test plugin: `body` runs after a shared prelude that reads JSON lines.
fn install(root: &Path, name: &str, kind: &str, protocol: &str, body: &str) {
    let dir = root.join(name);
    fs::create_dir_all(&dir).unwrap();
    let script = format!(
        "#!/usr/bin/env python3\n# SYNTHETIC test plugin for the stewie plugin host (labelled)\nimport json, os, sys\nopen('pid', 'w').write(str(os.getpid()))\n{body}\n"
    );
    fs::write(dir.join("run.py"), script).unwrap();
    fs::set_permissions(dir.join("run.py"), fs::Permissions::from_mode(0o755)).unwrap();
    let manifest = json!({"name": name, "kind": kind, "version": "0.0.1", "protocol": protocol, "command": ["run.py"], "capabilities": ["echo"]});
    fs::write(dir.join("plugin.json"), manifest.to_string()).unwrap();
}

const ECHO: &str = r#"
def say(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line)
    if m.get("op") == "hello":
        say({"ok": True, "protocol": "stewie-plugin-v1", "name": "echo", "capabilities": ["echo"]})
    elif m["op"] == "echo":
        say({"id": m["id"], "ok": True, "result": m["params"]})
    elif m["op"] == "crash":
        sys.exit(3)
    else:
        say({"id": m["id"], "ok": False, "error": "unknown op " + m["op"]})
"#;

const KINDS: [Kind; 4] = [
    Kind::Renderer,
    Kind::Simulator,
    Kind::Middleware,
    Kind::Inference,
];

#[test]
fn with_no_plugins_everything_is_not_available() {
    let empty = scratch("empty");
    for reg in [
        Registry::discover(&[]),
        Registry::discover(std::slice::from_ref(&empty)),
        Registry::discover(&[empty.join("missing")]),
    ] {
        assert!(reg.plugins().is_empty() && reg.rejected().is_empty());
        for k in KINDS {
            let e = reg.require(k).unwrap_err();
            assert!(e.to_string().contains("not available"), "{e}");
        }
    }
    fs::remove_dir_all(&empty).unwrap();
}

#[test]
fn bad_manifests_are_refused_with_a_reason() {
    let root = scratch("bad");
    install(&root, "oldproto", "renderer", "stewie-plugin-v0", ECHO);
    install(&root, "noexe", "simulator", "stewie-plugin-v1", ECHO);
    fs::remove_file(root.join("noexe/run.py")).unwrap();
    fs::create_dir_all(root.join("junk")).unwrap();
    fs::write(root.join("junk/plugin.json"), "{not json").unwrap();
    let reg = Registry::discover(std::slice::from_ref(&root));
    assert!(reg.plugins().is_empty());
    assert_eq!(reg.rejected().len(), 3, "{:?}", reg.rejected());
    assert!(
        reg.require(Kind::Renderer)
            .unwrap_err()
            .reason
            .contains("refused")
    );
    fs::remove_dir_all(&root).unwrap();
}

fn alive(dir: &Path) -> bool {
    let pid = fs::read_to_string(dir.join("pid")).unwrap();
    Path::new(&format!("/proc/{pid}")).exists()
        && !fs::read_to_string(format!("/proc/{pid}/stat"))
            .unwrap_or_default()
            .contains(") Z ")
}

#[test]
fn a_working_plugin_answers_and_reports_its_own_errors() {
    let root = scratch("echo");
    install(&root, "echo", "inference", "stewie-plugin-v1", ECHO);
    let reg = Registry::discover(std::slice::from_ref(&root));
    let plugin = reg.require(Kind::Inference).unwrap();
    let mut s = Session::start(plugin, Duration::from_secs(10)).unwrap();
    assert_eq!(s.capabilities, ["echo"]);
    let payload = json!({"frame": 7, "pts": [1.5, -2.0]});
    assert_eq!(s.call("echo", &payload).unwrap(), payload);
    assert_eq!(
        s.call("nope", &json!(null)),
        Err(PluginError::Failed("unknown op nope".into()))
    );
    assert!(
        matches!(
            s.call("crash", &json!(null)),
            Err(PluginError::Unavailable(_))
        ),
        "a crash is not available, not a result"
    );
    assert!(matches!(
        s.call("echo", &json!(1)),
        Err(PluginError::Unavailable(_))
    ));
    drop(s);
    assert!(!alive(&root.join("echo")), "the host reaps what it started");
    fs::remove_dir_all(&root).unwrap();
}

#[test]
fn a_silent_or_wrong_protocol_plugin_is_not_available_and_is_killed() {
    let root = scratch("silent");
    install(
        &root,
        "silent",
        "middleware",
        "stewie-plugin-v1",
        "import time\ntime.sleep(60)",
    );
    install(
        &root,
        "liar",
        "renderer",
        "stewie-plugin-v1",
        "sys.stdin.readline()\nprint(json.dumps({'ok': True, 'protocol': 'other'}), flush=True)\nimport time\ntime.sleep(60)",
    );
    let reg = Registry::discover(std::slice::from_ref(&root));
    let e = Session::start(
        reg.require(Kind::Middleware).unwrap(),
        Duration::from_millis(1500),
    )
    .unwrap_err();
    assert!(e.reason.contains("no answer"), "{e}");
    let e = Session::start(
        reg.require(Kind::Renderer).unwrap(),
        Duration::from_secs(10),
    )
    .unwrap_err();
    assert!(e.reason.contains("bad handshake"), "{e}");
    std::thread::sleep(Duration::from_millis(200));
    assert!(
        !alive(&root.join("silent")) && !alive(&root.join("liar")),
        "refused plugins are killed"
    );
    fs::remove_dir_all(&root).unwrap();
}
