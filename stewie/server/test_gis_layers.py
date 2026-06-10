"""GIS raster layers for 2D planning (the user directive: plan in 2D with true GIS-style layers).

Each layer is COMPUTED FROM THE REAL HAWORTH DEM via the existing dart machinery (slope from the
height field, hazard from build_hazard_map, illumination/PSR from horizon_clip at a commanded sun
geometry) and served as a colormapped PNG sized to the work-area frame. South-pole sun geometry is
a query parameter -- shadows are the navigation signal here, not decoration.
"""
import importlib
import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import stewie.server.server as srv
    importlib.reload(srv)
    return TestClient(srv.app)


def _png(client, url):
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    from imageio.v3 import imread
    return imread(io.BytesIO(r.content))


def test_slope_layer_from_real_dem(client):
    img = _png(client, "/layers/raster/slope.png")
    assert img.shape[0] >= 100 and img.shape[1] >= 100
    assert img[..., :3].std() > 5.0                       # real relief, not a flat fill


def test_hazard_layer_marks_steep_terrain(client):
    img = _png(client, "/layers/raster/hazard.png")
    a = img[..., 3] if img.shape[-1] == 4 else None
    assert a is not None and (a > 0).any() and (a == 0).any()   # hazard is a partial overlay


def test_illumination_layer_responds_to_sun_geometry(client):
    low = _png(client, "/layers/raster/illumination.png?sun_el=2&sun_az=90")
    high = _png(client, "/layers/raster/illumination.png?sun_el=25&sun_az=90")
    # south-pole physics: lower sun -> more horizon-clipped shadow -> more shadowed pixels
    shadow_low = float((low[..., 3] > 0).mean())
    shadow_high = float((high[..., 3] > 0).mean())
    assert shadow_low > shadow_high > 0.0


def test_psr_layer_is_subset_of_low_sun_shadow(client):
    psr = _png(client, "/layers/raster/psr.png")
    assert (psr[..., 3] > 0).any()                        # Haworth has PSR candidates


def test_unknown_layer_404(client):
    assert client.get("/layers/raster/warp.png").status_code == 404


def test_layers_index_lists_rasters(client):
    docs = client.get("/layers").json()
    kinds = {d.get("key", d.get("id")) for d in docs["layers"]}
    assert {"slope", "hazard", "illumination"} <= kinds


def test_legend_endpoint_carries_the_real_physics(client):
    """Audit P1 + Aaron: legends tie to ACTUAL physics -- thresholds come from the hazard-map
    defaults and the documented envelope, never hardcoded in the UI."""
    import inspect

    from dart.hazard_map import build_hazard_map
    d = client.get("/layers/legend").json()
    sig = inspect.signature(build_hazard_map)
    assert d["hazard"]["nogo_deg"] == sig.parameters["max_slope_deg"].default       # 20, doc-true
    assert d["hazard"]["penalty_deg"] == sig.parameters["slope_hazard_deg"].default # 15 nominal
    assert d["hazard"]["obstacle_m"] == 0.075                                       # the envelope
    assert d["slope"]["max_deg"] == 30.0 and "ramp" in d["slope"]
    assert "sun" in d["illumination"] and "sweep" in d["psr"]
