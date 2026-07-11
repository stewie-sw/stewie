"""Standalone FastAPI pixel-stream server for STEWIE viz2 (NOT ``stewie.server``).

On each ``WS /ws`` connection:
  1. read the first message = a session config (``protocol.parse_config``);
  2. resolve a DEM bundle (real sample, or a freshly generated labeled-synthetic procedural bundle);
  3. spawn ``Viz2Runtime`` (via ``viz2_serve.py``) — the SOLE conserved mutator — over that bundle;
  4. open a localhost TCP frame seam and spawn Godot ``viz2.tscn --live --stream`` on the host GPU
     (xvfb + vulkan), which connects to BOTH the runtime (drive) and this seam (frames);
  5. relay: Godot JPEG frames -> WS binary; WS input JSON -> Godot control frames.
On disconnect (either side) the session tears down every process + temp dir cleanly.

Binds 0.0.0.0:8900 (tailnet-private; reached via Tailscale). No auth for v1 (private deploy).
Run: ``scripts/run_viz2_stream.sh`` (or ``uvicorn stewie.stream.app:app --host 0.0.0.0 --port 8900``).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from stewie.stream import previews, protocol
from stewie.stream.framing import pack_frame, read_frame

# repo root: stewie/stream/app.py -> stewie/stream -> stewie -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
GODOT_PROJECT = Path(os.environ.get("STEWIE_GODOT_PROJECT", REPO_ROOT / "stewie" / "godot"))
SAMPLES_DIR = REPO_ROOT / "samples" / "lunar_dem"
STATIC_DIR = Path(__file__).resolve().parent / "static"

#: python used for the Viz2Runtime subprocess (same interpreter that serves this app by default).
STREAM_PY = os.environ.get("STEWIE_STREAM_PY", sys.executable)
#: runtime hold window; the session stops it explicitly on disconnect, this is the hard ceiling.
RUNTIME_SECONDS = float(os.environ.get("STEWIE_STREAM_RUNTIME_SECONDS", "600"))
STREAM_SIZE = os.environ.get("STEWIE_STREAM_SIZE", "960x540")
STREAM_FPS = os.environ.get("STEWIE_STREAM_FPS", "24")
STREAM_QUALITY = os.environ.get("STEWIE_STREAM_QUALITY", "0.72")
XVFB_SCREEN = os.environ.get("XVFB_SCREEN", "1920x1080x24")


def _resolve_godot() -> str:
    env = os.environ.get("STEWIE_GODOT")
    if env:
        return env
    candidates = [
        GODOT_PROJECT / ".tools" / "godot" / "Godot_v4.6.3-stable_linux.x86_64",
        Path("/mnt/projects/tools/Godot_v4.6.3-stable_linux.x86_64"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[-1])  # last resort; subprocess launch will surface a clear error


def _subproc_env() -> dict[str, str]:
    env = dict(os.environ)
    extra = [str(REPO_ROOT), str(REPO_ROOT / "packages" / "stewie-bodies"),
             str(REPO_ROOT / "packages" / "stewie-forge")]
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra + ([prev] if prev else []))
    return env


class StreamSession:
    """Owns one live browser session: the runtime + Godot subprocesses, the frame seam, teardown."""

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.session_dir = tempfile.mkdtemp(prefix="viz2_stream_")
        self._proc_bundle_dir: str | None = None
        self._serve: asyncio.subprocess.Process | None = None
        self._godot: asyncio.subprocess.Process | None = None
        self._srv: asyncio.AbstractServer | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._godot_connected = asyncio.Event()

    # -- bundle resolution --------------------------------------------------------------------
    def _resolve_bundle(self) -> str:
        if self.cfg["mode"] == "real":
            bundle = SAMPLES_DIR / self.cfg["site"]
            if not (bundle / "metadata.json").is_file():
                raise FileNotFoundError(
                    f"real site {self.cfg['site']!r} not found under {SAMPLES_DIR}")
            return str(bundle)
        # procedural: generate a LABELED-SYNTHETIC bundle (segregated under out/procedural_sandbox/)
        from stewie.terrain.procedural_bundle import generate_procedural_bundle
        name = f"stream_seed{self.cfg['world_seed']}_{int(time.time())}"
        generate_procedural_bundle(
            name, world_seed=self.cfg["world_seed"], params=self.cfg.get("params") or None,
            extent_m=256.0, cell_m=1.0, write_previews=True)
        bundle_dir = str(REPO_ROOT / "out" / "procedural_sandbox" / name)
        self._proc_bundle_dir = bundle_dir
        return bundle_dir

    # -- frame seam ---------------------------------------------------------------------------
    async def _on_godot(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # first (and only) Godot connection wins the seam.
        if self._godot_connected.is_set():
            writer.close()
            return
        self._reader = reader
        self._writer = writer
        self._godot_connected.set()

    async def start(self, *, connect_timeout: float = 90.0) -> None:
        bundle = self._resolve_bundle()

        # 1) the localhost frame seam (server accepts, Godot connects)
        self._srv = await asyncio.start_server(self._on_godot, "127.0.0.1", 0)
        seam_port = self._srv.sockets[0].getsockname()[1]

        # 2) the conserved runtime (writes the 0600 token file into session_dir)
        self._serve = await asyncio.create_subprocess_exec(
            STREAM_PY, str(REPO_ROOT / "stewie" / "runtime" / "viz2_serve.py"),
            "--bundle", bundle, "--session-dir", self.session_dir,
            "--seconds", str(RUNTIME_SECONDS), "--fine-cell-m", str(self.cfg["fine_cell_m"]),
            env=_subproc_env(), start_new_session=True)
        await self._await_token(timeout=20.0)

        # 3) Godot on the host GPU: drives THROUGH the runtime (--live) + streams frames (--stream)
        godot = _resolve_godot()
        args = [
            "xvfb-run", "-a", "--server-args", f"-screen 0 {XVFB_SCREEN}",
            godot, "--rendering-driver", "vulkan", "--path", str(GODOT_PROJECT),
            "res://viz2.tscn", "--",
            "--live", "--stream", "--session-dir", self.session_dir, "--site", bundle,
            "--stream-port", str(seam_port), "--size", STREAM_SIZE,
            "--stream-fps", STREAM_FPS, "--stream-quality", STREAM_QUALITY,
            "--sun-az", str(self.cfg["sun_az"]), "--sun-el", str(self.cfg["sun_el"]),
        ]
        self._godot = await asyncio.create_subprocess_exec(
            *args, env=_subproc_env(), start_new_session=True)

        # 4) wait for Godot to connect the frame seam (or surface a clear failure)
        try:
            await asyncio.wait_for(self._godot_connected.wait(), timeout=connect_timeout)
        except asyncio.TimeoutError as exc:
            rc = self._godot.returncode if self._godot else None
            raise RuntimeError(
                f"Godot did not connect the stream seam within {connect_timeout}s "
                f"(godot returncode={rc}); check xvfb/vulkan on the host GPU") from exc

    async def _await_token(self, *, timeout: float) -> None:
        token = os.path.join(self.session_dir, "viz2_session.json")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(token):
                return
            if self._serve is not None and self._serve.returncode is not None:
                raise RuntimeError(
                    f"viz2_serve exited early (rc={self._serve.returncode}) before writing the token")
            await asyncio.sleep(0.05)
        raise RuntimeError(f"viz2_serve never wrote the token file within {timeout}s")

    # -- relay --------------------------------------------------------------------------------
    async def pump_frames(self, ws: WebSocket) -> None:
        assert self._reader is not None
        while True:
            try:
                frame = await read_frame(self._reader)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                break  # Godot closed the seam
            await ws.send_bytes(frame)

    async def pump_input(self, ws: WebSocket) -> None:
        assert self._writer is not None
        while True:
            raw = await ws.receive_text()
            cmd = protocol.normalize_input(raw)
            if not cmd:
                continue
            self._writer.write(pack_frame(json.dumps(cmd).encode()))
            await self._writer.drain()

    # -- teardown -----------------------------------------------------------------------------
    async def stop(self) -> None:
        # signal Godot's stream loop + close the seam
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        if self._srv is not None:
            self._srv.close()
            try:
                await self._srv.wait_closed()
            except Exception:
                pass
        # STOP sentinel lets viz2_serve exit + emit its E3 evidence gracefully
        try:
            Path(self.session_dir, "STOP").touch()
        except Exception:
            pass
        await self._terminate(self._godot, grace=3.0)
        await self._terminate(self._serve, grace=5.0)
        # cleanup temp dirs (keep procedural previews? no — session-scoped, remove)
        shutil.rmtree(self.session_dir, ignore_errors=True)
        if self._proc_bundle_dir:
            shutil.rmtree(self._proc_bundle_dir, ignore_errors=True)

    @staticmethod
    async def _terminate(proc: asyncio.subprocess.Process | None, *, grace: float) -> None:
        if proc is None or proc.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass


app = FastAPI(title="STEWIE viz2 pixel-stream", version="1.0")

# Self-hosted three.js + any other static asset (NO external CDN, so the setup screen works on the
# tailnet). StaticFiles blocks path escapes; the vendored three.module.min.js lives under vendor/.
app.mount("/vendor", StaticFiles(directory=str(STATIC_DIR / "vendor")), name="vendor")


@app.get("/")
async def index() -> FileResponse:
    """The three.js SETUP screen (mode toggle + site/params + live preview + Launch)."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/stream")
async def stream_view() -> FileResponse:
    """The live pixel-stream view the setup screen's "Launch drive" opens (reads the assembled
    config from the URL hash; still standalone-usable with its built-in default config)."""
    return FileResponse(str(STATIC_DIR / "stream.html"))


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "service": "viz2-stream", "godot": _resolve_godot(),
            "godot_project": str(GODOT_PROJECT)}


@app.get("/bundles")
async def bundles() -> dict:
    """The real-site dropdown data: every REAL ``samples/lunar_dem/`` bundle (synthetic EXCLUDED),
    each with its VERBATIM citation. ``default`` marks the real-mode default site."""
    rows = previews.list_real_bundles()
    return {"bundles": rows, "default": previews.DEFAULT_SITE}


@app.get("/preview/heightmap")
async def preview_heightmap(site: str = Query(previews.DEFAULT_SITE)) -> dict:
    """A REAL, decimated heightmap (~128²) for the setup preview mesh + the site's REAL citation."""
    try:
        return previews.real_heightmap_preview(site)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/preview/procedural")
async def preview_procedural(
    seed: int = Query(0),
    H: float = Query(previews._normalize_params({})["H"]),
    wavelength: float = Query(previews._normalize_params({})["feature_wavelength_m"]),
    amplitude: float = Query(previews._normalize_params({})["amplitude_m"]),
    octaves: int = Query(previews._normalize_params({})["octaves"]),
) -> dict:
    """The SYNTHETIC preview: the REAL ``fbm_global`` field for (seed, H, wavelength, amplitude,
    octaves), labelled SYNTHETIC (citation null). Bit-exact with a direct ``fbm_global`` call."""
    params = {"H": H, "feature_wavelength_m": wavelength,
              "amplitude_m": amplitude, "octaves": octaves}
    try:
        return previews.procedural_heightmap_preview(seed, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws")
async def ws_stream(ws: WebSocket) -> None:
    await ws.accept()
    # 1) the first message is the session config
    try:
        cfg_raw = await ws.receive_text()
        cfg = protocol.parse_config(cfg_raw)
    except WebSocketDisconnect:
        return
    except protocol.ConfigError as exc:
        await ws.send_text(json.dumps({"type": "error", "error": str(exc)}))
        await ws.close(code=1003)
        return

    session = StreamSession(cfg)
    try:
        await session.start()
    except Exception as exc:  # bundle / runtime / godot launch failure -> report + close
        await ws.send_text(json.dumps({"type": "error", "error": f"{type(exc).__name__}: {exc}"}))
        await session.stop()
        await ws.close(code=1011)
        return

    await ws.send_text(json.dumps({"type": "ready", "mode": cfg["mode"],
                                   "site": cfg.get("site"), "fine_cell_m": cfg["fine_cell_m"]}))
    frames = asyncio.create_task(session.pump_frames(ws))
    inputs = asyncio.create_task(session.pump_input(ws))
    try:
        done, pending = await asyncio.wait({frames, inputs},
                                           return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        pass
    finally:
        for t in (frames, inputs):
            t.cancel()
        await asyncio.gather(frames, inputs, return_exceptions=True)
        await session.stop()
        try:
            await ws.close()
        except Exception:
            pass
