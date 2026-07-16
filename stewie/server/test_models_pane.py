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
    # REAL ML-01 / FS-12 governance: the deployment-ready gate + §25.3 no-command-path invariant. This is
    # the FS-12 model-integration/fine-tuning-hardening acceptance ON THE COCKPIT-FACING SURFACE (the
    # contract-object half -- deployment_ready False until every governed field is present, True when all
    # are, command_path=True rejected -- is asserted under [REQ:FS-12] in contracts/test_contracts.py). Here
    # the row's "before cockpit exposure" clause is verified: /models returns the governance criteria list
    # AND reports an honest EMPTY deployed_models (no learned model reaches the cockpit without the gate).
    g = j["model_governance"]  # [REQ:FS-12]
    assert g["command_path_enforced"] is True, "ModelArtifact command-path invariant not reported as enforced"
    assert len(g["deployment_ready_criteria"]) >= 6, "ML-01/FS-12 deployment-ready criteria not enumerated"
    assert g["deployed_models"] == [], "no learned model should be deployed/cockpit-exposed on the command path"


def test_rl01_deployed_rl_policy_gate(client):
    """[REQ:RL-01] Deployed-RL-policy gate: no learned/RL capability may be called operational until the
    versioned ModelArtifact carries its FULL deployment set -- training/eval lineage recorded, typed I/O
    schemas (the model card's contract half), positive inference budgets, calibration, an OOD detector,
    and a deterministic fallback -- and sits OFF the command path (the §25.3 safety shield, rejected at
    validation, not merely at the gate). Training scripts/environments alone (stewie/envs/rover_env.py,
    validation/rl/) never satisfy this row: /models must report deployed_models == [] until a real
    artifact with all of the above exists."""
    from pydantic import ValidationError

    from stewie.contracts import ModelArtifact

    full = dict(model_id="rl_traverse", name="rl-traversability-policy", version="0.1.0",
                task="terrain_assess", dataset_lineage="lac", eval_split="val",
                input_schema="WorldState", output_schema="Traversability",
                latency_budget_ms=50.0, memory_budget_mb=512.0,
                calibrated=True, ood_detector=True, fallback="deterministic_planner")
    assert ModelArtifact(**full).deployment_ready is True     # the gate is satisfiable, not vacuous
    # each required condition dropped IN TURN -> the artifact may exist, but is NOT deployment_ready:
    for drop in (dict(dataset_lineage=""), dict(eval_split=""),         # training/eval lineage
                 dict(input_schema=""), dict(output_schema=""),         # typed I/O contract (model card)
                 dict(latency_budget_ms=0.0), dict(memory_budget_mb=0.0),
                 dict(calibrated=False),
                 dict(ood_detector=False),                              # OOD acceptance leg
                 dict(fallback=None)):                                  # deterministic fallback (no rollback_to either)
        assert ModelArtifact(**{**full, **drop}).deployment_ready is False, \
            f"deployment_ready held without {drop} -- the RL-01 gate leaks"
    with pytest.raises(ValidationError):                                # §25.3 shield: rejected outright
        ModelArtifact(**{**full, "command_path": True})
    # the live governance surface: the lineage criteria are enumerated and NOTHING is operational.
    g = client.get("/models").json()["model_governance"]
    assert any("lineage" in c for c in g["deployment_ready_criteria"]), \
        "training/eval lineage is not an enumerated deployment-ready criterion"
    assert g["deployed_models"] == [], "an RL/learned model is reported operational without the RL-01 artifact set"


def test_models_endpoint_is_operator_gated(monkeypatch):
    # no key configured and NOT dev-open -> the privileged route is locked (fail-closed).
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    locked = TestClient(SRV.app)
    r = locked.get("/models")
    assert r.status_code in (401, 403, 503), f"models route is not auth-gated (got {r.status_code})"
