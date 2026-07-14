"""[REQ:BA-13] The Gazebo world carries the AUTHORITY'S OWN ROCKS as real collision geometry.

WHY THIS FILE EXISTS. BA-12 made the Gazebo terrain resolvable at rover scale (float DEM, 1 m cell, from the
conserved authority's own bundle). But terrain alone is a **bare graded surface**: there is nothing on it to
perceive, and nothing to hit. An Autoware stack driving a rock-free plain learns nothing about lunar
navigation, and the whole reason a Gazebo world exists here is perception.

The rocks must NOT be baked into the heightmap. At the DEM's 1 m cell a 0.29 m boulder is a **third of one
pixel** -- a raster physically cannot represent it, and smearing it into the terrain would produce a world
that LOOKS detailed and teaches a perception stack nothing. Rocks are OBJECTS, so they enter as objects:
collision + visual geometry, at their real positions, with their real radii, from the **sourced Golombek
size-frequency draw the conserved authority already carries** (the same `world_seed` -> the same rocks, so
Gazebo and viz2 see the SAME rock field -- one truth, two engines).

MEASURED, the real population over BA-12's 513 m terrain window (world_seed=0):
    67,721 clasts | radius min 12.8 cm, median 15.8 cm, max 0.29 m
EVERY ONE of them is larger than IPEx's 7.5 cm obstacle spec, so no size threshold can honestly thin them --
they all matter. 67,721 SDF *models* would be 67,721 entities and would kill the sim, so:
  * they go into ONE STATIC model with N <collision>/<visual> spheres in ONE link (cheap for ODE: static
    geometry, no dynamics), and
  * the rock field is scoped to the ROVER'S OPERATING AREA, not the full terrain extent.
Whatever is dropped is COUNTED AND LOGGED. Silent truncation reads as "we modelled everything" when we did
not, and that is the lie this project keeps refusing to tell.

THE BUG THIS GATE EXISTS TO CATCH. The authority's clasts are `center_m = [x, ELEVATION, y]` -- **Godot's
Y-up frame** -- while Gazebo is **Z-up**, and BA-12 additionally ZERO-BASED the terrain against a datum of
~1748 m. Get the axis swap or the datum wrong and every rock floats in the sky or is buried under the
surface, and it will still *look* like a rock field from a distance. So the gate below does not check that
rocks exist; it checks that **each rock sits on the ground it is supposed to be sitting on**, against the
very raster the world loads.
"""
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("rasterio")

from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M  # noqa: E402


def _build(d):
    from scripts.dem_to_gazebo_heightfield import build_heightfield
    try:
        return build_heightfield(str(d))
    except FileNotFoundError:
        pytest.skip("Haworth DEM bundle not present")


def test_the_world_actually_contains_rocks() -> None:
    """[REQ:BA-13] THE REQUIREMENT. A bare graded surface has nothing to perceive and nothing to hit."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        world = open(rec["world"], encoding="utf-8").read()
    assert rec["n_rocks"] > 100, f"only {rec['n_rocks']} rocks -- that is not a lunar surface"
    assert "<sphere>" in world, "the world declares no rock geometry"
    assert world.count("<collision") >= rec["n_rocks"], "rocks are visual-only -- the rover cannot hit them"
    assert world.count("<visual") >= rec["n_rocks"], "rocks are collision-only -- the rover cannot SEE them"


def test_every_rock_SITS_ON_THE_GROUND_the_world_actually_loads() -> None:
    """[REQ:BA-13] THE GATE THAT MATTERS, and the one a careless implementation fails invisibly.

    The authority's clasts are `[x, ELEVATION, y]` (Godot Y-UP); Gazebo is Z-UP; and BA-12 zero-based the
    terrain against a ~1748 m datum. Swap an axis or drop the datum and every rock floats in the sky or sinks
    out of sight -- and from a distance it would still look like a rock field.

    So: for each emitted rock, sample the EXPORTED RASTER (the exact terrain the world loads) under its (x,y)
    and assert its centre sits where the physics says it must:

        centre_z  ==  terrain_z + radius * (1 - 2 * buried_frac)

    which is the authority's own placement law (buried_frac 0.5 = exactly half-buried). A rock that misses
    this is not on the ground.
    """
    import tempfile

    import rasterio
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        with rasterio.open(rec["dem"]) as ds:
            terrain = ds.read(1)          # zero-based, float32, the raster the SDF loads
        rocks = rec["rocks"]              # (x, y, z, r, buried) in the LOCAL gz frame, metres

    assert rocks, "no rocks emitted"
    n, cell = rec["n"], rec["cell_m"]
    half = 0.5 * n * cell

    err = []
    for (x, y, z, r, buried) in rocks:
        # local gz frame -> raster indices, using EXACTLY the mapping the SDF's <size>/<pos> implies
        col = int(round((x + half) / cell))
        row = int(round((y + half) / cell))
        if not (0 <= row < n and 0 <= col < n):
            err.append(("outside the terrain", x, y))
            continue
        want = float(terrain[row, col]) + r * (1.0 - 2.0 * buried)
        err.append(abs(z - want))

    bad = [e for e in err if isinstance(e, tuple)]
    assert not bad, f"{len(bad)} rocks lie outside the terrain they are supposed to sit on: {bad[:3]}"
    resid = np.array([e for e in err if not isinstance(e, tuple)])
    # one DEM cell of tolerance: the rock's true footing is bilinear, we sample nearest-neighbour
    assert float(resid.max()) < cell, (
        f"a rock sits {resid.max():.3f} m off the surface (max allowed {cell:.3f} m). Either the Y-up->Z-up "
        f"axis swap or the BA-12 datum is wrong -- the rocks are floating or buried.")
    assert float(np.median(resid)) < 0.25 * cell, \
        f"rocks are systematically off the surface (median {np.median(resid):.3f} m) -- a frame bug"


def test_every_emitted_rock_is_big_enough_to_matter() -> None:
    """[REQ:BA-13] Sanity on the sourced draw: every Golombek clast here clears IPEx's own obstacle spec, so
    each one is a thing the rover must actually see and avoid. If this ever fails, the SFD changed."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
        radii = np.array([r for (_x, _y, _z, r, _b) in rec["rocks"]])
    assert float(radii.min()) >= OBSTACLE_HEIGHT_M, (
        f"the smallest emitted rock is {radii.min()*100:.1f} cm, under IPEx's {OBSTACLE_HEIGHT_M*100:.1f} cm "
        "obstacle spec -- it is noise, not an obstacle")
    assert float(radii.max()) > 0.2, "no boulder-scale clasts -- the size-frequency draw looks wrong"


def test_the_rock_field_is_SCOPED_and_what_was_dropped_is_COUNTED_not_silently_truncated() -> None:
    """[REQ:BA-13] 67,721 clasts over the full 513 m terrain would be 67,721 SDF entities and would kill the
    sim, so the field is scoped to the rover's operating area. NO SILENT CAPS: the provenance must state how
    many were in the terrain window and how many were emitted, so nobody reads this world as 'all the rocks'
    when it is not."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        rec = _build(d)
    assert rec["n_rocks_in_terrain"] > rec["n_rocks"], "the scoping did nothing -- or the provenance lies"
    assert rec["rock_window_m"] < rec["size_m"][0], "the rock window is not smaller than the terrain"
    assert rec["n_rocks"] == len(rec["rocks"]), "the emitted count disagrees with the emitted rocks"
    # and the world itself must SAY so -- a reader of the SDF must not think this is the whole field
    with tempfile.TemporaryDirectory() as d:
        rec2 = _build(d)
        world = open(rec2["world"], encoding="utf-8").read()
    assert str(rec2["n_rocks"]) in world and str(rec2["n_rocks_in_terrain"]) in world, \
        "the world does not record how many rocks it carries vs how many exist -- that is a silent cap"


def test_gazebo_and_viz2_see_THE_SAME_rocks() -> None:
    """[REQ:BA-13] ONE TRUTH, TWO ENGINES. The rock field is a seeded Golombek draw the conserved authority
    owns (TR-01 made the seed live). Gazebo must consume THAT draw, not roll its own -- otherwise the rover
    trips over a boulder in one engine that does not exist in the other, and no evidence transfers."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        a = _build(d)
    with tempfile.TemporaryDirectory() as d:
        b = _build(d)
    assert a["rock_seed"] == b["rock_seed"], "the rock draw is not seeded -- it is not reproducible"
    assert a["rocks"] == b["rocks"], "the same seed produced a different rock field -- it is not deterministic"
    assert a["source_bundle"] == b["source_bundle"] == "haworth_sfs_2km_1m", \
        "the rocks are not drawn over the authority's own DEM"
