"""#264: POST /dem/asbuilt returns the AS-BUILT (deformed) terrain over the worked grid -- the conserved,
mass-balanced surface (real DEM + cut/fill delta) the 3D mesh renders so placing a cut/berm actually
transforms the topology (a cut lowers, a berm raises). REAL Haworth bundle, no synthetic terrain."""
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")               # loopback dev-open -> require_auth passes
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_cut_lowers_the_surface(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/dem/asbuilt", json={"body": "moon", "site": "haworth", "orders": [
        {"action": "Pad cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 100, "depth_m": 0.5}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["rows"] > 1 and j["cols"] > 1
    n = j["rows"] * j["cols"]
    assert len(j["z"]) == n and len(j["base"]) == n and len(j["delta"]) == n
    assert j["delta_min"] <= -0.4, f"a 0.5 m cut must lower the surface (delta_min={j['delta_min']})"
    assert j["mass_moved_kg"] > 0


def test_fill_raises_the_surface(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    # a cut loads the drum; an adjacent berm fill draws from it and RAISES that footprint
    r = c.post("/dem/asbuilt", json={"body": "moon", "site": "haworth", "orders": [
        {"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 100, "depth_m": 0.5},
        {"action": "berm", "kind": "fill", "x": 12, "y": 0, "footprint_m2": 25, "depth_m": 0.3}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["delta_max"] >= 0.2, f"a 0.3 m berm must raise the surface (delta_max={j['delta_max']})"


def test_no_buildable_orders_is_400(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.post("/dem/asbuilt", json={"body": "moon", "site": "haworth", "orders": [
        {"action": "wp1", "kind": "goto", "x": 5, "y": 5}]})  # only a waypoint -> nothing to build
    assert r.status_code == 400 and "cut or fill" in r.json()["error"]
