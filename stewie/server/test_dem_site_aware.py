"""REG-01 site→DEM wiring: the DEM endpoints resolve the CHOSEN imported site's bundle, not just Haworth.

Before this, /dem/georef, /dem/site_xy and /dem/{name} hardcoded the Haworth bundle, so selecting
Shackleton or Nobile in the cockpit still drew Haworth's tile + coordinates. These tests pin the
site-parametric behavior end to end: the helper resolves each bundled site, and the endpoints return
that site's georef / preview.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from stewie.server.server import app
from stewie.terrain.site_dem import bundle_for_site

client = TestClient(app)

# the three real bundled tiles on disk (SITES registry with a bundle_dir)
BUNDLED = ("haworth", "shackleton_rim", "nobile_rim")


def test_bundle_for_site_resolves_each_bundled_site():
    seen = set()
    for site in BUNDLED:
        d = bundle_for_site(site)
        assert d and d not in seen, f"{site} must resolve to its OWN distinct bundle dir"
        seen.add(d)


def test_bundle_for_site_rejects_unknown_and_unimported():
    with pytest.raises(KeyError):
        bundle_for_site("not_a_real_site")
    with pytest.raises(FileNotFoundError):           # known site, no DEM bundle imported
        bundle_for_site("de_gerlache_rim")


def test_dem_preview_is_served_per_site():
    for site in BUNDLED:
        r = client.get(f"/dem/hillshade.png?site={site}")
        assert r.status_code == 200, (site, r.status_code)
        assert r.headers["content-type"] == "image/png"


def test_dem_preview_unknown_site_404():
    r = client.get("/dem/hillshade.png?site=not_a_real_site")
    assert r.status_code == 404


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("pyproj") is None, reason="pyproj ([planner] extra) absent")
def test_georef_is_site_specific():
    """The globe footprint differs per site (different tiles -> different center lat/lon). Proves the
    overlay follows the selected site instead of always drawing Haworth."""
    centers = {}
    for site in BUNDLED:
        r = client.get(f"/dem/georef?site={site}")
        assert r.status_code == 200, (site, r.text)
        j = r.json()
        assert j["ok"] and j["site"] == site
        centers[site] = (round(j["center"]["lat"], 4), round(j["center"]["lon"], 4))
    # all three tiles sit at distinct selenographic centers
    assert len(set(centers.values())) == len(BUNDLED), f"site centers not distinct: {centers}"


def test_georef_unknown_site_404():
    r = client.get("/dem/georef?site=not_a_real_site")
    assert r.status_code == 404


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("pyproj") is None, reason="pyproj ([planner] extra) absent")
def test_globe_drape_bbox_is_site_specific():
    """Slice 2: the globe drape (gis_layers.render_globe) reprojects the CHOSEN site's tile, so its
    footprint bbox differs per site instead of always being Haworth's."""
    boxes = {}
    for site in BUNDLED:
        r = client.get(f"/layers/globe/dem/bbox?site={site}")
        assert r.status_code == 200, (site, r.text)
        j = r.json()
        assert j["ok"]
        boxes[site] = (round(j["south"], 3), round(j["west"], 3))
    assert len(set(boxes.values())) == len(BUNDLED), f"globe drape bbox not site-distinct: {boxes}"


def test_globe_drape_unknown_site_404():
    r = client.get("/layers/globe/dem/bbox?site=not_a_real_site")
    assert r.status_code == 404


def test_raster_layer_is_site_specific_and_rejects_unknown():
    """REG-01 (review gap): the work-area raster /layers/raster/{kind}.png?site= got no site-correctness
    test, yet it has the SAME render() site->bundle->crop + site cache-key class that broke test_globe_cache.
    Each bundled site must render a DISTINCT raster (the crop follows the site, not always Haworth); an
    unknown or path-traversal site must 404 (the bundle_for_site KeyError guard -- pins the ?site= safety)."""
    pngs = {}
    for site in BUNDLED:
        r = client.get(f"/layers/raster/slope.png?site={site}")
        assert r.status_code == 200, (site, r.status_code)
        assert r.headers["content-type"] == "image/png"
        pngs[site] = r.content
    assert len({v for v in pngs.values()}) == len(BUNDLED), "raster not distinct per site (crop not following site)"
    assert client.get("/layers/raster/slope.png?site=not_a_real_site").status_code == 404
    # ?site= cannot path-traverse out of the registered bundle set (validated against SITES, not the FS)
    assert client.get("/layers/raster/slope.png?site=../../etc/passwd").status_code == 404
