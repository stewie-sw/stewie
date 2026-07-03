"""[REQ:BA-04] the Gazebo terrain is generated from the REAL Haworth LOLA DEM, not a flat plane."""
import numpy as np
import pytest
from PIL import Image


def test_heightfield_is_the_real_dem_not_a_plane(tmp_path):  # [REQ:BA-04]
    try:
        from scripts.dem_to_gazebo_heightfield import build_heightfield
        rec = build_heightfield(str(tmp_path))
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")
    n = rec["n"]
    im = Image.open(rec["png"])
    assert im.size == (n, n), f"heightmap not {n}x{n}: {im.size}"
    assert (n - 1) & (n - 2) == 0, f"heightmap side {n} is not 2^k+1 (gz LOD needs it)"
    arr = np.asarray(im)
    # a flat plane would be a single grey value; a real DEM spans the full 0..255 after normalization
    assert int(arr.min()) == 0 and int(arr.max()) == 255, "heightmap is flat / not full-range"
    assert rec["relief_m"] > 1.0, f"DEM relief implausibly small ({rec['relief_m']} m) -- not real terrain"
    world = open(rec["world"], encoding="utf-8").read()
    assert "<heightmap>" in world and "heightmap.png" in world, "world does not load the heightmap"
    assert "<plane>" not in world, "world still uses a flat regolith plane"
    assert f"{rec['relief_m']:.3f}" in world, "the heightmap z-size is not the DEM relief"


def test_converter_cli_writes_into_the_worlds_dir(tmp_path):  # [REQ:BA-04]
    try:
        from scripts.dem_to_gazebo_heightfield import main
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")
    rc = main([str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "haworth_heightfield.sdf").exists() and (tmp_path / "heightmap.png").exists()
