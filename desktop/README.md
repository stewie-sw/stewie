# STEWIE Desktop (Electron prototype)

The STEWIE cockpit as a **native Linux desktop app** instead of a browser tab — an Electron shell
wrapping the **existing** FastAPI cockpit. No frontend change: the renderer *is* the real cockpit.

## How it works (Electron + Python sidecar)

`main.js` (Electron main process):

1. grabs a free `127.0.0.1` port,
2. spawns the repo's `.venv/bin/stewie-serve` on it — the **real** server, not a stub
   (`PYTHONNOUSERSITE=1`, `PYTHONPATH` dropped, so the repo venv resolves its own packages),
3. polls `/healthz` until the server is up (40 s budget) — if the sidecar exits before it ever gets
   healthy, the error dialog shows the sidecar's captured stderr tail instead of a generic timeout,
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

## Build + install (local, this machine)

```bash
cd desktop
npm run dist                 # electron-builder -> dist/STEWIE-0.1.0.AppImage (~109 MB)
./install-local.sh           # -> ~/.local/bin/stewie-desktop + an app-menu .desktop launcher
```

`install-local.sh` preflights the sidecar before installing anything: it runs
`.venv/bin/python -c "import stewie.server.server"` from a neutral cwd (`PYTHONNOUSERSITE=1`,
`PYTHONPATH` dropped — the same env `main.js` spawns with) and exits with the exact
`pip install -e .[server]` remedy if the venv can't import the server (the real first-launch failure
mode: a venv without the stewie package passes the file-exists check, then dies at launch). It then
bakes `STEWIE_REPO=<repo>` into the launcher, so the installed AppImage finds the repo `.venv`
sidecar. Reverse it: `rm ~/.local/bin/stewie-desktop ~/.local/share/applications/stewie.desktop`.
(Headless verification runs the AppImage with `APPIMAGE_EXTRACT_AND_RUN=1` since there's no FUSE.)

## Visual smoke (Playwright)

```bash
PYTHONNOUSERSITE=1 STEWIE_DESKTOP=1 .venv/bin/stewie-serve --port 8795 --host 127.0.0.1 &
PYTHONNOUSERSITE=1 .venv/bin/python desktop/visual_smoke.py 8795 /tmp/pw
```

Drives real Chromium against a desktop-mode sidecar, asserts the operator-login gate is lifted
(`whoami = desktop-local (director)`), and screenshots all five work-area panes. Exits non-zero if
the gate is still up or a pane renders blank.

## Verified (2026-06-19, archimedes)

Launched under `Xvfb :99` and screenshotted: a native window renders the cockpit's **operator-access
login** screen, and the sidecar log shows the cockpit JS fetching live data from the spawned server
(`/layers/globe/dem.png`, `/twin/cg`, `/layers/legend` — all `200`). End-to-end chain proven:
Electron window → real cockpit → real FastAPI sidecar. Node 20, Electron 32.3.3.

## Known prototype gaps / next phases

- **Auth: DONE** — `main.js` spawns the sidecar with `STEWIE_DESKTOP=1`, which grants a
  loopback-only local-trust director (`whoami = desktop-local (director)`), so the app opens straight
  to the cockpit. The public/docker deploy never sets the flag.
- **Local install: DONE** — `npm run dist` builds the AppImage and `install-local.sh` installs it for
  this machine (the sidecar runs from the repo `.venv`).
- **Ship-to-other-machines bundle** (the real remaining packaging work, *not* built — no stub bundle):
  bundle a relocatable Python (PyInstaller or a vendored venv) + the `server`-extra deps
  (`numpy/scipy/matplotlib/pyproj/opencv-headless/fastapi`) + the ~255 MB of real DEM/validation assets
  INTO the AppImage, so it has no `STEWIE_REPO` dependency. Exclude `torch`/SB3 (RL-only) and the Godot
  binary (sensor-render track) to keep it ~0.5–1 GB. Native deps (scipy/opencv/pyproj) are the fiddly
  part; expect ~1–2 weeks for a robust signed, self-contained bundle.
- **WebGL**: Electron ships its own Chromium, so the Cesium globe + Three.js panes get consistent
  WebGL (the main reason to prefer Electron over a system-webview shell here). Under Xvfb it falls
  back to software GL; on a real GPU display it's hardware-accelerated.

`node_modules/`, `dist/`, and `package-lock.json` are git-ignored; this dir is additive and does not
touch the web-deploy path (`deploy/` + cloudflared).
