"""[REQ:BA-06] GridMap<->GeoTIFF round-trips a REAL DEM-derived fixture with its GEOREFERENCE preserved
(resolution + center position + dimensions) and the real elevation values intact. Fixture = a small tile of
the real Haworth LOLA DEM (subsampled real data, never synthetic)."""
import json
import os

import numpy as np
import pytest

pytest.importorskip("rasterio", reason="GeoTIFF I/O needs rasterio (server extra, not lean dev/core)")

from stewie.interop.gridmap_geotiff import GridMap, geotiff_to_gridmap, gridmap_to_geotiff

_DEM = "samples/lunar_dem/haworth_10km_5m"


def _real_tile(n: int = 48):
    meta = json.load(open(os.path.join(_DEM, "metadata.json")))["grid"]
    z = np.fromfile(os.path.join(_DEM, "heightmap.rf32"), dtype="<f4").reshape(meta["height"], meta["width"])
    return z[:n, :n].astype(np.float32), float(meta["cell_m"])


def test_ba06_gridmap_geotiff_roundtrip_preserves_georeference(tmp_path):  # [REQ:BA-06]
    tile, cell = _real_tile(48)
    gm = GridMap(resolution=cell, length_x=48 * cell, length_y=48 * cell, position=(1234.0, -567.0),
                 frame_id="moon_local", layers={"elevation": tile})
    p = str(tmp_path / "gm.tif")
    gridmap_to_geotiff(gm, "elevation", p)
    back = geotiff_to_gridmap(p)

    # GEOREFERENCE preserved (the BA-06 acceptance invariant for grid<->geotiff)
    assert back.resolution == pytest.approx(gm.resolution)
    assert (back.rows, back.cols) == (gm.rows, gm.cols)
    assert back.length_x == pytest.approx(gm.length_x) and back.length_y == pytest.approx(gm.length_y)
    assert back.position[0] == pytest.approx(gm.position[0])
    assert back.position[1] == pytest.approx(gm.position[1])
    assert back.frame_id == "moon_local"
    # the REAL elevation values round-trip losslessly through the float32 GeoTIFF
    np.testing.assert_array_equal(back.layers["elevation"], tile)


def test_ba06_gridmap_to_geotiff_rejects_a_shape_mismatch(tmp_path):  # [REQ:BA-06]
    gm = GridMap(resolution=5.0, length_x=240.0, length_y=240.0, position=(0.0, 0.0),
                 frame_id="map", layers={"elevation": np.zeros((10, 10), dtype=np.float32)})
    with pytest.raises(ValueError, match="shape"):
        gridmap_to_geotiff(gm, "elevation", str(tmp_path / "bad.tif"))   # 10x10 != 48x48 geometry
