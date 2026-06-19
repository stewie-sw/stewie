// STEWIE desktop shell (Electron).
//
// Wraps the EXISTING cockpit as a native Linux window -- no frontend change. The renderer is the
// real FastAPI cockpit; this main process owns its lifecycle:
//   1. grab a free localhost port,
//   2. spawn the repo's .venv `stewie-serve` on it (the real server, not a stub),
//   3. poll /healthz until the server is up,
//   4. load a BrowserWindow at http://127.0.0.1:<port>/,
//   5. kill the sidecar on every quit path.
//
// This is the "Electron + Python sidecar" pattern: the renderer talks to the backend over localhost
// HTTP exactly as it does on the web deploy, so nothing in stewie/server changes.

const { app, BrowserWindow, dialog } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const net = require("net");
const http = require("http");

// Locate the repo that holds the .venv sidecar. A packaged build (AppImage) sets STEWIE_REPO (its
// __dirname is inside the app bundle, not the repo); `npm start` (dev) falls back to the parent of desktop/.
const REPO = process.env.STEWIE_REPO || path.resolve(__dirname, "..");
const SERVE = path.join(REPO, ".venv", "bin", "stewie-serve");
const HEALTH_TIMEOUT_MS = 40000;

let serverProc = null;
let serverPort = 0;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once("error", reject);
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
}

function startServer(port) {
  // Mirror the documented venv-isolation: force PYTHONNOUSERSITE and drop any inherited PYTHONPATH
  // so the repo .venv resolves its own packages.
  const env = { ...process.env, PYTHONNOUSERSITE: "1", STEWIE_DESKTOP: "1" };
  delete env.PYTHONPATH;
  // STEWIE_DESKTOP=1 -> the server grants a loopback-only local-trust "director" so the single-user
  // desktop app opens straight to the cockpit (no operator login). Safe: the public/docker deploy
  // never sets this flag, and the grant additionally requires a loopback client (see deps.require_auth).
  const proc = spawn(SERVE, ["--port", String(port), "--host", "127.0.0.1"], {
    cwd: REPO,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  proc.stdout.on("data", (d) => process.stdout.write(`[stewie-serve] ${d}`));
  proc.stderr.on("data", (d) => process.stderr.write(`[stewie-serve] ${d}`));
  return proc;
}

function waitHealthz(port, deadline) {
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get({ host: "127.0.0.1", port, path: "/healthz", timeout: 2000 }, (res) => {
        res.resume();
        if (res.statusCode === 200) return resolve();
        retry();
      });
      req.on("error", retry);
      req.on("timeout", () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error("stewie-serve did not become healthy in time"));
      setTimeout(attempt, 300);
    };
    attempt();
  });
}

function createWindow(port) {
  const win = new BrowserWindow({
    width: 1600,
    height: 1000,
    title: "STEWIE",
    backgroundColor: "#0b0e14",
    webPreferences: {
      contextIsolation: true,     // Electron security defaults: the renderer gets no Node access;
      nodeIntegration: false,     // it is just the trusted localhost cockpit talking HTTP to the sidecar.
      sandbox: true,
    },
  });
  win.removeMenu();
  win.loadURL(`http://127.0.0.1:${port}/`);
  return win;
}

function stopServer() {
  if (serverProc && !serverProc.killed) {
    serverProc.kill("SIGTERM");
    // hard-stop if it lingers
    setTimeout(() => { if (serverProc && !serverProc.killed) serverProc.kill("SIGKILL"); }, 3000);
  }
}

app.whenReady().then(async () => {
  try {
    serverPort = await freePort();
    serverProc = startServer(serverPort);
    serverProc.on("exit", (code) => {
      if (code !== 0 && code !== null) {
        dialog.showErrorBox("STEWIE server stopped", `stewie-serve exited with code ${code}.`);
      }
    });
    await waitHealthz(serverPort, Date.now() + HEALTH_TIMEOUT_MS);
    createWindow(serverPort);
  } catch (err) {
    dialog.showErrorBox("STEWIE failed to start", String(err && err.message ? err.message : err));
    stopServer();
    app.quit();
  }
});

// single-window Linux app: quitting the window quits the app (and the sidecar)
app.on("window-all-closed", () => app.quit());
app.on("before-quit", stopServer);
process.on("exit", stopServer);
process.on("SIGINT", () => { stopServer(); process.exit(0); });
process.on("SIGTERM", () => { stopServer(); process.exit(0); });
