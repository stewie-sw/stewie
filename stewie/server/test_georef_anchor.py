"""#audit-2b: /dem/georef exposes the work area's TRUE anchor origin (the flattest buildable patch the
inset + planner use), so the cockpit can draw the WORK AREA rect THERE instead of the tile's (0,0) corner
(which sat ~8 km away -- the "work area stuck in the top-left" bug). Uses the REAL Haworth bundle."""
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("pyproj")


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")               # loopback dev-open -> require_auth passes
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_georef_returns_the_flattest_anchor_origin(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    g = c.get("/dem/georef", params={"site": "haworth"})
    assert g.status_code == 200, g.text
    j = g.json()
    assert j["ok"] and isinstance(j.get("anchor_xy"), list) and len(j["anchor_xy"]) == 2
    # it must equal the origin state.moon_dem hands the inset/planner (the flattest anchor), NOT (0,0)
    from stewie.server import state
    _dem, origin = state.moon_dem("haworth")
    assert abs(j["anchor_xy"][0] - float(origin[0])) < 1e-6
    assert abs(j["anchor_xy"][1] - float(origin[1])) < 1e-6
    assert j["anchor_xy"] != [0.0, 0.0]                      # Haworth's flattest patch is NOT the tile corner


def test_anchor_lonlat_differs_from_the_tile_corner(monkeypatch, tmp_path):
    """The rect drawn at the anchor must be a DIFFERENT place than the old (0,0)-corner rect -- proving the
    fix actually moves the work area to where the inset is."""
    c = _client(monkeypatch, tmp_path)
    ox, oy = c.get("/dem/georef", params={"site": "haworth"}).json()["anchor_xy"]
    corner = c.get("/dem/site_lonlat", params={"x": 0, "y": 0, "site": "haworth"}).json()
    anchor = c.get("/dem/site_lonlat", params={"x": ox, "y": oy, "site": "haworth"}).json()
    assert corner["ok"] and anchor["ok"]
    # >0.05 deg lat apart (~1.5 km) -- the old rect was genuinely far from the real work area
    assert abs(anchor["lat"] - corner["lat"]) > 0.05
