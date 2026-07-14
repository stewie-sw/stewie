"""[REQ:BA-04] the Gazebo terrain is generated from the REAL Haworth LOLA DEM, not a flat plane.

UPDATED BY BA-12, and the reason is worth stating because it is the whole lesson. BA-04's requirement -- real
DEM, not a flat plane -- was and remains right. Its GATE was not. It asserted:

    assert int(arr.min()) == 0 and int(arr.max()) == 255, "heightmap is flat / not full-range"

which "proves" the terrain is not flat by asserting THE 8-BIT RANGE IS FULLY USED -- i.e. it asserted the very
quantisation that made the world unusable (933.761 m of relief across 255 steps = a 3.662 m vertical step,
against a rover whose own wheel radius is 15.2 cm). The gate was green while the terrain could not resolve the
machine standing on it. It tested the ARTEFACT, not the REQUIREMENT.

So the artefact assertions move to the DEM (float32 GeoTIFF, read through gz-common's GDAL-backed `Dem`), and
the fidelity requirement -- can this terrain actually resolve a dig pass, an obstacle, a wheel? -- lives in
`test_gazebo_dem_fidelity.py` [REQ:BA-12], where it belongs.
"""
import numpy as np
import pytest

pytest.importorskip("rasterio")


def test_heightfield_is_the_real_dem_not_a_plane(tmp_path):  # [REQ:BA-04]
    try:
        from scripts.dem_to_gazebo_heightfield import build_heightfield
        rec = build_heightfield(str(tmp_path))
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")
    import rasterio
    n = rec["n"]
    with rasterio.open(rec["dem"]) as ds:
        assert (ds.height, ds.width) == (n, n), f"DEM not {n}x{n}: {(ds.height, ds.width)}"
        arr = ds.read(1)
    assert (n - 1) & (n - 2) == 0, f"DEM side {n} is not 2^k+1 (gz LOD is happiest there)"
    # a flat plane would be a single value; a real DEM carries real relief -- asserted in METRES now, not in
    # the 0..255 range of a quantised byte image (see the module docstring).
    assert float(arr.max() - arr.min()) > 1.0, "terrain is flat -- not a real DEM"
    assert np.isfinite(arr).all(), "the DEM carries non-finite elevations"
    assert rec["relief_m"] > 1.0, f"DEM relief implausibly small ({rec['relief_m']} m) -- not real terrain"
    world = open(rec["world"], encoding="utf-8").read()
    assert "<heightmap>" in world and "terrain.tif" in world, "world does not load the DEM"
    assert "<plane>" not in world, "world still uses a flat regolith plane"
    assert f"{rec['relief_m']:.3f}" in world, "the heightmap z-size is not the DEM relief"


def test_converter_cli_writes_into_the_worlds_dir(tmp_path):  # [REQ:BA-04]
    try:
        from scripts.dem_to_gazebo_heightfield import main
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")
    rc = main([str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "haworth_heightfield.sdf").exists() and (tmp_path / "terrain.tif").exists()
