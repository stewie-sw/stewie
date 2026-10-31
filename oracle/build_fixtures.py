"""Build every golden fixture from the existing Python implementation over REAL inputs.

    python oracle/build_fixtures.py          # rewrite all fixtures (CI then runs git diff --exit-code)

Fixtures:
  dem_samples        per bundled real DEM: heights at interior cells (read_dem_window), slope from the
                     3x3 neighbourhood (slope_deg_map), and the selenographic lat/lon of each cell centre
                     (dem_origin_to_latlon, pyproj in the bundle's own polar-stereographic CRS).
  ephem_topocentric  10,000 epochs over 2026-2035 at three catalog sites: SPICE str2et (UTC -> TDB) and
                     the apparent (LT+S) Sun and Earth vectors seen from the site (spkcpo, MOON_ME_DE440_ME421).
                     Needs the NAIF kernels (pipeline/fetch.py).
  horizon_profiles   720-azimuth terrain horizons (navigator R4 semantics) from two observers on each of three
                     real tiles: great-circle rays on the IAU 2015 lunar sphere, pyproj projection into the
                     tile, bilinear heights, exact spherical elevation (curvature), each ray stopping where
                     the tile's coverage ends (reach < max range means an unknown sector, not open sky).
  visibility_windows 60 days at the real Haworth-centre observer: the upper-limb margin of the Sun and the Earth
                     over the known horizon (SPICE spkcpo LT+S apparent direction, PCK radii, Earth polar
                     radius for a conservative limb, horizon linear in azimuth) and its zero crossings,
                     bisected to 0.01 s between 600 s samples.
  global_ldem_samples
                     PDS LOLA LDEM_16 (simple cylindrical, label-driven): bilinear heights at every catalog
                     site, at the 0/360 longitude seam, near the poles and at 200 random points.
  horizon_stacked    the Haworth-centre horizon over a two-source stack (the 5 m tile, then LDEM_16 where
                     the tile ends), 720 azimuths, 50 m step, out to 200 km: the base tier completes rays.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline"))  # fetch

import export_registries  # noqa: E402
import fetch  # noqa: E402
from fixture_io import REPO, write_fixture  # noqa: E402
from stewie.specs.sites import SITES  # noqa: E402
from stewie.terrain import site_dem  # noqa: E402

ORACLE_FIXTURES = os.path.join(REPO, "crates", "stewie-oracle", "fixtures")
SAMPLES_PER_AXIS = 4


def _bundled_dems() -> list[str]:
    root = os.path.join(REPO, "samples", "lunar_dem")
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "heightmap.rf32")))


def _interior_cells(width: int, height: int) -> list[tuple[int, int]]:
    """Evenly spaced interior cells (never on the border, so the 3x3 slope window is complete)."""
    rows = np.linspace(1, height - 2, SAMPLES_PER_AXIS).round().astype(int)
    cols = np.linspace(1, width - 2, SAMPLES_PER_AXIS).round().astype(int)
    return [(int(r), int(c)) for r in rows for c in cols]


def dem_samples() -> None:
    bundles, sources = [], []
    for name in _bundled_dems():
        bundle_dir = os.path.join(REPO, "samples", "lunar_dem", name)
        meta = json.load(open(os.path.join(bundle_dir, "metadata.json"), encoding="utf-8"))
        g = meta["grid"]
        cells = []
        for r, c in _interior_cells(int(g["width"]), int(g["height"])):
            win, cell_m = site_dem.read_dem_window(r - 1, c - 1, 3, 3, bundle_dir=bundle_dir)
            slope = site_dem.slope_deg_map(win, cell_m)[1, 1]
            lat, lon = site_dem.dem_origin_to_latlon(c * cell_m, r * cell_m, bundle_dir=bundle_dir)
            cells.append({"row": r, "col": c, "height_m": float(win[1, 1]), "slope_deg": float(slope),
                          "lat_deg": lat, "lon_deg": lon})
        bundles.append({"bundle": name, "cell_m": float(g["cell_m"]), "width": int(g["width"]),
                        "height": int(g["height"]), "crs": str(site_dem.bundle_crs(bundle_dir).to_wkt()),
                        "cells": cells})
        sources += [f"samples/lunar_dem/{name}/metadata.json", f"samples/lunar_dem/{name}/heightmap.rf32"]
    write_fixture(ORACLE_FIXTURES, "dem_samples", "oracle/build_fixtures.py::dem_samples "
                  "(stewie.terrain.site_dem read_dem_window, slope_deg_map, dem_origin_to_latlon)",
                  sources, {"samples_per_axis": SAMPLES_PER_AXIS, "bundles": bundles})


EPHEM_SITES = ("haworth", "shackleton_rim", "malapert_massif")
EPHEM_EPOCHS = 10_000


def ephem_topocentric() -> None:
    import spiceypy as sp                              # oracle-only dependency (dev lock)

    kernels = fetch.fetch("spice_kernels.json")
    sp.kclear()
    for path in kernels.values():
        sp.furnsh(path)
    radius_km = sp.bodvrd("MOON", "RADII", 3)[1][0]
    t0, t1 = sp.str2et("2026-01-01T00:00:00"), sp.str2et("2036-01-01T00:00:00")
    rng = np.random.default_rng(20261031)              # epoch sampling only; every value comes from SPICE
    samples = []
    for i, et_guess in enumerate(rng.uniform(t0, t1 - 60.0, EPHEM_EPOCHS)):
        utc = sp.et2utc(float(et_guess), "ISOC", 3) + "Z"
        et = sp.str2et(utc[:-1])
        site = SITES[EPHEM_SITES[i % len(EPHEM_SITES)]]
        lat, lon = np.radians(site.lat_deg), np.radians(site.lon_deg)
        obs = radius_km * np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
        row = {"utc": utc, "tdb": et, "site": site.name}
        for tgt in ("SUN", "EARTH"):
            pos, _lt = sp.spkcpo(tgt, et, "MOON_ME_DE440_ME421", "OBSERVER", "LT+S", obs, "MOON",
                                 "MOON_ME_DE440_ME421")
            row[tgt.lower() + "_m"] = [float(v) * 1000.0 for v in pos[:3]]
        samples.append(row)
    sites = {n: {"lat_deg": SITES[n].lat_deg, "lon_deg": SITES[n].lon_deg} for n in EPHEM_SITES}
    write_fixture(ORACLE_FIXTURES, "ephem_topocentric", "oracle/build_fixtures.py::ephem_topocentric "
                  "(spiceypy str2et, spkcpo LT+S, MOON_ME_DE440_ME421, observer on the sphere h=0)",
                  [f".cache/spice/{n}" for n in sorted(kernels)] + ["crates/stewie-contracts/fixtures/sites.json"],
                  {"moon_radius_km": radius_km, "sites": sites, "samples": samples})


HORIZON_TILES = ("haworth_10km_5m", "shackleton_rim_10km_5m", "haworth_sfs_2km_1m")
HORIZON_N_AZ = 720
HORIZON_MAX_RANGE_M = 200_000.0
HORIZON_EYE_M = 1.5


def _bilinear(z: np.ndarray, fx: np.ndarray, fy: np.ndarray) -> np.ndarray:
    """Bilinear heights at fractional (col, row); NaN outside the hull of cell centres."""
    h, w = z.shape
    out = np.full(fx.shape, np.nan)
    ok = (fx >= 0) & (fy >= 0) & (fx <= w - 1) & (fy <= h - 1)
    c0 = np.minimum(np.floor(fx[ok]).astype(int), w - 2)
    r0 = np.minimum(np.floor(fy[ok]).astype(int), h - 2)
    tx, ty = fx[ok] - c0, fy[ok] - r0
    out[ok] = ((1 - ty) * ((1 - tx) * z[r0, c0] + tx * z[r0, c0 + 1])
               + ty * ((1 - tx) * z[r0 + 1, c0] + tx * z[r0 + 1, c0 + 1]))
    return out


def _horizon(z, cell, x0, y1, fwd, radius, lat0, lon0, h_obs):
    """One 720-ray horizon: (elev_deg, reach_m) per azimuth (clockwise from north)."""
    steps = np.arange(1, int(HORIZON_MAX_RANGE_M / cell) + 1) * cell
    delta = steps / radius
    phi1, lam1 = np.radians(lat0), np.radians(lon0)
    elev, reach = [], []
    for k in range(HORIZON_N_AZ):
        az = np.radians(360.0 * k / HORIZON_N_AZ)
        phi2 = np.arcsin(np.sin(phi1) * np.cos(delta) + np.cos(phi1) * np.sin(delta) * np.cos(az))
        lam2 = lam1 + np.arctan2(np.sin(az) * np.sin(delta) * np.cos(phi1),
                                 np.cos(delta) - np.sin(phi1) * np.sin(phi2))
        e, n = fwd.transform(np.degrees(lam2), np.degrees(phi2))
        ht = _bilinear(z, (np.asarray(e) - (x0 + cell / 2)) / cell, ((y1 - cell / 2) - np.asarray(n)) / cell)
        covered = ~np.isnan(ht)
        stop = int(np.argmin(covered)) if not covered.all() else len(steps)
        if stop == 0:
            elev.append(None)
            reach.append(0.0)
            continue
        rt = radius + ht[:stop]
        ro = radius + h_obs
        ang = np.arctan2(rt * np.cos(delta[:stop]) - ro, rt * np.sin(delta[:stop]))
        elev.append(float(np.degrees(ang.max())))
        reach.append(float(steps[stop - 1]))
    return elev, reach


def horizon_profiles() -> None:
    from pyproj import Transformer

    radius = float(json.load(open(os.path.join(REPO, "crates", "stewie-contracts", "fixtures", "bodies.json"),
                                  encoding="utf-8"))["moon"]["ellipsoid_radius_m"])
    profiles, sources = [], ["crates/stewie-contracts/fixtures/bodies.json"]
    for name in HORIZON_TILES:
        bundle_dir = os.path.join(REPO, "samples", "lunar_dem", name)
        meta = json.load(open(os.path.join(bundle_dir, "metadata.json"), encoding="utf-8"))
        z, cell = site_dem.load_haworth_dem(bundle_dir)
        g, b = meta["grid"], meta["world_bounds_m"]
        crs = site_dem.bundle_crs(bundle_dir)
        fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
        inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
        for row, col in ((g["height"] // 2, g["width"] // 2), (g["height"] // 4, (3 * g["width"]) // 4)):
            e = b["x0"] + cell * (col + 0.5)
            n = b["y1"] - cell * (row + 0.5)
            lon0, lat0 = inv.transform(e, n)
            h_obs = float(z[row, col]) + HORIZON_EYE_M
            elev, reach = _horizon(z, cell, b["x0"], b["y1"], fwd, radius, lat0, lon0, h_obs)
            profiles.append({"tile": name, "row": int(row), "col": int(col), "lat_deg": float(lat0),
                             "lon_deg": float(lon0), "eye_m": HORIZON_EYE_M, "step_m": cell,
                             "elev_deg": elev, "reach_m": reach})
        sources += [f"samples/lunar_dem/{name}/metadata.json", f"samples/lunar_dem/{name}/heightmap.rf32"]
    write_fixture(ORACLE_FIXTURES, "horizon_profiles", "oracle/build_fixtures.py::horizon_profiles "
                  "(NumPy + pyproj; spherical great-circle rays, bilinear heights, curvature)",
                  sources, {"n_az": HORIZON_N_AZ, "max_range_m": HORIZON_MAX_RANGE_M, "profiles": profiles})


VIS_START, VIS_END, VIS_SAMPLE_S = "2027-01-01T00:00:00", "2027-03-02T00:00:00", 600.0


def _limb_margin_fn(sp, horizon, lat, lon, obs_km):
    """margin(et, body) = upper-limb elevation minus the known horizon at the body's azimuth [deg]."""
    elev = np.array(horizon["elev_deg"], dtype=float)
    n = len(elev)
    phi, lam = np.radians(lat), np.radians(lon)
    east = np.array([-np.sin(lam), np.cos(lam), 0.0])
    north = np.array([-np.sin(phi) * np.cos(lam), -np.sin(phi) * np.sin(lam), np.cos(phi)])
    up = np.array([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])
    radius_km = {b: min(sp.bodvrd(b, "RADII", 3)[1]) for b in ("SUN", "EARTH")}

    def margin(et: float, body: str) -> float:
        v, _lt = sp.spkcpo(body, et, "MOON_ME_DE440_ME421", "OBSERVER", "LT+S", obs_km, "MOON",
                           "MOON_ME_DE440_ME421")
        v = np.asarray(v[:3])
        e, nn, u = float(v @ east), float(v @ north), float(v @ up)
        az = math.degrees(math.atan2(e, nn)) % 360.0
        el = math.degrees(math.atan2(u, math.hypot(e, nn)))
        ang = math.degrees(math.asin(radius_km[body] / float(np.linalg.norm(v))))
        k = az / (360.0 / n)
        k0 = int(math.floor(k)) % n
        f = k - math.floor(k)
        return el + ang - ((1 - f) * elev[k0] + f * elev[(k0 + 1) % n])

    return margin


def visibility_windows() -> None:
    import spiceypy as sp

    kernels = fetch.fetch("spice_kernels.json")
    sp.kclear()
    for path in kernels.values():
        sp.furnsh(path)
    hz = json.load(open(os.path.join(ORACLE_FIXTURES, "horizon_profiles.payload.json"), encoding="utf-8"))
    prof = next(p for p in hz["profiles"] if p["tile"] == "haworth_10km_5m" and p["row"] == 1000)
    bundle_dir = os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m")
    z, _cell = site_dem.load_haworth_dem(bundle_dir)
    ground = float(z[prof["row"], prof["col"]])
    radius_km = sp.bodvrd("MOON", "RADII", 3)[1][0]
    lat, lon = prof["lat_deg"], prof["lon_deg"]
    r = radius_km + (ground + prof["eye_m"]) / 1000.0
    phi, lam = np.radians(lat), np.radians(lon)
    obs = r * np.array([np.cos(phi) * np.cos(lam), np.cos(phi) * np.sin(lam), np.sin(phi)])
    margin = _limb_margin_fn(sp, prof, lat, lon, obs)
    t0, t1 = sp.str2et(VIS_START), sp.str2et(VIS_END)
    ts = np.arange(t0, t1 + 0.5 * VIS_SAMPLE_S, VIS_SAMPLE_S)
    ts[-1] = min(ts[-1], t1)
    cases = []
    for body in ("SUN", "EARTH"):
        m = [margin(float(t), body) for t in ts]
        out = []
        for i in range(len(ts) - 1):
            if (m[i] < 0) != (m[i + 1] < 0):
                lo, hi, mlo = float(ts[i]), float(ts[i + 1]), m[i]
                while hi - lo > 0.01:
                    mid = 0.5 * (lo + hi)
                    mm = margin(mid, body)
                    if (mm < 0) == (mlo < 0):
                        lo, mlo = mid, mm
                    else:
                        hi = mid
                out.append(0.5 * (lo + hi))
        cases.append({"body": body, "crossings_tdb": out})
    write_fixture(ORACLE_FIXTURES, "visibility_windows", "oracle/build_fixtures.py::visibility_windows "
                  "(spiceypy spkcpo LT+S, PCK radii, horizon_profiles haworth centre, bisection 0.01 s)",
                  [f".cache/spice/{n}" for n in sorted(kernels)]
                  + ["samples/lunar_dem/haworth_10km_5m/heightmap.rf32",
                     "crates/stewie-oracle/fixtures/horizon_profiles.payload.json"],
                  {"start_utc": VIS_START + "Z", "end_utc": VIS_END + "Z", "sample_s": VIS_SAMPLE_S,
                   "eye_m": prof["eye_m"], "ground_m": ground, "site": {"lat_deg": lat, "lon_deg": lon},
                   "horizon": {"tile": prof["tile"], "elev_deg": prof["elev_deg"], "reach_m": prof["reach_m"]},
                   "cases": cases})


def _pds_label(path: str) -> dict:
    """KEY = value pairs of a PDS3 label (comments, quotes and <units> stripped)."""
    out = {}
    for line in open(path, encoding="ascii", errors="replace"):
        line = line.split("/*", 1)[0].strip()
        if "=" in line:
            k, v = (x.strip() for x in line.split("=", 1))
            out[k] = v.split("<", 1)[0].strip().strip('"')
    return out


class _PdsGrid:
    """LOLA LDEM simple-cylindrical grid read straight from the IMG, independent of the Rust reader."""

    def __init__(self, img: str, lbl: str):
        lab = _pds_label(lbl)
        self.lines, self.samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
        self.scale, self.res = float(lab["SCALING_FACTOR"]), float(lab["MAP_RESOLUTION"])
        self.l0, self.s0 = float(lab["LINE_PROJECTION_OFFSET"]), float(lab["SAMPLE_PROJECTION_OFFSET"])
        self.lon_c, self.west = float(lab["CENTER_LONGITUDE"]), float(lab["WESTERNMOST_LONGITUDE"])
        self.dn = np.fromfile(img, dtype="<i2").reshape(self.lines, self.samples)

    def height(self, lat: float, lon: float):
        row = self.l0 - lat * self.res
        col = self.s0 + ((((lon - self.west) % 360.0) + self.west) - self.lon_c) * self.res
        if not (0.0 <= row <= self.lines - 1):
            return None
        r0 = min(int(math.floor(row)), self.lines - 2)
        c0 = int(math.floor(col))
        ty, tx = row - r0, col - c0
        c0w, c1w = c0 % self.samples, (c0 + 1) % self.samples
        z = self.dn
        v = ((1 - ty) * ((1 - tx) * float(z[r0, c0w]) + tx * float(z[r0, c1w]))
             + ty * ((1 - tx) * float(z[r0 + 1, c0w]) + tx * float(z[r0 + 1, c1w])))
        return v * self.scale


def global_ldem_samples() -> None:
    files = fetch.fetch("terrain_sources.json")
    g = _PdsGrid(files["ldem_16.img"], files["ldem_16.lbl"])
    pts = [(s.lat_deg, s.lon_deg) for s in SITES.values()]
    pts += [(0.0, 0.0), (0.0, 359.99), (0.0, -0.01), (12.3, 180.0), (-45.0, -179.99), (89.96, 10.0),
            (-89.96, 250.0), (89.99, 10.0), (-89.99, 10.0)]
    rng = np.random.default_rng(20261031)                 # sampling locations only; heights come from LOLA
    pts += [(float(a), float(b)) for a, b in zip(rng.uniform(-89.9, 89.9, 200), rng.uniform(-180, 360, 200))]
    samples = [{"lat_deg": a, "lon_deg": b, "height_m": g.height(a, b)} for a, b in pts]
    write_fixture(ORACLE_FIXTURES, "global_ldem_samples", "oracle/build_fixtures.py::global_ldem_samples "
                  "(numpy over the PDS IMG, label-driven bilinear, longitude wrap, no answer in the polar caps)",
                  [".cache/terrain/ldem_16.img", ".cache/terrain/ldem_16.lbl",
                   "crates/stewie-contracts/fixtures/sites.json"], {"samples": samples})


STACK_STEP_M = 50.0


def horizon_stacked() -> None:
    from pyproj import Transformer

    files = fetch.fetch("terrain_sources.json")
    g = _PdsGrid(files["ldem_16.img"], files["ldem_16.lbl"])
    radius = float(json.load(open(os.path.join(REPO, "crates", "stewie-contracts", "fixtures", "bodies.json"),
                                  encoding="utf-8"))["moon"]["ellipsoid_radius_m"])
    name = "haworth_10km_5m"
    bundle_dir = os.path.join(REPO, "samples", "lunar_dem", name)
    meta = json.load(open(os.path.join(bundle_dir, "metadata.json"), encoding="utf-8"))
    z, cell = site_dem.load_haworth_dem(bundle_dir)
    b, gr = meta["world_bounds_m"], meta["grid"]
    crs = site_dem.bundle_crs(bundle_dir)
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    row, col = gr["height"] // 2, gr["width"] // 2
    lon0, lat0 = inv.transform(b["x0"] + cell * (col + 0.5), b["y1"] - cell * (row + 0.5))
    h_obs = float(z[row, col]) + HORIZON_EYE_M
    steps = np.arange(1, int(HORIZON_MAX_RANGE_M / STACK_STEP_M) + 1) * STACK_STEP_M
    delta = steps / radius
    phi1, lam1 = np.radians(lat0), np.radians(lon0)
    elev, reach, from_global = [], [], 0
    for k in range(HORIZON_N_AZ):
        az = np.radians(360.0 * k / HORIZON_N_AZ)
        phi2 = np.arcsin(np.sin(phi1) * np.cos(delta) + np.cos(phi1) * np.sin(delta) * np.cos(az))
        lam2 = lam1 + np.arctan2(np.sin(az) * np.sin(delta) * np.cos(phi1),
                                 np.cos(delta) - np.sin(phi1) * np.sin(phi2))
        lat2, lon2 = np.degrees(phi2), np.degrees(lam2)
        e, n = fwd.transform(lon2, lat2)
        ht = _bilinear(z, (np.asarray(e) - (b["x0"] + cell / 2)) / cell, ((b["y1"] - cell / 2) - np.asarray(n)) / cell)
        for i in np.nonzero(np.isnan(ht))[0]:
            v = g.height(float(lat2[i]), float(lon2[i]))
            ht[i] = np.nan if v is None else v
            from_global += v is not None
        covered = ~np.isnan(ht)
        stop = int(np.argmin(covered)) if not covered.all() else len(steps)
        rt = radius + ht[:stop]
        ang = np.arctan2(rt * np.cos(delta[:stop]) - (radius + h_obs), rt * np.sin(delta[:stop]))
        elev.append(float(np.degrees(ang.max())) if stop else None)
        reach.append(float(steps[stop - 1]) if stop else 0.0)
    write_fixture(ORACLE_FIXTURES, "horizon_stacked", "oracle/build_fixtures.py::horizon_stacked "
                  "(tile then LDEM_16 per sample; spherical rays; 50 m step; 200 km)",
                  [f"samples/lunar_dem/{name}/metadata.json", f"samples/lunar_dem/{name}/heightmap.rf32",
                   ".cache/terrain/ldem_16.img", ".cache/terrain/ldem_16.lbl",
                   "crates/stewie-contracts/fixtures/bodies.json"],
                  {"tile": name, "lat_deg": float(lat0), "lon_deg": float(lon0), "eye_m": HORIZON_EYE_M,
                   "ground_m": float(z[row, col]), "step_m": STACK_STEP_M, "n_az": HORIZON_N_AZ,
                   "max_range_m": HORIZON_MAX_RANGE_M, "samples_from_global": int(from_global),
                   "elev_deg": elev, "reach_m": reach})


def main() -> None:
    export_registries.main()
    dem_samples()
    ephem_topocentric()
    horizon_profiles()
    visibility_windows()
    global_ldem_samples()
    horizon_stacked()


if __name__ == "__main__":
    main()
