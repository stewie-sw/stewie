"""#260b: /dem/workarea.png accepts a lat/lon origin OVERRIDE so the operator can move the work area off
the auto flattest-anchor. A re-anchored window renders a DIFFERENT patch than the default; a lat/lon
outside the tile falls back to the default anchor (never errors). REAL Haworth bundle, no synthetic data."""
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("pyproj")
pytest.importorskip("PIL")


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_workarea_reanchor_renders_a_different_patch(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    base = c.get("/dem/workarea.png", params={"site": "haworth", "kind": "dem"})
    assert base.status_code == 200 and base.headers["content-type"] == "image/png"
    # a lat/lon well inside the tile but away from the flattest anchor (-86.45,-25 -> origin ~7390,7805 vs
    # the default ~4115,6915) -> a different hillshade patch
    re = c.get("/dem/workarea.png", params={"site": "haworth", "kind": "dem", "lat": -86.45, "lon": -25.0})
    assert re.status_code == 200 and re.headers["content-type"] == "image/png"
    assert re.content != base.content                        # the window re-anchored to a different patch


def test_workarea_offtile_latlon_falls_back_to_default(monkeypatch, tmp_path):
    """A lat/lon outside the mapped tile must NOT 500 -- it falls back to the flattest anchor (== default)."""
    c = _client(monkeypatch, tmp_path)
    base = c.get("/dem/workarea.png", params={"site": "haworth", "kind": "dem"})
    off = c.get("/dem/workarea.png", params={"site": "haworth", "kind": "dem", "lat": 10.0, "lon": 100.0})
    assert off.status_code == 200
    assert off.content == base.content                       # off-tile -> default anchor, identical bytes
