"""[REQ:FR-03] the Release + Execute complete authority-evidence panel. Clause 1: a released revision returns
every command-authority field (the 7-field FS-28 card the React Release pane renders). Clause 2: an ineligible
command surfaces its refusal reason, and the full /rc/eligibility gate set the panel binds is present. Real
endpoints + a real prepared mission's orders; no synthetic data."""
import os

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PANE = os.path.join(_ROOT, "frontend", "src", "panes", "Authority.tsx")


def test_fr03_released_revision_shows_every_authority_field(monkeypatch):  # [REQ:FR-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    sm = c.get("/sample_mission/01_flatten_pad").json()          # a REAL prepared mission (cut/fill orders)
    r = c.post("/executive/release-plan",
               json={"orders": sm["orders"], "mission_id": "fr03", "body": sm.get("body", "moon")})
    assert r.status_code == 200, r.text
    ca = r.json()["command_authority"]
    for f in ("plan_hash", "signed_by", "runtime_profile", "sensor_profile",
              "namespace", "authorized", "watchdog_deadline_s"):
        assert f in ca and ca[f] is not None, f"released revision missing authority field {f}"


def test_fr03_ineligible_surfaces_refusal_reason_and_full_gate_set(monkeypatch):  # [REQ:FR-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    e = c.get("/rc/eligibility").json()
    assert e["eligible"] is False and e["reason"]                # an ineligible command carries a reason
    for g in ("mode_ok", "sensor_fresh", "map_fresh", "covariance_ok",
              "watchdog_alive", "link_ack", "safe_inactive"):
        assert g in e, f"/rc/eligibility missing gate {g} the panel binds"


def test_fr03_authority_pane_binds_eligibility_and_release():  # [REQ:FR-03]
    src = open(_PANE, encoding="utf-8").read()
    assert "/rc/eligibility" in src and "useResource" in src     # the gate evidence
    assert "/executive/release-plan" in src and "command-authority" in src  # the sign-off card
