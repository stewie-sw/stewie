"""[REQ:BA-04/BA-12] Generate a Gazebo terrain world from the REAL Haworth lunar DEM.

Crops a window of the CONSERVED AUTHORITY'S OWN DEM and writes it as a georeferenced **float32 GeoTIFF**,
plus a world SDF whose terrain geometry is that DEM. No fabricated terrain -- the raster IS the DEM.

WHAT CHANGED, AND WHY (BA-12). This script used to write an **8-bit greyscale PNG**, and its docstring
asserted that was forced: "gz-sim reads an 8-bit grayscale heightmap of side 2^n+1". **THAT IS FALSE**, and
it was verified false in our own container (`stewie-gazebo:jazzy`):

    libgz-common5-geospatial.so.5.8.0   ->  ldd shows libgdal.so.34      ** LINKS GDAL **
    gz/common/geospatial/Dem.hh         ->  class Dem : public HeightmapData ("Encapsulates a DEM file")
                                            double Elevation(double x, double y)

gz-sim reads a **GeoTIFF DEM directly, with float elevation**. So the quantisation was self-inflicted, and
it was severe -- 8 bits across 933.761 m of relief is a **3.662 m vertical step**, against a machine whose
anti-bridging dig pass is 13.2 mm (1/277 of a step), whose obstacle spec is 7.5 cm (1/49 of a step), and
whose own wheel radius is 15.2 cm (1/24 of a step). At rover scale the world was a smooth blob: no rocks,
no obstacles, no ruts, no berms. That does not merely block excavation -- it breaks the PERCEPTION AND
NAVIGATION the Gazebo world exists to serve.

AND A SECOND TRUTH, WORSE THAN THE QUANTISATION. The old default sourced `haworth_10km_5m` (5 m cell) while
viz2 and the conserved authority drive on `haworth_sfs_2km_1m` (1 m cell). Gazebo's terrain was **not even
the same DEM**. The architecture rule is that the conserved authority is the SINGLE physics authority and
Gazebo is a ROS sensor shell that CONSUMES its raster -- one truth, two engines. Two truths mean evidence
gathered in one engine does not transfer to the other, which is exactly the divergence to avoid.

WHAT THIS DOES NOT CLAIM. Horizontal resolution is bounded by the DEM itself. You cannot resolve a 7.5 cm
obstacle from a 1 m raster, and inventing sub-metre terrain would be fabrication. Rocks and boulders belong
as **clast collision models** (the sourced Golombek draw the authority already carries), NOT baked into a
heightmap -- no raster at 1 m can represent a 0.3 m boulder, and pretending otherwise is how you get a world
that looks detailed and teaches a perception stack nothing.

CLI: python -m scripts.dem_to_gazebo_heightfield [out_dir]
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

from stewie.terrain.site_dem import load_haworth_dem

#: The bundle the CONSERVED AUTHORITY (viz2 / Viz2Runtime / the frozen scenarios) actually drives on. Gazebo
#: reads THE SAME ONE -- that is the whole point (one truth, two engines).
AUTHORITY_BUNDLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "samples", "lunar_dem", "haworth_sfs_2km_1m")

#: Window side in cells. 513 = 2^9+1 (kept 2^k+1: gz's heightmap LOD is happiest there, and it costs nothing).
#: At the authority's 1 m cell that is a 512 m worksite -- large enough to navigate, small enough to stay at
#: FULL DEM resolution instead of decimating the very detail this row exists to preserve.
_N = 513


#: [REQ:BA-13] Side of the ROCK window, in metres, centred in the terrain. The full 513 m terrain window holds
#: 67,721 Golombek clasts -- 67,721 SDF entities would kill the sim -- and the rover does not need boulders
#: 250 m away to navigate. This is the operating area, and whatever falls outside it is COUNTED AND REPORTED,
#: never silently dropped.
ROCK_WINDOW_M = 128.0

#: The seeded Golombek draw the CONSERVED AUTHORITY owns (TR-01 made the seed live). Gazebo consumes THIS
#: draw rather than rolling its own, so both engines see the SAME rocks: one truth, two engines.
ROCK_SEED = 0


def _pow2_plus_1(n: int) -> int:
    """Largest 2^k+1 that fits in n."""
    return (1 << int(math.log2(max(n - 1, 2)))) + 1


def _rocks_local(bundle: str, r0: int, c0: int, n: int, cell: float, datum_m: float,
                 window_m: float, seed: int) -> tuple[list, int]:
    """[REQ:BA-13] The authority's clasts, converted into Gazebo's LOCAL worksite frame.

    THE FRAME CONVERSION IS THE WHOLE RISK, so it is spelled out. The authority emits each clast as

        center_m = [x_world, ELEVATION, y_world]        <- GODOT'S Y-UP frame, absolute IAU_2015:30135 metres

    while Gazebo is **Z-UP**, and BA-12 additionally ZERO-BASED the terrain against a ~1748 m datum and
    centred it on the world origin. Get the axis swap or the datum wrong and every rock floats in the sky or
    sinks out of sight -- and from a distance it would still look like a rock field, which is why the gate
    checks each rock against the raster rather than merely counting them.

        gz_x = x_world  - window_centre_x
        gz_y = y_world  - window_centre_y
        gz_z = ELEVATION - datum_m

    The ELEVATION already carries the burial (`terrain + r*(1 - 2*buried_frac)`, the authority's own placement
    law), so it is used as-is rather than re-derived.
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_rfc", os.path.join(here, "viz2_rockfield_clasts.py"))
    rfc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rfc)

    field = rfc.build_clasts(bundle, r0, c0, n, world_seed=seed)
    clasts = field["clasts"]
    n_in_terrain = len(clasts)

    # the terrain window's centre, in the DEM's own world metres (the SDF centres the heightmap on 0,0)
    with open(os.path.join(bundle, "metadata.json"), encoding="utf-8") as fh:
        wb = json.load(fh)["world_bounds_m"]
    cx = float(wb["x0"]) + (c0 + n / 2.0) * cell
    cy = float(wb["y0"]) + (r0 + n / 2.0) * cell

    half_w = 0.5 * float(window_m)
    rocks = []
    for c in clasts:
        x_w, elev, y_w = (float(v) for v in c["center_m"])   # Y-UP: [x, ELEVATION, y]
        gx, gy = x_w - cx, y_w - cy                          # -> Z-UP planar
        if abs(gx) > half_w or abs(gy) > half_w:
            continue                                         # outside the rover's operating area
        rocks.append((round(gx, 4), round(gy, 4), round(elev - datum_m, 4),
                      float(c["radius_m"]), float(c["buried_frac"])))
    return rocks, n_in_terrain


def _rockfield_sdf(rocks: list) -> str:
    """ONE STATIC MODEL with N <collision>/<visual> spheres in ONE link. N separate <model>s would be N
    entities and would kill the sim; N collision shapes in a single static link is cheap for ODE (static
    geometry, no dynamics, no per-entity bookkeeping)."""
    parts = []
    for i, (x, y, z, r, _b) in enumerate(rocks):
        parts.append(
            f'        <collision name="c{i}"><pose>{x} {y} {z} 0 0 0</pose>'
            f'<geometry><sphere><radius>{r:.4f}</radius></sphere></geometry></collision>\n'
            f'        <visual name="v{i}"><pose>{x} {y} {z} 0 0 0</pose>'
            f'<geometry><sphere><radius>{r:.4f}</radius></sphere></geometry>'
            f'<material><ambient>0.18 0.17 0.16 1</ambient><diffuse>0.30 0.29 0.27 1</diffuse></material>'
            f'</visual>\n')
    return ('    <model name="rockfield">\n      <static>true</static>\n      <link name="rocks">\n'
            + "".join(parts) + '      </link>\n    </model>\n')


def _world_sdf(size_x: float, size_y: float, relief: float, dem_uri: str, datum_m: float = 0.0,
               rocks: list | None = None, n_rocks_in_terrain: int = 0,
               rock_window_m: float = 0.0) -> str:
    z = max(relief, 0.1)
    rocks = rocks or []
    # NO SILENT CAPS. State what this world carries vs what actually exists, so nobody reads it as "all the
    # rocks" when it is scoped to the rover's operating area.
    rock_note = (f"     ROCKS: {len(rocks)} clast collision+visual spheres from the sourced Golombek draw "
                 f"(seed {ROCK_SEED}), scoped to a {rock_window_m:.0f} m rover operating area centred in the "
                 f"terrain. {n_rocks_in_terrain} clasts exist across the full {size_x:.0f} m terrain window; "
                 f"the remainder are OUT OF SCOPE, not missing. They are OBJECTS, not heightmap detail: at "
                 f"the DEM's 1 m cell a 0.29 m boulder is a third of one pixel, so a raster physically cannot "
                 f"represent one.\n")
    return f"""<?xml version="1.0"?>
<!-- {rock_note.strip()} -->
<!-- [REQ:BA-04/BA-12] GENERATED by scripts/dem_to_gazebo_heightfield.py from the real Haworth LOLA DEM.
     The terrain is a FLOAT32 GeoTIFF DEM read through gz-common's GDAL-backed Dem class -- NOT an 8-bit
     PNG (which quantised 933 m of relief into 3.66 m steps and made the world unusable at rover scale),
     and NOT a flat plane. Sourced from the SAME bundle the conserved authority drives on: one truth, two
     engines.

     LOCAL WORKSITE FRAME. The DEM is ZERO-BASED: gz uses a DEM's RAW values on the z axis (it takes only
     the x/y extent from <size>), so raw lunar elevations put the terrain 1.7 km above the world origin and
     the rover would spawn underneath it. Elevations here run 0..{z:.3f} m; the absolute datum is
     {datum_m:.3f} m, so a true elevation is `z + {datum_m:.3f}`.

     Regenerate; do not hand-edit. -->
<sdf version="1.9">
  <world name="stewie_lunar">
    <gravity>0 0 -1.62</gravity>
    <physics name="1ms" type="ignored"><max_step_size>0.001</max_step_size></physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <light type="directional" name="sun">
      <cast_shadows>true</cast_shadows><direction>0.5 0.2 -0.85</direction>
      <diffuse>1 1 1 1</diffuse><specular>0.3 0.3 0.3 1</specular>
    </light>
    <model name="haworth_terrain">
      <static>true</static>
      <link name="surface">
        <collision name="collision">
          <geometry><heightmap>
            <uri>{dem_uri}</uri>
            <size>{size_x:.3f} {size_y:.3f} {z:.3f}</size>
            <pos>0 0 0</pos>
          </heightmap></geometry>
        </collision>
        <visual name="visual">
          <geometry><heightmap>
            <uri>{dem_uri}</uri>
            <size>{size_x:.3f} {size_y:.3f} {z:.3f}</size>
            <pos>0 0 0</pos>
          </heightmap></geometry>
          <material><ambient>0.25 0.25 0.25 1</ambient><diffuse>0.35 0.35 0.35 1</diffuse></material>
        </visual>
      </link>
    </model>
{_rockfield_sdf(rocks)}  </world>
</sdf>
"""


def build_heightfield(out_dir: str, *, n: int = _N, bundle_dir: str | None = None) -> dict:
    """Crop the authority's DEM -> write terrain.tif (float32, georeferenced) + haworth_heightfield.sdf.

    The raster carries the DEM's OWN elevations in metres -- no normalisation, no rescale, NO QUANTISATION.
    `<size>` still states the extent + relief because gz uses it to place the DEM in the world; the float
    values are what it interpolates between.
    """
    import rasterio
    from rasterio.transform import Affine

    bundle = bundle_dir or AUTHORITY_BUNDLE
    Z, cell = load_haworth_dem(bundle)
    H, W = Z.shape
    n = _pow2_plus_1(min(n, H, W))
    r0, c0 = (H - n) // 2, (W - n) // 2
    win = np.ascontiguousarray(Z[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    zmin, zmax = float(win.min()), float(win.max())
    relief = zmax - zmin

    # ZERO-BASE THE ELEVATIONS -- and this is not cosmetic, it was a real bug caught only by loading the
    # world in the container. For a DEM heightmap gz uses the raster's RAW values on the z axis and IGNORES
    # the `<size>` z (it uses `<size>` only for the x/y extent). Shipping raw lunar elevations therefore put
    # the terrain 1.7 km above the world origin -- gz reported
    #     ODE Heightfield AABB: min = {-256, -256, ~0} max = {256, 256, 1764.56}
    # so the rover would have spawned a mile underneath the ground it is supposed to drive on. The file was
    # perfectly correct and the world was broken; only running it proved it.
    #
    # The Gazebo world is a LOCAL WORKSITE FRAME (the same local-origin discipline as GW-12 for the render
    # path), so the surface sits on z=0 and the absolute datum is RECORDED rather than lost: `datum_m` below
    # and the SDF header both carry it, so any elevation can be recovered as `z + datum_m`.
    local = np.ascontiguousarray(win - zmin, dtype=np.float32)     # FLOAT, not uint8; 0 .. relief

    os.makedirs(out_dir, exist_ok=True)
    dem = os.path.join(out_dir, "terrain.tif")
    # Georeference the crop in the DEM's own grid (origin at the window's top-left, cell-sized pixels), so
    # the raster carries its provenance instead of floating free of it. The CRS is best-effort: if gz's GDAL
    # cannot resolve the lunar authority it simply falls back to `<size>` for the extent, which is correct
    # anyway -- so a missing CRS costs provenance, never geometry.
    transform = Affine.translation(c0 * cell, r0 * cell) * Affine.scale(cell, cell)
    crs = None
    try:
        from rasterio.crs import CRS
        crs = CRS.from_user_input("IAU_2015:30135")   # the lunar south-polar frame the bundle is in
    except Exception:                                  # noqa: BLE001 - provenance is optional, geometry is not
        crs = None
    with rasterio.open(dem, "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", transform=transform, crs=crs, nodata=None) as ds:
        ds.write(local, 1)

    # [REQ:BA-13] The rocks. NOT baked into the raster -- at a 1 m cell a 0.29 m boulder is a third of one
    # pixel, so the terrain physically cannot carry it. They enter as OBJECTS: collision + visual geometry at
    # their real positions and radii, from the CONSERVED AUTHORITY'S OWN seeded Golombek draw, so Gazebo and
    # viz2 see the same rock field (one truth, two engines).
    rocks, n_in_terrain = _rocks_local(bundle, r0, c0, n, cell, zmin, ROCK_WINDOW_M, ROCK_SEED)

    size_x = size_y = float(n * cell)
    world = os.path.join(out_dir, "haworth_heightfield.sdf")
    with open(world, "w", encoding="utf-8") as fh:
        fh.write(_world_sdf(size_x, size_y, relief, "terrain.tif", zmin,
                            rocks, n_in_terrain, ROCK_WINDOW_M))
    return {"dem": dem, "world": world, "n": n, "cell_m": cell, "relief_m": relief,
            "size_m": (size_x, size_y, relief), "z_range_m": (zmin, zmax), "datum_m": zmin,
            "crs": str(crs) if crs else None,
            "rocks": rocks, "n_rocks": len(rocks), "n_rocks_in_terrain": n_in_terrain,
            "rock_window_m": ROCK_WINDOW_M, "rock_seed": ROCK_SEED,
            "source_bundle": os.path.basename(os.path.normpath(bundle))}


def main(argv=None) -> int:
    a = argv if argv is not None else sys.argv[1:]
    out = a[0] if a else os.path.join(os.path.dirname(__file__), "..", "ros2_ws",
                                      "src", "stewie_description", "worlds")
    rec = build_heightfield(os.path.abspath(out))
    print(f"wrote {rec['world']} + {rec['dem']}: {rec['n']}x{rec['n']} @ {rec['cell_m']:g} m "
          f"(float32, from {rec['source_bundle']}), relief {rec['relief_m']:.1f} m, "
          f"extent {rec['size_m'][0]:.0f} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
