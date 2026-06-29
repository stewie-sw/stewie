"""ArcGIS-G2 (#249): persisted VALUE-raster products + map-algebra. The globe analysis layers are RGBA
renders; this adds the data product -- a slope VALUE raster (degrees) as a georeferenced COG (GeoTIFF),
plus a reclassify map-algebra option (ArcGIS Slope + Reclassify). Computed from the REAL Haworth DEM;
auth-gated like the other exports (#246 operational-data egress). rasterio-backed (honest 503 if absent)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("rasterio")
pytest.importorskip("pyproj")
import rasterio

from lode import gis_export as GE
from lode import mission_planner as MP


def _client(monkeypatch, tmp_path, *, dev_open=True):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    if dev_open:
        monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    else:
        monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


# ---- pure functions (unit) ----------------------------------------------------------------------

def test_slope_value_array_is_degrees_with_real_relief():
    arr = GE.slope_value_array(MP.load_haworth_dem())
    assert arr.dtype == np.float32
    assert float(arr.min()) >= 0.0 and float(arr.max()) <= 90.0       # slope is a [0,90] degree field
    assert float(arr.std()) > 1.0                                     # real Haworth relief, not flat fill


def test_reclassify_digitizes_by_ascending_breaks():
    a = np.array([0.0, 5.0, 12.0, 25.0, 40.0], dtype="float32")
    out = GE.reclassify(a, [10.0, 20.0, 30.0])
    assert out.dtype == np.int32
    assert list(out) == [0, 0, 1, 2, 3]                               # class = #breaks strictly below value
    with pytest.raises(ValueError):
        GE.reclassify(a, [20.0, 10.0])                                # non-ascending breaks rejected


def test_reclassify_maps_nan_to_nodata_not_top_class():
    """A nodata (NaN) cell must become the -1 sentinel, NOT the highest class (np.digitize sorts NaN
    above every bin). Latent on the clean Haworth tile; live for any imported DEM with nodata holes."""
    out = GE.reclassify(np.array([5.0, np.nan, 25.0], dtype="float32"), [10.0, 20.0])
    assert list(out) == [0, -1, 2]                                   # NaN -> -1, not class 2


def test_value_raster_cog_is_single_band_georeferenced_geotiff(tmp_path):
    out = str(tmp_path / "slope.tif")
    GE.value_raster_cog(MP.load_haworth_dem(), out, "slope", bundle_dir=MP.bundle_for_site("haworth"))
    with rasterio.open(out) as src:
        assert src.count == 1 and src.dtypes[0] == "float32"
        crs = str(src.crs)                                           # rasterio expands IAU_2015:30135 to WKT
        assert "Moon" in crs and "Polar_Stereographic" in crs        # the lunar south-polar-stereo CRS
        assert src.transform.a > 0                                    # a real pixel size (georeferenced)
        z = src.read(1)
        assert 0.0 <= float(z.min()) and float(z.max()) <= 90.0
        # georeferencing matches the DEM's own world bounds (catches a y0/y1 north-up swap)
        import json
        import os
        meta = json.load(open(os.path.join(MP._haworth_bundle(MP.bundle_for_site("haworth")), "metadata.json")))
        b = meta["world_bounds_m"]
        assert abs(src.bounds.left - b["x0"]) < 1e-6 and abs(src.bounds.top - b["y1"]) < 1e-6


def test_value_raster_cog_reclassified_is_integer_classes(tmp_path):
    out = str(tmp_path / "slope_rc.tif")
    GE.value_raster_cog(MP.load_haworth_dem(), out, "slope",
                        breaks=[10.0, 20.0, 30.0], bundle_dir=MP.bundle_for_site("haworth"))
    with rasterio.open(out) as src:
        assert src.dtypes[0] == "int32"
        assert set(np.unique(src.read(1))).issubset({0, 1, 2, 3})     # reclassify -> 4 classes


# ---- the route (integration) --------------------------------------------------------------------

def test_route_slope_cog_returns_geotiff(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/export/cog/slope.tif", params={"site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] in ("image/tiff", "image/tiff; application=geotiff")
    with rasterio.MemoryFile(r.content) as mf, mf.open() as src:
        assert src.count == 1 and src.dtypes[0] == "float32"
        assert "Moon" in str(src.crs) and "Polar_Stereographic" in str(src.crs)
        assert float(src.read(1).max()) <= 90.0


def test_route_reclassify_returns_integer_classes(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/export/cog/slope.tif", params={"site": "haworth", "breaks": "10,20,30"})
    assert r.status_code == 200, r.text
    with rasterio.MemoryFile(r.content) as mf, mf.open() as src:
        assert src.dtypes[0] == "int32"
        assert set(np.unique(src.read(1))).issubset({0, 1, 2, 3})


def test_route_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=False)               # no key, no dev-open -> locked
    assert c.get("/export/cog/slope.tif").status_code in (401, 403, 503)


def test_route_unknown_kind_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/export/cog/bogus.tif", params={"site": "haworth"}).status_code == 400


def test_route_bad_breaks_rejected(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/export/cog/slope.tif", params={"site": "haworth", "breaks": "30,20,10"}).status_code == 400
    assert c.get("/export/cog/slope.tif", params={"site": "haworth", "breaks": "a,b"}).status_code == 400


def test_route_unknown_site_errors_cleanly(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/export/cog/slope.tif", params={"site": "no-such-site-xyz"})
    assert r.status_code in (404, 503)                               # clean error, never a 500 or a fake raster


def test_route_rasterio_absent_is_honest_503(monkeypatch, tmp_path):
    """The no-stub rule's branch: if the rasterio backend is unavailable, the route reports 503 honestly
    rather than emitting a fake raster."""
    monkeypatch.setattr("lode.gis_export.cog_available", lambda: (False, "rasterio absent (test)"))
    c = _client(monkeypatch, tmp_path)
    r = c.get("/export/cog/slope.tif", params={"site": "haworth"})
    assert r.status_code == 503 and r.json()["ok"] is False
