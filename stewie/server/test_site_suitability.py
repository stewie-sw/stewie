"""SS-01 SITE-SURVEY SUITABILITY: a per-site landing/construction suitability SCORE that AGGREGATES
the REAL FORGE costmap (the same passability the planner routes on) over the site's framed work-area crop,
plus the binding constraint (the dominant veto reason) and the descriptive terrain sub-fields
(slope / roughness / bearing / traction / sinkage). Every value is composed from the real site DEM via the
SAME producers the map drapes + the GW-07 point inspector use (_costmap_compose / _terra_fields /
slope_deg_map / costmap_layers._roughness); nothing here fabricates a reading -- the score is literally the
fraction of the real work-area cells that pass the real physics gates, so there is no invented weighting.

Backend contract for SS-01. The public GET /world/site-suitability is bindable by the keyless public /ide/
Mission-Plan panel (like /world/point). The panel binding is verified LIVE via Playwright by the main thread.
"""
import importlib
import math

import pytest
from fastapi.testclient import TestClient

# The veto reasons compose can attribute a blocked cell to (costmap_layers.BLOCKING_LEGEND_ORDER order).
_KNOWN_REASONS = {"slope", "sinkage", "tip_risk", "negative_obstacle", "psr", "keepout", "reservation"}
_GRADES = {"excellent", "good", "marginal", "poor", "unsuitable"}


def _assert_suitability_shape(d):
    """The SS-01 payload invariants -- asserted the SAME way for the direct producer and the route."""
    assert d["ok"] is True
    # score is 0..100 and is EXACTLY round(100 * suitable_fraction) -- no invented weighting.
    assert isinstance(d["score"], int) and 0 <= d["score"] <= 100
    sf = d["suitable_fraction"]
    assert isinstance(sf, float) and 0.0 <= sf <= 1.0
    assert d["score"] == round(100.0 * sf)
    assert d["grade"] in _GRADES
    # cell accounting: every cell is passable OR attributed to exactly one first-blocking reason.
    n = d["n_cells"]
    assert n > 0 and 0 <= d["n_suitable"] <= n
    assert d["n_suitable"] == round(sf * n)
    blk = d["blocking"]
    assert isinstance(blk, list)
    reasons = [b["reason"] for b in blk]
    assert set(reasons) <= _KNOWN_REASONS
    # blocked counts sum with the suitable count to the whole grid (mutually-exclusive first-blocking reason).
    # The COUNT accounting is EXACT; the fraction sum is only rounding-tolerant (each fraction is 6-decimal).
    assert sum(b["count"] for b in blk) == n - d["n_suitable"]
    assert abs(sf + sum(b["fraction"] for b in blk) - 1.0) < 1e-3
    # blocking is sorted by descending count, and the binding constraint is that head (or None if fully suitable).
    counts = [b["count"] for b in blk]
    assert counts == sorted(counts, reverse=True)
    if d["n_suitable"] == n:
        assert d["binding_constraint"] is None and blk == []
    else:
        assert d["binding_constraint"] == blk[0]["reason"]
    # descriptive sub-fields are REAL finite readings off the crop.
    f = d["fields"]
    for k in ("slope_deg", "roughness", "bearing_pa", "traction_margin", "sinkage_m"):
        assert k in f
        for _sk, _sv in f[k].items():
            assert isinstance(_sv, float) and math.isfinite(_sv)
    assert 0.0 <= f["traction_margin"]["mean"] <= 1.0
    assert f["slope_deg"]["max"] >= f["slope_deg"]["mean"] >= 0.0
    # provenance + grid + thresholds present (honest disclosure, no fabricated numbers).
    assert d["grid"]["rows"] > 0 and d["grid"]["cols"] > 0 and d["grid"]["cell_m"] > 0
    assert d["thresholds"]["max_slope_deg"] > 0
    assert isinstance(d["provenance"], str) and d["provenance"]


def test_producer_on_real_haworth_dem():  # SS-01
    """The producer runs on the REAL Haworth LOLA work-area crop and satisfies every accounting invariant."""
    from stewie.server import gis_layers as GL
    d = GL.site_suitability("haworth")
    _assert_suitability_shape(d)
    assert d["site"] == "haworth"
    # the framed work-area crop is the 128x128 @ 5 m frame (_work_area half=64).
    assert d["grid"]["rows"] == 128 and d["grid"]["cols"] == 128 and d["grid"]["cell_m"] == 5.0


def test_producer_unknown_site_raises():  # SS-01
    """An unknown/unimported site raises (KeyError/FileNotFoundError) so the route can 404 -- never a
    fabricated score for a site with no DEM bundle."""
    from stewie.server import gis_layers as GL
    with pytest.raises((KeyError, FileNotFoundError)):
        GL.site_suitability("no_such_site_xyz")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_TWINS", {})
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_route_is_public_no_key(client):  # SS-01
    """The public /ide/ Mission-Plan panel has no API key (nginx blanks the identity), so site-suitability
    MUST be reachable WITHOUT auth -- like /world/point, unlike the auth-gated /world (which 401s)."""
    assert client.get("/world?site=haworth").status_code == 401
    r = client.get("/world/site-suitability?site=haworth")
    assert r.status_code == 200, r.text
    _assert_suitability_shape(r.json())


def test_route_unknown_site_404(client):  # SS-01
    """A site with no DEM bundle on disk -> 404 (no fabricated score)."""
    r = client.get("/world/site-suitability?site=no_such_site_xyz")
    assert r.status_code == 404
    assert r.json()["ok"] is False
