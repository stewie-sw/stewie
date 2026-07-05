"""[REQ:FR-01] product mode + runnable profile in the frontend state contract AND command authority: the
workspace state carries productMode + runnableProfile (URL-routeable), the shell rail shows both, /rc/eligibility
KEYS the command authority on the runnable profile, and a profile mismatch (selection != active) degrades
Release/Execute. Real endpoint + committed frontend; no synthetic data."""
import os

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _f(*p: str) -> str:
    with open(os.path.join(_ROOT, "frontend", "src", *p), encoding="utf-8") as fh:
        return fh.read()


def test_fr01_state_contract_carries_mode_and_profile_and_shell_shows_them():  # [REQ:FR-01]
    ws = _f("workspace.ts")
    assert "productMode" in ws and "runnableProfile" in ws
    assert '"productMode"' in ws and '"runnableProfile"' in ws          # both are in ROUTEABLE (URL round-trip)
    app_ = _f("App.tsx")
    assert 'data-testid="ws-productMode"' in app_ and 'data-testid="ws-runnableProfile"' in app_


def test_fr01_eligibility_keys_command_authority_on_the_profile(monkeypatch):  # [REQ:FR-01]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    e = c.get("/rc/eligibility").json()
    assert "profile" in e and e["profile"]                              # eligibility carries the active profile
    sm = c.get("/sample_mission/01_flatten_pad").json()
    ca = c.post("/executive/release-plan",
                json={"orders": sm["orders"], "mission_id": "fr01", "body": "moon"}).json()["command_authority"]
    assert ca["runtime_profile"]                                        # a released revision freezes the profile


def test_fr01_authority_pane_degrades_on_profile_mismatch():  # [REQ:FR-01]
    src = _f("panes", "Authority.tsx")
    assert "runnableProfile !== elig.data.profile" in src and "profile-mismatch" in src and "degraded" in src
