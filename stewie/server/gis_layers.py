"""GIS raster layers over the REAL Haworth work-area DEM (the 2D planning substrate).

Each layer is computed by the existing dart machinery and rendered as an RGBA PNG overlay sized to
the work-area frame: slope (height-field gradient), hazard (build_hazard_map cost: graded amber ->
no-go red), illumination/shadow (horizon_clip at a commanded south-pole sun geometry -- shadows are
the NAVIGATION signal at Haworth, the same physics the shadow-SLAM track estimates against), and
PSR candidates (never lit across a sweep of sun azimuths at polar elevation). Rasters are cached by
(kind, params); the DEM never changes under the server.
"""
from __future__ import annotations

import io

import numpy as np

_CACHE: dict = {}


def _work_area(mp, bundle_dir=None):
    """The work-area crop the planner frames: load_haworth_dem returns (heightmap, cell_m); the
    flattest-anchor gives the site center in DEM meters. ``bundle_dir`` selects the chosen site (REG-01)."""
    pair = mp.load_haworth_dem(bundle_dir=bundle_dir)    # the (heightmap, cell_m) tuple
    dem, cell_m = pair
    ax, ay = mp.flattest_anchor(pair)                    # takes the PAIR; returns (x, y) DEM meters
    r0 = int(ay / cell_m); c0 = int(ax / cell_m)
    half = 64                                            # 128x128 cells @5 m = 640 m frame
    r0 = max(0, min(dem.shape[0] - 2 * half, r0 - half))
    c0 = max(0, min(dem.shape[1] - 2 * half, c0 - half))
    return dem[r0:r0 + 2 * half, c0:c0 + 2 * half], (r0, c0), float(cell_m)


def _to_png(rgba: np.ndarray) -> bytes:
    from imageio.v3 import imwrite
    buf = io.BytesIO()
    imwrite(buf, rgba.astype(np.uint8), extension=".png")
    return buf.getvalue()


def _upscale(a: np.ndarray, k: int = 4) -> np.ndarray:
    return np.repeat(np.repeat(a, k, axis=0), k, axis=1)


def render(kind: str, *, cell_m: float = 5.0, sun_el: float = 6.0, sun_az: float = 90.0,
           mp=None, site: str = "haworth") -> bytes | None:
    """Render one raster layer as PNG bytes; None for unknown kinds. REG-01: ``site`` selects the
    imported tile so the work-area raster follows the chosen site, not just Haworth."""
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                # raises KeyError/FileNotFoundError -> route 404
    key = (kind, site, round(float(sun_el), 2), round(float(sun_az), 2))
    if key in _CACHE:
        return _CACHE[key]
    dem, _, cell_m = _work_area(mp, bundle_dir)

    if kind == "hazard":
        # the inset hazard is the ROCK+slope navigation COST (build_hazard_map) the routing detours on -- a
        # RICHER layer than the globe/3D slope-proxy (_layer_rgba); kept distinct on purpose (#239 decision).
        from dart.hazard_map import build_hazard_map
        hm = build_hazard_map((dem, cell_m))             # the (Z, cell_m) pair convention
        cost = np.asarray(hm.cost, dtype=float)
        nogo = ~np.isfinite(cost)
        graded = np.clip((np.where(np.isfinite(cost), cost, 0.0) - 1.0) / 4.0, 0, 1)
        rgba = np.zeros((*cost.shape, 4))
        rgba[..., 0] = 255
        rgba[..., 1] = 140 * (1 - graded)
        rgba[..., 3] = np.where(nogo, 230, 170 * graded)  # transparent where benign
        rgba[nogo, 1] = 0
    elif kind in ("slope", "illumination", "incidence", "psr"):
        # #234 cleanup: these are byte-identical to the globe/work-area drape, so share the ONE source of
        # truth (_layer_rgba) instead of re-implementing each formula here. A new shared layer kind now only
        # needs adding to _layer_rgba -- this inset path picks it up. (hazard stays the richer cost above.)
        rgba = _layer_rgba(dem, cell_m, kind, sun_az, sun_el)
        if rgba is None:
            return None
    else:
        return None
    png = _to_png(_upscale(rgba))
    _CACHE[key] = png
    return png


RASTER_DEFS = [
    {"key": "slope", "name": "Slope (deg, from the real DEM)", "kind": "raster", "group": "terrain"},
    {"key": "hazard", "name": "Hazard / no-go (nav cost)", "kind": "raster", "group": "safety",
     "default": True},   # T6.1: the /layers/raster inset hazard is the rock+slope build_hazard_map COST;
    # the globe/3D drape (_layer_rgba) is a slope>=20 PROXY + the planner routes on slope_costmap (gate 25) --
    # slope-family, not byte-identical (#239: the drape carries no rock data; rock-fused cost is inset-only).
    {"key": "illumination", "name": "Shadow (horizon-clipped sun)", "kind": "raster", "group": "sun"},
    {"key": "incidence", "name": "Sun incidence (grazing-angle, from the DEM)", "kind": "raster", "group": "sun"},
    {"key": "psr", "name": "Permanently shadowed regions (PSR, never lit)", "kind": "raster", "group": "sun"},
    {"key": "grid", "name": "Site grid (100 m / 500 m)", "kind": "raster", "group": "reference", "default": True},
]


# ---- the GLOBE drape: reproject polar-stereo rasters to GEOGRAPHIC grids -----------------------
# Aaron's screenshot (2026-06-10): a stereographic image draped into a lat/lon rectangle renders
# ROTATED/misaligned. The standard GIS fix: resample onto a lat/lon grid server-side; every layer
# carries ITS OWN bbox. Implementation: build the output lat/lon grid, forward-project each output
# pixel into the polar-stereo frame (pyproj, IAU_2015:30135 -- the SAME CRS as the tile bounds),
# and sample the source raster. Vectorized numpy; cached by (kind, sun params).

_GLOBE_CACHE: dict = {}

def _np_load_rgba(path):
    import numpy as _np
    return _np.load(path)



def _tile_geo(mp, bundle_dir=None):
    """(heightmap, cell_m, world_bounds dict, the pyproj fwd transformer). ``bundle_dir`` selects the
    chosen site's tile (REG-01); None = the Haworth default / $STEWIE_DEM_DIR."""
    import json as _json
    import os as _os

    from pyproj import CRS, Transformer
    pair = mp.load_haworth_dem(bundle_dir=bundle_dir)
    meta = _json.load(open(_os.path.join(mp._haworth_bundle(bundle_dir), "metadata.json")))
    crs = CRS.from_user_input("IAU_2015:30135")
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    return pair[0], float(pair[1]), meta["world_bounds_m"], fwd


def _geographic_bbox_of_extent(x0, y0, x1, y1):
    """Project an extent's boundary ring from the polar-stereo frame (IAU_2015:30135) to selenographic
    lat/lon, returning bbox{south,north,west,east}. Ring (not just corners) because the projection bows
    the edges. Shared by the globe reproject and the OGC WMS capabilities extent (no raster needed).
    CAVEAT (off-pole assumption): a simple lon/lat min/max box. Valid for an OFF-POLE work-site tile
    (Haworth: west~-29 east~-22 south~-86.5 north~-86.1). A tile that ENCLOSES the pole or crosses the
    +/-180 antimeridian would collapse lon to ~[-180,180] and need a split bbox -- the existing globe
    drape shares this assumption, so this helper does not regress it."""
    import numpy as _np
    from pyproj import CRS, Transformer
    t = _np.linspace(0.0, 1.0, 64)
    ring_x = _np.concatenate([x0 + (x1 - x0) * t, _np.full(64, x1), x1 - (x1 - x0) * t, _np.full(64, x0)])
    ring_y = _np.concatenate([_np.full(64, y0), y0 + (y1 - y0) * t, _np.full(64, y1), y1 - (y1 - y0) * t])
    crs = CRS.from_user_input("IAU_2015:30135")
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    lons, lats = inv.transform(ring_x, ring_y)
    return {"south": float(lats.min()), "north": float(lats.max()),
            "west": float(lons.min()), "east": float(lons.max())}


def geographic_bbox(site: str = "haworth", mp=None):
    """The selenographic lat/lon bounding box of a site's tile -- the OGC WMS GetCapabilities extent,
    computed WITHOUT a raster render (reads only the tile metadata's polar-stereo world bounds)."""
    import json as _json
    import os as _os
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                    # raises KeyError/FileNotFoundError
    meta = _json.load(open(_os.path.join(mp._haworth_bundle(bundle_dir), "metadata.json")))
    b = meta["world_bounds_m"]
    return _geographic_bbox_of_extent(b["x0"], b["y0"], b["x1"], b["y1"])


def _reproject(source_rgba, b, fwd, *, out_px: int = 1024, sub=None):
    """Resample an RGBA raster (north-up in the stereo frame, extent = b or the sub-window) onto a
    geographic grid. Returns (rgba_geo uint8, bbox{south,north,west,east})."""
    import numpy as _np
    if sub is not None:
        x0, y0, x1, y1 = sub
    else:
        x0, y0, x1, y1 = b["x0"], b["y0"], b["x1"], b["y1"]
    bbox = _geographic_bbox_of_extent(x0, y0, x1, y1)        # the geographic extent (shared helper)
    # the output grid -> stereo coords -> source pixel indices
    H = out_px
    W = max(64, int(out_px * (bbox["east"] - bbox["west"])
                    / max(1e-9, (bbox["north"] - bbox["south"])) *
                    _np.cos(_np.radians((bbox["south"] + bbox["north"]) / 2.0))))
    W = min(W, 4096)
    lon_g, lat_g = _np.meshgrid(_np.linspace(bbox["west"], bbox["east"], W),
                                _np.linspace(bbox["north"], bbox["south"], H))
    xs, ys = fwd.transform(lon_g, lat_g)
    sh, sw = source_rgba.shape[:2]
    col = (xs - x0) / (x1 - x0) * (sw - 1)
    row = (y1 - ys) / (y1 - y0) * (sh - 1)              # north-up raster: row 0 = y1
    valid = (col >= 0) & (col <= sw - 1) & (row >= 0) & (row <= sh - 1)
    ci = _np.clip(col.round().astype(int), 0, sw - 1)
    ri = _np.clip(row.round().astype(int), 0, sh - 1)
    out = source_rgba[ri, ci]
    out[~valid] = 0                                      # transparent outside the true footprint
    return out.astype("uint8"), bbox


def _layer_rgba(dem, cell, kind, sun_az=315.0, sun_el=45.0):
    """GIS-WA2: each layer's colouring as a PURE function of a DEM patch + its cell size -- the single
    source of truth shared by the globe drape (render_globe, full-tile, reprojected) and the order-frame
    work-area drape (/dem/workarea.png, native crop). Returns (H,W,4) uint8 RGBA, or None for an unknown
    kind. 'dem'/'hillshade' = 315/45 lambertian relief; slope/incidence/psr/illumination from the gradient
    or the real horizon (dart.illumination).
    HAZARD honesty (#239): this is a slope>=20deg TESTED-envelope [WHEELTEST] PROXY -- it is NOT the
    rock+roughness-fused navigation COST that render() draws via dart.hazard_map.build_hazard_map (the
    surveyed work-area inset), nor the slope_costmap (gate 25deg) the PLANNER actually routes on. The
    drape patches carry no rock data, so the rock-fused cost only exists in the inset; these three are
    slope-FAMILY but not byte-identical. Don't 'unify' to build_hazard_map: the planner doesn't route on it."""
    import numpy as np
    dem = np.asarray(dem, dtype=float)
    if kind in ("dem", "hillshade"):
        gy, gx = np.gradient(dem, cell)
        az, el = np.radians(float(sun_az)), np.radians(float(sun_el))
        nx, ny, nz = -gx, -gy, np.ones_like(gx)
        norm = np.sqrt(nx * nx + ny * ny + nz * nz)
        lx = np.cos(el) * np.sin(az); ly = np.cos(el) * np.cos(az); lz = np.sin(el)
        shade = np.clip((nx * lx + ny * ly + nz * lz) / norm, 0.0, 1.0)
        g8 = (40 + shade * 200).astype("uint8")          # lift the floor so shadows stay readable
        return np.dstack([g8, g8, g8, np.full(g8.shape, 255, dtype="uint8")])
    if kind == "slope":
        gy, gx = np.gradient(dem, cell)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        t = np.clip(slope / 30.0, 0, 1)
        rgba = np.zeros((*slope.shape, 4))
        rgba[..., 0] = 60 + 195 * t; rgba[..., 1] = 200 * (1 - t); rgba[..., 2] = 40
        rgba[..., 3] = 90 + 120 * t
        return rgba.astype("uint8")
    if kind == "hazard":
        gy, gx = np.gradient(dem, cell)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        nogo = slope > 20.0                               # the TESTED envelope [WHEELTEST]
        graded = np.clip((slope - 15.0) / 5.0, 0, 1)      # nominal->tested band
        rgba = np.zeros((*slope.shape, 4))
        rgba[..., 0] = 255; rgba[..., 1] = 140 * (1 - graded)
        rgba[..., 3] = np.where(nogo, 230, 170 * graded)
        rgba[nogo, 1] = 0
        return rgba.astype("uint8")
    if kind == "illumination":
        from dart.illumination import horizon_clip
        lit = horizon_clip(dem, cell, float(sun_az), float(sun_el))
        rgba = np.zeros((*lit.shape, 4))
        rgba[..., 2] = 180; rgba[..., 3] = np.where(lit, 0, 165)
        return rgba.astype("uint8")
    if kind == "psr":
        from dart.illumination import horizon_clip
        ever_lit = np.zeros(dem.shape, dtype=bool)
        for az in range(0, 360, 30):
            ever_lit |= horizon_clip(dem, cell, float(az), 3.0)
        rgba = np.zeros((*dem.shape, 4))
        rgba[..., 0] = 90; rgba[..., 2] = 200
        rgba[..., 3] = np.where(ever_lit, 0, 200)
        return rgba.astype("uint8")
    if kind == "incidence":
        # TW-07: per-pixel solar INCIDENCE angle (DEM-normal vs sun direction) -- grazing light washes out
        # cameras + yields poor solar flux even where geometrically lit. Amber ramp 0deg faint -> 90+deg
        # opaque. Ported here (#239) so the globe + work-area/3D incidence drape work (was _layer_rgba->None).
        from dart.illumination import incidence_angle_deg
        inc = incidence_angle_deg(dem, cell, float(sun_az), float(sun_el))
        t = np.clip(np.nan_to_num(inc, nan=90.0) / 90.0, 0, 1)
        rgba = np.zeros((*inc.shape, 4))
        rgba[..., 0] = 255; rgba[..., 1] = 200 * (1 - t); rgba[..., 2] = 40
        rgba[..., 3] = 40 + 170 * t
        return rgba.astype("uint8")
    return None


def render_globe(kind: str, *, sun_el: float = 6.0, sun_az: float = 90.0, mp=None,
                 grid_color: str = "39ff14", site: str = "haworth"):
    """The geographic drape for the globe: 'dem' = the full-tile hillshade; the GIS rasters
    reproject over the WORK AREA's own extent. Returns (rgba uint8, bbox). REG-01: ``site`` selects the
    imported tile so the globe drape follows the chosen site, not just Haworth."""
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                # raises KeyError/FileNotFoundError -> route 404
    key = ("globe", kind, site, round(float(sun_el), 2), round(float(sun_az), 2),
           grid_color if kind == "grid" else "")
    if key in _GLOBE_CACHE:
        return _GLOBE_CACHE[key]
    # disk cache: survive restarts; PSR/illumination cost seconds-to-minutes to compute
    import json as _json
    import os as _oss
    from stewie.specs import config as _CFG
    cdir = _oss.path.join(_CFG.data_dir(), "globe_cache")
    _oss.makedirs(cdir, exist_ok=True)
    # _r2: cache-version token -- bumped when the render math changes (R-1: dem drape now native-res, not
    # 1024) so a stale globe_cache entry can't keep serving the old resolution after a deploy. Bump on any
    # future render change.
    stem = _oss.path.join(cdir, f"{kind}_{site}_{key[3]}_{key[4]}_r2" + (f"_{grid_color}" if kind == "grid" else ""))
    if _oss.path.exists(stem + ".npy") and _oss.path.exists(stem + ".json"):
        out = (_np_load_rgba(stem + ".npy"), _json.load(open(stem + ".json")))
        _GLOBE_CACHE[key] = out
        return out

    import numpy as _np
    dem_full, cell_m, b, fwd = _tile_geo(mp, bundle_dir)
    if kind == "dem":
        # CLEAN cartographic hillshade (315/45 lambertian) computed from the RAW heightmap via the shared
        # _layer_rgba helper (the order-frame work-area drape uses the same). The real-sun SHADOW layer is
        # separate. R-1 (#234): drape at the DEM's NATIVE resolution, not a fixed 1024 (which ~2x-downsampled
        # the 2000-px / 5 m Haworth tile). Cap at 2048 so an oversized DEM can't blow up the reproject.
        rgba = _layer_rgba(dem_full, cell_m, "dem")
        out = _reproject(rgba, b, fwd, out_px=min(int(_np.asarray(dem_full).shape[0]), 2048))
    else:
        # FULL-TILE analysis rasters for the globe (Aaron 2026-06-10: "when hazard is clicked the
        # full tile isn't loaded") -- computed from the whole heightmap at a working downsample;
        # the work-area crop remains the inset's product. Disclosure: ROCK hazards exist only
        # where mapped (the surveyed crop); the full-tile hazard is slope-derived.
        # PSR's 12-azimuth horizon sweep measured 44 s at 768px (Aaron: "psr does not load in
        # main screen") -- the sweep runs at 384px (~4x faster, same 30-deg azimuth step); other
        # kinds keep 768. Products disk-cache under data_dir so each computes ONCE per sun key.
        if kind == "grid":
            # #54: the site reference grid (the lunar-ops analog of MGRS): site-frame eastings/
            # northings every 100 m (minor) and 500 m (major). Labels live in the inset axes +
            # the cursor's site-meters readout; the drape carries the LINES.
            n = 1000                                       # 10 m/px over the 10 km tile
            # color chosen by the operator (Aaron: white is unreadable over hazard/slope;
            # default = neon wiremesh green)
            h = grid_color.lstrip("#")
            try:
                cr, cg, cb = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except (ValueError, IndexError):
                cr, cg, cb = 0x39, 0xFF, 0x14
            rgba = _np.zeros((n, n, 4), dtype="uint8")
            for m in range(0, 10001, 100):
                i = min(n - 1, int(m / 10000 * n))
                major = (m % 500 == 0)
                a = 170 if major else 80
                for ch, v in ((0, cr), (1, cg), (2, cb)):
                    rgba[i, :, ch] = v; rgba[:, i, ch] = v
                rgba[i, :, 3] = _np.maximum(rgba[i, :, 3], a)
                rgba[:, i, 3] = _np.maximum(rgba[:, i, 3], a)
            out = _reproject(rgba, b, fwd, out_px=1024)
            _GLOBE_CACHE[key] = out
            return out
        px = 384 if kind == "psr" else 768
        stride = max(1, dem_full.shape[0] // px)
        dem = _np.asarray(dem_full, dtype=float)[::stride, ::stride]
        cm = cell_m * stride
        # the per-kind colouring is the shared _layer_rgba helper (same formulas the order-frame
        # work-area drape uses); here it runs on the downsampled full tile + is reprojected for the globe.
        rgba = _layer_rgba(dem, cm, kind, sun_az, sun_el)
        if rgba is None:
            return None
        out = _reproject(rgba, b, fwd, out_px=1024)   # _layer_rgba already returns uint8
    _GLOBE_CACHE[key] = out
    # RC-03 (audit 2026-06-11): write ATOMICALLY (.part -> os.replace) so a concurrent reader /
    # the startup warm thread never sees a torn .npy; the JSON sidecar lands LAST as the commit
    # marker (a reader checks .npy AND .json, so a half-written pair is never both-present).
    try:
        import json as _json
        import os as _os3
        import numpy as _np2
        npt, jt = stem + ".npy.part", stem + ".json.part"
        with open(npt, "wb") as _nf:                     # GIS-04: save to the file OBJECT -> writes the EXACT
            _np2.save(_nf, out[0]); _nf.flush(); _os3.fsync(_nf.fileno())   # .npy.part (np.save to a PATH appends '.npy')
        with open(jt, "w") as _jf:
            _json.dump(out[1], _jf); _jf.flush(); _os3.fsync(_jf.fileno())
        _os3.replace(npt, stem + ".npy")                 # the data
        _os3.replace(jt, stem + ".json")                 # the commit marker, last
    except OSError:
        pass
    return out
