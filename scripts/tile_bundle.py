"""Tile a real LOLA DEM bundle EXACTLY like Haworth: 100 m numbered tiles + 25 m sub-graticule, a
leakage-safe spatial-block train/test/val split, and per-tile lat/lon + per-layer-stats annotations.

This is the driver that runs the frozen ``stewie.dataset`` pipeline (``tile_grid`` / ``splits`` /
``annotations``) over a committed ``samples/lunar_dem/<name>_10km_5m`` bundle and emits the three
per-bundle artifacts the ML-dataset consumers read:

    <bundle>/tiling/tile_index.json     -- the numbered 100 m grid (extent + center/corner lat/lon +
                                           pixel window per tile), with the split label folded in.
    <bundle>/tiling/splits.json         -- the leakage-safe split scheme + per-tile labels + the
                                           overlapping training chips (id + window + center lat/lon).
    <bundle>/tiling/annotations.geojson -- a GeoJSON FeatureCollection: one Feature per 100 m tile,
                                           its closed selenographic corner polygon + per-layer
                                           (dem/slope/aspect) real-pixel statistics + split label.
    <bundle>/tiling/manifest.json       -- provenance + the pixel-size note (see below).

Real data only. Geometry comes from the bundle's ``metadata.json`` ``world_bounds_m`` (the exact
10 km extent in the shared south-polar stereographic frame, IAU_2015:30135); every statistic is
computed over the bundle's real ``heightmap.rf32`` through the SAME producers ``stewie.dataset`` uses
(``site_dem.slope_deg_map`` for slope, ``gis_layers.aspect_deg`` for aspect). Nothing is fabricated.

PIXEL-SIZE NOTE (in the manifest): the tile SPEC is physical -- 100 m tiles, 25 m sub-graticule --
so at the LOLA bundles' 5 m native cell each 100 m tile is 20 px (Haworth's 1 m SfS tiling makes the
same 100 m tile 100 px). Same physical grid, coarser native sampling: physically consistent, and the
manifest records both the metre spec and the resulting pixel side so a consumer never confuses them.

    python scripts/tile_bundle.py --bundle samples/lunar_dem/peak_near_shackleton_10km_5m
    python scripts/tile_bundle.py --all           # every heightmap-bearing bundle under samples/lunar_dem
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # noqa: E402

from stewie.dataset.annotations import annotate_tiles, to_geojson_featurecollection  # noqa: E402
from stewie.dataset.dem_source import (DemGeometry, geographic_crs_authority,  # noqa: E402
                                       selenographic_transformers)
from stewie.dataset.splits import spatial_block_split  # noqa: E402
from stewie.dataset.tile_grid import TileGrid  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SITE_ROOT = os.path.join(_REPO_ROOT, "samples", "lunar_dem")
TILE_M = 100.0
SUB_M = 25.0
LAYERS = ("dem", "slope", "aspect")


class Rf32WindowReader:
    """Windowed reader over a bundle's raw ``heightmap.rf32`` (row-major C ``<f4``), matching the
    ``stewie.dataset.GeoTiffWindowReader`` call signature ``reader(r0, c0, h, w) -> float32``.

    The bundle heightmap is the REAL 10 km @ 5 m crop the ``build_from_dem`` datum path wrote (its
    ``derive_height`` round-trips the source DEM to ~1e-14 m), so a tile's window is real LOLA-derived
    elevation. NoData (``metadata`` sentinel, if any) maps to NaN, exactly as the GeoTIFF reader does."""

    def __init__(self, path: str, width: int, height: int, nodata: float | None = None):
        self.path = path
        self.width = int(width)
        self.height = int(height)
        self.nodata = nodata
        self._mm = np.memmap(path, dtype="<f4", mode="r", shape=(self.height, self.width))

    def __call__(self, r0: int, c0: int, h: int, w: int) -> np.ndarray:
        W, H = self.width, self.height
        r0 = max(0, min(int(r0), H)); c0 = max(0, min(int(c0), W))
        h = max(0, min(int(h), H - r0)); w = max(0, min(int(w), W - c0))
        out = np.array(self._mm[r0:r0 + h, c0:c0 + w], dtype=np.float32)
        if self.nodata is not None:
            out = np.where(out == np.float32(self.nodata), np.float32("nan"), out)
        return out


def _load_meta(bundle: str) -> dict:
    with open(os.path.join(bundle, "metadata.json"), encoding="utf-8") as fh:
        return json.load(fh)


def bundle_geometry(bundle: str, meta: dict) -> DemGeometry:
    """A :class:`DemGeometry` for the bundle's 10 km @ 5 m crop, from its ``metadata.json`` alone.

    ``world_bounds_m`` are pixel-AREA outer edges (``build_from_dem`` §3): ``x_min = x0_center -
    cell/2`` .. , so the first-pixel center is ``(x_min + cell/2, y_max - cell/2)`` -- the same
    convention ``read_geotiff_geometry`` produces. CRS/radius are the shared curated-Haworth frame the
    tiling transform reuses; ``path`` is the real ``heightmap.rf32`` the reader reads (coherent)."""
    g = meta["grid"]
    W, H = int(g["width"]), int(g["height"])
    cell = float(g["cell_m"])
    wb = meta["world_bounds_m"]
    x_min = min(wb["x0"], wb["x1"]); x_max = max(wb["x0"], wb["x1"])
    y_min = min(wb["y0"], wb["y1"]); y_max = max(wb["y0"], wb["y1"])
    prov = meta.get("dem_provenance", {}) or {}
    radius = float(prov.get("sphere_radius_m", 1737400.0))
    # CRS authority: the shared south-polar stereographic frame the tiling transform builds from.
    _fwd, _inv = selenographic_transformers()   # warm the shared 30135 transformers (fail fast if absent)
    from stewie.dataset.dem_source import _bundle_crs
    auth = _bundle_crs().to_authority()
    crs_authority = ":".join(auth) if auth else "IAU_2015:30135"
    return DemGeometry(
        path=os.path.join(bundle, "heightmap.rf32"),
        width=W, height=H, cell_m=cell,
        x0_center=x_min + cell / 2.0, y0_center=y_max - cell / 2.0,
        x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
        crs_authority=crs_authority, radius_m=radius, nodata=None,
        raster_type="PixelIsArea",
    )


def _tile_index_record(t, split: str | None) -> dict:
    # The numbered-grid lookup: identity + extent + center + pixel window + split. The 4 corner
    # lat/lon are the annotations.geojson polygon geometry (not duplicated here to keep the index lean).
    return {
        "index": t.index, "row": t.row, "col": t.col, "tile_id": t.tile_id,
        "extent_m": [round(t.x0, 3), round(t.y0, 3), round(t.x1, 3), round(t.y1, 3)],
        "center_latlon": [round(t.center_lat, 6), round(t.center_lon, 6)],
        "px_window": [t.px_row0, t.px_col0, t.px_h, t.px_w],
        "valid_frac": round(t.valid_frac, 6),
        "split": split,
    }


def _chip_record(c) -> dict:
    return {
        "tile_id": c.tile_id, "row": c.row, "col": c.col,
        "px_window": [c.px_row0, c.px_col0, c.px_h, c.px_w],
        "center_latlon": [round(c.center_lat, 6), round(c.center_lon, 6)],
        "extent_m": [round(c.x0, 3), round(c.y0, 3), round(c.x1, 3), round(c.y1, 3)],
    }


def _provenance(bundle: str, meta: dict, geometry: DemGeometry) -> dict:
    prov = meta.get("dem_provenance", {}) or {}
    return {
        "bundle": os.path.basename(os.path.normpath(bundle)),
        "region": str(meta.get("region", "")),
        "source_dem": str(prov.get("source", "")),          # the real source tif, verbatim from the bundle
        "citation": str(prov.get("citation", "")),          # LOLA Barker/Mazarico (or SfS for the 1 m tile)
        "frame": str(prov.get("frame", "")),
        "crs": geometry.crs_authority,
        "geographic_crs": geographic_crs_authority(),
        "sphere_radius_m": geometry.radius_m,
        "license_basis": str(prov.get("license_basis", "")),
        "stats_read_from": "heightmap.rf32 (the committed 10 km @ 5 m crop of the source DEM)",
    }


def tile_bundle(bundle: str, *, tile_m: float = TILE_M, sub_m: float = SUB_M,
                out_subdir: str = "tiling", out_dir: str | None = None, layers=LAYERS) -> dict:
    """Tile one bundle like Haworth and write ``tile_index.json`` / ``splits.json`` /
    ``annotations.geojson`` / ``manifest.json`` under ``<bundle>/<out_subdir>/``. Returns the manifest.

    Self-verifies: tile count == ceil(extent/tile_m) on each axis; every tile center lat/lon is finite
    and south-polar (< -80 deg); the no-leakage gate holds (no training chip shares a pixel with any
    val/test tile); the splits are disjoint and cover the valid tiles."""
    bundle = os.path.abspath(bundle)
    hm = os.path.join(bundle, "heightmap.rf32")
    if not os.path.exists(hm):
        raise FileNotFoundError(f"{bundle}: no heightmap.rf32 -- a metadata-only bundle cannot be tiled")
    meta = _load_meta(bundle)
    geometry = bundle_geometry(bundle, meta)
    reader = Rf32WindowReader(hm, geometry.width, geometry.height, nodata=geometry.nodata)

    grid = TileGrid(geometry, tile_m=tile_m, sub_m=sub_m)
    split = spatial_block_split(grid)                        # 70/15/15 leakage-safe defaults

    # --- self-verify (real-data invariants; raise, never emit a bad tiling) ----------------------
    exp_cols = int(math.ceil(geometry.extent_x_m / tile_m))
    exp_rows = int(math.ceil(geometry.extent_y_m / tile_m))
    if grid.n_cols != exp_cols or grid.n_rows != exp_rows or grid.n_tiles != exp_cols * exp_rows:
        raise AssertionError(f"tile count {grid.n_tiles} != ceil(extent/tile_m) {exp_cols * exp_rows}")
    for t in grid.tiles:
        if not (math.isfinite(t.center_lat) and math.isfinite(t.center_lon)):
            raise AssertionError(f"tile {t.tile_id}: non-finite center lat/lon")
        if not (t.center_lat < -80.0):
            raise AssertionError(f"tile {t.tile_id}: center lat {t.center_lat} not south-polar")
    _assert_no_leakage(split)
    train = {t.index for t in split.train_tiles}
    val = {t.index for t in split.val_tiles}
    test = {t.index for t in split.test_tiles}
    dropped = {t.index for t in split.dropped}
    valid = {t.index for t in grid.tiles if t.valid_frac >= 1.0}
    if not (train.isdisjoint(val) and train.isdisjoint(test) and val.isdisjoint(test)):
        raise AssertionError("splits are not disjoint")
    if train | val | test | dropped != valid:
        raise AssertionError("splits do not cover the valid tiles")

    # --- annotations over the real pixel windows -------------------------------------------------
    annotations = annotate_tiles(grid.tiles, reader, geometry, split_result=split, layers=layers)
    prov = _provenance(bundle, meta, geometry)
    fc = _round_geojson(to_geojson_featurecollection(annotations, geometry, provenance=prov))

    # --- write artifacts -------------------------------------------------------------------------
    out_dir = out_dir or os.path.join(bundle, out_subdir)
    os.makedirs(out_dir, exist_ok=True)
    tile_index = {
        "bundle": prov["bundle"], "tile_m": tile_m, "sub_m": sub_m,
        "n_rows": grid.n_rows, "n_cols": grid.n_cols, "n_tiles": grid.n_tiles,
        "native_cell_m": geometry.cell_m,
        "tile_px": int(round(tile_m / geometry.cell_m)), "sub_px": int(round(sub_m / geometry.cell_m)),
        "world_bounds_m": meta["world_bounds_m"], "provenance": prov,
        "tiles": [_tile_index_record(t, split.split_of(t.index)) for t in grid.tiles],
    }
    splits_doc = {
        "bundle": prov["bundle"], "scheme": split.scheme,
        "train_tiles": sorted(train), "val_tiles": sorted(val), "test_tiles": sorted(test),
        "dropped_tiles": sorted(dropped),
        "train_chips": [_chip_record(c) for c in split.train_chips],
    }
    manifest = {
        "bundle": prov["bundle"], "region": prov["region"],
        "grid": {"width": geometry.width, "height": geometry.height, "native_cell_m": geometry.cell_m},
        "tiling_spec": {
            "tile_m": tile_m, "sub_m": sub_m,
            "tile_px": int(round(tile_m / geometry.cell_m)),
            "sub_px": int(round(sub_m / geometry.cell_m)),
            "n_rows": grid.n_rows, "n_cols": grid.n_cols, "n_tiles": grid.n_tiles,
            "pixel_size_note": (
                f"Physical {tile_m:g} m tiles / {sub_m:g} m sub-graticule. At the {geometry.cell_m:g} m "
                f"native LOLA cell each tile is {int(round(tile_m / geometry.cell_m))} px "
                f"(Haworth's 1 m SfS tiling makes the same {tile_m:g} m tile {int(round(tile_m / 1.0))} px). "
                "Same physical spec, coarser native sampling -- physically consistent."),
        },
        "split_counts": {
            "train_tiles": len(train), "val_tiles": len(val), "test_tiles": len(test),
            "dropped_tiles": len(dropped), "train_chips": len(split.train_chips),
        },
        "layers": list(layers),
        "artifacts": {
            "tile_index": "tile_index.json", "splits": "splits.json",
            "annotations": "annotations.geojson",
        },
        "provenance": prov,
    }

    _write_json(os.path.join(out_dir, "tile_index.json"), tile_index)
    _write_json(os.path.join(out_dir, "splits.json"), splits_doc)
    _write_json(os.path.join(out_dir, "annotations.geojson"), fc)
    _write_json(os.path.join(out_dir, "manifest.json"), manifest)
    return manifest


def _assert_no_leakage(split) -> None:
    """No training chip may share a pixel with any val or test tile (the load-bearing gate)."""
    def win(t):
        return (t.px_row0, t.px_col0, t.px_row0 + t.px_h, t.px_col0 + t.px_w)

    def overlap(a, b) -> bool:
        ar0, ac0, ar1, ac1 = win(a); br0, bc0, br1, bc1 = win(b)
        return not (ar1 <= br0 or br1 <= ar0 or ac1 <= bc0 or bc1 <= ac0)

    evals = list(split.val_tiles) + list(split.test_tiles)
    if not split.train_chips or not evals:
        raise AssertionError("empty train chips or eval tiles -- split is degenerate")
    for chip in split.train_chips:
        for tile in evals:
            if overlap(chip, tile):
                raise AssertionError(f"LEAKAGE: chip {chip.tile_id} overlaps eval tile {tile.tile_id}")


def _round_geojson(fc: dict) -> dict:
    """Round the FeatureCollection's floats for compact, low-noise diffs (real data, just fewer
    digits): geometry coordinates to 6 decimal deg (~0.03 m at the lunar radius), property statistics
    to 6 significant figures. Ints (count, index, row, col) are untouched."""
    def sig6(x):
        return x if isinstance(x, int) or not math.isfinite(x) else float(f"{x:.6g}")

    for feat in fc.get("features", []):
        ring = feat["geometry"]["coordinates"][0]
        feat["geometry"]["coordinates"][0] = [[round(lo, 6), round(la, 6)] for lo, la in ring]
        props = feat["properties"]
        for k, v in list(props.items()):
            if isinstance(v, float):
                props[k] = sig6(v)
    return fc


def _write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, separators=(",", ":"))
        fh.write("\n")


def _heightmap_bundles(root: str) -> list[str]:
    import glob
    out = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "heightmap.rf32")) \
                and os.path.exists(os.path.join(d, "metadata.json")):
            out.append(os.path.abspath(d))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tile a real LOLA DEM bundle like Haworth (100 m / 25 m).")
    ap.add_argument("--bundle", help="path to one samples/lunar_dem/<name>_10km_5m bundle")
    ap.add_argument("--all", action="store_true", help="tile every heightmap-bearing bundle under the site root")
    ap.add_argument("--site-root", default=DEFAULT_SITE_ROOT)
    ap.add_argument("--tile-m", type=float, default=TILE_M)
    ap.add_argument("--sub-m", type=float, default=SUB_M)
    args = ap.parse_args(argv)

    if args.all:
        bundles = _heightmap_bundles(args.site_root)
    elif args.bundle:
        bundles = [args.bundle]
    else:
        ap.error("pass --bundle <dir> or --all")

    for b in bundles:
        man = tile_bundle(b, tile_m=args.tile_m, sub_m=args.sub_m)
        sc = man["split_counts"]
        print(f"tiled {man['bundle']:32s} {man['tiling_spec']['n_tiles']} tiles "
              f"({man['tiling_spec']['tile_px']} px) "
              f"train/val/test={sc['train_tiles']}/{sc['val_tiles']}/{sc['test_tiles']} "
              f"chips={sc['train_chips']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
