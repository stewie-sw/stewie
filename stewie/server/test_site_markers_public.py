"""Keyless PUBLIC site markers for the lunar IDE's click-a-site-to-zoom (SiteZoom.jsx) + the Whole-Moon dive
(WholeMoon.jsx).

GET /world/site-markers returns the drawn-pin subset ({name, label, lon, lat, extent_m}) sourced from the SAME
artemis_sites.geojson that draws the VISIBLE main-map pins (gis/build_project.py), reachable WITHOUT the
director key -- so the public /ide/ plugins resolve a pin click. The auth-gated /sites operational registry
(routers.config, S-06) stays gated and its centers differ from the pins by 2-90 km, which is exactly why the
plugins bind THIS instead. No operational field may leak.

REAL DATA: stewie/server/fixtures/artemis_sites_sample.geojson -- a verbatim 3-site subset (Site01/06/11,
pins + footprints) of the real data/gis/vectors/artemis_sites.geojson (PGDA Product 78 DEM COG extents).
"""
import importlib
import json
import os

import pytest
from fastapi.testclient import TestClient

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "artemis_sites_sample.geojson")
# the public subset a marker may carry -- name/label (key), lon/lat (center), extent_m (bbox). Nothing else.
_ALLOWED = {"name", "label", "lon", "lat", "extent_m"}
# operational / registry fields that MUST NOT leak into the public marker (they live on the geojson props +
# sites.py site_rows()); their presence would defeat the point of keeping /sites gated (S-06).
_FORBIDDEN = {"imported", "artemis_candidate", "note", "bundle_dir", "site", "kind", "source",
              "center_lon", "center_lat", "dem_min_m", "dem_max_m", "area_km2", "width_m", "height_m"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")        # auth IS configured -> a keyless caller is rejected...
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)    # ...and NOT dev-open (so /sites 401s keyless)
    monkeypatch.delenv("STEWIE_DESKTOP", raising=False)
    monkeypatch.delenv("STEWIE_TRUST_TAILSCALE", raising=False)
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_SITE_VECTORS", _FIXTURE)     # point the route at the committed real-data subset
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _geojson_pins(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    pins = {}
    for f in d["features"]:
        if f["geometry"]["type"] == "Point":
            p = f["properties"]
            pins[p["site"]] = (f["geometry"]["coordinates"], p["extent_m"])
    return pins


def test_site_markers_is_public_no_key_but_registry_stays_gated(client):
    # the auth-gated operational registry (S-06) rejects a keyless browser call...
    assert client.get("/sites").status_code == 401
    # ...while the public marker subset is reachable WITHOUT a key (nginx forwards none, like /world/layer-manifest).
    r = client.get("/world/site-markers")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True
    assert isinstance(j["sites"], list) and len(j["sites"]) == 3    # the 3 real fixture pins (footprints skipped)


def test_site_markers_are_the_public_subset_only_no_operational_leak(client):
    sites = client.get("/world/site-markers").json()["sites"]
    for s in sites:
        assert set(s.keys()) == _ALLOWED, f"unexpected marker keys: {set(s.keys()) - _ALLOWED}"
        assert not (_FORBIDDEN & set(s.keys())), "an operational registry field leaked into the public marker"
        assert isinstance(s["lon"], float) and isinstance(s["lat"], float)
        assert isinstance(s["extent_m"], list) and len(s["extent_m"]) == 4
        assert isinstance(s["name"], str) and s["name"]
        assert isinstance(s["label"], str) and s["label"]


def test_site_markers_resolve_the_geojson_pin_positions(client):
    # the markers must sit on the VISIBLE pins: positions == the geojson pin geometry, so a click resolves to it
    # and the SiteZoom hit-test (js/mission/siteZoom.js) lands inside the pin's box.
    pins = _geojson_pins(_FIXTURE)
    by = {s["name"]: s for s in client.get("/world/site-markers").json()["sites"]}
    assert set(by) == set(pins)                # every geojson pin -> exactly one marker (footprints skipped)
    for site, (coords, extent) in pins.items():
        m = by[site]
        assert m["lon"] == pytest.approx(coords[0]) and m["lat"] == pytest.approx(coords[1])
        assert m["extent_m"] == pytest.approx(extent)


def test_site_markers_degrade_honestly_when_vectors_absent(monkeypatch, tmp_path):
    from stewie.server.routers import world
    # no vectors file found -> [] (the click no-ops; never a fabricated position).
    monkeypatch.setattr(world, "_site_vectors_path", lambda: None)
    assert world.site_markers() == []
    # present-but-empty geojson -> [] (robust, not a 500).
    empty = tmp_path / "empty.geojson"
    empty.write_text('{"type":"FeatureCollection","features":[]}')
    monkeypatch.setattr(world, "_site_vectors_path", lambda: str(empty))
    assert world.site_markers() == []
    # malformed file -> [] (parse error is caught honestly).
    bad = tmp_path / "bad.geojson"
    bad.write_text("not json {")
    monkeypatch.setattr(world, "_site_vectors_path", lambda: str(bad))
    assert world.site_markers() == []
