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
_CACHE_MAX = 256          # #283: FIFO cap so the per-(kind,site,sun) PNG cache can't grow without bound


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
           mp=None, site: str = "haworth", slope_vmax: float = 30.0, slope_classes: int = 0) -> bytes | None:
    """Render one raster layer as PNG bytes; None for unknown kinds. REG-01: ``site`` selects the
    imported tile so the work-area raster follows the chosen site, not just Haworth. G5 (#251):
    slope_vmax/slope_classes are the slope layer's graduated-renderer controls (so the PIP-overlay raster
    matches the globe drape's symbology); ignored for other kinds."""
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                # raises KeyError/FileNotFoundError -> route 404

    if kind == "traffic":
        # [REQ:TW-11] the traversal-hardening (Dr) layer from the site's persistent TrafficMemory -- WHERE the
        # rover drove and HOW MUCH the repeated traffic hardened the regolith (color = the physics Dr band;
        # opacity = the per-layer normalized hardening, so a repeatedly-driven haul road reads darker/opaque).
        # NOT cached: it changes as each SIM run folds new traffic (a cache would serve a stale corridor).
        from stewie.specs.config import data_dir
        from stewie.twin import traffic_memory as _TW
        mem = _TW.load_site(data_dir(), site)
        if mem is None:                                  # no traffic recorded yet -> a transparent (not blank-404) layer
            dem, _rc, _cm = _work_area(mp, bundle_dir)
            return _to_png(_upscale(np.zeros((*dem.shape, 4))))
        return _to_png(_upscale(_traffic_rgba(mem)))

    # #283: quantize the sun to INT degrees + bound it, and key the cache on it ONLY for sun-sensitive kinds
    # (slope/hazard/psr ignore the sun -- keying on sub-degree sun would bust the cache + grow _CACHE without
    # bound on the /layers/raster route, mirroring the dem.py /dem/workarea.png treatment, #239). Quantizing
    # the VALUE (not just the key) keeps the cached layer consistent with its key.
    sun_el = float(max(-90, min(90, round(float(sun_el)))))
    sun_az = float(round(float(sun_az)) % 360)
    sym = (round(float(slope_vmax), 2), int(slope_classes)) if kind == "slope" else (30.0, 0)   # G5 key
    sun_part = (sun_el, sun_az) if kind in ("illumination", "incidence") else None
    key = (kind, site, sun_part, sym)
    if key in _CACHE:
        return _CACHE[key]
    dem, (r0, c0), cell_m = _work_area(mp, bundle_dir)

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
        gnb = None
        if kind in ("illumination", "incidence"):   # #266: re-express the TRUE sun az in the grid frame
            try:
                from stewie.terrain.site_dem import grid_north_bearing_deg
                cx = (c0 + dem.shape[1] / 2.0) * cell_m; cy = (r0 + dem.shape[0] / 2.0) * cell_m
                gnb = grid_north_bearing_deg(cx, cy, bundle_dir=bundle_dir)
            except (ImportError, ValueError):        # pyproj absent / off-tile -> skip (uncorrected)
                gnb = None
        rgba = _layer_rgba(dem, cell_m, kind, sun_az, sun_el,
                           slope_vmax=slope_vmax, slope_classes=slope_classes, grid_north_bearing=gnb)
        if rgba is None:
            return None
    else:
        return None
    png = _to_png(_upscale(rgba))
    _CACHE[key] = png
    if len(_CACHE) > _CACHE_MAX:
        try:                                             # #283: FIFO evict. council #55 pass2 [1]: guard iter+next
            _CACHE.pop(next(iter(_CACHE)), None)         # against a concurrent insert (render() runs in the sync
        except (RuntimeError, StopIteration):            # threadpool) -- 'dict changed size' would else 500 a tile
            pass
    return png


# [REQ:TW-11] the traversal-hardening Dr band ramp (design section 7 §1.8): loose -> paved.
_TRAFFIC_THRESHOLDS = (0.2, 0.4, 0.6, 0.8)
_TRAFFIC_COLORS = ((247, 247, 247), (204, 204, 204), (150, 150, 150), (99, 99, 99), (37, 37, 37))


def _traffic_rgba(mem) -> np.ndarray:
    """RGBA for the TW-11 traffic layer: COLOR = the physics Dr band (loose #f7f7f7 -> paved #252525);
    OPACITY = per-layer normalized hardening on the driven cells (transparent where pristine), so a
    repeatedly driven haul road reads darker + more opaque than a single pass. Honest to the modest IPEx-wheel
    Dr regime -- it shows WHERE traffic hardened and the RELATIVE intensity; the /world/traffic-layer readout
    carries the absolute Dr + bearing uplift."""
    dr = mem.relative_density()
    passes = np.asarray(mem._passes)
    rgba = np.zeros((*dr.shape, 4), dtype=np.float64)
    idx = np.digitize(dr, _TRAFFIC_THRESHOLDS)           # 0..4 -> the Dr band
    for k, col in enumerate(_TRAFFIC_COLORS):
        rgba[idx == k, :3] = col
    trafficked = passes > 0
    peak = float(dr.max()) if dr.size else 0.0
    norm = (dr / peak) if peak > 0.0 else np.zeros_like(dr)
    rgba[..., 3] = np.where(trafficked, 60.0 + 180.0 * norm, 0.0)   # min-visible + intensity ramp
    return rgba


def _render_globe_traffic(mp, bundle_dir, site):
    """[REQ:TW-11] the GEOGRAPHIC globe drape of the site's persistent TrafficMemory traversal-compaction (Dr):
    the REAL per-cell hardening the SIM execute->remember loop folded in (traffic_fold -> traffic_memory),
    reprojected over the FIXED work-area crop the TrafficMemory grid lives on (the SAME 128x128 @ cell_m frame
    every /layers/raster layer + traffic_fold.work_grid_frame use), so it CO-REGISTERS with the dem/slope/hazard
    drapes. Where the rover has driven it shows the real compaction (_traffic_rgba over Dr); where it has not it
    is transparent (honest -- no fabricated compaction). Returns (rgba uint8, bbox). Uncached (each SIM run folds
    new traffic; a cache would serve a stale road)."""
    import numpy as _np

    from stewie.specs.config import data_dir
    from stewie.twin import traffic_memory as _TW
    dem_full, _cell_m, b, fwd, tile_crs = _tile_geo(mp, bundle_dir)
    H, W = _np.asarray(dem_full).shape[:2]
    mem = _TW.load_site(data_dir(), site)
    if mem is not None:
        # the crop offset is the mem's OWN order-frame origin (c0*cell_m, r0*cell_m) -- exactly where the fold
        # placed it -- so the drape is self-consistent with the accumulator grid.
        rows, cols = int(mem.rows), int(mem.cols)
        c0 = int(round(float(mem.origin[0]) / float(mem.cell_m)))
        r0 = int(round(float(mem.origin[1]) / float(mem.cell_m)))
        rgba = _traffic_rgba(mem)
    else:
        # no traffic recorded yet -> a fully transparent drape over the work-area crop (not a blank 404).
        crop, (r0, c0), _cm = _work_area(mp, bundle_dir)
        rows, cols = int(crop.shape[0]), int(crop.shape[1])
        rgba = _np.zeros((rows, cols, 4), dtype=_np.float64)
    # the crop's tile-frame extent, using the SAME (W-1)/(H-1) linear map the full-tile drape (_reproject over
    # b) uses, so the traffic sub-window lands exactly on DEM rows [r0, r0+rows) cols [c0, c0+cols) -- the work
    # area -- aligned with the dem/slope/hazard globe drapes. Crop row 0 = north (max tile Y), like every drape.
    bx0, by0, bx1, by1 = b["x0"], b["y0"], b["x1"], b["y1"]
    sx0 = bx0 + c0 / (W - 1) * (bx1 - bx0)
    sx1 = bx0 + (c0 + cols - 1) / (W - 1) * (bx1 - bx0)
    sy1 = by1 - r0 / (H - 1) * (by1 - by0)
    sy0 = by1 - (r0 + rows - 1) / (H - 1) * (by1 - by0)
    # out_px modest: the source is a 128-cell crop, so a 512-px geographic grid is already oversampled and keeps
    # this UNCACHED path light while co-registering with the cached full-tile drapes.
    return _reproject(rgba, b, fwd, out_px=512, sub=(sx0, sy0, sx1, sy1), crs=tile_crs)


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
    {"key": "traffic", "name": "Traffic hardening (Dr, TW-11)", "kind": "raster", "group": "terrain"},   # traversal-compaction
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
    """(heightmap, cell_m, world_bounds dict, the pyproj fwd transformer, the tile CRS). ``bundle_dir``
    selects the chosen site's tile (REG-01); None = the Haworth default / $STEWIE_DEM_DIR. PLAN-ANYWHERE:
    the CRS is the tile's OWN frame -- IAU_2015:30135 for the curated sites, a local AEQD frame for an
    ad-hoc crop -- so the globe reproject georeferences an off-site tile through its own frame (~0 warp)."""
    import json as _json
    import os as _os

    from pyproj import Transformer
    from stewie.terrain.site_dem import bundle_crs
    pair = mp.load_haworth_dem(bundle_dir=bundle_dir)
    meta = _json.load(open(_os.path.join(mp._haworth_bundle(bundle_dir), "metadata.json")))
    crs = bundle_crs(bundle_dir)
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    return pair[0], float(pair[1]), meta["world_bounds_m"], fwd, crs


def _geographic_bbox_of_extent(x0, y0, x1, y1, crs=None):
    """Project an extent's boundary ring from the TILE frame to selenographic lat/lon, returning
    bbox{south,north,west,east}. ``crs`` is the tile's frame (default IAU_2015:30135 south-polar
    stereographic for the curated sites; a local AEQD frame for a PLAN-ANYWHERE ad-hoc tile). Ring (not
    just corners) because the projection bows the edges. Shared by the globe reproject and the OGC WMS
    capabilities extent (no raster needed). CAVEAT (off-pole assumption): a simple lon/lat min/max box.
    Valid for an OFF-POLE work-site tile (Haworth: west~-29 east~-22 south~-86.5 north~-86.1) and for a
    small local-frame ad-hoc tile. A tile that ENCLOSES the pole or crosses the +/-180 antimeridian would
    collapse lon to ~[-180,180] and need a split bbox -- the existing globe drape shares this assumption."""
    import numpy as _np
    from pyproj import CRS, Transformer
    if crs is None:
        crs = CRS.from_user_input("IAU_2015:30135")
    t = _np.linspace(0.0, 1.0, 64)
    ring_x = _np.concatenate([x0 + (x1 - x0) * t, _np.full(64, x1), x1 - (x1 - x0) * t, _np.full(64, x0)])
    ring_y = _np.concatenate([_np.full(64, y0), y0 + (y1 - y0) * t, _np.full(64, y1), y1 - (y1 - y0) * t])
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
    from stewie.terrain.site_dem import bundle_crs
    return _geographic_bbox_of_extent(b["x0"], b["y0"], b["x1"], b["y1"], bundle_crs(bundle_dir))


def _reproject(source_rgba, b, fwd, *, out_px: int = 1024, sub=None, crs=None):
    """Resample an RGBA raster (north-up in the tile frame, extent = b or the sub-window) onto a
    geographic grid. Returns (rgba_geo uint8, bbox{south,north,west,east}). ``crs`` = the tile's frame
    (fwd maps lon/lat -> that frame); default IAU_2015:30135 for the curated sites."""
    import numpy as _np
    if sub is not None:
        x0, y0, x1, y1 = sub
    else:
        x0, y0, x1, y1 = b["x0"], b["y0"], b["x1"], b["y1"]
    bbox = _geographic_bbox_of_extent(x0, y0, x1, y1, crs)   # the geographic extent (shared helper)
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


def grid_sun_az(sun_az_true_deg, grid_north_bearing_deg):
    """#266: express a TRUE selenographic sun azimuth (solar.py sun_az_el, 'azimuth from local north,
    eastward') in dart.illumination's DEM-GRID azimuth (CW from +row), so the horizon march points at
    the real sun.

    Two facts make this a REFLECTION, not a rotation: (1) the DEM is IAU_2015:30135 south-polar
    stereographic, so grid axes are rotated from true north by the meridian convergence (~|lon| at the
    pole); (2) load_haworth_dem keeps the north-up raster (row 0 = max stereo-Y), while
    dart.illumination ASSUMES origin-lower-left (+row = north) -- the row-flip makes the (row,col) grid
    LEFT-handed vs the true compass. Empirically (real Haworth tile) the +row direction (grid az=0) has
    true bearing B = grid_north_bearing_deg ~= 205.5 deg, and +col (grid az=90) has B-90 -- so a grid
    march at azimuth ``a`` points at true bearing ``B - a``. Inverting for the sun: a = B - sun_az_true.
    grid_north_bearing_deg is measured per tile (site_dem.grid_north_bearing_deg) so this generalises to
    any imported DEM/longitude. NOTE: feeding the true azimuth straight in (the pre-#266 bug) marched at
    ``B - sun_az_true`` instead of ``sun_az_true`` -- a reflection whose error is ~26 deg near az=90
    (what the cockpit council first saw) but up to ~180 deg at other sun positions."""
    return (float(grid_north_bearing_deg) - float(sun_az_true_deg)) % 360.0


# ---- LY-05 DEM-derivative analysis drapes: aspect, curvature, roughness -----------------------------
# aspect + curvature are computed from the SAME numpy.gradient the slope drape uses (one heightfield
# gradient); roughness reuses lode.costmap_layers._roughness (the window-RMS-slope definition) as the ONE
# source of truth (imported + called, never reimplemented). Colours: aspect = a cyclic hue wheel (azimuth
# is periodic, so 0deg and 360deg share a colour), curvature = a diverging blue<->red ramp about zero
# (near-planar transparent), roughness = a sequential pale->deep ramp. All three are sun-independent (pure
# DEM derivatives), so their globe/3D-drape cache keys carry the sun but the pixels never vary with it.
_CURV_DIVERGING = ((0.0, (33, 102, 172)),    # convex-up ridge/mound (Laplacian < 0) -- blue
                   (0.5, (247, 247, 247)),   # ~planar (Laplacian ~ 0)                -- white
                   (1.0, (178, 24, 43)))     # concave-up hollow/valley (Laplacian > 0) -- red
_ROUGH_SEQUENTIAL = ((0.0, (255, 255, 217)),  # smooth   -- pale
                     (0.5, (65, 182, 196)),   # moderate
                     (1.0, (34, 39, 110)))    # rough    -- deep


def _hsv_to_rgb(h, s, v):
    """Vectorised HSV->RGB (all inputs broadcast in [0,1]); returns (...,3) float in [0,1]. Used for the
    cyclic aspect hue wheel so the azimuth wraps continuously (0deg and 360deg share a colour)."""
    import numpy as np
    h = np.asarray(h, dtype=float) % 1.0
    s = np.clip(np.asarray(s, dtype=float), 0.0, 1.0)
    v = np.clip(np.asarray(v, dtype=float), 0.0, 1.0)
    h6 = h * 6.0
    i = np.floor(h6).astype(int) % 6
    f = h6 - np.floor(h6)
    p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
    cond = [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5]
    r = np.select(cond, [v, q, p, p, t, v])
    g = np.select(cond, [t, v, v, q, p, p])
    b = np.select(cond, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


def aspect_deg(dem, cell):
    """[REQ:LY-05] the gradient AZIMUTH field [deg, 0..360) -- the compass direction the surface faces
    DOWNHILL (steepest descent), from the SAME numpy.gradient the slope drape uses. 0deg = grid-north
    (north-up raster, row 0 = north), 90deg = east (+col), measured clockwise. This is the raw value the
    aspect drape colours (exposed so a test can assert it against the real DEM)."""
    import numpy as np
    dem = np.asarray(dem, dtype=float)
    gy, gx = np.gradient(dem, cell)                      # gy = dz/drow, gx = dz/dcol (== the slope drape)
    # downslope (steepest-descent) direction = -(gx, gy); express as a compass azimuth CW from grid-north.
    # north-up raster: going north = decreasing row, so the downslope NORTH component is +gy, and the EAST
    # (+col) component is -gx. azimuth CW from north = atan2(east, north) = atan2(-gx, gy).
    return np.degrees(np.arctan2(-gx, gy)) % 360.0


def curvature_laplacian(dem, cell):
    """[REQ:LY-05] the Laplacian curvature field grad^2 z = d2z/dx2 + d2z/dy2 [1/m], from the SAME
    numpy.gradient the slope drape uses (differentiated a second time). Sign: convex-up ridges/mounds are
    NEGATIVE, concave-up hollows/valleys POSITIVE. The raw value the curvature drape colours (exposed so a
    test can assert it against the real DEM)."""
    import numpy as np
    dem = np.asarray(dem, dtype=float)
    gy, gx = np.gradient(dem, cell)
    gyy, _ = np.gradient(gy, cell)                       # d2z/dy2
    _, gxx = np.gradient(gx, cell)                       # d2z/dx2
    return gxx + gyy


def _aspect_rgba(dem, cell):
    """LY-05 aspect drape: colour the gradient-azimuth field (aspect_deg) on a cyclic hue wheel so the
    0/360 wrap is seamless; near-flat cells fade out (aspect is undefined where the gradient vanishes)."""
    import numpy as np
    dem = np.asarray(dem, dtype=float)
    gy, gx = np.gradient(dem, cell)                      # for the flat-cell fade (same gradient as aspect_deg)
    aspect = aspect_deg(dem, cell)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))
    a = np.clip(slope_deg / 5.0, 0.0, 1.0)               # fade near-flat; opaque by ~5deg slope
    rgb = _hsv_to_rgb(aspect / 360.0, np.full(aspect.shape, 0.85), np.full(aspect.shape, 0.95))
    rgba = np.zeros((*aspect.shape, 4))
    rgba[..., :3] = rgb * 255.0
    rgba[..., 3] = 35.0 + 185.0 * a
    return rgba.astype("uint8")


def _curvature_rgba(dem, cell):
    """LY-05 curvature drape: colour the Laplacian-curvature field (curvature_laplacian) on a diverging
    ramp about zero -- convex-up ridges (negative) blue, concave-up hollows (positive) red; near-planar
    ground transparent. Robustly scaled by the 98th percentile of |Laplacian|."""
    import numpy as np
    lap = curvature_laplacian(dem, cell)
    finite = np.isfinite(lap)
    vals = np.abs(lap[finite])
    scale = float(np.percentile(vals, 98.0)) if vals.size else 1.0
    if scale <= 0.0:
        scale = 1e-9
    t = np.clip(lap / scale, -1.0, 1.0)                  # -1..1 diverging
    rgba = np.zeros((*lap.shape, 4))
    rgba[..., :3] = _ramp_rgb((t + 1.0) / 2.0, _CURV_DIVERGING)
    rgba[..., 3] = 45.0 + 180.0 * np.abs(t)              # transparent near planar, opaque at the extremes
    return rgba.astype("uint8")


def _roughness_rgba(dem, cell):
    """LY-05 roughness drape: the window-RMS-slope roughness, reusing lode.costmap_layers._roughness (the
    3x3-window std of the slope field) as the ONE source of truth -- imported + called, NOT reimplemented,
    so this drape and the FORGE costmap roughness layer can never drift. Sequential pale->deep ramp,
    robustly stretched between the 2nd/98th percentiles."""
    import numpy as np

    from lode.costmap_layers import CostmapContext
    from lode.costmap_layers import _roughness as _lode_roughness
    ctx = CostmapContext(Z=np.asarray(dem, dtype=float), cell_m=float(cell))
    rough, _mask, _name = _lode_roughness(ctx)           # the SAME window-RMS-slope roughness the costmap uses
    r = np.asarray(rough, dtype=float)
    finite = np.isfinite(r)
    vals = r[finite]
    lo = float(np.percentile(vals, 2.0)) if vals.size else 0.0
    hi = float(np.percentile(vals, 98.0)) if vals.size else 1.0
    if hi <= lo:
        hi = lo + 1e-9
    t = np.clip((np.where(finite, r, lo) - lo) / (hi - lo), 0.0, 1.0)
    rgba = np.zeros((*r.shape, 4))
    rgba[..., :3] = _ramp_rgb(t, _ROUGH_SEQUENTIAL)
    rgba[..., 3] = 70.0 + 150.0 * t
    return rgba.astype("uint8")


def _layer_rgba(dem, cell, kind, sun_az=315.0, sun_el=45.0, *, slope_vmax=30.0, slope_classes=0,
                grid_north_bearing=None):
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
        # G5 (#251): graduated renderer. slope_vmax = the ramp's classification domain (operator-tunable,
        # default 30 deg); slope_classes>=2 = a classified (equal-interval N-band) renderer vs the stretch.
        vmax = max(1.0, float(slope_vmax))
        t = np.clip(slope / vmax, 0, 1)
        n = int(slope_classes)
        if n >= 2:
            t = np.clip(np.floor(t * n), 0, n - 1) / (n - 1)
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
        saz = grid_sun_az(sun_az, grid_north_bearing) if grid_north_bearing is not None else float(sun_az)  # #266 true->grid
        lit = horizon_clip(dem, cell, saz, float(sun_el))
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
        saz = grid_sun_az(sun_az, grid_north_bearing) if grid_north_bearing is not None else float(sun_az)  # #266 true->grid
        inc = incidence_angle_deg(dem, cell, saz, float(sun_el))
        t = np.clip(np.nan_to_num(inc, nan=90.0) / 90.0, 0, 1)
        rgba = np.zeros((*inc.shape, 4))
        rgba[..., 0] = 255; rgba[..., 1] = 200 * (1 - t); rgba[..., 2] = 40
        rgba[..., 3] = 40 + 170 * t
        return rgba.astype("uint8")
    if kind == "aspect":                                  # LY-05: gradient azimuth (cyclic)
        return _aspect_rgba(dem, cell)
    if kind == "curvature":                               # LY-05: Laplacian curvature (diverging)
        return _curvature_rgba(dem, cell)
    if kind == "roughness":                               # LY-05: window-RMS-slope roughness (lode source of truth)
        return _roughness_rgba(dem, cell)
    return None


# ---- the costmap ANALYSIS drape (AS-11): make the planner's real cost surface + veto reasons VISIBLE ----
# Two globe kinds computed from the REAL 12-layer FORGE costmap (lode.costmap_layers.compose) on the
# site's real DEM.  cost = a green(low)->red(high) heatmap of the PLAN-INDEPENDENT traversability cost
# (the summed slope/roughness/sinkage/slip/illumination/shadow-confidence/energy the planner routes on,
# MINUS the goal-specific distance-to-goal); blocking = the categorical veto grid (transparent where
# passable, one hue per reason a cell is impassable).  Single source of truth for the colours so the
# /layers/legend endpoint and the renderer never drift.
COST_RAMP = (
    (0.0, (33, 145, 80)),      # low cost  -- green (easy going)
    (0.5, (241, 196, 15)),     # mid cost  -- amber
    (1.0, (192, 40, 40)),      # high cost -- red (costly to cross)
)
BLOCKING_COLORS = {
    # veto-capable layers (a cell can be impassable for these) -- each a distinct hue
    "slope": (214, 40, 40),               # too steep to traverse (slope cap)
    "sinkage": (0, 158, 158),             # Bekker wheel burial past the depth cap
    "tip_risk": (190, 30, 160),           # static-stability tip-over limit
    "negative_obstacle": (150, 82, 24),   # drop-off / crater-rim / pit edge
    "psr": (124, 74, 214),                # shadowed this epoch (cold-trap candidate, no solar)
    "keepout": (110, 110, 110),           # operator no-go
    "reservation": (30, 128, 224),        # held by another vehicle
    # cost-only layers (never veto) -- carried so ANY reason has a colour, kept muted
    "roughness": (150, 150, 60),
    "slip": (150, 96, 60),
    "illumination": (60, 128, 150),
    "shadow_confidence": (86, 86, 128),
    "energy": (176, 116, 44),
}
# the veto-capable reasons, in compose's reason-priority order (the legend enumerates these)
BLOCKING_LEGEND_ORDER = ("slope", "sinkage", "tip_risk", "negative_obstacle", "psr", "keepout", "reservation")


def blocking_legend():
    """The categorical blocking-reason legend: each veto reason -> its hex colour (matches _blocking_rgba)."""
    return [{"reason": n, "hex": "#%02x%02x%02x" % BLOCKING_COLORS[n]} for n in BLOCKING_LEGEND_ORDER]


def _costmap_compose(dem, cell, sun_az, sun_el, *, grid_north_bearing=None, max_slope_deg=25.0):
    """Compose the REAL 12-layer FORGE costmap (`lode.costmap_layers`) on a DEM patch at THIS cell size,
    returning the CompositeCostmap (plan-independent cost + passable mask + per-cell blocking reason).
    The negative-obstacle drop cap is SCALED to the cell (a drop steeper than the traversable slope cap
    over one cell) so a coarse globe tile is not blanket-blocked by the rover-scale 0.15 m step. The sun
    layers (illumination/psr/shadow) read the DEM-grid azimuth (grid_sun_az), like the other sun drapes."""
    import math

    import numpy as np

    from lode import costmap_layers as CL
    saz = grid_sun_az(sun_az, grid_north_bearing) if grid_north_bearing is not None else float(sun_az)
    max_drop = float(cell) * math.tan(math.radians(float(max_slope_deg)))
    ctx = CL.CostmapContext(Z=np.asarray(dem, dtype=float), cell_m=float(cell),
                            max_slope_deg=float(max_slope_deg), max_drop_m=max_drop,
                            sun_az_deg=saz, sun_el_deg=float(sun_el))
    return CL.compose(ctx)


def _ramp_rgb(t, stops):
    """Piecewise-linear RGB along an ordered (t, (r,g,b)) ramp; t in [0,1]. Returns (...,3) float."""
    import numpy as np
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    ts = [s[0] for s in stops]
    chans = [np.interp(t, ts, [s[1][k] for s in stops]) for k in range(3)]
    return np.stack(chans, axis=-1)


def _cost_heatmap_rgba(cost):
    """Green(low) -> red(high) heatmap of the plan-independent traversability cost. Robustly stretched
    between the 2nd/98th percentiles so outliers don't wash out the ramp; alpha rises with cost."""
    import numpy as np
    c = np.asarray(cost, dtype=float)
    finite = np.isfinite(c)
    vals = c[finite]
    lo = float(np.percentile(vals, 2.0)) if vals.size else 0.0
    hi = float(np.percentile(vals, 98.0)) if vals.size else 1.0
    if hi <= lo:
        hi = lo + 1e-6
    t = np.clip((np.where(finite, c, lo) - lo) / (hi - lo), 0.0, 1.0)
    rgba = np.zeros((*c.shape, 4), dtype=float)
    rgba[..., :3] = _ramp_rgb(t, COST_RAMP)
    rgba[..., 3] = 110.0 + 120.0 * t
    return rgba.astype("uint8")


def _blocking_rgba(reason, passable):
    """Categorical veto overlay: transparent where passable, one distinct hue per blocking reason (which
    costmap layer FIRST vetoes the cell). Opaque EXACTLY on the impassable cells (AS-11 visibility)."""
    import numpy as np
    r = np.asarray(reason, dtype=object)
    pas = np.asarray(passable, dtype=bool)
    blocked = ~pas
    rgba = np.zeros((*r.shape, 4), dtype=float)
    for name, col in BLOCKING_COLORS.items():
        m = blocked & (r == name)
        if m.any():
            rgba[m, 0], rgba[m, 1], rgba[m, 2], rgba[m, 3] = col[0], col[1], col[2], 205.0
    return rgba.astype("uint8")


def _costmap_rgba(dem, cell, kind, sun_az, sun_el, *, grid_north_bearing=None):
    """RGBA for the costmap analysis drape: 'cost' = the traversability-cost heatmap, 'blocking' = the
    categorical veto grid. Both from ONE real compose on the DEM patch. None for any other kind."""
    cm = _costmap_compose(dem, cell, sun_az, sun_el, grid_north_bearing=grid_north_bearing)
    if kind == "cost":
        return _cost_heatmap_rgba(cm.cost)
    if kind == "blocking":
        return _blocking_rgba(cm.reason, cm.passable)
    return None


# ---- the PHYSICS (TM) analysis drape (T12): the terramechanics-spine per-cell fields draped -----------
# The "Physics (TM)" catalog group's rows (physics.bearing/sinkage/slip_risk/traction_margin/energy_cost/
# excavation_resistance) are each COMPUTED FROM the REAL terramechanics spine: stewie.specs.terramechanics_
# spine binds every row to a live solver callable in stewie.physics.sinkage / stewie.physics.slip (the same
# conserved tier2_numpy solver the drive loop uses). Every field is a pure function of the per-cell DEM slope
# (the IPEx mass / lunar g / soil moduli / contact patch are fixed constants), so it is evaluated EXACTLY via
# a fine slope LUT (a few hundred scalar spine solves) then interpolated onto the DEM's slope map -- no
# re-implementation of the physics, no synthetic data. Sequential ColorBrewer ramps; ONE colour source per
# kind (PHYSICS_LAYERS), shared by _physics_rgba (renderer) and the /layers/legend endpoint (physics_legend).
#
# HONEST 6/7: physics.compaction is deliberately NOT here. Its catalog source_class is `observed/derived`
# (the compaction/sinter/support STATE where the rover has actually driven/worked -- the TrafficMemory Dr
# family, same as traffic.compaction), so it has no plan-independent per-cell value on the bare DEM. It is
# reported as catalog-only rather than fabricated (task/no-synthetic rule).
_PHYS_BLUES = ((0.0, (222, 235, 247)), (0.5, (66, 146, 198)), (1.0, (8, 48, 107)))       # bearing (load)
_PHYS_BROWNS = ((0.0, (243, 232, 210)), (0.5, (191, 138, 80)), (1.0, (94, 55, 18)))      # sinkage (burial)
_PHYS_GYR = ((0.0, (33, 145, 80)), (0.5, (241, 196, 15)), (1.0, (192, 40, 40)))          # slip / traction
_PHYS_PURPLES = ((0.0, (239, 237, 245)), (0.5, (158, 154, 200)), (1.0, (84, 39, 143)))   # excavation R_c
_PHYS_YLORRD = ((0.0, (255, 237, 160)), (0.5, (253, 141, 60)), (1.0, (153, 0, 13)))      # drive energy

# ONE source of truth per physics kind: the spine field it renders, its unit, the sequential ramp (low ->
# high end), whether the "risky/constrained" end is the LOW field value (invert), a short ramp label, and the
# legend text. `invert` orients the ramp+opacity so the HIGH (redder/more-opaque) end is always the risky one.
PHYSICS_LAYERS = {
    "bearing": {
        "field": "contact_pressure", "unit": "Pa", "ramp_stops": _PHYS_BLUES, "invert": False,
        "ramp": "pale (low) -> deep blue (high pressure)",
        "text": "ground contact pressure p = wheel normal load / contact patch -- the Bekker bearing driver "
                "(stewie.physics.sinkage.contact_pressure); highest on flat ground, easing where the normal "
                "load tilts off-normal on a grade."},
    "sinkage": {
        "field": "sinkage", "unit": "m", "ramp_stops": _PHYS_BROWNS, "invert": False,
        "ramp": "pale (firm) -> dark brown (deep burial)",
        "text": "slip-coupled wheel sinkage z the rover would settle to per cell (Bekker static solve "
                "stewie.physics.sinkage.bekker_sinkage deepened by the slip.slip_sinkage equilibrium); "
                "grows on steep/loose ground toward burial."},
    "slip_risk": {
        "field": "slip_risk", "unit": "slip ratio", "ramp_stops": _PHYS_GYR, "invert": False,
        "ramp": "green (grip) -> amber -> red (entrapment)",
        "text": "wheel slip ratio for the demanded thrust (stewie.physics.slip.slip_for_demand at the "
                "per-cell slip-sinkage equilibrium); red = the traction budget is exceeded and the wheel "
                "digs in (Spirit-mode entrapment)."},
    "traction_margin": {
        "field": "traction_margin", "unit": "fraction", "ramp_stops": _PHYS_GYR, "invert": True,
        "ramp": "green (ample) -> amber -> red (no margin)",
        "text": "traction headroom (H_max - demand) / H_max from the Coulomb-Mohr budget "
                "(stewie.physics.slip.traction_budget) vs the along-slope demand; red = little margin left "
                "before slip runaway."},
    "energy_cost": {
        "field": "energy_cost", "unit": "W", "ramp_stops": _PHYS_YLORRD, "invert": False,
        "ramp": "pale yellow (cheap) -> deep red (costly)",
        "text": "steady drive power on the grade from the Bekker motion resistance "
                "(stewie.physics.slip.bekker_drive_power_w); rises steeply with slope and diverges at "
                "entrapment (energy per traverse)."},
    "excavation_resistance": {
        "field": "excavation_resistance", "unit": "N", "ramp_stops": _PHYS_PURPLES, "invert": False,
        "ramp": "pale (easy) -> deep purple (resistant)",
        "text": "Bekker compaction (motion) resistance R_c the wheel must climb out of its own sinkage rut "
                "(stewie.physics.slip.compaction_resistance); the excavation/rolling resistance, rising with "
                "sinkage on steeper ground."},
}
_PHYSICS_KINDS = frozenset(PHYSICS_LAYERS)


def physics_legend() -> dict:
    """The PHYSICS (TM) legend: each servable physics kind -> its unit + colour ramp + text, built from the
    SAME PHYSICS_LAYERS spec the renderer colours with (one source of truth, like blocking_legend())."""
    return {k: {"unit": v["unit"], "ramp": v["ramp"], "text": v["text"]} for k, v in PHYSICS_LAYERS.items()}


# ---- [REQ:GW-07] the SELECTION-INSPECTOR per-cell point query -------------------------------------
# One clicked map location -> the servable layers' ACTUAL values at that DEM cell, computed by the SAME
# functions the drapes render with (slope_deg_map, _terra_fields, _costmap_compose) so the inspector value
# IS the drape value at that cell. Every layer carries its catalog id + unit; a layer with no plan-
# independent per-cell scalar (sun-parameterized / reference grid / observed-only) is reported available=
# False with an honest reason, never a fabricated number. Runtime evidence (as-built / observed) comes from
# the composed CurrentTerrainView's per-cell provenance.
_POINT_SUN_EL = 6.0     # the globe cost drape's default sun (deg elevation); cost is plan-independent so a
_POINT_SUN_AZ = 90.0    # fixed default is honest for a point cost. Reported in the payload so it is legible.

# each servable catalog row -> how the inspector fills its per-cell attribute. `scalar` rows have a real
# per-cell value; `none` rows are honestly not point-queryable here (with a reason). label/unit are shown.
_POINT_NODATA = {
    "terrain.illumination": "sun-parameterized (horizon shadowing) -- set the sun to query per cell",
    "terrain.incidence": "sun-parameterized (solar incidence angle) -- set the sun to query per cell",
    "terrain.psr": "permanently-shadowed sweep -- an area classification, not a per-cell scalar here",
    "base.grid": "reference grid overlay -- no measured cell value",
    "traffic.compaction": "observed traversal compaction -- only where the rover has driven",
}


def _point_setup(site: str) -> dict:
    """#59: the per-SITE invariant part of point_values -- resolve the DEM + compose the CurrentTerrainView
    ONCE. points_values() shares one ctx across a whole batch of cells (a cross-section) instead of redoing the
    DEM resolve + the 2000x2000 terrain-view compose per point. Raises KeyError/FileNotFoundError for an
    unknown/absent site (the route -> 404), exactly as the inline resolve did."""
    from stewie.server import state
    dem, origin = state.moon_dem(site)
    if dem is None:
        raise FileNotFoundError(f"no DEM bundle for site {site!r}")
    Z, cell = dem
    return {"Z": np.asarray(Z), "cell": cell, "origin": origin,   # Z native; the 97x97 patch is upcast per-cell
            "view": state.current_terrain_view(site, dem, origin)}


def latlon_to_order(site: str, lon: float, lat: float, *, _ctx: dict | None = None) -> tuple[float, float]:
    """[council #55, HIGH correctness] Convert a selenographic lon/lat (deg) to the ORDER frame (anchor-relative
    m) that point_values + transect_profile expect. MP.latlon_to_dem_origin returns ABSOLUTE DEM-pixel-metres
    (from pixel (0,0) -- the flattest_anchor frame), but point_values resolves a cell as round((origin+xy)/cell)
    where origin is the site's NONZERO flattest anchor; feeding the absolute value straight in double-counts the
    anchor, so an interior click lands ~origin/cell cells off (usually out of bounds). Subtracting the origin
    here maps a lat/lon to its TRUE cell. Raises ValueError (out-of-tile) / ImportError (no pyproj) /
    KeyError|FileNotFoundError (unknown or unimported site)."""
    from lode import mission_planner as MP
    ctx = _ctx if _ctx is not None else _point_setup(site)
    ox, oy = float(ctx["origin"][0]), float(ctx["origin"][1])
    ax, ay = MP.latlon_to_dem_origin(float(lat), float(lon), bundle_dir=MP.bundle_for_site(site))
    return ax - ox, ay - oy


def point_values(site: str, x_m: float, y_m: float, *, _ctx: dict | None = None) -> dict:
    """[REQ:GW-07] Resolve an order-frame (x, y) [m] on ``site`` to its DEM cell and return the servable
    layers' per-cell values + the cell's runtime evidence. Reuses the drape field functions so the reading
    matches the map. Raises KeyError/FileNotFoundError for an unknown/unimported site (the route -> 404).
    An out-of-tile click returns cell.in_bounds=False and every attribute available=False (honest no-data).
    """
    from stewie.terrain.site_dem import slope_deg_map

    ctx = _ctx if _ctx is not None else _point_setup(site)   # #59: shared once-per-batch by points_values()
    Z, cell, origin, view = ctx["Z"], ctx["cell"], ctx["origin"], ctx["view"]
    import math
    ox, oy = float(origin[0]), float(origin[1])   # Z stays native; only the 97x97 patch is upcast to float64 below
    height, width = Z.shape
    xf, yf = float(x_m), float(y_m)
    finite = math.isfinite(xf) and math.isfinite(yf)
    if not finite:                                       # council #55 pass2 [2]: pydantic accepts inf/nan; the raw
        col, row, in_bounds = -1, -1, False              # int(round) OverflowErrors AND an inf echoed in position
    else:                                                # breaks FastAPI's JSON -> HTTP 500. Honest out-of-tile.
        col = int(round((ox + xf) / cell))
        row = int(round((oy + yf) / cell))
        in_bounds = (0 <= row < height) and (0 <= col < width)
    px, py = (round(xf, 2), round(yf, 2)) if finite else (None, None)

    # every servable row's presentation shell (catalog id -> label/unit). The scalar rows get filled below.
    def _attr(lid, label, unit, value=None, available=False, note=None, reason=None):
        a = {"id": lid, "label": label, "unit": unit, "value": value, "available": bool(available)}
        if note is not None:
            a["note"] = note
        if reason is not None or lid == "traffic.traversability":
            a["reason"] = reason
        return a

    order = [
        ("base.dem", "Elevation", "m"), ("terrain.slope", "Slope", "deg"),
        ("hazard.slope_nogo", "Slope no-go", ""),
        ("physics.bearing", "Bearing (contact pressure)", "Pa"),
        ("physics.sinkage", "Sinkage", "m"), ("physics.slip_risk", "Slip risk", "slip ratio"),
        ("physics.traction_margin", "Traction margin", "fraction"),
        ("physics.energy_cost", "Drive power", "W"),
        ("physics.excavation_resistance", "Excavation resistance", "N"),
        ("traffic.cost_global", "Traversal cost", ""),
        ("traffic.traversability", "Passable", ""),
        ("terrain.illumination", "Illumination", ""), ("terrain.incidence", "Incidence", "deg"),
        ("terrain.psr", "PSR", ""), ("base.grid", "Reference grid", ""),
        ("traffic.compaction", "Traversal compaction", "Dr"),
    ]
    meta: dict = {
        "ok": True, "site": site,
        "cell": {"row": row, "col": col, "cell_m": float(cell), "in_bounds": in_bounds,
                 "grid_rows": int(height), "grid_cols": int(width)},
        "position": {"x_m": px, "y_m": py,   # council #55 pass2 [2]: px/py are None for a non-finite input (no inf in JSON)
                     "dem_origin_m": [round(ox, 2), round(oy, 2)]},
        "sun": {"el_deg": _POINT_SUN_EL, "az_deg": _POINT_SUN_AZ},
    }
    attributes: list[dict] = []

    if not in_bounds:
        # honest no-data everywhere: never invent a reading off the tile.
        for lid, lab, unit in order:
            attributes.append(_attr(lid, lab, unit, note="outside the site tile -- no data at this location"))
        return {**meta, "attributes": attributes,
                "runtime_evidence": {"cell_source": "out_of_bounds", "as_built_delta_m": 0.0,
                                     "as_built_version": 0, "twin_version": 0, "observed_fraction": 0.0,
                                     "observed_at_cell": False},
                "actions": _point_actions(in_bounds=False, passable=False)}

    # a local window around the cell -> the drape field functions (exact at the centre, fast on a patch).
    half = 48
    r0, r1 = max(0, row - half), min(height, row + half + 1)
    c0, c1 = max(0, col - half), min(width, col + half + 1)
    patch = np.asarray(Z[r0:r1, c0:c1], dtype=float)   # #59: upcast only the 97x97 window (exact from float32)
    lr, lc = row - r0, col - c0

    elevation = float(Z[row, col])
    slope = float(np.asarray(slope_deg_map(patch, cell))[lr, lc])
    fields = _terra_fields(patch, cell)                                   # the six terramechanics-spine fields
    cm = _costmap_compose(patch, cell, _POINT_SUN_AZ, _POINT_SUN_EL)      # plan-independent cost + veto
    cost = float(cm.cost[lr, lc])
    passable = bool(cm.passable[lr, lc])
    reason = str(cm.reason[lr, lc]) or None

    scalars = {
        "base.dem": elevation, "terrain.slope": slope,
        "physics.bearing": float(fields["bearing"][lr, lc]),
        "physics.sinkage": float(fields["sinkage"][lr, lc]),
        "physics.slip_risk": float(fields["slip_risk"][lr, lc]),
        "physics.traction_margin": float(fields["traction_margin"][lr, lc]),
        "physics.energy_cost": float(fields["energy_cost"][lr, lc]),
        "physics.excavation_resistance": float(fields["excavation_resistance"][lr, lc]),
        "traffic.cost_global": cost,
    }
    for lid, lab, unit in order:
        if lid in scalars:
            attributes.append(_attr(lid, lab, unit, value=round(scalars[lid], 4), available=True))
        elif lid == "hazard.slope_nogo":
            attributes.append(_attr(lid, lab, unit, value=bool(slope > 20.0), available=True,
                                    note="slope > 20 deg tested-envelope no-go [WHEELTEST]"))
        elif lid == "traffic.traversability":
            attributes.append(_attr(lid, lab, unit, value=passable, available=True, reason=reason))
        else:
            attributes.append(_attr(lid, lab, unit, note=_POINT_NODATA.get(lid, "no per-cell value")))

    # runtime evidence: the composed CurrentTerrainView's per-cell provenance (as-built / observed) at the cell.
    # 'view' is the CurrentTerrainView composed once in _point_setup (shared across a points_values batch)
    if view is not None:
        src = int(np.asarray(view.source)[row, col])
        src_label = {0: "pristine", 1: "as_built", 2: "observed"}.get(src, "pristine")
        delta = float(np.asarray(view.heights)[row, col] - elevation)
        runtime = {"cell_source": src_label, "as_built_delta_m": round(delta, 4),
                   "as_built_version": int(view.as_built_version), "twin_version": int(view.twin_version),
                   "observed_fraction": float(view.observed_fraction), "observed_at_cell": src == 2}
    else:
        runtime = {"cell_source": "pristine", "as_built_delta_m": 0.0, "as_built_version": 0,
                   "twin_version": 0, "observed_fraction": 0.0, "observed_at_cell": False}

    return {**meta, "attributes": attributes, "runtime_evidence": runtime,
            "actions": _point_actions(in_bounds=True, passable=passable)}


def points_values(site: str, coords) -> list:
    """[REQ:GW-07] Batch of point_values on ONE site (the #45 cross-section transect): resolve the DEM +
    compose the CurrentTerrainView ONCE (_point_setup), then read each (x, y) [order-frame metres]. Each
    element is byte-identical to a standalone point_values(site, x, y) call -- only the per-site setup is
    shared, the per-cell terramechanics LUT stays per-patch (guarded by test_points_batch)."""
    ctx = _point_setup(site)
    return [point_values(site, float(x), float(y), _ctx=ctx) for (x, y) in coords]


# ---- SS-01: site-survey suitability ---------------------------------------------------------------
# The veto reasons compose can attribute a blocked cell to, in compose's first-blocking priority order
# (mirrors BLOCKING_LEGEND_ORDER). Kept here so the aggregate never invents a reason the costmap can't emit.
_SUITABILITY_REASONS = ("slope", "sinkage", "tip_risk", "negative_obstacle", "psr", "keepout", "reservation")


def _suitability_grade(score: int) -> str:
    """A STATED rating band on the (real, weight-free) suitable-fraction score -- a decision-support label,
    like the SD-01 constructability verdict's status string, NOT a physical measurement. Documented so the
    band boundaries are legible and no hidden weighting hides behind a single number."""
    if score >= 90:
        return "excellent"
    if score >= 75:
        return "good"
    if score >= 50:
        return "marginal"
    if score >= 25:
        return "poor"
    return "unsuitable"


def site_suitability(site: str) -> dict:
    """SS-01 Site-survey suitability for landing/construction: AGGREGATE the REAL 12-layer FORGE costmap
    (`lode.costmap_layers.compose`, the SAME passability the planner routes on + the GW-07 point inspector
    reads) over the site's framed work-area crop into a suitability SCORE, its binding constraint (the
    dominant first-blocking veto reason), and the descriptive terrain sub-fields (slope / roughness / bearing
    / traction / sinkage). The score is literally the fraction of the real work-area cells that pass the real
    physics gates -- there is NO invented weighting; the only stated policy is the human-readable grade band
    (_suitability_grade). Every field is composed from the real site DEM via the SAME producers the map drapes
    use (_costmap_compose / _terra_fields / slope_deg_map / costmap_layers._roughness), so nothing here
    fabricates a reading. Raises KeyError/FileNotFoundError for an unknown/unimported site (route -> 404)."""
    import math

    from lode import mission_planner as mp
    from lode.costmap_layers import CostmapContext
    from lode.costmap_layers import _roughness as _lode_roughness
    from stewie.terrain.site_dem import slope_deg_map
    bundle_dir = mp.bundle_for_site(site)                         # raises KeyError/FileNotFoundError -> route 404
    dem, (r0, c0), cell_m = _work_area(mp, bundle_dir)            # the 128x128 @ cell_m planner-framed work-area crop
    demf = np.asarray(dem, dtype=float)

    # #266: re-express the fixed cost-drape sun azimuth in the DEM grid frame (as the illumination/psr drapes
    # do), so the psr veto matches the map. Best-effort: pyproj absent / off-tile -> uncorrected (None).
    gnb = None
    try:
        from stewie.terrain.site_dem import grid_north_bearing_deg
        cx = (c0 + demf.shape[1] / 2.0) * cell_m
        cy = (r0 + demf.shape[0] / 2.0) * cell_m
        gnb = grid_north_bearing_deg(cx, cy, bundle_dir=bundle_dir)
    except (ImportError, ValueError):
        gnb = None

    # The ONE real compose (plan-independent cost + passable mask + first-blocking reason per cell), at the
    # SAME fixed cost-drape sun the point inspector uses (reported so the reading is legible, not hidden).
    cm = _costmap_compose(demf, cell_m, _POINT_SUN_AZ, _POINT_SUN_EL, grid_north_bearing=gnb)
    passable = np.asarray(cm.passable, dtype=bool)
    reason = np.asarray(cm.reason, dtype=object)
    n = int(passable.size)
    n_suitable = int(passable.sum())
    suitable_fraction = (n_suitable / n) if n else 0.0
    score = round(100.0 * suitable_fraction)

    # first-blocking reason histogram over the BLOCKED cells (mutually exclusive -> counts + suitable sum to n).
    blocked = ~passable
    counts: list[tuple[str, int]] = []
    for name in _SUITABILITY_REASONS:
        cnt = int((blocked & (reason == name)).sum())
        if cnt:
            counts.append((name, cnt))
    counts.sort(key=lambda kv: -kv[1])                            # descending -> head is the binding constraint
    blocking = [{"reason": nm, "count": c, "fraction": round(c / n, 6)} for nm, c in counts]
    binding_constraint = counts[0][0] if counts else None

    # descriptive sub-fields (real readings off the crop; each from the SAME producer a drape/inspector uses).
    slope = np.asarray(slope_deg_map(demf, cell_m), dtype=float)
    rough, _rm, _rn = _lode_roughness(CostmapContext(Z=demf, cell_m=float(cell_m)))   # LY-05 single source of truth
    rough = np.asarray(rough, dtype=float)
    terra = _terra_fields(demf, cell_m)                          # the terramechanics spine (bearing/sinkage/margin)

    def _f(v) -> float:
        return round(float(v), 4)

    fields = {
        "slope_deg": {"mean": _f(np.nanmean(slope)), "p95": _f(np.nanpercentile(slope, 95.0)),
                      "max": _f(np.nanmax(slope))},
        "roughness": {"mean": _f(np.nanmean(rough)), "p95": _f(np.nanpercentile(rough, 95.0))},
        "bearing_pa": {"mean": _f(np.nanmean(terra["bearing"]))},                 # contact pressure (Pa)
        "traction_margin": {"mean": _f(np.nanmean(terra["traction_margin"])),
                            "min": _f(np.nanmin(terra["traction_margin"]))},
        "sinkage_m": {"mean": _f(np.nanmean(terra["sinkage"])), "max": _f(np.nanmax(terra["sinkage"]))},
    }
    return {
        "ok": True, "site": site,
        "score": int(score), "grade": _suitability_grade(int(score)),
        "suitable_fraction": round(suitable_fraction, 6),
        "n_cells": n, "n_suitable": n_suitable,
        "binding_constraint": binding_constraint,
        "blocking": blocking,
        "fields": fields,
        "thresholds": {"max_slope_deg": 25.0, "max_sinkage_m": 0.10,
                       "max_drop_m": round(float(cell_m) * math.tan(math.radians(25.0)), 4)},
        "grid": {"rows": int(demf.shape[0]), "cols": int(demf.shape[1]), "cell_m": float(cell_m)},
        "sun": {"el_deg": _POINT_SUN_EL, "az_deg": _POINT_SUN_AZ},
        "provenance": ("FORGE costmap compose (lode.costmap_layers) + terramechanics spine (_terra_fields) "
                       "+ LY-05 roughness over the real site work-area crop; score = passable fraction, no "
                       "invented weighting; grade band is a stated decision-support label"),
    }


_PSR_MASK_CACHE: dict = {}   # site -> never-lit bool mask; the horizon sweep is DEM-fixed, so cache per site


def _site_psr_mask(site, ctx):
    """[REQ:SD-03] REAL per-cell PSR (permanently-shadowed) mask for a site: cells never illuminated across a
    0..360 deg sun-azimuth sweep at 3 deg polar elevation (dart.illumination.horizon_clip on the site DEM) --
    the same physics the `psr` raster layer draws. The DEM is strided to ~384 px before the sweep (as the psr
    RASTER layer does) so the 12-azimuth horizon march is fast; PSR is a large-scale cold-trap classification,
    so a coarse mask is faithful. Returns (step, never_lit_mask); cache-safe (horizon geometry is DEM-fixed)."""
    cached = _PSR_MASK_CACHE.get(site)
    if cached is not None:
        return cached
    import numpy as np

    from dart.illumination import horizon_clip
    dem_full = np.asarray(ctx["Z"], dtype=float)
    cell = ctx["cell"]
    h, w = dem_full.shape
    step = max(1, int(round(max(h, w) / 384)))    # stride so the sweep runs on ~384 px (the psr-raster budget)
    dem = dem_full[::step, ::step]
    ever_lit = np.zeros(dem.shape, dtype=bool)
    for az in range(0, 360, 30):
        ever_lit |= horizon_clip(dem, cell * step, float(az), 3.0)
    result = (step, ~ever_lit)
    _PSR_MASK_CACHE[site] = result
    return result


def transect_profile(site: str, points, frame: str = "order") -> dict:
    """[REQ:SD-03] The #45 resource-exploration cross-section: sample the REAL per-cell layers along a drawn
    transect. `points` are order-frame (x, y) [m] samples when frame='order', or selenographic [lon, lat] deg
    when frame='lonlat' (what the public /ide sends -- a 30135 click reprojected to 30100, converted to order
    metres here via the same MP.latlon_to_dem_origin /world/point uses). Each sample carries elevation (LOLA DEM),
    slope + bearing + sinkage (the terramechanics spine), PSR (horizon-computed cold-trap), and the cumulative
    along-transect distance. Ice-stability (thermal depth-to-ice) is NOT included -- terrain.thermal has no real
    producer (catalog-only, no Diviner raster wired); it is reported as an explicit data gap, never fabricated.
    Reuses the once-per-site setup + point_values math (byte-identical to /world/point per cell)."""
    import math

    ctx = _point_setup(site)
    step, psr = _site_psr_mask(site, ctx)
    Z, cell, origin = ctx["Z"], ctx["cell"], ctx["origin"]
    ox, oy = float(origin[0]), float(origin[1])
    h, w = Z.shape
    ph, pw = psr.shape
    order_pts: list = []
    if frame == "lonlat":                                # public /ide: reproject 30135 click -> 30100 lon/lat,
        # POST here; convert to the ORDER frame point_values uses (latlon_to_order subtracts the flattest anchor
        # -- council #55 HIGH). council #55 [3]: an out-of-tile sample raises ValueError -- catch it PER-POINT so
        # a transect that only PARTIALLY crosses the tile still returns its in-tile samples (None = no-data row)
        # instead of 422-ing the whole draw.
        for p in points:
            try:
                order_pts.append(latlon_to_order(site, float(p[0]), float(p[1]), _ctx=ctx))
            except ValueError:
                order_pts.append(None)
    else:                                                # council #55 pass3: route a non-finite order coord to None
        order_pts = [((float(p[0]), float(p[1]))         # (symmetric with the lonlat branch) -- the duplicate col/row
                      if math.isfinite(float(p[0])) and math.isfinite(float(p[1])) else None)   # math below is
                     for p in points]                    # unguarded, and round(inf) OverflowErrors -> HTTP 500
    samples = []
    prev = None
    dist = 0.0
    for op in order_pts:
        if op is None:                                   # council #55 [3]: out-of-tile lonlat sample -> honest
            samples.append({                             # no-data row (position unknown, so distance is carried,
                "dist_m": round(dist, 2), "x_m": None, "y_m": None, "in_bounds": False,   # not advanced)
                "elevation_m": None, "slope_deg": None, "bearing_pa": None, "sinkage_m": None, "psr": None,
            })
            continue
        x, y = float(op[0]), float(op[1])
        if prev is not None:
            dist += math.hypot(x - prev[0], y - prev[1])
        prev = (x, y)
        a = {at["id"]: at for at in point_values(site, x, y, _ctx=ctx)["attributes"]}
        col = int(round((ox + x) / cell))
        row = int(round((oy + y) / cell))
        in_b = (0 <= row < h) and (0 <= col < w)
        dr, dc = row // step, col // step                       # full-res cell -> strided PSR grid
        samples.append({
            "dist_m": round(dist, 2), "x_m": round(x, 2), "y_m": round(y, 2), "in_bounds": in_b,
            "elevation_m": a.get("base.dem", {}).get("value"),
            "slope_deg": a.get("terrain.slope", {}).get("value"),
            "bearing_pa": a.get("physics.bearing", {}).get("value"),
            "sinkage_m": a.get("physics.sinkage", {}).get("value"),
            "psr": (bool(psr[dr, dc]) if (in_b and 0 <= dr < ph and 0 <= dc < pw) else None),
        })
    return {
        "site": site, "n": len(samples), "samples": samples,
        "sources": {
            "elevation_m": "LOLA DEM (base.dem, prior/observed)",
            "slope_deg": "derived from the DEM gradient",
            "bearing_pa": "terramechanics spine (physics.bearing, derived/estimated)",
            "sinkage_m": "terramechanics spine (physics.sinkage, derived/estimated)",
            "psr": "permanently-shadowed = never lit across a 0..360 deg sun-azimuth sweep at 3 deg elevation "
                   "(dart.illumination horizon-clip on the real DEM)",
        },
        "unavailable": {
            "ice_stability": "NO real per-cell producer -- terrain.thermal is catalog-only (no Diviner/thermal "
                             "ice-stability raster wired). NOT fabricated. PSR (cold-trap candidate) is the real "
                             "ice-relevant proxy; a quantitative depth-to-ice needs a Diviner/LOLA thermal dataset.",
        },
    }


def _point_actions(*, in_bounds: bool, passable: bool) -> list:
    """[REQ:GW-07] The mission actions a clicked cell affords, each with an enabled flag + a reason so a
    disabled control names WHY (the FR-03 / AU-01 command-authority discipline, at the map-cell scale).
    plan-here anchors a plan; place-structure + add-keepout author mission features -- all gated on real
    state (an out-of-tile or impassable cell cannot host a structure)."""
    if not in_bounds:
        why = "outside the site tile"
        return [
            {"id": "plan_here", "label": "Plan here", "enabled": False, "reason": why},
            {"id": "place_structure", "label": "Place structure", "enabled": False, "reason": why},
            {"id": "add_keepout", "label": "Add keep-out", "enabled": False, "reason": why},
        ]
    return [
        {"id": "plan_here", "label": "Plan here", "enabled": True, "reason": None},
        {"id": "place_structure", "label": "Place structure", "enabled": bool(passable),
         "reason": None if passable else "cell is impassable (blocked terrain)"},
        {"id": "add_keepout", "label": "Add keep-out", "enabled": True, "reason": None},
    ]


def _terra_fields(dem, cell):
    """Per-cell terramechanics-spine fields on a DEM patch, each a REAL solver output as a pure function of
    the per-cell slope. Evaluated via a 512-sample slope LUT (scalar spine solves) then interpolated onto the
    DEM slope map -- exact to the LUT resolution, the same values the drive-loop solver produces. Returns a
    dict of (H,W) float fields keyed by physics kind (bearing/sinkage/slip_risk/traction_margin/
    excavation_resistance/energy_cost)."""
    import math

    import numpy as np

    from lode.planner_routing import slope_deg_map
    from stewie.physics import sinkage as SK
    from stewie.physics import slip as SL
    from stewie.specs import constants as K
    from stewie.specs import ipex_specs

    slope = np.asarray(slope_deg_map(dem, cell), dtype=float)
    smax = float(min(89.0, np.nanmax(slope))) if slope.size else 1.0
    grid = np.linspace(0.0, max(smax, 1.0), 512)          # fine theta LUT [deg]; interp is exact for a monotone f
    mass = float(ipex_specs.ROVER_MASS_CLASS_KG)
    g = float(ipex_specs.LUNAR_G_MS2)
    weight = mass * g
    n = int(K.N_WHEELS)
    cl_m, cw_m = 0.10, 0.18                                # slip-module contact patch (matches the profile wheel)
    bearing = np.empty_like(grid)
    sink = np.empty_like(grid)
    slp = np.empty_like(grid)
    margin = np.empty_like(grid)
    resist = np.empty_like(grid)
    power = np.empty_like(grid)
    for i in range(grid.size):
        th = math.radians(float(grid[i]))
        n_cell = weight * math.cos(th) / n                # per-wheel normal load [N] on the grade
        bearing[i] = SK.contact_pressure(n_cell, cw_m, cl_m)                     # spine: contact_pressure
        eq = SL.slip_sinkage_equilibrium(weight, th)                            # ONE spine slip-sinkage solve
        sink[i] = eq["sinkage_m"]                                               # spine: bekker_sinkage (+slip)
        slp[i] = eq["slip"]                                                     # spine: slip_for_demand
        b, d = eq["budget_n"], eq["demand_n"]                                   # spine: traction_budget
        margin[i] = max(0.0, (b - d) / b) if b > 0.0 else 0.0
        resist[i] = eq["resistance_n"]                                          # spine: compaction_resistance
        power[i] = SL.bekker_drive_power_w(mass_kg=mass, g_ms2=g,
                                           slope_deg=float(grid[i]))["drive_power_w"]   # spine: drive_energy

    def _interp(vals):
        return np.interp(slope, grid, vals)

    return {"bearing": _interp(bearing), "sinkage": _interp(sink), "slip_risk": _interp(slp),
            "traction_margin": _interp(margin), "excavation_resistance": _interp(resist),
            "energy_cost": _interp(power)}


def _physics_heatmap_rgba(field, stops, *, invert=False):
    """Sequential heatmap of a physics field along ``stops``, robustly stretched between the 2nd/98th
    percentiles so the entrapment-tail outliers (drive power / sinkage spike near entrapment) don't wash out
    the ramp. ``invert`` orients so the ramp HIGH end (redder) + the opacity peak land on the risky value
    (low traction margin)."""
    import numpy as np
    f = np.asarray(field, dtype=float)
    finite = np.isfinite(f)
    vals = f[finite]
    lo = float(np.percentile(vals, 2.0)) if vals.size else 0.0
    hi = float(np.percentile(vals, 98.0)) if vals.size else 1.0
    if hi <= lo:
        hi = lo + 1e-9
    t = np.clip((np.where(finite, f, lo) - lo) / (hi - lo), 0.0, 1.0)
    if invert:
        t = 1.0 - t
    rgba = np.zeros((*f.shape, 4), dtype=float)
    rgba[..., :3] = _ramp_rgb(t, stops)
    rgba[..., 3] = 110.0 + 120.0 * t                       # alpha rises toward the risky end (like the cost drape)
    return rgba.astype("uint8")


def _physics_rgba(dem, cell, kind):
    """RGBA for one PHYSICS (TM) drape kind: the real terramechanics-spine field (bearing/sinkage/slip_risk/
    traction_margin/energy_cost/excavation_resistance) coloured by its PHYSICS_LAYERS ramp. None for any
    non-physics or observed-only kind (physics.compaction has no plan-independent per-cell field)."""
    spec = PHYSICS_LAYERS.get(kind)
    if spec is None:
        return None
    fields = _terra_fields(dem, cell)
    return _physics_heatmap_rgba(fields[kind], spec["ramp_stops"], invert=spec["invert"])


def render_globe(kind: str, *, sun_el: float = 6.0, sun_az: float = 90.0, mp=None,
                 grid_color: str = "39ff14", site: str = "haworth",
                 slope_vmax: float = 30.0, slope_classes: int = 0):
    """The geographic drape for the globe: 'dem' = the full-tile hillshade; the GIS rasters
    reproject over the WORK AREA's own extent. Returns (rgba uint8, bbox). REG-01: ``site`` selects the
    imported tile so the globe drape follows the chosen site, not just Haworth. G5: slope_vmax/slope_classes
    are the slope layer's graduated-renderer controls (ignored for other kinds)."""
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                # raises KeyError/FileNotFoundError -> route 404
    if kind == "traffic":
        # [REQ:TW-11] the OBSERVED traversal-compaction drape from the site's persistent TrafficMemory (Dr).
        # NOT cached: it changes as each SIM run folds new traffic (a cache would drape a stale road).
        return _render_globe_traffic(mp, bundle_dir, site)
    # G5 symbology key: a 2-tuple always (the (30.0,0) default for non-slope is constant -> no fragmentation)
    sym = (round(float(slope_vmax), 2), int(slope_classes)) if kind == "slope" else (30.0, 0)
    key = ("globe", kind, site, round(float(sun_el), 2), round(float(sun_az), 2),
           grid_color if kind == "grid" else "", sym)
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
    # G5: a non-default slope symbology gets its own cache file; the default (30/continuous) keeps the
    # original stem so existing cached slope tiles are reused.
    sym_tag = f"_v{sym[0]}_c{sym[1]}" if (kind == "slope" and sym != (30.0, 0)) else ""
    stem = _oss.path.join(cdir, f"{kind}_{site}_{key[3]}_{key[4]}_r2"
                          + (f"_{grid_color}" if kind == "grid" else "") + sym_tag)
    if _oss.path.exists(stem + ".npy") and _oss.path.exists(stem + ".json"):
        out = (_np_load_rgba(stem + ".npy"), _json.load(open(stem + ".json")))
        _GLOBE_CACHE[key] = out
        return out

    import numpy as _np
    dem_full, cell_m, b, fwd, tile_crs = _tile_geo(mp, bundle_dir)
    if kind == "dem":
        # CLEAN cartographic hillshade (315/45 lambertian) computed from the RAW heightmap via the shared
        # _layer_rgba helper (the order-frame work-area drape uses the same). The real-sun SHADOW layer is
        # separate. R-1 (#234): drape at the DEM's NATIVE resolution, not a fixed 1024 (which ~2x-downsampled
        # the 2000-px / 5 m Haworth tile). Cap at 2048 so an oversized DEM can't blow up the reproject.
        rgba = _layer_rgba(dem_full, cell_m, "dem")
        out = _reproject(rgba, b, fwd, out_px=min(int(_np.asarray(dem_full).shape[0]), 2048), crs=tile_crs)
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
            out = _reproject(rgba, b, fwd, out_px=1024, crs=tile_crs)
            _GLOBE_CACHE[key] = out
            return out
        # cost/blocking compose the full 12-layer costmap (one shared horizon sweep, like psr) so they
        # render at the cheaper psr resolution; the slope-family kinds keep 768.
        px = 384 if kind in ("psr", "cost", "blocking") else 768
        stride = max(1, dem_full.shape[0] // px)
        dem = _np.asarray(dem_full, dtype=float)[::stride, ::stride]
        cm = cell_m * stride
        # the per-kind colouring is the shared _layer_rgba helper (same formulas the order-frame
        # work-area drape uses); here it runs on the downsampled full tile + is reprojected for the globe.
        gnb = None
        # #266: re-express the TRUE sun az in the grid frame for every kind whose illumination/psr/shadow
        # layers march the DEM horizon (illumination/incidence + the costmap's cost/blocking composites).
        if kind in ("illumination", "incidence", "cost", "blocking"):
            try:
                from stewie.terrain.site_dem import grid_north_bearing_deg
                _h, _w = dem_full.shape[:2]           # native-frame tile centre (orientation, stride-invariant)
                gnb = grid_north_bearing_deg((_w / 2.0) * cell_m, (_h / 2.0) * cell_m, bundle_dir=bundle_dir)
            except (ImportError, ValueError):
                gnb = None
        if kind in ("cost", "blocking"):
            # the AS-11 costmap analysis drape (real lode.costmap_layers.compose on the full tile)
            rgba = _costmap_rgba(dem, cm, kind, sun_az, sun_el, grid_north_bearing=gnb)
        elif kind in _PHYSICS_KINDS:
            # the T12 PHYSICS (TM) drape: the terramechanics-spine per-cell field (sun-independent -- a pure
            # function of the DEM slope + fixed vehicle/soil constants)
            rgba = _physics_rgba(dem, cm, kind)
        else:
            rgba = _layer_rgba(dem, cm, kind, sun_az, sun_el,
                               slope_vmax=slope_vmax, slope_classes=slope_classes, grid_north_bearing=gnb)
        if rgba is None:
            return None
        out = _reproject(rgba, b, fwd, out_px=1024, crs=tile_crs)   # _layer_rgba already returns uint8
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


# ---- [REQ:LY-05] the CONTOURS vector product: real elevation isolines of the site DEM ----------------
# A REAL vector product (not a raster drape): contourpy (matplotlib's contour engine) traces the elevation
# isolines of the site's LOLA heightfield at a stated interval, and each polyline is reprojected from the
# tile frame to selenographic lon/lat (OGC CRS84, lon-lat order) so it co-registers with the globe drapes.
# Served as GeoJSON. Registered in the LY-01 catalog as base.contours (display-only by default). No
# fabricated geometry -- every vertex comes from the real DEM. (osgeo.gdal / gdal_contour into the .qgz is
# the QGIS-side alternative the PRD names; it is unavailable in this venv -- osgeo is not importable -- so
# the GeoJSON endpoint is the real, tested vector producer here.)
def contour_geojson(site: str = "haworth", interval: float = 50.0, *, mp=None,
                    max_levels: int = 400, target_px: int = 512, max_vertices: int = 200_000) -> dict:
    """[REQ:LY-05] REAL elevation contours of the site DEM at ``interval`` metres as a GeoJSON
    FeatureCollection -- one MultiLineString Feature per elevation level, coordinates in selenographic
    lon/lat (OGC:CRS84). The DEM is strided to ~``target_px`` before tracing (a coarse isoline is faithful
    for a display contour and keeps the trace light); the level count is capped and the total vertex count
    is bounded (``truncated`` flag when hit). Raises KeyError/FileNotFoundError for an unknown/unimported
    site (the route -> 404)."""
    import math

    import numpy as np
    from contourpy import contour_generator
    from pyproj import Transformer
    if mp is None:
        from lode import mission_planner as mp
    bundle_dir = mp.bundle_for_site(site)                 # raises KeyError/FileNotFoundError -> route 404
    dem_full, cell_m, b, _fwd, tile_crs = _tile_geo(mp, bundle_dir)
    Z = np.asarray(dem_full, dtype=float)
    H, W = Z.shape
    stride = max(1, int(round(max(H, W) / max(2, int(target_px)))))
    Zd = Z[::stride, ::stride]
    hd, wd = Zd.shape
    x0, y0, x1, y1 = b["x0"], b["y0"], b["x1"], b["y1"]
    xs = np.linspace(x0, x1, wd)                          # tile-frame East metres per column
    ys = np.linspace(y1, y0, hd)                          # north-up raster: row 0 = y1 (max north)
    zmin = float(np.nanmin(Zd)); zmax = float(np.nanmax(Zd))
    iv = float(interval)
    if not math.isfinite(iv) or iv <= 0.0:
        iv = 50.0
    lo = math.ceil(zmin / iv) * iv
    levels: list[float] = []
    v = lo
    while v <= zmax and len(levels) < int(max_levels):
        levels.append(round(v, 3)); v += iv
    inv = Transformer.from_crs(tile_crs, tile_crs.geodetic_crs, always_xy=True)   # tile frame -> lon/lat
    gen = contour_generator(xs, ys, Zd, line_type="Separate")
    features: list[dict] = []
    n_vertices = 0
    truncated = False
    for lev in levels:
        coords: list = []
        for pl in gen.lines(float(lev)):                 # each pl = (N,2) polyline in (tile East, tile North) m
            arr = np.asarray(pl, dtype=float)
            if arr.shape[0] < 2:
                continue
            lon, lat = inv.transform(arr[:, 0], arr[:, 1])
            line = [[round(float(a), 6), round(float(o), 6)] for a, o in zip(lon, lat)]
            coords.append(line)
            n_vertices += len(line)
            if n_vertices >= int(max_vertices):
                truncated = True
                break
        if coords:
            features.append({"type": "Feature", "properties": {"elevation_m": float(lev)},
                             "geometry": {"type": "MultiLineString", "coordinates": coords}})
        if truncated:
            break
    return {"type": "FeatureCollection",
            "properties": {"site": site, "interval_m": iv, "levels": len(features),
                           "z_min_m": round(zmin, 2), "z_max_m": round(zmax, 2),
                           "vertices": n_vertices, "truncated": truncated, "crs": "OGC:CRS84",
                           "source": "LOLA DEM elevation isolines (contourpy on the real heightfield)",
                           "eligibility": "display-only (base.contours, LY-01 catalog)"},
            "features": features}
