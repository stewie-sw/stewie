"""[REQ:BA-06] DEM<->Godot heightfield round-trips a REAL Haworth DEM tile: the BOUNDS (min/max/rows/cols/
cell) are preserved exactly and the metre heights are recovered within float quantization. Fixture = a real
interior tile of the Haworth LOLA DEM (subsampled real data, never synthetic)."""
import json
import os

import numpy as np
import pytest

from stewie.interop.dem_godot_heightfield import (
    dem_to_godot_heightfield,
    godot_heightfield_to_dem,
    read_godot_heightfield,
    write_godot_heightfield,
)

_DEM = "samples/lunar_dem/haworth_10km_5m"


def _real_tile(n: int = 48):
    meta = json.load(open(os.path.join(_DEM, "metadata.json")))["grid"]
    z = np.fromfile(os.path.join(_DEM, "heightmap.rf32"), dtype="<f4").reshape(meta["height"], meta["width"])
    return z[900:900 + n, 900:900 + n].astype(np.float32), float(meta["cell_m"])   # interior tile, real relief


def test_ba06_dem_godot_heightfield_roundtrip_preserves_bounds(tmp_path):  # [REQ:BA-06]
    dem, cell = _real_tile(48)
    hf = dem_to_godot_heightfield(dem, cell, frame_id="moon_local")
    assert hf.normalized.dtype == np.float32
    assert 0.0 <= float(hf.normalized.min()) and float(hf.normalized.max()) <= 1.0   # valid Godot [0,1] field

    stem = str(tmp_path / "hf")
    write_godot_heightfield(hf, stem)
    hf2 = read_godot_heightfield(stem)
    dem2, cell2 = godot_heightfield_to_dem(hf2)

    # BOUNDS preserved exactly (the BA-06 acceptance invariant for dem<->heightfield)
    assert hf2.min_height_m == pytest.approx(float(dem.min()))
    assert hf2.max_height_m == pytest.approx(float(dem.max()))
    assert cell2 == cell and dem2.shape == dem.shape and hf2.frame_id == "moon_local"
    # metre heights recovered within float quantization (sub-mm on this tile's span)
    span = float(dem.max() - dem.min())
    np.testing.assert_allclose(dem2, dem, atol=max(1e-3, span * 1e-6))


def test_ba06_flat_dem_heightfield_roundtrips():  # [REQ:BA-06]
    # honesty: a zero-span (flat) DEM must not divide-by-zero; it round-trips to the constant height.
    flat = np.full((16, 16), -42.5, dtype=np.float32)
    dem2, _ = godot_heightfield_to_dem(dem_to_godot_heightfield(flat, 5.0))
    np.testing.assert_array_equal(dem2, flat)
