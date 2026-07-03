"""[REQ:BA-05] the STEWIE coordinate-frame transform chain, as a typed contract + verified converters.

The autonomy stack spans six frames -- body_crs -> site_enu -> map -> odom -> base_link -> sensors --
plus the Godot render frame (Y-up). This module makes the STATIC seams explicit and TESTED and names the
DYNAMIC seams (owned by the ROS TF tree at runtime), so a wiring mistake between frames is a caught error,
not a silent misprojection. It reuses the existing georef (`stewie.terrain.site_dem`) and does not
duplicate or fabricate coordinates.

Frames (outer geodetic -> inner sensor):
- body_crs   : planetary lat/lon on the body ellipsoid (GI-02: Moon IAU_2015:30100 / Mars :49900).
- site_enu   : local East-North-Up metres, anchored at the site DEM origin. IS the ROS `map` frame.
- map        : ROS world frame (== site_enu by construction).
- odom       : ROS odometry frame; map->odom is the localization drift correction (dynamic TF).
- base_link  : rover body (REP-103: x-fwd, y-left, z-up); odom->base_link is odometry (dynamic TF).
- sensors    : URDF fixed sensor joints off base_link (static, from ipex.urdf.xacro).
- Godot      : the render frame (Y-up); ROS<->Godot is a fixed axis swap (below).
"""
from __future__ import annotations

Vec3 = tuple[float, float, float]

# The six-frame chain, each seam tagged static/dynamic + its owner.
FRAME_CHAIN: tuple[tuple[str, str, str], ...] = (
    ("body_crs", "site_enu", "static: planetary lat/lon <-> local ENU at the DEM origin (site_dem georef)"),
    ("site_enu", "map", "static: the site ENU IS the ROS `map` frame (identity by construction)"),
    ("map", "odom", "dynamic: localization drift correction (ROS TF)"),
    ("odom", "base_link", "dynamic: wheel/visual odometry (ROS TF)"),
    ("base_link", "sensors", "static: URDF fixed sensor joints (ipex.urdf.xacro)"),
)


def rep103_to_godot(x: float, y: float, z: float) -> Vec3:
    """ROS REP-103 (Z-up: x-fwd, y-left, z-up) -> Godot (Y-up). Per `sidecar.gd`:
    ``(x,y,z)_zup -> (x,z,-y)_yup`` (e.g. the Z-up spin axis (0,1,0) maps to Godot (0,0,-1))."""
    return (x, z, -y)


def godot_to_rep103(gx: float, gy: float, gz: float) -> Vec3:
    """Godot (Y-up) -> ROS REP-103 (Z-up). Exact inverse of :func:`rep103_to_godot`:
    ``(gx,gy,gz) -> (gx,-gz,gy)``."""
    return (gx, -gz, gy)


def body_to_site_enu(lat: float, lon: float, *, bundle_dir: str | None = None) -> tuple[float, float]:
    """Planetary lat/lon (body CRS) -> local ENU metres at the site DEM origin. Wraps
    `stewie.terrain.site_dem.latlon_to_dem_origin` (no duplication). Raises ImportError if pyproj
    (the [planner] extra) is absent -- it never fabricates coordinates."""
    from stewie.terrain.site_dem import latlon_to_dem_origin
    return latlon_to_dem_origin(lat, lon, bundle_dir=bundle_dir)


def site_enu_to_body(x: float, y: float, *, bundle_dir: str | None = None) -> tuple[float, float]:
    """Local ENU metres (site DEM-origin frame) -> planetary lat/lon. Inverse of
    :func:`body_to_site_enu`; wraps `stewie.terrain.site_dem.dem_origin_to_latlon`."""
    from stewie.terrain.site_dem import dem_origin_to_latlon
    return dem_origin_to_latlon(x, y, bundle_dir=bundle_dir)
