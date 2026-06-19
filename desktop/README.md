# STEWIE Desktop (Electron prototype)

The STEWIE cockpit as a **native Linux desktop app** instead of a browser tab — an Electron shell
wrapping the **existing** FastAPI cockpit. No frontend change: the renderer *is* the real cockpit.

## How it works (Electron + Python sidecar)

`main.js` (Electron main process):

1. grabs a free `127.0.0.1` port,
2. spawns the repo's `.venv/bin/stewie-serve` on it — the **real** server, not a stub
   (`PYTHONNOUSERSITE=1`, `PYTHONPATH` dropped, so the repo venv resolves its own packages),
3. polls `/healthz` until the server is up (40 s budget),
4. opens a `BrowserWindow` at `http://127.0.0.1:<port>/`,
5. kills the sidecar on every quit path (`window-all-closed`, `before-quit`, `SIGINT/SIGTERM`).

The renderer talks to the backend over localhost HTTP exactly as the web deploy does, so nothing in
`stewie/server` changes. Security defaults are on (`contextIsolation: true`, `nodeIntegration: false`,
`sandbox: true`) — the renderer gets no Node access; it's just the trusted local cockpit.

## Run (dev)

```bash
cd desktop
npm install
# npm >= 9 may block Electron's postinstall (the Chromium download). If `node_modules/electron/dist/`
# is missing, run it explicitly:  node node_modules/electron/install.js
npm start
```

Requires the repo's Python venv at `../.venv` with the server extra installed
(`pip install -e .[server]`). Needs a display; headless hosts can use `xvfb-run -a npm start`.

## Verified (2026-06-19, archimedes)

Launched under `Xvfb :99` and screenshotted: a native window renders the cockpit's **operator-access
login** screen, and the sidecar log shows the cockpit JS fetching live data from the spawned server
(`/layers/globe/dem.png`, `/twin/cg`, `/layers/legend` — all `200`). End-to-end chain proven:
Electron window → real cockpit → real FastAPI sidecar. Node 20, Electron 32.3.3.

## Known prototype gaps / next phases

- **Auth**: the cockpit's operator login is active (it was built for a multi-user *server*). A
  single-user desktop build probably wants a local-trust bypass (e.g. auto-mint a local operator
  token, or a `STEWIE_DESKTOP=1` path that skips the login gate). Not done here.
- **Packaging → distributable** (the real remaining work, *not* built — no stub bundle): turn this
  into an AppImage / `.deb` via `electron-builder`, bundling a relocatable Python (PyInstaller or a
  vendored venv) + the `server`-extra deps (`numpy/scipy/matplotlib/pyproj/opencv-headless/fastapi`)
  + the ~255 MB of real DEM/validation assets the server reads. Exclude `torch`/SB3 (RL-only) and the
  Godot binary (sensor-render track) to keep the artifact ~0.5–1 GB. Native deps (scipy/opencv/pyproj)
  are the fiddly part; expect ~1–2 weeks for a robust signed bundle.
- **WebGL**: Electron ships its own Chromium, so the Cesium globe + Three.js panes get consistent
  WebGL (the main reason to prefer Electron over a system-webview shell here). Under Xvfb it falls
  back to software GL; on a real GPU display it's hardware-accelerated.

`node_modules/`, `dist/`, and `package-lock.json` are git-ignored; this dir is additive and does not
touch the web-deploy path (`deploy/` + cloudflared).
