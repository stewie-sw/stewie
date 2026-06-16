"""DEM source registry (TW-01/02/03, M11): the catalog of REAL public lunar DEM products selectable as
base layers -- LRO LOLA global, LOLA south-pole, LROC NAC SfS, PDS radar, PGDA COGs, CGI Moon Kit. Only
the small Haworth tile is bundled; every other source is real-data-gated (you supply a downloaded file,
exactly like dem_import / Katwijk -- no synthetic terrain). Every source carries provenance + license so
the THIRD_PARTY audit (#124) and the cockpit layer selector have a single source of truth.

Run: <venv>/bin/python -m pytest dart/test_dem_sources.py -q
"""
import pytest

from dart import dem_sources as S


def test_catalog_has_the_known_real_products():
    ids = {s.id for s in S.list_dem_sources()}
    for expected in ("lola_global_118m", "lola_sp", "lroc_nac_sfs_1m", "pds_radar_sp", "pgda_sp_cog",
                     "cgi_moon_kit", "haworth_10km_5m"):
        assert expected in ids, expected


def test_only_haworth_is_bundled_rest_are_real_data_gated():
    by = {s.id: s for s in S.list_dem_sources()}
    assert by["haworth_10km_5m"].bundled is True
    assert all(not s.bundled for s in S.list_dem_sources() if s.id != "haworth_10km_5m")


def test_every_source_is_lunar_framed_and_provenanced():
    for s in S.list_dem_sources():
        assert s.body == "moon"
        assert s.frame_radius_m == 1737400          # MOON_ME mean radius, never an Earth datum
        assert s.crs in ("south_polar_stereographic", "simple_cylindrical", "render_only")
        assert s.access_url.startswith("http") and s.license and s.resolution_m > 0


def test_lookup_and_unknown_raises():
    assert S.dem_source("lola_global_118m").resolution_m == 118.0
    assert S.dem_source("haworth_10km_5m").ingest == "dem_import"
    with pytest.raises(KeyError):
        S.dem_source("mars_hirise")                 # not in the lunar catalog


def test_ingest_readiness_is_honest():
    by = {s.id: s for s in S.list_dem_sources()}
    # PGDA south-pole GeoTIFF + the bundled tile are ingested today (dem_import, same-frame)
    assert by["pgda_sp_cog"].ingest == "dem_import" and by["haworth_10km_5m"].ingest == "dem_import"
    # global/equirect products need non-polar reprojection (TW-02); .cub needs GDAL/ISIS; CGI is render-only
    assert by["lola_global_118m"].ingest == "reproject"
    assert by["pds_radar_sp"].ingest in ("dem_import", "gdal_cub")
    assert by["cgi_moon_kit"].ingest == "render_only"   # visualization product, not metric-controlled


def test_planning_grade_excludes_render_only():
    # a layer offered for MISSION PLANNING must be metric-controlled; CGI Moon Kit is viz-only
    planning = {s.id for s in S.list_dem_sources() if s.planning_grade}
    assert "cgi_moon_kit" not in planning
    assert "lola_sp" in planning and "haworth_10km_5m" in planning
