"""[REQ:MT-04] The package is split into lean dependency profiles: the DEFAULT install is base-only and the
`core` profile boots stewie-serve + /healthz WITHOUT the heavy CV/GIS/benchmark extras; each profile is
declared and `server` composes them (so the Dockerfile/wheel-smoke [server] extra is unchanged). Proven
against the REAL pyproject + a clean-subprocess import of the minimal server."""
import os
import subprocess
import sys
import tomllib

_HEAVY = ("opencv", "rasterio", "matplotlib", "torch", "trimesh", "imageio")


def _extras() -> dict:
    with open("pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["optional-dependencies"]


def test_mt04_profiles_declared_and_core_is_lean():  # [REQ:MT-04]
    ex = _extras()
    assert {"core", "perception", "planning", "server", "ros", "dev"} <= set(ex)
    core = " ".join(ex["core"]).lower()
    for heavy in _HEAVY:
        assert heavy not in core, f"core must stay lean; {heavy!r} leaked into it"
    # server COMPOSES the granular profiles (unchanged resolution for the Dockerfile/wheel-smoke product extra)
    joined = " ".join(ex["server"])
    assert "stewie[core]" in joined and "stewie[perception]" in joined and "stewie[planning]" in joined


def test_mt04_minimal_server_boots_lean_without_heavy_extras():  # [REQ:MT-04]
    # a CLEAN subprocess (no test pollution): importing the server + hitting /healthz must not import any
    # heavy CV/GIS/benchmark lib -- proving `pip install stewie[core]` yields a working, lean server.
    code = (
        "import sys; import stewie.server.server as S;"
        "from fastapi.testclient import TestClient;"
        "assert TestClient(S.app).get('/healthz').json()['status'] in ('ok','degraded');"
        "heavy=[m for m in ('cv2','rasterio','matplotlib','torch','trimesh') "
        "if m in sys.modules or any(k.startswith(m+'.') for k in sys.modules)];"
        "print('HEAVY:'+','.join(heavy)); sys.exit(1 if heavy else 0)"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "PYTHONNOUSERSITE": "1"})
    assert r.returncode == 0, f"minimal server + /healthz imported heavy libs: {r.stdout.strip()} {r.stderr[-400:]}"
