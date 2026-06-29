"""ArcGIS-G5 (#251): user-editable symbology / graduated renderer for the slope layer. The ramp max
(classification domain) and class count were hardcoded (slope/30, continuous) in gis_layers._layer_rgba;
this makes them operator-tunable -- ArcGIS's graduated-colors renderer (stretch vs N equal-interval
classes). Default (vmax=30, continuous) stays byte-identical. Uses a REAL Haworth DEM crop (no synthetic)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("pyproj")

from lode import mission_planner as MP
from stewie.server import gis_layers as G


def _patch():
    dem, cell = MP.load_haworth_dem()
    return np.asarray(dem)[:96, :96], float(cell)                    # a real DEM crop with relief


def test_default_symbology_is_unchanged():
    """The default call must equal explicit vmax=30, classes=0 -- the existing drape is not altered."""
    dem, cell = _patch()
    a = G._layer_rgba(dem, cell, "slope")
    b = G._layer_rgba(dem, cell, "slope", slope_vmax=30.0, slope_classes=0)
    assert np.array_equal(a, b)


def test_vmax_restretches_the_ramp():
    """A smaller ramp max saturates the ramp sooner: a tighter vmax must change the coloring, and a cell
    above vmax must be fully saturated (the reddest/most-opaque end)."""
    dem, cell = _patch()
    wide = G._layer_rgba(dem, cell, "slope", slope_vmax=30.0)
    tight = G._layer_rgba(dem, cell, "slope", slope_vmax=8.0)
    assert not np.array_equal(wide, tight)                            # the stretch changed the picture
    # at vmax=8, every cell steeper than 8 deg sits at the ramp top -> red ch 255, alpha 210 (60+195, 90+120)
    slope = np.degrees(np.arctan(np.hypot(*np.gradient(dem, cell)[::-1])))
    steep = slope >= 8.0
    assert steep.any()
    assert (tight[..., 0][steep] == 255).all() and (tight[..., 3][steep] == 210).all()


def test_classes_quantize_into_discrete_bands():
    """A classified renderer collapses the continuous ramp into <= N distinct colors."""
    dem, cell = _patch()
    cont = G._layer_rgba(dem, cell, "slope", slope_classes=0)
    classified = G._layer_rgba(dem, cell, "slope", slope_classes=4)
    assert len(np.unique(classified[..., 0])) <= 4                   # <= N distinct red levels (bands)
    assert len(np.unique(cont[..., 0])) > 4                          # continuous has many


def test_render_globe_vmax_is_in_the_cache_key():
    """Two ramp maxima must yield two different cached rasters (not a stale single entry)."""
    a, _ = G.render_globe("slope", slope_vmax=30.0)
    b, _ = G.render_globe("slope", slope_vmax=10.0)
    assert not np.array_equal(a, b)
    a2, _ = G.render_globe("slope", slope_vmax=30.0)                 # cache returns the SAME vmax=30 raster
    assert np.array_equal(a, a2)


# ---- route ---------------------------------------------------------------------------------------

def _client():
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_route_vmax_changes_the_png():
    c = _client()
    qs = {"site": "haworth"}
    base = c.get("/layers/globe/slope.png", params=qs)
    tight = c.get("/layers/globe/slope.png", params={**qs, "vmax": "8"})
    assert base.status_code == 200 and tight.status_code == 200
    assert base.content != tight.content                             # vmax flows through to the render


def test_route_classes_param_renders():
    c = _client()
    r = c.get("/layers/globe/slope.png", params={"site": "haworth", "classes": "5"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_route_clamps_out_of_range_symbology():
    """Absurd vmax/classes must not error or render unbounded -- clamped to sane bounds (200, not 500)."""
    c = _client()
    assert c.get("/layers/globe/slope.png", params={"site": "haworth", "vmax": "0", "classes": "999"}).status_code == 200
    assert c.get("/layers/globe/slope.png", params={"site": "haworth", "vmax": "1e9"}).status_code == 200


def test_route_nan_vmax_falls_back_to_default():
    """council MINOR-2: a NaN vmax must NOT produce a degenerate (all-zero) raster -- it falls back to the
    default 30 deg, so the result equals the default render."""
    c = _client()
    base = c.get("/layers/globe/slope.png", params={"site": "haworth"})
    nan = c.get("/layers/globe/slope.png", params={"site": "haworth", "vmax": "nan"})
    assert base.status_code == 200 and nan.status_code == 200
    assert base.content == nan.content                               # NaN -> default 30, not a blank tile


# ---- council MAJOR-1: the PIP-overlay raster path must honor the SAME symbology as the globe drape ----

def test_render_raster_default_unchanged():
    """render() (the /layers/raster PIP path) default must equal explicit vmax=30/classes=0 -- no regression."""
    assert G.render("slope") == G.render("slope", slope_vmax=30.0, slope_classes=0)


def test_render_raster_honors_vmax():
    """The PIP-overlay raster render reflects vmax (so it cannot disagree with the globe drape)."""
    assert G.render("slope", slope_vmax=8.0) != G.render("slope", slope_vmax=30.0)


def test_raster_route_vmax_changes_png(monkeypatch, tmp_path):
    """The /layers/raster/slope.png route threads vmax through (dev-open: the route is heavy_quota-gated)."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    base = c.get("/layers/raster/slope.png", params={"site": "haworth"})
    tight = c.get("/layers/raster/slope.png", params={"site": "haworth", "vmax": "8"})
    assert base.status_code == 200 and tight.status_code == 200
    assert base.content != tight.content
