"""ArcGIS-G1 (#248): STEWIE serves an OGC WMS 1.3.0 service over its already-rendered globe layers,
so any QGIS/ArcGIS client can consume them. GetCapabilities advertises the 7 layers + their lunar
selenographic bbox; GetMap honors an arbitrary BBOX/WIDTH/HEIGHT (real subsetting, not always-full-
extent) across CRS84 and EPSG:4326 axis orders. Public + per-IP rate-limited, matching the wrapped
globe drape (GIS-03). Uses the REAL haworth render (no synthetic data)."""
import io
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("pyproj")
pytest.importorskip("PIL")

from PIL import Image

_WMS = "{http://www.opengis.net/wms}"
_KINDS = ("dem", "slope", "hazard", "illumination", "incidence", "psr", "grid")


def _client():
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def _caps_bbox(root):
    """Pull the south-polar EX_GeographicBoundingBox off the first named child Layer."""
    for lyr in root.iter(f"{_WMS}Layer"):
        if lyr.find(f"{_WMS}Name") is not None:
            gb = lyr.find(f"{_WMS}EX_GeographicBoundingBox")
            if gb is not None:
                return {
                    "west": float(gb.findtext(f"{_WMS}westBoundLongitude")),
                    "east": float(gb.findtext(f"{_WMS}eastBoundLongitude")),
                    "south": float(gb.findtext(f"{_WMS}southBoundLatitude")),
                    "north": float(gb.findtext(f"{_WMS}northBoundLatitude")),
                }
    raise AssertionError("no named Layer with EX_GeographicBoundingBox in capabilities")


def test_getcapabilities_is_valid_wms_1_3_0_with_all_layers():
    c = _client()
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetCapabilities"})
    assert r.status_code == 200, r.text
    assert "xml" in r.headers["content-type"]
    root = ET.fromstring(r.content)
    assert root.tag == f"{_WMS}WMS_Capabilities"
    assert root.attrib.get("version") == "1.3.0"
    names = {e.text for e in root.iter(f"{_WMS}Layer") for e in [e.find(f"{_WMS}Name")] if e is not None}
    assert set(_KINDS).issubset(names)                       # every globe layer is advertised
    # CRS:84 is advertised so axis order is unambiguous; the lunar geographic CRS is declared (honesty).
    crss = {e.text for e in root.iter(f"{_WMS}CRS")}
    crs_join = " ".join(c for c in crss if c)
    assert "CRS:84" in crs_join or "CRS84" in crs_join       # WMS 1.3.0 lon/lat token is "CRS:84"
    assert any("IAU_2015" in (x or "") and "30100" in (x or "") for x in crss)
    bb = _caps_bbox(root)
    assert bb["south"] < bb["north"] <= -85.0                # a south-polar selenographic tile


def test_getmap_returns_png_of_requested_size():
    c = _client()
    root = ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content)
    bb = _caps_bbox(root)
    r = c.get("/ogc/wms", params={
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "slope",
        "CRS": "CRS84", "BBOX": f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}",
        "WIDTH": "128", "HEIGHT": "96", "FORMAT": "image/png"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    im = Image.open(io.BytesIO(r.content))
    assert im.size == (128, 96)                              # GetMap honored WIDTH x HEIGHT


def test_getmap_crs84_and_epsg4326_axis_orders_agree():
    """CRS84 BBOX is lon,lat; EPSG:4326 in WMS 1.3.0 is lat,lon. The SAME ground area requested both
    ways must return the SAME image -- the 1.3.0 axis-order rule is handled, not ignored."""
    c = _client()
    bb = _caps_bbox(ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content))
    common = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "dem",
              "WIDTH": "64", "HEIGHT": "64", "FORMAT": "image/png"}
    r84 = c.get("/ogc/wms", params={**common, "CRS": "CRS84",
                                    "BBOX": f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}"})
    r4326 = c.get("/ogc/wms", params={**common, "CRS": "EPSG:4326",
                                      "BBOX": f"{bb['south']},{bb['west']},{bb['north']},{bb['east']}"})
    assert r84.status_code == 200 and r4326.status_code == 200, (r84.text, r4326.text)
    assert r84.content == r4326.content                      # identical pixels => axis order correct


def test_getmap_subwindow_differs_from_full_extent():
    """The eastern and western halves must each differ from the full extent AND from each other --
    proves a real bbox crop (a one-pixel diff or an always-full-extent bug would not satisfy this)."""
    c = _client()
    bb = _caps_bbox(ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content))
    mid = (bb["west"] + bb["east"]) / 2.0
    common = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "dem",
              "CRS": "CRS84", "WIDTH": "80", "HEIGHT": "80", "FORMAT": "image/png"}
    full = c.get("/ogc/wms", params={**common, "BBOX": f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}"})
    east = c.get("/ogc/wms", params={**common, "BBOX": f"{mid},{bb['south']},{bb['east']},{bb['north']}"})
    west = c.get("/ogc/wms", params={**common, "BBOX": f"{bb['west']},{bb['south']},{mid},{bb['north']}"})
    assert full.status_code == east.status_code == west.status_code == 200
    assert full.content != east.content and full.content != west.content and east.content != west.content


def test_getmap_out_of_extent_is_fully_transparent():
    """A BBOX far off the south-polar tile must return a fully transparent PNG, not stale/garbage pixels."""
    c = _client()
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "dem",
                                  "CRS": "CRS84", "BBOX": "100,-10,110,-5", "WIDTH": "32", "HEIGHT": "32",
                                  "FORMAT": "image/png"})
    assert r.status_code == 200, r.text
    im = Image.open(io.BytesIO(r.content)).convert("RGBA")
    assert max(px[3] for px in im.getdata()) == 0            # alpha all zero -> nothing outside the tile


def test_getmap_rejects_non_1_3_0_version():
    """The service is 1.3.0-only: a 1.1.1 GetMap is refused (its EPSG:4326 axis order is lon,lat, so
    silently serving it would return the wrong window). A ServiceException, not a blank image."""
    c = _client()
    bb = _caps_bbox(ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content))
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap", "LAYERS": "dem",
                                  "CRS": "CRS84", "BBOX": f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}",
                                  "WIDTH": "16", "HEIGHT": "16", "FORMAT": "image/png"})
    assert r.status_code == 400 and "ServiceException" in r.text


def test_getmap_rejects_multiple_layers():
    """Multiple LAYERS must be refused (we do not composite), not silently reduced to the first."""
    c = _client()
    bb = _caps_bbox(ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content))
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "dem,slope",
                                  "CRS": "CRS84", "BBOX": f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}",
                                  "WIDTH": "16", "HEIGHT": "16", "FORMAT": "image/png"})
    assert r.status_code == 400 and "ServiceException" in r.text


def test_bad_request_returns_service_exception():
    c = _client()
    # unknown REQUEST -> a ServiceExceptionReport with a 400 (not a 200, not a 500)
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "Frobnicate"})
    assert r.status_code == 400 and "ServiceException" in r.text
    # GetMap with an unknown layer
    bb = "{},{},{},{}".format(-180, -90, 180, -85)
    r2 = c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetMap", "LAYERS": "bogus",
                                   "CRS": "CRS84", "BBOX": bb, "WIDTH": "16", "HEIGHT": "16",
                                   "FORMAT": "image/png"})
    assert "ServiceException" in r2.text
    # absurd WIDTH (DoS guard) -> ServiceException, not a multi-GB render
    r3 = c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetMap", "LAYERS": "dem",
                                   "CRS": "CRS84", "BBOX": bb, "WIDTH": "99999", "HEIGHT": "99999",
                                   "FORMAT": "image/png"})
    assert "ServiceException" in r3.text


def test_getmap_total_pixel_area_budget_rejects_within_per_dimension_cap():  # #288
    """Both WIDTH and HEIGHT individually within the per-dimension cap (<=4096) can STILL demand a multi-GB
    render when their PRODUCT is huge (4096x4096 builds ~7 float64 WxH meshgrids ~ 1 GB). On this PUBLIC,
    only IP-rate-limited route that is a memory DoS the per-dimension cap does not catch. A total
    pixel-area budget must reject it; a normal tile within the budget still renders."""
    c = _client()
    root = ET.fromstring(c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}).content)
    bb = _caps_bbox(root)
    box = f"{bb['west']},{bb['south']},{bb['east']},{bb['north']}"
    common = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "dem",
              "CRS": "CRS84", "BBOX": box, "FORMAT": "image/png"}
    big = c.get("/ogc/wms", params={**common, "WIDTH": "4096", "HEIGHT": "4096"})   # 16.7M px, within per-dim cap
    assert "ServiceException" in big.text, "4096x4096 (within per-dim cap) not rejected by an area budget (#288)"
    ok = c.get("/ogc/wms", params={**common, "WIDTH": "512", "HEIGHT": "512"})       # within the area budget
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png", ok.text


def test_wms_is_public_no_auth_required(monkeypatch):
    """Consistent with the wrapped globe drape (GIS-03): the base-map WMS is reachable without a key."""
    monkeypatch.setenv("STEWIE_API_KEY", "secret-key")       # auth configured, but WMS is public base-map
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    r = c.get("/ogc/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"})
    assert r.status_code == 200                              # no X-API-Key, still served
