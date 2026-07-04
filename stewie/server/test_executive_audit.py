"""[REQ:EG-07] The EG-07 audit trail is POPULATED by the LIVE executive flow (the noted integration follow-up
is now wired): a director SIM run appends a tamper-evident, verifiable audit record carrying all nine fields,
exposed read-only at /executive/audit."""
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]

_NINE = ("actor", "action", "timestamp", "location", "mode", "reason",
         "before_state", "after_state", "evidence")


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                    # dev-open -> director-authed
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_eg07_executive_run_appends_a_verified_audit_record(monkeypatch, tmp_path):  # [REQ:EG-07]
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text

    aud = c.get("/executive/audit")
    assert aud.status_code == 200, aud.text
    j = aud.json()
    assert j["verified"] is True                                 # the hash-chain is intact (tamper-evident)

    runs = [rec for rec in j["records"] if rec["action"] == "executive.run"]
    assert runs, "the SIM run did not append an executive.run audit record"
    last = runs[-1]
    for field in (*_NINE, "prev_hash", "record_hash"):
        assert last.get(field) not in ("", None), f"audit field {field!r} missing/empty"
    assert last["mode"] == "sim"                                 # SIM-labeled, never live
    assert last["after_state"] in ("completed", "safed")        # the real run terminal state
