"""[REQ:BA-12] The Gazebo terrain is RESOLVABLE AT ROVER SCALE and reads the CONSERVED AUTHORITY'S OWN DEM.

WHY THIS FILE EXISTS. BA-04 put a real lunar DEM under the Gazebo rover instead of a flat plane, and that was
real progress. But it shipped an **8-bit greyscale PNG**, and its test asserted the wrong thing:

    assert int(arr.min()) == 0 and int(arr.max()) == 255, "heightmap is flat / not full-range"

That gate "proves" the terrain is not flat by asserting the 8-BIT RANGE IS FULLY USED -- i.e. it asserts the
very quantisation that makes the world useless. BA-04 is glyphed done, its test is green, and the rover
cannot resolve its own wheel. It tested the ARTEFACT (a PNG that spans 0..255) instead of the REQUIREMENT
(terrain a rover can perceive and drive on).

WHAT THE OLD WORLD ACTUALLY WAS, measured:
    513x513 px over 2565 m            ->  5.00 m per pixel
    8-bit over 933.761 m of relief    ->  3.662 m per vertical STEP
against the machine that has to drive on it:
    IPEx drum footprint    0.3526 m   ->  1/14 of ONE pixel
    anti-bridging bite     0.0132 m   ->  1/277 of ONE vertical step
    IPEx obstacle spec     0.075 m    ->  1/49 of ONE vertical step
    rover wheel radius     0.1524 m   ->  1/24 of ONE vertical step
At rover scale it is a smooth blob: no rocks, no obstacles, no ruts, no berms. That does not merely block
excavation -- IT BREAKS PERCEPTION AND NAVIGATION, which is the whole reason a Gazebo world exists here. An
Autoware stack driving over a featureless 5 m/px surface has nothing to perceive.

AND THE PREMISE WAS FALSE. The generator's docstring claims "gz-sim reads an 8-bit grayscale heightmap".
VERIFIED WRONG in our own container (stewie-gazebo:jazzy):
    libgz-common5-geospatial.so.5.8.0  ->  ldd shows libgdal.so.34   ** LINKS GDAL **
    gz/common/geospatial/Dem.hh: class Dem : public HeightmapData -- "Encapsulates a DEM file"
                                 double Elevation(double x, double y);  float MinElevation()/MaxElevation()
gz-sim reads a GeoTIFF DEM directly, with FLOAT elevation. The 3.662 m quantisation was SELF-INFLICTED.

AND A SECOND TRUTH, WHICH IS WORSE THAN THE QUANTISATION. The generator sourced `haworth_10km_5m` (5 m
cell) while viz2 and the conserved authority drive on `haworth_sfs_2km_1m` (1 m cell). Gazebo's terrain was
NOT EVEN THE SAME DEM. Per the architecture decision (the conserved authority is the SINGLE physics
authority; Gazebo is a ROS sensor shell), Gazebo must consume the AUTHORITY'S raster -- one truth, two
engines -- or evidence gathered in one will not transfer to the other.

WHAT THIS ROW DOES *NOT* CLAIM. Horizontal resolution is bounded by the DEM itself: you cannot resolve a
7.5 cm obstacle from a 1 m raster, and inventing sub-metre terrain would be fabrication. Rocks and boulders
therefore belong as CLAST COLLISION MODELS (the sourced Golombek draw the authority already carries), NOT
baked into a heightmap. This row fixes the two things that ARE fixable and were simply wrong: the vertical
quantisation (now exact) and the second truth (now one).
"""
from __future__ import annotations

import os

import numpy as np
import pytest

pytest.importorskip("rasterio")

from stewie.specs import constants as K  # noqa: E402
from stewie.specs.ipex_specs import (  # noqa: E402
    DRUM_DIMENSIONS_M, MAX_CUT_DEPTH_FRAC, OBSTACLE_HEIGHT_M, WHEEL_RADIUS_M)

AUTHORITY_BUNDLE = "haworth_sfs_2km_1m"     # the bundle viz2 + the conserved authority actually drive on


def _build(tmp_path):
    from scripts.dem_to_gazebo_heightfield import build_heightfield
    try:
        return build_heightfield(str(tmp_path))
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")


def test_the_terrain_is_a_FLOAT_dem_not_an_8bit_png() -> None:
    """[REQ:BA-12] THE HEADLINE. gz-sim links GDAL and reads a float GeoTIFF DEM (verified in our own
    container), so the 8-bit PNG's 3.662 m vertical step was self-inflicted. The exported raster must carry
    FLOAT elevation -- no quantisation at all."""
    import tempfile

    import rasterio
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        assert rec["dem"].endswith(".tif"), f"the terrain is still not a DEM: {rec['dem']}"
        with rasterio.open(rec["dem"]) as ds:
            assert ds.dtypes[0].startswith("float"), (
                f"the Gazebo terrain is {ds.dtypes[0]}, not float -- elevation is being quantised")
            band = ds.read(1)
    # a float raster reproduces the real relief exactly; an 8-bit one could not
    assert float(band.max() - band.min()) > 1.0, "the exported DEM is flat -- not real terrain"


def test_the_vertical_resolution_can_actually_SEE_the_rover_and_its_dig() -> None:
    """[REQ:BA-12] The requirement the old gate never asked. The terrain must resolve the things the machine
    physically does. The old 8-bit world could not: one dig pass was 1/277 of a vertical step, and the
    rover's own wheel was 1/24 of one."""
    import tempfile

    import rasterio
    bite_m = DRUM_DIMENSIONS_M["small"]["scoop_height"] * MAX_CUT_DEPTH_FRAC   # the anti-bridging bite
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        with rasterio.open(rec["dem"]) as ds:
            band = ds.read(1)
    # float32 ULP at lunar-polar elevations (~1700 m) is ~1e-4 m -- four orders below the bite.
    step_m = float(np.spacing(np.float32(abs(band).max())))
    assert step_m < bite_m / 10.0, (
        f"vertical step {step_m*1000:.3f} mm cannot resolve a {bite_m*1000:.1f} mm dig pass")
    assert step_m < OBSTACLE_HEIGHT_M / 10.0, (
        f"vertical step {step_m*1000:.3f} mm cannot resolve the {OBSTACLE_HEIGHT_M*100:.1f} cm obstacle "
        "IPEx must climb")
    assert step_m < WHEEL_RADIUS_M / 10.0, (
        f"vertical step {step_m*1000:.3f} mm cannot resolve the rover's own {WHEEL_RADIUS_M*100:.1f} cm wheel")


def test_gazebo_reads_the_SAME_dem_the_conserved_authority_drives_on() -> None:
    """[REQ:BA-12] ONE TRUTH, TWO ENGINES. The generator sourced `haworth_10km_5m` (5 m) while viz2 and the
    authority drive on `haworth_sfs_2km_1m` (1 m) -- Gazebo's terrain was NOT EVEN THE SAME DEM. Two truths
    mean evidence gathered in one engine does not transfer to the other, which is precisely the divergence
    the architecture decision forbids."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
    assert AUTHORITY_BUNDLE in rec["source_bundle"], (
        f"Gazebo is reading {rec['source_bundle']!r}, not the authority's {AUTHORITY_BUNDLE!r} -- two truths")
    assert rec["cell_m"] == pytest.approx(1.0), (
        f"the export downsampled the authority's DEM to {rec['cell_m']} m -- horizontal detail was thrown "
        "away that the source actually has")


def test_the_world_sdf_loads_the_dem_and_no_longer_the_quantised_png() -> None:
    """[REQ:BA-12] The SDF must actually point at the float DEM. A correct raster the world never loads is
    worth nothing -- the exact class of bug this project keeps finding."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        world = open(rec["world"], encoding="utf-8").read()
    assert "<heightmap>" in world and "<plane>" not in world
    assert os.path.basename(rec["dem"]) in world, "the world does not load the exported DEM"
    assert "heightmap.png" not in world, "the world still loads the quantised 8-bit PNG"


def test_the_world_states_its_own_SIZE_because_gz_cannot_autosize_a_LUNAR_dem() -> None:
    """[REQ:BA-12] A limitation of gz-sim itself, found only by loading the world in the container, and
    pinned here because nothing in the code said it.

    `gz-common`'s `Dem` auto-computes a DEM's extent by transforming its corners to **EPSG:4326 (Earth
    WGS84)**. PROJ correctly REFUSES that for a lunar raster:

        PROJ: Source and target ellipsoid do not belong to the same celestial body (Moon vs Earth)
        [Err] [Dem.cc:390] Unable to transform terrain coordinate system for coordinates (0,0)
        [Wrn] [Dem.cc:232] Failed to automatically compute DEM size.

    So **gz can never auto-size a lunar DEM**, and the `<size>` element is LOAD-BEARING, not decorative --
    it is the only thing that gives the world its true extent. Verified in-container: with `<size>` present,
    `ODE Heightfield AABB: min = {-256,-256,-0.05} max = {256,256,16.646}` -- correct.

    PROJ offers `PROJ_IGNORE_CELESTIAL_BODY=YES` to bypass the check. We deliberately DO NOT set it: it
    would make PROJ treat the Moon as Earth and compute the extent against Earth's radius -- a wrong number
    that looks right, which is worse than a loud fallback to a value we control."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        world = open(rec["world"], encoding="utf-8").read()
    sx, sy, _ = rec["size_m"]
    assert f"<size>{sx:.3f} {sy:.3f}" in world, (
        "the world does not state its <size>; gz cannot auto-size a lunar DEM (PROJ refuses Moon->Earth), "
        "so without it the terrain has no true extent")
    assert sx == pytest.approx(rec["n"] * rec["cell_m"]), "the stated extent is not the DEM's real extent"


def test_the_dem_is_zero_based_so_the_terrain_sits_on_the_world_origin() -> None:
    """[REQ:BA-12] Caught ONLY by loading the world -- the file was perfectly correct and the world was
    broken. For a DEM heightmap gz uses the raster's RAW values on the z axis (it takes only x/y from
    `<size>`), so shipping raw lunar elevations put the surface 1.7 km above the origin:

        ODE Heightfield AABB: ... max = {256, 256, 1764.56}     <- the rover spawns UNDER the ground

    The raster is therefore zero-based (a LOCAL worksite frame, the same discipline as GW-12's local render
    origin) and the absolute datum is RECORDED, not lost."""
    import tempfile

    import rasterio
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        with rasterio.open(rec["dem"]) as ds:
            band = ds.read(1)
        world = open(rec["world"], encoding="utf-8").read()   # inside: the tempdir is gone after this block

    assert float(band.min()) == pytest.approx(0.0, abs=1e-3), (
        f"the DEM is not zero-based (min {band.min():.3f} m) -- gz will float the terrain above the origin")
    assert float(band.max()) == pytest.approx(rec["relief_m"], rel=1e-4), \
        "the zero-based DEM does not span the real relief"
    # the absolute datum must be recoverable, or the local frame has THROWN AWAY the elevation
    assert rec["datum_m"] > 1000.0, "the absolute lunar datum was not recorded -- elevation is unrecoverable"
    assert rec["z_range_m"][0] == pytest.approx(rec["datum_m"])
    assert f"{rec['datum_m']:.3f}" in world, "the world does not record the datum it was zero-based against"


def test_the_old_8bit_path_would_FAIL_this_gate() -> None:
    """[REQ:BA-12] NON-VACUITY, stated as arithmetic rather than by re-running the dead code. If the vertical
    step were still 8-bit over the tile's relief, every assertion above would fail -- which is the whole
    point: the previous gate was green while the world was unusable."""
    relief_m = 933.761                       # the old world's <size> z
    old_step_m = relief_m / 255.0            # 8-bit
    bite_m = DRUM_DIMENSIONS_M["small"]["scoop_height"] * MAX_CUT_DEPTH_FRAC
    assert old_step_m > 3.0, "the old 8-bit step was not what we measured"
    assert old_step_m > 100.0 * bite_m, (
        "the old world's vertical step must dwarf a dig pass -- if it did not, this row had no reason to "
        "exist")
    assert old_step_m > 10.0 * WHEEL_RADIUS_M, "the old world could not even resolve the rover's wheel"
    assert K.RHO_SURFACE > 0                 # (touch the conserved constants: same source of truth)
