#!/usr/bin/env python3
"""Encode a lunar polar-stereographic DEM into a deck.gl-ready binary terrain point grid that renders on
GeoLibre's globe at the TRUE pole (no mercator cutoff, no geographic squish). For each native polar-stereo
cell (x,y,z) we compute (lon,lat) via the exact inverse and keep z as altitude -> deck.gl PointCloudLayer /
mesh on the GlobeView places it correctly at 85-90 deg S. Downsampled to a renderable grid; full-res tiling
is a later LOD pass. Output: <site>.bin (Float32 [lon,lat,elev]*N + Uint8 [r,g,b]*N) + <site>.json meta."""
import json
import struct
import sys

import numpy as np
from osgeo import gdal, osr

R_MOON = 1737400
STEREO = f"+proj=stere +lat_0=-90 +lon_0=0 +k=1 +x_0=0 +y_0=0 +a={R_MOON} +b={R_MOON} +units=m +no_defs"
GEO = f"+proj=longlat +a={R_MOON} +b={R_MOON} +no_defs"


class _TF:
    def __init__(self):
        s = osr.SpatialReference(); s.ImportFromProj4(STEREO); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        d = osr.SpatialReference(); d.ImportFromProj4(GEO); d.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        self.ct = osr.CoordinateTransformation(s, d)

    def transform(self, x, y):
        pts = np.array(self.ct.TransformPoints(list(zip(x.tolist(), y.tolist()))))
        return pts[:, 0], pts[:, 1]


TF = _TF()


def ramp(z, zmin, zmax):
    """simple hypsometric ramp -> uint8 RGB (dark blue low -> tan/white high)."""
    t = np.clip((z - zmin) / max(zmax - zmin, 1e-6), 0, 1)
    r = (60 + t * 195).astype(np.uint8)
    g = (70 + t * 160).astype(np.uint8)
    b = (110 + (1 - t) * 60).astype(np.uint8)
    return r, g, b


def run(src, out_bin, out_json, target=700):
    ds = gdal.Open(src)
    gt = ds.GetGeoTransform()
    band = ds.GetRasterBand(1)
    nd = band.GetNoDataValue()
    W, H = ds.RasterXSize, ds.RasterYSize
    step = max(1, min(W, H) // target)
    elev = band.ReadAsArray()[::step, ::step].astype(np.float64)
    h, w = elev.shape
    # native polar-stereo x/y for each kept cell (pixel centre)
    cols = (np.arange(w) * step + 0.5)
    rows = (np.arange(h) * step + 0.5)
    X = gt[0] + gt[1] * cols
    Y = gt[3] + gt[5] * rows
    XX, YY = np.meshgrid(X, Y)
    Xf, Yf = XX.ravel(), YY.ravel()
    lon, lat = TF.transform(Xf, Yf)  # for the lat/lon context in meta only
    z = elev.ravel()
    mask = np.isfinite(z) & (z != nd) & (z > -1e5)
    Xf, Yf, z, lon, lat = Xf[mask], Yf[mask], z[mask], lon[mask], lat[mask]
    zmin, zmax = float(z.min()), float(z.max())
    r, g, b = ramp(z, zmin, zmax)
    n = z.size
    # Local Cartesian metres, centred on the site (X east, Y north, Z up = elevation). deck.gl OrbitView
    # renders this directly with NO globe pole singularity -- _GlobeView renders 85 deg S but fails at the
    # 88-90 deg S Artemis sites, which is exactly where the mission is. This is the native polar-stereo frame.
    cx, cy = float(Xf.mean()), float(Yf.mean())
    lx = (Xf - cx).astype("<f4")
    ly = (Yf - cy).astype("<f4")
    lz = z.astype("<f4")
    with open(out_bin, "wb") as f:
        f.write(np.column_stack([lx, ly, lz]).astype("<f4").tobytes())
        f.write(np.column_stack([r, g, b]).astype("u1").tobytes())
    json.dump({"count": int(n), "posBytes": int(n * 12), "colBytes": int(n * 3),
               "elev_min": zmin, "elev_max": zmax,
               "x_extent": [float(lx.min()), float(lx.max())],
               "y_extent": [float(ly.min()), float(ly.max())],
               "lat_range": [float(lat.min()), float(lat.max())],
               "lon_range": [float(lon.min()), float(lon.max())]},
              open(out_json, "w"), indent=2)
    print(f"  {out_bin.split('/')[-1]}: {n} pts, elev {zmin:.0f}..{zmax:.0f}m, "
          f"extent {lx.max()-lx.min():.0f}x{ly.max()-ly.min():.0f}m, lat[{lat.min():.2f},{lat.max():.2f}]")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2], sys.argv[3])
