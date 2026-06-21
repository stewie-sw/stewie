"""FS-03 wiring guard: the Models work area exists end-to-end -- the Models tab + #pane_models in the
served page, the models_render.js module loaded, and GET /models returning the REAL system-profile +
vehicle + body registries and the ML-01 model-deployment governance (not a placeholder shell). The pure
HTML builders are unit-tested in models_render.test.js (node:test); the live signed-in render is exercised
by scripts/cockpit_render.py. This is the fast static+route guard that the wiring is present and the
endpoint serves real data."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import stewie.server.server as SRV

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback in-process -> require_auth = dev-open (director)
    return TestClient(SRV.app)


def test_models_tab_and_pane_in_served_page():
    html = _read(_INDEX)
    assert 'data-view="models"' in html, "no Models tab in the work-area tab bar"
    assert 'id="pane_models"' in html, "no #pane_models container"
    assert 'id="vtab-models"' in html and 'data-minrole="operator"' in html, \
        "Models tab is not operator-gated (data-minrole)"
    # the pure renderer module is loaded BEFORE cockpit.js (it sets window.STEWIE_MODELS_RENDER)
    i_mod = html.find("/assets/models_render.js")
    i_cockpit = html.find("/assets/cockpit.js")
    assert i_mod != -1, "models_render.js is not loaded by index.html"
    assert i_mod < i_cockpit, "models_render.js must load before cockpit.js"


def test_cockpit_wires_the_models_view():
    js = _read(_COCKPIT)
    assert 'models: "pane_models"' in js, "VIEW_PANE has no models -> pane mapping"
    assert "function loadModels" in js, "no loadModels() renderer"
    assert "modelsProfilesHTML" in js and "modelsRegistriesHTML" in js and "modelsGovernanceHTML" in js, \
        "loadModels does not call the renderers"


def test_models_endpoint_serves_the_real_registries(client):
    r = client.get("/models")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    # REAL system-profile registry (specs/profiles.py): counts + sha256 + VERIFIED status.
    from stewie.specs import bodies as B
    from stewie.specs import profiles as P
    from stewie.specs import vehicles as VH
    assert j["profile_count"] == len(P.available_profiles()), "profile count != registry"
    pids = {p["id"] for p in j["profiles"]}
    assert P.DEFAULT_PROFILE_ID in pids, "default profile missing from the registry"
    p0 = j["profiles"][0]
    assert len(p0["sha256"]) == 64, "profile sha256 is not the real exact-bytes digest"
    assert p0["status"] in ("VERIFIED", "UNVERIFIED")
    assert p0["deployment_ready"] == (p0["status"] == "VERIFIED")
    # REAL vehicle + body registries with real counts:
    assert j["vehicle_count"] == len(VH.VEHICLES) and j["body_count"] == len(B.BODIES)
    assert "moon" in {b["id"] for b in j["bodies"]}
    moon = next(b for b in j["bodies"] if b["id"] == "moon")
    assert moon["g_m_s2"] > 0 and moon["provenance"], "body row is a placeholder (no real constants/provenance)"
    # REAL ML-01 governance: the deployment-ready gate + §25.3 no-command-path invariant.
    g = j["model_governance"]
    assert g["command_path_enforced"] is True, "ModelArtifact command-path invariant not reported as enforced"
    assert len(g["deployment_ready_criteria"]) >= 6, "ML-01 deployment-ready criteria not enumerated"
    assert g["deployed_models"] == [], "no learned model should be deployed on the command path"


def test_models_endpoint_is_operator_gated(monkeypatch):
    # no key configured and NOT dev-open -> the privileged route is locked (fail-closed).
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    locked = TestClient(SRV.app)
    r = locked.get("/models")
    assert r.status_code in (401, 403, 503), f"models route is not auth-gated (got {r.status_code})"
