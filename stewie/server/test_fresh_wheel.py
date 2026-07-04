"""WP0.6 (RB-06) — the GOLD acceptance: a fresh wheel installs and the server product runs.

Builds the wheel, installs `stewie[server]` into a CLEAN venv (proving the server extra carries every
import-time dependency), and in that venv imports the server + runs a real Mars plan (no DEM asset
needed) writing its report to a configurable $STEWIE_DATA_DIR. This is slow (a wheel build + a clean
network install ~2-3 min), so it is OPT-IN: set STEWIE_WHEEL_SMOKE=1 to run it (release/scheduled gate).
The fast import-graph proxy in test_server_install.py runs in standard CI every time.
"""
from __future__ import annotations

import glob
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import venv

import pytest

if os.environ.get("STEWIE_WHEEL_SMOKE") != "1":
    pytest.skip("fresh-wheel smoke is opt-in (slow + network); set STEWIE_WHEEL_SMOKE=1",
                allow_module_level=True)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Run inside the clean venv: server imports (fastapi), planner runs a Mars plan (matplotlib report),
# the report lands in the configured data dir, and the stewie-serve entrypoint resolves. No DEM, no httpx.
_SMOKE = r"""
import os
os.environ["STEWIE_DATA_DIR"] = os.environ["SMOKE_DATA"]
import stewie.server.server                       # FastAPI app builds -> server extra deps present
from stewie.server.server import main             # console_scripts: stewie-serve = server:main
assert callable(main)
import stewie                                      # registers the gym envs
from lode import mission_planner as MP
m = MP.mission_from_dict({"name": "wheel", "body": "mars", "charger": [0, 0],
                          "orders": [{"action": "pad", "kind": "cut", "x": 10, "y": 10,
                                      "footprint_m2": 9, "depth_m": 0.05}]})
pdf, md, totals = MP.run(m, stem="wheel_smoke")
assert os.path.exists(pdf) and pdf.startswith(os.environ["SMOKE_DATA"]), pdf
print("FRESH WHEEL OK")
"""


def test_fresh_wheel_server_runs(tmp_path):  # [REQ:PO-01]
    # stewie-serve runs after a fresh wheel install with the one documented [server] product extra
    dist = tmp_path / "dist"
    # build the stewie wheel + the two extracted standalone packages (stewie-bodies, stewie-forge) that the
    # stewie.specs.bodies / stewie.physics.terramechanics shims re-export (PO-17/PO-18), via pip's own backend.
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(dist), _REPO,
                    os.path.join(_REPO, "packages", "stewie-bodies"),
                    os.path.join(_REPO, "packages", "stewie-forge")],
                   check=True, capture_output=True, text=True)
    wheels = glob.glob(str(dist / "stewie-*.whl"))
    pkg_wheels = glob.glob(str(dist / "stewie_bodies-*.whl")) + glob.glob(str(dist / "stewie_forge-*.whl"))
    assert wheels, "wheel build produced no root .whl"
    assert len(pkg_wheels) == 2, f"expected stewie-bodies + stewie-forge wheels, got {pkg_wheels}"

    venv_dir = tmp_path / "venv"
    venv.create(str(venv_dir), with_pip=True)
    py = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "python")
    # CLEAN env for the clean venv: drop the parent's PYTHONPATH (points at the repo source),
    # PYTHONHOME/VIRTUAL_ENV, and PYTHONNOUSERSITE so the venv python resolves ITS OWN site-packages.
    clean = {k: v for k, v in os.environ.items()
             if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTHONNOUSERSITE")}
    subprocess.run([py, "-m", "pip", "install", "--quiet", f"{wheels[0]}[server]", *pkg_wheels],
                   check=True, capture_output=True, text=True, env=clean)

    env = {**clean, "SMOKE_DATA": str(tmp_path / "appdata")}
    r = subprocess.run([py, "-c", _SMOKE], env=env, capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, f"fresh-wheel smoke failed:\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    assert "FRESH WHEEL OK" in r.stdout
    # the report was written under the configured data dir, in the clean venv (not the source tree)
    assert glob.glob(str(tmp_path / "appdata" / "reports" / "wheel_smoke.*"))

    # [REQ:PO-01] the CLI itself: the installed `stewie-serve` script reports version + config surface
    # and the server BOOTS + serves /healthz from the wheel install (loopback, ephemeral port).
    serve = str(venv_dir / ("Scripts" if os.name == "nt" else "bin") / "stewie-serve")
    wheel_version = os.path.basename(wheels[0]).split("-")[1]     # stewie-<ver>-py3-none-any.whl
    v = subprocess.run([serve, "--version"], env=clean, capture_output=True, text=True)
    assert v.returncode == 0, f"stewie-serve --version failed:\nSTDOUT:\n{v.stdout}\nSTDERR:\n{v.stderr}"
    assert wheel_version in v.stdout, f"--version output {v.stdout!r} missing wheel version {wheel_version}"
    h = subprocess.run([serve, "--help"], env=clean, capture_output=True, text=True)
    assert h.returncode == 0, f"stewie-serve --help failed:\nSTDOUT:\n{h.stdout}\nSTDERR:\n{h.stderr}"
    assert "--port" in h.stdout and "--host" in h.stdout          # the CLI config surface is documented

    with socket.socket() as s:                                    # a free loopback port for the boot
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    boot_env = {**clean, "STEWIE_DATA_DIR": str(tmp_path / "appdata")}
    proc = subprocess.Popen([serve, "--port", str(port)], env=boot_env, cwd=str(tmp_path),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        body = None
        for _ in range(60):                                       # up to ~12 s for a cold uvicorn boot
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:
                    body = json.loads(resp.read().decode())
                break
            except OSError:
                time.sleep(0.2)
        if body is None:
            out = proc.communicate(timeout=10)[0] if proc.poll() is not None else ""
            raise AssertionError(f"stewie-serve never served /healthz (rc={proc.poll()}):\n{out}")
        assert body["status"] in ("ok", "degraded"), body
        assert body["version"] == wheel_version, body             # the INSTALLED dist answers, not source
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.environ["STEWIE_WHEEL_SMOKE"] = "1"
        test_fresh_wheel_server_runs(__import__("pathlib").Path(d))
        print("ok")
