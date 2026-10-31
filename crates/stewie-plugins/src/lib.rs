//! The plugin host (RW-50, D-R01). Godot, Gazebo, ROS 2 and the ONNX models are plugins: separate
//! processes the core starts only when asked and never links. A plugin is a directory holding a
//! `plugin.json` manifest (contract `plugin_manifest.schema.json`) on the search path
//! (`STEWIE_PLUGIN_PATH`, colon-separated). The protocol, `stewie-plugin-v1`, is one JSON object per line:
//! the host sends `{"op": "hello", "protocol": "stewie-plugin-v1"}` and the plugin must answer
//! `{"ok": true, "protocol": "stewie-plugin-v1", "name": ..., "capabilities": [...]}` before the timeout;
//! then each request `{"id": n, "op": ..., "params": ...}` gets `{"id": n, "ok": true, "result": ...}` or
//! `{"id": n, "ok": false, "error": "..."}`.
//!
//! Every way a plugin can be absent or broken (no manifest, a malformed one, a missing executable, no
//! handshake, a crash, a timeout) surfaces as [`Unavailable`] or [`PluginError`]: the caller reports
//! "not available" and never substitutes a result.

use std::fmt;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

use serde_json::{Value, json};
use stewie_contracts::plugin_manifest::{PluginManifest, PluginManifestKind};

pub const PROTOCOL: &str = "stewie-plugin-v1";

/// What a plugin provides.
pub type Kind = PluginManifestKind;

/// A discovered, valid plugin.
#[derive(Debug, Clone)]
pub struct Plugin {
    pub manifest: PluginManifest,
    pub dir: PathBuf,
}

/// The plugin a caller needs is not there or not working: report "not available".
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Unavailable {
    pub what: String,
    pub reason: String,
}

impl fmt::Display for Unavailable {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: not available ({})", self.what, self.reason)
    }
}

impl std::error::Error for Unavailable {}

/// Installed plugins, and manifests that were found but refused (with why).
#[derive(Debug, Default)]
pub struct Registry {
    plugins: Vec<Plugin>,
    rejected: Vec<(PathBuf, String)>,
}

fn executable(p: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        p.metadata()
            .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    }
    #[cfg(not(unix))]
    {
        p.is_file()
    }
}

impl Registry {
    /// Search `STEWIE_PLUGIN_PATH`. Unset or empty means no plugins.
    #[must_use]
    pub fn from_env() -> Self {
        let dirs: Vec<PathBuf> = std::env::var_os("STEWIE_PLUGIN_PATH")
            .map(|v| std::env::split_paths(&v).collect())
            .unwrap_or_default();
        Self::discover(&dirs)
    }

    /// Read `<dir>/*/plugin.json` under each search directory. A missing directory holds no plugins.
    #[must_use]
    pub fn discover(dirs: &[PathBuf]) -> Self {
        let mut reg = Self::default();
        for d in dirs {
            let Ok(entries) = std::fs::read_dir(d) else {
                continue;
            };
            let mut found: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path().join("plugin.json"))
                .filter(|p| p.is_file())
                .collect();
            found.sort();
            for path in found {
                match Self::load(&path) {
                    Ok(p) => reg.plugins.push(p),
                    Err(why) => reg.rejected.push((path, why)),
                }
            }
        }
        reg
    }

    fn load(path: &Path) -> Result<Plugin, String> {
        let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let manifest: PluginManifest =
            serde_json::from_str(&text).map_err(|e| format!("manifest: {e}"))?;
        // the schema's `const` is not enforced by the generated type, so the protocol is checked here
        if manifest.protocol.as_str() != Some(PROTOCOL) {
            return Err(format!("protocol {} is not {PROTOCOL}", manifest.protocol));
        }
        let dir = path.parent().unwrap_or(Path::new(".")).to_path_buf();
        let exe = dir.join(&*manifest.command[0]);
        if !executable(&exe) {
            return Err(format!("{} is not an executable file", exe.display()));
        }
        Ok(Plugin { manifest, dir })
    }

    #[must_use]
    pub fn plugins(&self) -> &[Plugin] {
        &self.plugins
    }

    #[must_use]
    pub fn rejected(&self) -> &[(PathBuf, String)] {
        &self.rejected
    }

    /// The first installed plugin of `kind`.
    ///
    /// # Errors
    /// [`Unavailable`] when none is installed.
    pub fn require(&self, kind: Kind) -> Result<&Plugin, Unavailable> {
        self.plugins
            .iter()
            .find(|p| p.manifest.kind == kind)
            .ok_or_else(|| Unavailable {
                what: format!("{kind} plugin"),
                reason: if self.rejected.is_empty() {
                    "none installed".into()
                } else {
                    format!(
                        "none installed; {} manifest(s) refused",
                        self.rejected.len()
                    )
                },
            })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PluginError {
    /// The process ended, timed out or broke the protocol.
    Unavailable(Unavailable),
    /// The plugin answered and reported an error for this request.
    Failed(String),
}

impl fmt::Display for PluginError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PluginError::Unavailable(u) => write!(f, "{u}"),
            PluginError::Failed(m) => write!(f, "plugin reported: {m}"),
        }
    }
}

impl std::error::Error for PluginError {}

/// A running plugin. Dropping it kills the process.
#[derive(Debug)]
pub struct Session {
    name: String,
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<String>,
    next_id: u64,
    timeout: Duration,
    pub capabilities: Vec<String>,
}

impl Session {
    /// Start `plugin` and complete the handshake within `timeout`.
    ///
    /// # Errors
    /// [`Unavailable`] if it will not start, answers wrongly, or stays silent.
    pub fn start(plugin: &Plugin, timeout: Duration) -> Result<Self, Unavailable> {
        let name = plugin.manifest.name.to_string();
        let un = |reason: String| Unavailable {
            what: format!("{name} plugin"),
            reason,
        };
        let argv = &plugin.manifest.command;
        let mut child = Command::new(plugin.dir.join(&*argv[0]))
            .args(argv[1..].iter().map(|a| &**a))
            .current_dir(&plugin.dir)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| un(format!("cannot start: {e}")))?;
        let (Some(stdin), Some(stdout)) = (child.stdin.take(), child.stdout.take()) else {
            let _ = child.kill();
            return Err(un("no stdio".into()));
        };
        let (tx, lines) = mpsc::channel();
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
        let mut s = Self {
            name: name.clone(),
            child,
            stdin,
            lines,
            next_id: 0,
            timeout,
            capabilities: Vec::new(),
        };
        let hello = s
            .exchange(&json!({"op": "hello", "protocol": PROTOCOL}))
            .map_err(|e| match e {
                PluginError::Unavailable(u) => u,
                PluginError::Failed(m) => un(m),
            })?;
        if hello.get("ok") != Some(&Value::Bool(true))
            || hello.get("protocol").and_then(Value::as_str) != Some(PROTOCOL)
        {
            return Err(un(format!("bad handshake: {hello}")));
        }
        s.capabilities = hello
            .get("capabilities")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|c| c.as_str().map(str::to_owned))
                    .collect()
            })
            .unwrap_or_default();
        Ok(s)
    }

    fn unavailable(&self, reason: String) -> PluginError {
        PluginError::Unavailable(Unavailable {
            what: format!("{} plugin", self.name),
            reason,
        })
    }

    fn exchange(&mut self, msg: &Value) -> Result<Value, PluginError> {
        let line = format!("{msg}\n");
        if self
            .stdin
            .write_all(line.as_bytes())
            .and_then(|()| self.stdin.flush())
            .is_err()
        {
            return Err(self.unavailable("process is gone".into()));
        }
        match self.lines.recv_timeout(self.timeout) {
            Ok(reply) => {
                serde_json::from_str(&reply).map_err(|e| self.unavailable(format!("not JSON: {e}")))
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {
                Err(self.unavailable(format!("no answer within {:?}", self.timeout)))
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                Err(self.unavailable("process exited".into()))
            }
        }
    }

    /// Send one request and wait for its answer.
    ///
    /// # Errors
    /// [`PluginError::Unavailable`] on exit, timeout or a reply to another request;
    /// [`PluginError::Failed`] when the plugin reports an error.
    pub fn call(&mut self, op: &str, params: &Value) -> Result<Value, PluginError> {
        self.next_id += 1;
        let id = self.next_id;
        let reply = self.exchange(&json!({"id": id, "op": op, "params": params}))?;
        if reply.get("id").and_then(Value::as_u64) != Some(id) {
            return Err(self.unavailable(format!("reply to the wrong request: {reply}")));
        }
        if reply.get("ok") == Some(&Value::Bool(true)) {
            Ok(reply.get("result").cloned().unwrap_or(Value::Null))
        } else {
            Err(PluginError::Failed(
                reply
                    .get("error")
                    .and_then(Value::as_str)
                    .unwrap_or("unspecified")
                    .to_owned(),
            ))
        }
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}
