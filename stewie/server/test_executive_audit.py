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


def test_mp07_executive_run_reports_a_plan_executability_card(monkeypatch, tmp_path):  # [REQ:MP-07]
    # the run carries the MP-07 plan-executability card: the 8 §30.3 preconditions derived from real state.
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    card = r.json()["executability"]
    assert set(card) == {"executable", "unmet", "preconditions"}
    pre = card["preconditions"]
    assert set(pre) == {"required_capabilities", "assigned_assets", "physics_score", "resource_budget",
                        "rehearsal_result", "safety_check", "approval_record", "rollback_abort_rule"}
    # a nominal dig on real Haworth: approved + rehearsed + conserved-scored gates provably hold
    assert pre["approval_record"] is True and pre["rehearsal_result"] is True and pre["physics_score"] is True
    assert isinstance(card["executable"], bool) and isinstance(card["unmet"], list)


def test_eg08_executive_run_reports_the_energy_reconciliation(monkeypatch, tmp_path):  # [REQ:EG-08]
    # the run reconciles predicted (budgeted) vs observed (slip-truth) energy -> EG-08 proposals.
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    rc = r.json()["reconciliation"]
    assert rc["quantity"] == "energy_J"
    assert set(rc) >= {"predicted", "observed", "residual", "implicates_model", "proposals"}
    assert isinstance(rc["proposals"], list)
    if rc["residual"] != 0.0:                                     # a real slip-energy surprise emits a proposal
        assert rc["proposals"], "a nonzero energy residual must emit a reconciliation proposal"
        assert all(p["state"] == "proposed" for p in rc["proposals"])   # walked OBSERVED->COMPARED->PROPOSED


def test_eg05_executive_run_mints_a_live_execution_token(monkeypatch, tmp_path):  # [REQ:EG-05]
    # a completed run meets all 6 training->live preconditions -> a signed LiveExecutionToken; a safed run none.
    c = _client(monkeypatch, tmp_path)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j["live_token"]
    if j["executability"]["preconditions"]["safety_check"]:      # completed-not-safed
        assert tok["issued"] is True and tok["signature"] and tok["mission_id"]   # all 6 met -> signed token
    else:
        assert tok["issued"] is False and tok["reason"]          # a safed run -> refused, with a reason
