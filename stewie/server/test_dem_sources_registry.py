"""DEM layers (#150): the dem_sources catalog and the /world provenance label must reflect the DEM
bundles actually on disk. Three real LOLA tiles are bundled -- Haworth plus the two Artemis-candidate
rim tiles (Nobile Rim 1 / Shackleton rim, PGDA Product 78). Each must be a planning-grade catalog entry
whose id matches a real samples/lunar_dem/<id> directory, and /world must report that id as the site's
provenance (not just the site name).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_dem_sources_registry.py -q
"""
from __future__ import annotations

import importlib
import os

from dart import dem_sources

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SAMPLES = os.path.join(_ROOT, "samples", "lunar_dem")

_BUNDLED = {"haworth_10km_5m", "nobile_rim1_10km_5m", "shackleton_rim_10km_5m"}


def test_every_bundled_source_has_a_real_on_disk_bundle():
    bundled = {s.id for s in dem_sources.list_dem_sources() if s.bundled}
    assert _BUNDLED <= bundled, f"catalog missing bundled tiles: {_BUNDLED - bundled}"
    for sid in bundled:
        d = os.path.join(_SAMPLES, sid)
        assert os.path.isdir(d), f"bundled source {sid!r} has no on-disk bundle dir"
        assert os.path.exists(os.path.join(d, "heightmap.rf32")), f"{sid!r} bundle has no heightmap"


def test_new_tiles_are_planning_grade_real_lola_entries():
    for sid in ("nobile_rim1_10km_5m", "shackleton_rim_10km_5m"):
        s = dem_sources.dem_source(sid)
        assert s.bundled and s.planning_grade, f"{sid} must be a bundled, planning-grade source"
        assert s.instrument == "LOLA" and s.resolution_m == 5.0
        assert s.crs == "south_polar_stereographic"


def test_world_route_reports_the_real_bundle_id_as_provenance(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    for site, expect in (("shackleton_rim", "shackleton_rim_10km_5m"),
                         ("nobile_rim", "nobile_rim1_10km_5m"),
                         ("haworth", "haworth_10km_5m")):
        r = c.get(f"/world?site={site}")
        assert r.status_code == 200, f"{site}: {r.status_code} {r.text[:120]}"
        assert r.json()["world"]["dem_source"] == expect, f"{site} provenance != {expect}"


def test_dem_sources_catalog_route_lists_the_bundled_tiles(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    j = c.get("/dem/sources").json()
    assert j["ok"]
    by_id = {s["id"]: s for s in j["sources"]}
    assert _BUNDLED <= set(by_id), "the catalog route omits a bundled tile"
    for sid in _BUNDLED:
        assert by_id[sid]["bundled"] and by_id[sid]["planning_grade"]
    # a render-only product must be present and correctly flagged non-planning-grade (honesty)
    assert any(not s["planning_grade"] for s in j["sources"]), "no non-planning-grade product flagged"


def test_cockpit_surfaces_the_dem_source_catalog():
    """#150 FS-18: the route connects to a pane -- the Contents section fetches + renders /dem/sources."""
    html = open(os.path.join(_ROOT, "stewie", "server", "index.html")).read()
    js = open(os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")).read()
    assert 'id="demsources"' in html, "no #demsources container in the Contents section"
    assert "loadDemSources" in js and "/dem/sources" in js, "the cockpit does not fetch the DEM catalog"
