"""B3: operator/director split sessions over the real closed-loop executive.

One server-side session = one run_closed_loop execution recorded leg-by-leg. The OPERATOR view is
telemetry-constrained (through stewie.bridge.telemetry) and truth-denylisted; the DIRECTOR view
(API-key gated) carries the full record + the seen-vs-actual debrief. Fast-forward never alters the
link accounting (B3.4).
"""
import importlib

import pytest
from fastapi.testclient import TestClient

TRUTH_DENY = {"true_J", "slip", "slope_deg", "true_energy_J"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "director-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    # the reload baked the monkeypatched env (REPORTS under tmp_path, auth key) into the CACHED
    # module -- later tests then 404 on reports (caught 2026-06-10: a cross-file ordering leak).
    # Undo the env FIRST, then restore a clean module for whoever imports it next.
    monkeypatch.undo()
    importlib.reload(srv)


def _mission():
    return {"name": "b3 session", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "cut", "kind": "cut", "x": 8, "y": 6, "footprint_m2": 16,
                        "depth_m": 0.05, "label": "pad"},
                       {"action": "fill", "kind": "fill", "x": 16, "y": 10, "footprint_m2": 12,
                        "depth_m": 0.2, "label": "berm"}],
            "profile": "mission_default"}


def test_session_start_runs_the_real_loop(client):
    r = client.post("/session/start", json=_mission(), headers={"X-API-Key": "director-key"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["ok"] and s["n_legs"] > 0 and "session_id" in s


def test_operator_view_is_truth_denylisted_and_link_constrained(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    op = client.get(f"/session/{sid}/operator")            # operator URL is OPEN (B3 contract)
    assert op.status_code == 200
    doc = op.json()
    for leg in doc["legs"]:
        assert not (TRUTH_DENY & set(leg)), f"truth leaked to the operator: {TRUTH_DENY & set(leg)}"
    assert doc["link"]["profile"] == "mission_default"
    assert doc["link"]["stats"]["sent"] + doc["link"]["stats"]["dropped"] >= doc["n_legs_total"] - 1


def test_debrief_requires_director_key_and_shows_divergence(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    assert client.get(f"/session/{sid}/debrief").status_code == 401
    d = client.get(f"/session/{sid}/debrief", headers={"X-API-Key": "director-key"})
    assert d.status_code == 200
    doc = d.json()
    assert len(doc["legs"]) == doc["n_legs_total"]
    leg = doc["legs"][0]
    assert "true_J" in leg and "nominal_J" in leg          # both tracks present
    assert "energy_divergence_J" in doc and doc["energy_divergence_J"] >= 0.0


def test_fast_forward_does_not_touch_link_accounting(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    before = client.get(f"/session/{sid}/operator").json()["link"]["stats"]
    client.get(f"/session/{sid}/debrief", params={"fast_forward": 10},
               headers={"X-API-Key": "director-key"})
    after = client.get(f"/session/{sid}/operator").json()["link"]["stats"]
    assert before == after


def test_unknown_session_404(client):
    assert client.get("/session/nope/operator").status_code == 404


def test_mission_summary_artifact(client):
    sid = client.post("/session/start", json=_mission(),
                      headers={"X-API-Key": "director-key"}).json()["session_id"]
    r = client.get(f"/session/{sid}/summary", headers={"X-API-Key": "director-key"})
    assert r.status_code == 200
    md = r.text
    for token in ("# Mission summary", "legs", "energy", "link", "divergence"):
        assert token in md, f"summary missing {token!r}"
    # the artifact persists for the debrief record
    import stewie.specs.config as CFG, os
    files = os.listdir(os.path.join(CFG.data_dir(), "sessions"))
    assert any(sid in f for f in files)


def test_t42_sessions_stamp_one_sun_state(client):
    """ARGUS T4.2: a session carries mission_t0; operator AND director views stamp the SAME sun
    (az/el from the one solar authority at that time) -- camera frames, shadow layers, and the
    debrief all agree on lighting."""
    r = client.post("/session/start", json={**_mission(), "mission_t0_s": 600000},
                    headers={"X-API-Key": "director-key"})
    sid = r.json()["session_id"]
    op = client.get(f"/session/{sid}/operator").json()
    db = client.get(f"/session/{sid}/debrief", headers={"X-API-Key": "director-key"}).json()
    assert op["sun"] == db["sun"]                         # one sun state, both views
    assert op["sun"]["mission_t0_s"] == 600000
    from stewie.specs.solar import sun_az_el
    az, el = sun_az_el(-87.45, 600000.0)
    assert op["sun"]["az_deg"] == pytest.approx(az) and op["sun"]["el_deg"] == pytest.approx(el)
