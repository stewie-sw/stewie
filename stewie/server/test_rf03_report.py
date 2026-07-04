"""[REQ:RF-03] the first migrated React pane (Report) binds the REAL backend contract (/world + /world/
transactions) through the fixture-state convention. This asserts the response keys ReportPane reads are
present + the 4-state convention (loading/error/empty/ready) is declared. Real endpoints; no synthetic data."""
import os

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def test_rf03_report_binds_the_world_contract(monkeypatch):  # [REQ:RF-03]
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    c = TestClient(app, base_url="http://127.0.0.1")
    w = c.get("/world")
    assert w.status_code == 200, w.text
    body = w.json()
    assert "world" in body and "layer_manifest" in body   # the keys ReportPane reads
    t = c.get("/world/transactions?limit=20")
    assert t.status_code == 200 and "transactions" in t.json()   # the timeline the pane lists


def test_rf03_state_convention_declares_all_four_fixture_states():  # [REQ:RF-03]
    src = open(os.path.join(_ROOT, "frontend", "src", "fetchState.ts"), encoding="utf-8").read()
    for state in ("loading", "error", "empty", "ready"):
        assert f'"{state}"' in src, f"the RF-03 ResourceState convention is missing the {state!r} state"
    rep = open(os.path.join(_ROOT, "frontend", "src", "panes", "Report.tsx"), encoding="utf-8").read()
    assert "useResource" in rep and "data-state" in rep   # the pane renders via the state convention


def test_rf03_migrated_report_binds_the_same_evidence_as_vanilla():  # [REQ:RF-03] parity vs the vanilla pane
    react = open(os.path.join(_ROOT, "frontend", "src", "panes", "Report.tsx"), encoding="utf-8").read()
    vanilla = open(os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js"), encoding="utf-8").read()
    # the migrated React Report binds the SAME backend evidence source (the world-transaction timeline) that
    # the vanilla loadReport fetches -- structural parity before the pane can flip.
    assert "/world/transactions" in react and "/world/transactions" in vanilla
