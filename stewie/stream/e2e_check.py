"""REAL end-to-end check for the viz2 pixel-stream (NOT part of the fast suite — timeout-wrap it).

Starts the FastAPI stream server, connects a real ``websockets`` client, sends a config for the real
``haworth_sfs_2km_1m`` bundle + a forward twist, receives >=5 JPEG frames, and asserts each decodes to
a NON-BLACK terrain raster AND that the frames CHANGE across the drive (mean-abs pixel diff above a
liveness threshold — the rover/pose moved). Exercises the whole live loop end-to-end: browser WS ->
server -> Godot(--live --stream, xvfb+vulkan on the host GPU) -> Viz2Runtime -> frames back.

Run (timeout-wrapped so it can never hang a gate):
    timeout 300 .venv/bin/python -m stewie.stream.e2e_check
Exit 0 on PASS, 1 on FAIL/ERROR. Prints the exact blocker + the Godot/server log paths on failure.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PORT = int(os.environ.get("STEWIE_STREAM_E2E_PORT", "8917"))
SCRATCH = Path(os.environ.get("STEWIE_STREAM_LOGDIR", "/tmp")) / "viz2_stream_e2e"


def _subproc_env() -> dict[str, str]:
    env = dict(os.environ)
    extra = [str(REPO_ROOT), str(REPO_ROOT / "packages" / "stewie-bodies"),
             str(REPO_ROOT / "packages" / "stewie-forge")]
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra + ([prev] if prev else []))
    env.setdefault("STEWIE_GODOT", "/mnt/projects/tools/Godot_v4.6.3-stable_linux.x86_64")
    env.setdefault("STEWIE_GODOT_PROJECT", str(REPO_ROOT / "stewie" / "godot"))
    return env


def _decode(buf: bytes) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(io.BytesIO(buf)).convert("RGB"))


async def _recv_n_frames(ws, want: int, first_timeout: float, frame_timeout: float) -> list[bytes]:
    frames: list[bytes] = []
    timeout = first_timeout
    while len(frames) < want:
        msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
        if isinstance(msg, str):
            m = json.loads(msg)
            if m.get("type") == "error":
                raise RuntimeError(f"server reported error: {m.get('error')}")
            # 'ready' or other control text — keep waiting for binary frames
            continue
        frames.append(bytes(msg))
        timeout = frame_timeout
    return frames


async def run_check(port: int = DEFAULT_PORT, site: str = "haworth_sfs_2km_1m",
                    want: int = 6) -> dict:
    import websockets
    uri = f"ws://127.0.0.1:{port}/ws"
    # if the public-exposure guard is on (VIZ2_STREAM_TOKEN set), pass the token so /ws admits us;
    # unset -> connect exactly as before (the guard is off). /healthz is exempt, so the readiness
    # poll needs no token either way.
    token = os.environ.get("VIZ2_STREAM_TOKEN", "")
    if token:
        uri += f"?token={token}"
    async with websockets.connect(uri, max_size=None, open_timeout=20) as ws:
        await ws.send(json.dumps({"mode": "real", "site": site, "sun": {"az": 135, "el": 18}}))
        await ws.send(json.dumps({"v": 1.0, "omega": 0.12}))   # drive forward + gentle left
        raw = await _recv_n_frames(ws, want, first_timeout=120.0, frame_timeout=25.0)

    arrs = [_decode(b) for b in raw]
    means = [float(a.mean()) for a in arrs]
    # each frame must be a real, non-black terrain raster
    for i, (b, a, mu) in enumerate(zip(raw, arrs, means)):
        assert b[:2] == b"\xff\xd8", f"frame {i} is not JPEG (missing FFD8)"
        assert a.size > 0, f"frame {i} decoded empty"
        assert mu > 5.0, f"frame {i} is (near) black (mean={mu:.2f}) — no terrain rendered"
    # frames must CHANGE across the drive (the rover/pose moved)
    n = min(arrs[0].shape[0], arrs[-1].shape[0])
    m = min(arrs[0].shape[1], arrs[-1].shape[1])
    diff = float(np.abs(arrs[0][:n, :m].astype(np.int16) - arrs[-1][:n, :m].astype(np.int16)).mean())
    assert diff > 1.0, f"frames did not change under drive (mean-abs diff={diff:.4f})"
    return {"frames": len(raw), "sizes": [a.shape for a in arrs],
            "means": [round(x, 2) for x in means], "first_last_diff": round(diff, 3),
            "bytes": [len(b) for b in raw]}


def _wait_healthz(port: int, timeout: float = 20.0) -> bool:
    import httpx
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def main() -> int:
    port = DEFAULT_PORT
    SCRATCH.mkdir(parents=True, exist_ok=True)
    srv_log = SCRATCH / "server.log"
    env = _subproc_env()
    log_fh = open(srv_log, "wb")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "stewie.stream.app:app",
         "--host", "0.0.0.0", "--port", str(port), "--ws", "websockets"],
        cwd=str(REPO_ROOT), env=env, stdout=log_fh, stderr=subprocess.STDOUT,
        start_new_session=True)
    try:
        if not _wait_healthz(port):
            print(f"E2E FAIL: stream server never became healthy on :{port} (see {srv_log})")
            return 1
        print(f"E2E: server up on :{port}; connecting websocket + driving the real Haworth sim…")
        t0 = time.monotonic()
        stats = asyncio.run(run_check(port))
        dt = time.monotonic() - t0
        print(f"E2E PASS in {dt:.1f}s: {json.dumps(stats)}")
        print(f"       server log: {srv_log}")
        return 0
    except Exception as exc:
        print(f"E2E FAIL: {type(exc).__name__}: {exc}")
        print(f"       server log (Godot/runtime stderr rides here): {srv_log}")
        return 1
    finally:
        try:
            os.killpg(os.getpgid(server.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(server.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        log_fh.close()


if __name__ == "__main__":
    raise SystemExit(main())
