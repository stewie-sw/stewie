"""annotations: per-tile lat/lon + per-layer real-pixel stats, exported as GeoJSON.

Every layer statistic comes from a REAL pixel window of the fixture (a subsampled real Haworth DEM);
slope reuses ``site_dem.slope_deg_map`` and aspect reuses ``gis_layers.aspect_deg`` (real producers).
"""
from __future__ import annotations

import json

from stewie.dataset.annotations import (
    annotate_tiles,
    tile_annotation,
    to_geojson_featurecollection,
)
from stewie.dataset.splits import spatial_block_split
from stewie.dataset.tile_grid import TileGrid


def test_tile_annotation_real_layer_stats(fixture_geometry, fixture_reader):
    grid = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    ann = tile_annotation(grid.tile(0), fixture_reader, fixture_geometry, split="train")
    assert ann.tile_id == "r000c000" and ann.split == "train"
    assert set(("dem", "slope", "aspect")).issubset(ann.layers)

    dem = ann.layers["dem"]
    assert dem.count == 100 * 100 and abs(dem.valid_frac - 1.0) < 1e-12
    assert abs(dem.mean - 1816.579) < 1e-2          # real elevation mean over the window
    assert abs(dem.min - 1812.959) < 1e-2
    assert abs(dem.max - 1819.948) < 1e-2
    assert dem.std > 0.0

    slope = ann.layers["slope"]
    assert 0.0 <= slope.min <= slope.max <= 90.0
    assert abs(slope.mean - 3.4003) < 1e-2

    aspect = ann.layers["aspect"]
    assert 0.0 <= aspect.min and aspect.max < 360.0

    # provenance carries the real datum + CRS + source citation
    assert ann.provenance["crs"] == "IAU_2015:30135"
    assert abs(ann.provenance["sphere_radius_m"] - 1737400.0) < 1e-3
    assert "haworth" in ann.provenance["source_dem"].lower()   # fixture or full DEM
    assert "citation" in ann.provenance
    assert ann.tile_m == 100.0 and ann.sub_m == 25.0


def test_annotate_tiles_carries_split_labels(fixture_geometry, fixture_reader):
    grid = TileGrid(fixture_geometry, tile_m=25.0, sub_m=25.0)
    sp = spatial_block_split(grid, overlap_m=5.0)
    anns = annotate_tiles(sp.val_tiles, fixture_reader, fixture_geometry, split_result=sp)
    assert anns and all(a.split == "val" for a in anns)


def test_geojson_featurecollection_valid_and_closed(fixture_geometry, fixture_reader):
    grid = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    anns = annotate_tiles(grid.tiles, fixture_reader, fixture_geometry)
    fc = to_geojson_featurecollection(anns, fixture_geometry)

    # serialises + parses as JSON
    fc2 = json.loads(json.dumps(fc))
    assert fc2["type"] == "FeatureCollection"
    assert len(fc2["features"]) == len(anns) == 9
    assert "crs" in fc2 and "provenance" in fc2
    assert fc2["provenance"]["crs"] == "IAU_2015:30135"

    for feat in fc2["features"]:
        assert feat["type"] == "Feature"
        geom = feat["geometry"]
        assert geom["type"] == "Polygon"
        ring = geom["coordinates"][0]
        assert len(ring) == 5 and ring[0] == ring[-1]     # closed 4-corner polygon
        for lon, lat in ring:
            assert -30.0 < lon < -15.0 and -88.0 < lat < -86.0   # real Haworth lon/lat
        props = feat["properties"]
        for key in ("tile_id", "index", "split", "center_lat", "center_lon", "valid_frac"):
            assert key in props
        assert "dem_mean" in props and "slope_mean" in props


def test_real_full_dem_tile0_annotation(real_dem_path):
    from stewie.dataset.dem_source import GeoTiffWindowReader, read_geotiff_geometry
    g = read_geotiff_geometry(real_dem_path)
    reader = GeoTiffWindowReader(real_dem_path)
    grid = TileGrid(g, tile_m=100.0, sub_m=25.0)
    ann = tile_annotation(grid.tile(0), reader, g)
    assert ann.layers["dem"].count > 0 and ann.layers["dem"].valid_frac > 0.0
    assert -88.0 < ann.center_latlon[0] < -86.0
