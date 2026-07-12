"""Standalone FastAPI pixel-stream server for STEWIE viz2 (NOT ``stewie.server``).

On each ``WS /ws`` connection:
  1. read the first message = a session config (``protocol.parse_config``);
  2. resolve a DEM bundle (real sample, or a freshly generated labeled-synthetic procedural bundle);
  3. spawn ``Viz2Runtime`` (via ``viz2_serve.py``) — the SOLE conserved mutator — over that bundle;
  4. open a localhost TCP frame seam and spawn Godot ``viz2.tscn --live --stream`` on the host GPU
     (xvfb + vulkan), which connects to BOTH the runtime (drive) and this seam (frames);
  5. relay: Godot JPEG frames -> WS binary; WS input JSON -> Godot control frames.
On disconnect (either side) the session tears down every process + temp dir cleanly.

Binds 0.0.0.0:8900. On the tailnet it runs open (private); to expose it PUBLICLY (Cloudflare)
set ``VIZ2_STREAM_TOKEN`` so every route + the WS require a ``?token=<T>`` link, plus the always-on
``VIZ2_STREAM_MAX_SESSIONS`` (GPU concurrency cap) and ``VIZ2_STREAM_MAX_CONN_PER_MIN`` (per-IP
connection rate-limit) guards in ``stewie.stream.security``.
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

from stewie.stream import previews, protocol, security
from stewie.stream.framing import pack_frame, read_frame

# repo root: stewie/stream/app.py -> stewie/stream -> stewie -> <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]
GODOT_PROJECT = Path(os.environ.get("STEWIE_GODOT_PROJECT", REPO_ROOT / "stewie" / "godot"))
SAMPLES_DIR = REPO_ROOT / "samples" / "lunar_dem"
STATIC_DIR = Path(__file__).resolve().parent / "static"
#: saved command bags (ROS-bag-style record/replay of the full control surface).
BAGS_DIR = REPO_ROOT / "out" / "viz2_bags"


def _safe_bag_name(name: str) -> str:
    safe = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_")[:64]
    return safe or "session"


def _load_bag(name: str) -> dict:
    with open(BAGS_DIR / (_safe_bag_name(name) + ".json")) as fh:
        return json.load(fh)

#: python used for the Viz2Runtime subprocess (same interpreter that serves this app by default).
STREAM_PY = os.environ.get("STEWIE_STREAM_PY", sys.executable)
#: runtime hold window; the session stops it explicitly on disconnect, this is the hard ceiling. Must
#: EXCEED Godot's _stream_max_seconds (900) so the physics never dies mid-stream (was 600 -> 5-min freeze).
RUNTIME_SECONDS = float(os.environ.get("STEWIE_STREAM_RUNTIME_SECONDS", "960"))
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
        # command bag (ROS-bag-style): config + every control frame with a relative timestamp, for
        # save + deterministic playback (the record->replay / RL seam).
        self._bag: list[dict] = [{"t": 0.0, "config": dict(cfg)}]
        self._bag_t0: float | None = None
        # frame egress: a single-slot LATEST buffer + event, so a slow browser drops stale frames rather
        # than backpressuring the seam TCP into Godot's render/ack loop (the terminal-deadman chain).
        self._latest_frame: bytes | None = None
        self._latest_status: bytes | None = None   # JSON status frames (slip/entrapment/pose) from Godot
        self._frame_evt = asyncio.Event()

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

    # -- rock field ---------------------------------------------------------------------------
    def _generate_rockfield(self, bundle: str) -> str | None:
        """Spatial-k Golombek rock field over the REAL DEM window around the resolved spawn, written as
        a scene-frame clast JSON for ``viz2_root.gd --clasts``. Real data only (boulders drawn from the
        sourced size-frequency law over the real heightfield's morphology). Best-effort: any failure ->
        no rocks and the drive still works."""
        # the runtime now seeds the rock field, SETS it on its WorkSite (physics ride-over/block), and
        # writes clasts.json into the session dir -- prefer that ONE source so a rock seen == a rock felt.
        _rt = os.path.join(self.session_dir, "clasts.json")
        if os.path.isfile(_rt):
            return _rt
        if self.cfg.get("mode") != "real":
            return None
        try:
            import importlib.util
            tok = json.loads(Path(self.session_dir, "viz2_session.json").read_text().splitlines()[0])
            sx, sy = tok["start_xy"]
            x0, y0, cell = tok["world_x0"], tok["world_y0"], tok["base_cell_m"]
            bw, bh = int(tok["base_w"]), int(tok["base_h"])
            n = max(8, min(int(round(140.0 / cell)), bw, bh))       # ~140 m field around the spawn
            c0 = int(min(max(0, round((sx - x0) / cell - n / 2)), bw - n))
            r0 = int(min(max(0, round((sy - y0) / cell - n / 2)), bh - n))
            spec = importlib.util.spec_from_file_location(
                "viz2_rockfield_clasts", str(REPO_ROOT / "scripts" / "viz2_rockfield_clasts.py"))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            result = mod.build_clasts(bundle, r0, c0, n, d_min_m=0.15, d_max_m=0.8, world_seed=0)
            out = os.path.join(self.session_dir, "clasts.json")
            with open(out, "w") as fh:
                json.dump(result, fh)
            n_clasts = len(result.get("clasts", []))
            print("viz2-stream: rock field seeded — %d clasts over [%d:%d,%d:%d]"
                  % (n_clasts, r0, r0 + n, c0, c0 + n), flush=True)
            return out if n_clasts > 0 else None
        except Exception as exc:
            print("viz2-stream: rock field skipped (%s: %s)" % (type(exc).__name__, exc), flush=True)
            return None

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

        # 2b) seed the DISPLAY rock field (spatial-k Golombek over the REAL DEM) around the resolved
        #     spawn the runtime just wrote, so the drive view shows real-statistics boulders.
        clasts_path = self._generate_rockfield(bundle)

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
        if clasts_path:
            args += ["--clasts", clasts_path]
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
    async def _read_seam(self) -> None:
        """Drain frames from the Godot seam as fast as they arrive into a single-slot LATEST buffer, so a
        slow browser never backpressures the seam TCP -> the Godot render/ack loop -> the terminal
        deadman. Stale frames are simply overwritten (drop-latest). (council #5)"""
        assert self._reader is not None
        while True:
            try:
                frame = await read_frame(self._reader)
            except (asyncio.IncompleteReadError, ConnectionResetError):
                break  # Godot closed the seam
            # discriminate a small JSON STATUS frame (slip/entrapment/pose) from a JPEG frame with zero
            # wire change: a JPEG always starts 0xFF 0xD8 (SOI), a status object starts '{'. (council #8)
            if frame[:1] == b"{":
                self._latest_status = frame
            else:
                self._latest_frame = frame
            self._frame_evt.set()

    async def _send_ws(self, ws: WebSocket) -> None:
        """Deliver the freshest frame + any pending status to the browser. If the browser link is slow
        this task lags, but the seam reader keeps draining, so only the LATEST frame is sent."""
        while True:
            await self._frame_evt.wait()
            self._frame_evt.clear()
            status = self._latest_status
            self._latest_status = None
            frame = self._latest_frame
            self._latest_frame = None
            if status is not None:
                await ws.send_text(status.decode("utf-8", "replace"))
            if frame is not None:
                await ws.send_bytes(frame)

    async def _watch_procs(self, ws: WebSocket) -> None:
        """End the session (and tell the browser) if the runtime or Godot exits early -- otherwise a dead
        runtime streams a frozen sim for minutes with no signal (RUNTIME_SECONDS gap). (council #6)"""
        while True:
            await asyncio.sleep(1.0)
            rc_s = self._serve.returncode if self._serve is not None else None
            rc_g = self._godot.returncode if self._godot is not None else None
            if rc_s is not None or rc_g is not None:
                who = "runtime" if rc_s is not None else "renderer"
                try:
                    await ws.send_text(json.dumps({"type": "error",
                                                   "error": f"{who} exited (session ended)"}))
                except Exception:
                    pass
                return

    async def pump_input(self, ws: WebSocket) -> None:
        assert self._writer is not None
        if self._bag_t0 is None:
            self._bag_t0 = time.monotonic()
        while True:
            raw = await ws.receive_text()
            # server-side control verb: SAVE the recorded session bag (not forwarded to Godot)
            obj: object = None
            try:
                obj = json.loads(raw)
            except (ValueError, TypeError):
                obj = None
            if isinstance(obj, dict) and obj.get("save"):
                name = self._save_bag(str(obj.get("save")))
                await ws.send_text(json.dumps({"type": "saved", "name": name,
                                               "commands": len(self._bag) - 1}))
                continue
            cmd = protocol.normalize_input(raw)
            if not cmd:
                continue
            # record (timestamped) THEN forward — the bag replays byte-for-byte
            self._bag.append({"t": max(0.0, time.monotonic() - self._bag_t0), "cmd": cmd})
            self._writer.write(pack_frame(json.dumps(cmd).encode()))
            await self._writer.drain()

    def _save_bag(self, name: str) -> str:
        """Persist the recorded command bag (config + timestamped control frames) to out/viz2_bags/."""
        safe = _safe_bag_name(name)
        BAGS_DIR.mkdir(parents=True, exist_ok=True)
        dur = float(self._bag[-1]["t"]) if len(self._bag) > 1 else 0.0
        payload = {"config": self._bag[0]["config"], "duration_s": dur,
                   "n_commands": len(self._bag) - 1, "events": self._bag[1:]}
        with open(BAGS_DIR / (safe + ".json"), "w") as fh:
            json.dump(payload, fh)
        return safe

    async def pump_playback(self, events: list[dict]) -> None:
        """Replay a saved bag's control frames to Godot at their recorded relative timestamps — the
        deterministic record->replay seam. Frames keep streaming (pump_frames) so the browser watches
        the replay; after the last command the session holds until the browser disconnects."""
        assert self._writer is not None
        t0 = time.monotonic()
        for ev in events:
            wait = float(ev.get("t", 0.0)) - (time.monotonic() - t0)
            if wait > 0:
                await asyncio.sleep(min(wait, 30.0))
            cmd = ev.get("cmd")
            if isinstance(cmd, dict) and cmd:
                self._writer.write(pack_frame(json.dumps(cmd).encode()))
                await self._writer.drain()
        while True:                             # hold the replayed session open for viewing
            await asyncio.sleep(3600)

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

# Public-exposure guard: token auth (when VIZ2_STREAM_TOKEN is set) + per-IP connection rate-limit.
# No-op for the token gate when the env var is unset (tailnet mode behaves exactly as before); the
# rate-limit + concurrency cap are always-on GPU protections. The WS /ws is guarded in its endpoint.
security.install_http_guard(app)

# Self-hosted three.js + any other static asset (NO external CDN, so the setup screen works on the
# tailnet). StaticFiles blocks path escapes; the vendored three.module.min.js lives under vendor/.
# /vendor/* is EXEMPT from the token gate (see security._is_exempt) so the ES-module import works
# from a single ?token=T link without rewriting the import URL.
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


@app.get("/bags")
async def bags_list() -> dict:
    """Saved command bags (record/replay): name, duration, command count, and the recorded site/mode."""
    rows = []
    if BAGS_DIR.is_dir():
        for p in sorted(BAGS_DIR.glob("*.json")):
            try:
                b = json.loads(p.read_text())
                cfg = b.get("config") or {}
                rows.append({"name": p.stem, "duration_s": round(float(b.get("duration_s", 0.0)), 1),
                             "n_commands": int(b.get("n_commands", 0)),
                             "site": cfg.get("site"), "mode": cfg.get("mode")})
            except (ValueError, OSError):
                continue
    return {"bags": rows}


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
    # 0) public-exposure guard: token + per-IP rate-limit (accepts the socket, or closes 4401/4429).
    if not await security.ws_guard_admit(ws):
        return
    # 1) the first message is either the session config, or {play: <bag>} to REPLAY a saved bag
    playback_events: list | None = None
    try:
        cfg_raw = await ws.receive_text()
        try:
            first = json.loads(cfg_raw)
        except (ValueError, TypeError):
            first = None
        if isinstance(first, dict) and first.get("play"):
            bag = _load_bag(str(first["play"]))
            cfg = protocol.parse_config(json.dumps(bag.get("config") or {}))
            playback_events = list(bag.get("events") or [])
        else:
            cfg = protocol.parse_config(cfg_raw)
    except WebSocketDisconnect:
        return
    except FileNotFoundError:
        await ws.send_text(json.dumps({"type": "error", "error": "bag not found"}))
        await ws.close(code=1003)
        return
    except protocol.ConfigError as exc:
        await ws.send_text(json.dumps({"type": "error", "error": str(exc)}))
        await ws.close(code=1003)
        return

    # 2) concurrency cap: reserve a live-GPU session slot BEFORE spawning Godot/Viz2Runtime. The
    #    (cap+1)th connection is refused with an at-capacity close and NO GPU process is spawned.
    if not security.acquire_session():
        await ws.send_text(json.dumps({"type": "error", "error": "at capacity, try again shortly"}))
        await ws.close(code=security.WS_CLOSE_AT_CAPACITY, reason="at capacity")
        return

    try:
        session = StreamSession(cfg)
        try:
            # Start; report failure BEST-EFFORT (the browser may already be gone) but ALWAYS fall
            # through to the outer finally -> session.stop(), so a disconnect during the up-to-90s Godot
            # connect wait can never leak the GPU process / tmpdir. (council #6)
            try:
                await session.start()
            except Exception as exc:  # bundle / runtime / godot launch failure
                try:
                    await ws.send_text(json.dumps({"type": "error",
                                                   "error": f"{type(exc).__name__}: {exc}"}))
                    await ws.close(code=1011)
                except Exception:
                    pass
                return
            try:
                await ws.send_text(json.dumps({"type": "ready", "mode": cfg["mode"],
                                               "site": cfg.get("site"), "fine_cell_m": cfg["fine_cell_m"]}))
                if playback_events is not None:
                    await ws.send_text(json.dumps({"type": "playback",
                                                   "commands": len(playback_events)}))
            except Exception:
                return

            # frame egress is decoupled: a fast drop-latest seam reader + a separate ws sender, so a slow
            # browser can never backpressure the render/ack loop into the terminal deadman. A monitor task
            # ends the session if the runtime/renderer dies early.
            reader = asyncio.create_task(session._read_seam())
            sender = asyncio.create_task(session._send_ws(ws))
            monitor = asyncio.create_task(session._watch_procs(ws))
            if playback_events is not None:
                inputs = asyncio.create_task(session.pump_playback(playback_events))
            else:
                inputs = asyncio.create_task(session.pump_input(ws))
            tasks = {reader, sender, monitor, inputs}
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            except WebSocketDisconnect:
                pass
            finally:
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await session.stop()          # ALWAYS stop, even if start() returned early (no leak)
            try:
                await ws.close()
            except Exception:
                pass
    finally:
        # always free the reserved GPU slot, whatever tore the session down.
        security.release_session()
