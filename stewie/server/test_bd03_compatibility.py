"""[REQ:BD-03] the body-by-backend compatibility matrix (/physics/compatibility) behind the Plan/Models body
+ physics-backend selectors defers to the REAL rules: a gravity-loaded body validated for the backend is
supported; a MICROGRAVITY body (Bennu/Phobos) is REFUSED fail-closed (Bekker out-of-regime). Real endpoint +
real body registry; no synthetic data."""
import os

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_bd03_compatibility_matrix_regime_refusal(monkeypatch):  # [REQ:BD-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/physics/compatibility")
    assert r.status_code == 200, r.text
    j = r.json()
    be = j["backends"][0]                                   # tier2_numpy (the conserved Bekker backend)
    m = j["matrix"]
    assert m["moon"][be]["supported"] is True and m["moon"][be]["regime_ok"] is True
    for micro in ("bennu", "phobos"):                       # microgravity bodies are refused fail-closed
        assert m[micro][be]["supported"] is False
        assert m[micro][be]["regime_ok"] is False
        assert "microgravity" in m[micro][be]["reason"]


def test_bd03_soil_override_allows_analog(monkeypatch):  # [REQ:BD-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    j = c.get("/physics/compatibility?allow_analog=true").json()
    be = j["backends"][0]
    assert j["allow_analog"] is True
    # with the soil override a microgravity body is SUPPORTED via analog, but regime_ok stays False (caveated)
    assert j["matrix"]["bennu"][be]["supported"] is True
    assert j["matrix"]["bennu"][be]["regime_ok"] is False
    assert "analog" in j["matrix"]["bennu"][be]["reason"]


def test_bd03_models_pane_binds_the_compatibility_endpoint():  # [REQ:BD-03]
    pane = open(os.path.join(_ROOT, "frontend", "src", "panes", "Models.tsx"), encoding="utf-8").read()
    assert "/physics/compatibility" in pane and "useResource" in pane
    assert "physicsBackend" in pane                         # the physics-backend selector is wired to state
