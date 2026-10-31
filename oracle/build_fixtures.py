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
  polar_ldem_samples PDS LOLA LDEM_85S_40M, LDEM_75S_240M and LDEM_75N_240M (polar stereographic, label-driven,
                     pyproj on the label's sphere): bilinear heights at every catalog site, at the pole and at
                     200 random points (mirrored for the north cap), None outside the grid.
  pgda_avgvisib      PGDA product 69 AVGVISIB_85S_060M (average solar visibility, hourly over 18.6 years) at
                     the pixel nearest each catalog site inside the map: value, 3x3 range, pixel-centre
                     lat/lon. The validation protocol for RW-61 (R5) rides along in the payload.
  terramechanics_cases
                     stewie_forge terramechanics/bearing and stewie.physics slip over a fixed input grid
                     (synthetic inputs, labelled; the implementation is the real one), with the parameter set
                     params_for_body gives each body, including the microgravity refusal.
  column_ops         stewie.physics ColumnState from a real 32x32 crop of the Haworth bundle through a fixed
                     sequence (flatten, dump, deposit, cut, fill, sinter): every return, the total mass after
                     each step, the final fields and the loose mask; plus set_height_via_mass on a copy.
  sandpile_runs      stewie.physics.sandpile on the same real crop: a large pile deposited and relaxed to rest
                     under four configurations (8/4-connected, cohesion steepening, a sintered floor as
                     receiver); steps, snapshot count, a mid snapshot and the final fields. A fifth run on a SYNTHETIC
                     flat layer (labelled) reaches rest, which the real crop never does (D-R52).
  excavation_cases   stewie.physics.excavation (McKyes/Reece FEE: N-factors, least-draft rupture angle,
                     specific energy) and stewie.physics.material (cell strength and the per-cell record)
                     over a fixed input grid (synthetic inputs, labelled; the implementation is the real one).
  rover_ops          stewie.physics.rover on a SYNTHETIC uniform 64x64 grid at 5 cm with a spoil patch
                     (labelled; wheel-scale ruts have no real fine grid here): step_pose arcs, four-wheel
                     passes (constant and physical with slip), a single rut, a drum cut with dump,
                     straight_path edge cases and the yaw wrap.
  conform_cases      stewie.physics.rover.conform_pose on the REAL Haworth crop heights (5 m cells): rest
                     plane, pitch/roll, contacts and per-wheel normal loads at several poses and payloads,
                     with and without SYNTHETIC rocks (labelled) under a wheel, one past the climb limit.
  drive_runs         stewie.physics.drive.drive_step loops: a plain drive on the REAL Haworth crop; a SYNTHETIC
                     5 cm ramp steepening to 40 deg (material, skid-steer, a dig reaction) driven to
                     entrapment; a SYNTHETIC flat grid with rocks (labelled). Per-step telemetry, final fields;
                     plus stability() over a tilt grid with NaN and a CG offset.
  world_log_cases    stewie.twin.envelope.TransactionLog: SYNTHETIC commits (labelled) with awkward floats,
                     nested beliefs, linked/unlinked packet+vehicle ids and escape-heavy provenance; the
                     exact journal bytes Python writes; plus Python float repr over the exponent range.
  twin_store_cases   stewie.twin.versioned.TwinStore over the REAL Haworth crop heights: a real unchanged
                     resync, SYNTHETIC offset and integral patches (labelled), an edge patch and undos;
                     the journal bytes, current map, observed mask and identity.
  route_cases        lode.planner_routing on a REAL 160x160 Haworth crop (5 m): legs under 25 and 12 deg
                     caps, circle/rect/polygon keep-outs, SYNTHETIC illumination and map-uncertainty layers
                     (labelled), an off-DEM endpoint and a keep-out wall that forces window widening; plus
                     one full costmap with every term.
  route_extras       lode.planner_routing on the same real window: footprint-inflated legs, haul elevation
                     gain and cumulative ascent (with off-grid points), outward-spiral coverage routes and
                     their terrain feasibility.
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


class _PdsPolar:
    """LOLA polar-stereographic IMG (an LDEM or an illumination map), label-driven, independent of the Rust
    reader: pixel centre (l, s) at ((s - S0) * scale, (L0 - l) * scale), projected by pyproj."""

    def __init__(self, img: str, lbl: str):
        from pyproj import Transformer

        lab = _pds_label(lbl)
        self.lines, self.samples = int(lab["LINES"]), int(lab["LINE_SAMPLES"])
        self.scale, self.cell = float(lab["SCALING_FACTOR"]), float(lab["MAP_SCALE"])
        self.l0, self.s0 = float(lab["LINE_PROJECTION_OFFSET"]), float(lab["SAMPLE_PROJECTION_OFFSET"])
        r = float(lab["A_AXIS_RADIUS"]) * 1000.0
        stere = f"+proj=stere +lat_0={float(lab['CENTER_LATITUDE'])} +lon_0={float(lab['CENTER_LONGITUDE'])} +k=1 +R={r}"
        geo = f"+proj=longlat +R={r} +no_defs"
        self.fwd = Transformer.from_crs(geo, stere, always_xy=True)
        self.inv = Transformer.from_crs(stere, geo, always_xy=True)
        self.dn = np.fromfile(img, dtype="<i2").reshape(self.lines, self.samples)

    def pixel(self, lat: float, lon: float) -> tuple[float, float]:
        e, n = self.fwd.transform(lon, lat)
        return self.l0 - n / self.cell, self.s0 + e / self.cell

    def height(self, lat: float, lon: float):
        row, col = self.pixel(lat, lon)
        if not (0.0 <= row <= self.lines - 1 and 0.0 <= col <= self.samples - 1):
            return None
        r0, c0 = min(int(math.floor(row)), self.lines - 2), min(int(math.floor(col)), self.samples - 2)
        ty, tx = row - r0, col - c0
        z = self.dn
        v = ((1 - ty) * ((1 - tx) * float(z[r0, c0]) + tx * float(z[r0, c0 + 1]))
             + ty * ((1 - tx) * float(z[r0 + 1, c0]) + tx * float(z[r0 + 1, c0 + 1])))
        return v * self.scale

    def centre_latlon(self, row: int, col: int) -> tuple[float, float]:
        lon, lat = self.inv.transform((col - self.s0) * self.cell, (self.l0 - row) * self.cell)
        return float(lat), float(lon)


def polar_ldem_samples() -> None:
    files = fetch.fetch("terrain_sources.json")
    south = [(s.lat_deg, s.lon_deg) for s in SITES.values()]
    south += [(-90.0, 0.0), (-89.9999, 123.0), (-85.0, 45.0), (-84.0, 0.0), (-75.0, 45.0), (-60.0, 10.0)]
    rng = np.random.default_rng(20261031)                 # sampling locations only; heights come from LOLA
    south += [(float(a), float(b)) for a, b in zip(rng.uniform(-90.0, -74.0, 200), rng.uniform(-180, 360, 200))]
    north = [(-a, b) for a, b in south]                   # the same pattern mirrored onto the north cap
    grids = {}
    for name, pts in (("ldem_85s_40m", south), ("ldem_75s_240m", south), ("ldem_75n_240m", north)):
        g = _PdsPolar(files[f"{name}.img"], files[f"{name}.lbl"])
        grids[name] = [{"lat_deg": a, "lon_deg": b, "height_m": g.height(a, b)} for a, b in pts]
    write_fixture(ORACLE_FIXTURES, "polar_ldem_samples", "oracle/build_fixtures.py::polar_ldem_samples "
                  "(numpy over the PDS IMG, label-driven pixel registration, pyproj polar stereographic on the "
                  "label sphere, bilinear, None outside the grid)",
                  [".cache/terrain/ldem_85s_40m.img", ".cache/terrain/ldem_85s_40m.lbl",
                   ".cache/terrain/ldem_75s_240m.img", ".cache/terrain/ldem_75s_240m.lbl",
                   ".cache/terrain/ldem_75n_240m.img", ".cache/terrain/ldem_75n_240m.lbl",
                   "crates/stewie-contracts/fixtures/sites.json"], {"grids": grids})


# RW-61 protocol (D-R43; start_m D-R74: horizon rays count terrain from one PGDA pixel out, since the 60 m product
# cannot resolve terrain inside its own pixel and a knife-edge crest otherwise shadows itself). Ten eclipse years (346.620075 d each) from 2026-01-01, inside the bundled ephemeris:
# the Sun's latitude cycle over the Moon closes, PGDA's 18.6-year span does not fit the 2026-2035 pack.
PGDA_PROTOCOL = {"start_utc": "2026-01-01T00:00:00Z", "span_days": 3466.20075, "step_s": 3600.0,
                 "n_az": 720, "max_range_m": 300_000.0, "step_m": 40.0, "eye_m": 0.0, "tolerance": 0.05, "start_m": 60.0}


def pgda_avgvisib() -> None:
    files = fetch.fetch("validation_products.json")
    g = _PdsPolar(files["avgvisib_85s_060m_201608.img"], files["avgvisib_85s_060m_201608.lbl"])
    sites, outside = [], []
    for name, s in sorted(SITES.items()):
        row, col = (round(v) for v in g.pixel(s.lat_deg, s.lon_deg))
        if not (1 <= row <= g.lines - 2 and 1 <= col <= g.samples - 2):
            outside.append(name)
            continue
        win = g.dn[row - 1:row + 2, col - 1:col + 2].astype(float) * g.scale
        lat, lon = g.centre_latlon(row, col)
        sites.append({"name": name, "catalog": {"lat_deg": s.lat_deg, "lon_deg": s.lon_deg},
                      "pixel": {"line": row, "sample": col, "lat_deg": lat, "lon_deg": lon},
                      "visibility": float(g.dn[row, col]) * g.scale,
                      "window_min": float(win.min()), "window_max": float(win.max())})
    write_fixture(ORACLE_FIXTURES, "pgda_avgvisib", "oracle/build_fixtures.py::pgda_avgvisib "
                  "(PGDA product 69 AVGVISIB_85S_060M_201608 IMG, DN * SCALING_FACTOR, nearest pixel to each "
                  "catalog site; pyproj polar stereographic on the label sphere)",
                  [".cache/validation/avgvisib_85s_060m_201608.img",
                   ".cache/validation/avgvisib_85s_060m_201608.lbl",
                   "crates/stewie-contracts/fixtures/sites.json"],
                  {"product": "AVGVISIB_85S_060M_201608", "protocol": PGDA_PROTOCOL,
                   "sites": sites, "outside_product": outside})


def terramechanics_cases() -> None:
    """Grid inputs are synthetic (labelled); every output is the Python implementation's."""
    from stewie.physics import body_params, slip as SL
    from stewie_forge import bearing as BR, terramechanics as TM

    bodies, refused = {}, []
    for name in ("moon", "mars", "earth", "ceres", "bp1_testbed", "bennu", "phobos"):
        try:
            prm = body_params.params_for_body(name)
            bodies[name] = {"params": prm.to_dict(), "analog": False}
        except ValueError:
            refused.append(name)
            bodies[name] = {"params": body_params.params_for_body(name, allow_analog=True).to_dict(),
                            "analog": True}
    cases: dict[str, list] = {k: [] for k in ("bekker", "contact", "density_factor", "slip_multiplier",
                                               "traction", "thrust", "slip_for_demand", "resistance",
                                               "equilibrium", "drive_power", "bearing")}
    for name in ("moon", "mars", "earth"):
        p = body_params.params_for_body(name)
        for pr in (0.0, 50.0, 500.0, 5000.0, 50000.0):
            for b in (0.04, 0.1, 0.18, 0.5):
                for st in (1.0, 1.3, 1.48):
                    cases["bekker"].append({"body": name, "pressure_pa": pr, "b_m": b, "stiffening": st,
                                            "z_m": TM.bekker_pressure_sinkage(pr, b_m=b, k_c=p.k_c, k_phi=p.k_phi,
                                                                             n=p.n_sinkage, stiffening=st)})
        for load in (0.0, 5.0, 12.15, 24.3, 100.0):
            for dens in (None, 1300.0, 1600.0, 1920.0):
                for cl, cw in ((0.10, 0.18), (0.04, 0.20)):
                    cases["contact"].append({"body": name, "load_n": load, "density": dens, "len_m": cl, "width_m": cw,
                                             "z_m": TM.wheel_static_sinkage(load, params=p, density=dens,
                                                                            contact_len_m=cl, contact_width_m=cw)})
        for sl in (-0.1, 0.0, 0.1, 0.5, 0.9, 0.95, 0.99):
            cases["slip_multiplier"].append({"body": name, "slip": sl,
                                             "m": TM.slip_sinkage_multiplier(sl, c1=p.slip_c1, c2=p.slip_c2)})
        for nl in (0.0, 12.15, 100.0):
            for area in (0.018, 0.008):
                h = SL.traction_budget(nl, cohesion=p.cohesion, phi_rad=p.phi_rad, contact_area_m2=area)
                cases["traction"].append({"body": name, "normal_n": nl, "area_m2": area, "h_max_n": h})
                if h <= 0.0:
                    continue
                for sl in (0.0, 1e-9, 0.01, 0.1, 0.5, 0.99):
                    cases["thrust"].append({"body": name, "slip": sl, "h_max_n": h, "len_m": 0.10,
                                            "h_n": SL.developed_thrust(sl, h, contact_len_m=0.10, k_shear=p.k_shear)})
                for frac in (0.0, 0.1, 0.5, 0.9, 0.999, 1.0, 1.2):
                    s_, ent = SL.slip_for_demand(frac * h, h, contact_len_m=0.10, k_shear=p.k_shear)
                    cases["slip_for_demand"].append({"body": name, "demand_n": frac * h, "h_max_n": h,
                                                     "len_m": 0.10, "slip": s_, "entrapped": ent})
        for z in (0.0, 0.001, 0.01, 0.05):
            for w in (0.18, 0.04):
                cases["resistance"].append({"body": name, "z_m": z, "width_m": w,
                                            "r_n": SL.compaction_resistance(z, contact_width_m=w, k_c=p.k_c,
                                                                            k_phi=p.k_phi, n=p.n_sinkage)})
        for wt in (30.0 * 1.62, 60.0 * 1.62, 30.0 * 9.81):
            for deg in (0, 5, 10, 15, 20, 25, 30, 35):
                for frac, extra, dens in ((1.0, 0.0, None), (0.5, 0.0, None), (1.0, 20.0, None), (1.0, 0.0, 1600.0)):
                    eq = SL.slip_sinkage_equilibrium(wt, math.radians(deg), n_wheels=4, contact_len_m=0.10,
                                                     contact_width_m=0.18, params=p, density=dens, demand_frac=frac,
                                                     extra_demand_n=extra, s_entrap=0.95, z_entrap_m=0.36)
                    cases["equilibrium"].append({"body": name, "weight_n": wt, "slope_deg": deg, "demand_frac": frac,
                                                 "extra_n": extra, "density": dens, **eq})
        for deg in (-10.0, 0.0, 10.0, 20.0):
            d = SL.bekker_drive_power_w(mass_kg=30.0, g_ms2=1.62, slope_deg=deg, v_ms=0.3, efficiency=0.5, params=p,
                                        n_wheels=4, contact_len_m=0.10, contact_width_m=0.18)
            cases["drive_power"].append({"body": name, "slope_deg": deg, **d})
    for z in (0.0, 0.001, 0.01, 0.05, 0.2):
        for t in (0.0, 0.05, 0.1, 0.3):
            cases["density_factor"].append({"z_m": z, "thickness_m": t, "f": TM.sinkage_to_density_factor(z, t)})
    for deg in (0.0, 10.0, 30.0, 35.0, 45.0):
        for c in (0.0, 170.0, 1000.0):
            for gam in (1300.0 * 1.62, 1600.0 * 9.81):
                for wb, dd in ((0.5, 0.0), (2.0, 0.3)):
                    phi = math.radians(deg)
                    cases["bearing"].append({"phi_deg": deg, "c_pa": c, "gamma_n_m3": gam, "width_m": wb, "depth_m": dd,
                                             "factors": list(BR.bearing_capacity_factors(phi)),
                                             "q_ult_pa": BR.ultimate_bearing_capacity_pa(c, phi, gam, wb, surcharge_depth_m=dd),
                                             "q_allow_pa": BR.allowable_bearing_pa(c, phi, gam, wb, surcharge_depth_m=dd)})
    write_fixture(ORACLE_FIXTURES, "terramechanics_cases", "oracle/build_fixtures.py::terramechanics_cases "
                  "(stewie_forge.terramechanics, stewie_forge.bearing, stewie.physics.slip, body_params; "
                  "synthetic input grid, labelled)",
                  ["packages/stewie-forge/stewie_forge/terramechanics.py", "packages/stewie-forge/stewie_forge/bearing.py",
                   "stewie/physics/slip.py", "stewie/physics/body_params.py", "crates/stewie-contracts/fixtures/bodies.json"],
                  {"bodies": bodies, "refused_without_analog": refused, "cases": cases})


COLUMN_CROP = (1000, 1032, 1000, 1032)


def column_ops() -> None:
    from stewie.physics.column_state import ColumnState
    from stewie.physics.worksite import coarse_base_from_bundle
    from stewie.specs import constants as K

    name = "haworth_10km_5m"
    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", name))
    r0, r1, c0, c1 = COLUMN_CROP
    crop = lambda a: np.array(a[r0:r1, c0:c1], dtype=np.float64)                    # noqa: E731
    cs = ColumnState(c1 - c0, r1 - r0, base.cell_m, mass_areal=crop(base.mass_areal), density=crop(base.density),
                     state_label=np.array(base.state_label[r0:r1, c0:c1], dtype=np.uint8),
                     disturbance=crop(base.disturbance), datum=crop(base.datum))
    initial = {"mass_areal": cs.mass_areal.ravel().tolist(), "density": cs.density.ravel().tolist(),
               "state_label": cs.state_label.ravel().tolist(), "disturbance": cs.disturbance.ravel().tolist(),
               "datum": cs.datum.ravel().tolist()}
    shape = cs.mass_areal.shape

    def rect(a, b, c, d):
        m = np.zeros(shape, dtype=bool)
        m[a:b, c:d] = True
        return m

    steps = []
    h = cs.derive_height()
    a = rect(4, 16, 4, 16)
    target = float(h[a].min()) + 0.05
    moved, hi = __import__("stewie.physics.worksite", fromlist=["flatten_to_level"]).flatten_to_level(cs, a, target)
    steps.append({"op": "flatten", "rect": [4, 16, 4, 16], "target_m": target, "ret": moved,
                  "cut_cells": int(hi.sum()), "total_kg": cs.total_mass()})
    half = 0.5 * cs.drum_inventory
    steps.append({"op": "dump", "rect": [18, 26, 4, 12], "kg": half, "spoil": K.RHO_SPOIL,
                  "ret": cs.dump_from_inventory(rect(18, 26, 4, 12), half, K.RHO_SPOIL), "total_kg": cs.total_mass()})
    steps.append({"op": "deposit", "rect": [2, 30, 20, 30], "kg_m2": 10.0, "spoil": K.RHO_SPOIL,
                  "ret": cs.deposit_field(rect(2, 30, 20, 30), 10.0, K.RHO_SPOIL), "total_kg": cs.total_mass()})
    steps.append({"op": "cut", "rect": [20, 32, 14, 22], "kg_m2": 50.0,
                  "ret": cs.cut_to_inventory(rect(20, 32, 14, 22), 50.0), "total_kg": cs.total_mass()})
    e = rect(0, 8, 24, 32)
    tgt = float(cs.derive_height()[e].max())
    steps.append({"op": "fill", "rect": [0, 8, 24, 32], "target_m": tgt, "max_lift_m": 0.02, "spoil": K.RHO_SPOIL,
                  "ret": cs.fill_toward(e, tgt, max_lift_m=0.02, spoil_density=K.RHO_SPOIL), "total_kg": cs.total_mass()})
    steps.append({"op": "sinter", "rect": [26, 30, 0, 4], "density": K.RHO_SINTERED,
                  "ret": cs.sinter(rect(26, 30, 0, 4), K.RHO_SINTERED), "total_kg": cs.total_mass()})
    final = {"mass_areal": cs.mass_areal.ravel().tolist(), "density": cs.density.ravel().tolist(),
             "state_label": cs.state_label.ravel().tolist(), "disturbance": cs.disturbance.ravel().tolist(),
             "height": cs.derive_height().ravel().tolist(), "drum_kg": cs.drum_inventory}
    from stewie.physics.column_state import loose_mask
    lifted = cs.derive_height() + 0.01
    cs.set_height_via_mass(lifted)
    write_fixture(ORACLE_FIXTURES, "column_ops", "oracle/build_fixtures.py::column_ops (stewie.physics.column_state "
                  "+ worksite.flatten_to_level on a real Haworth crop)",
                  [f"samples/lunar_dem/{name}/metadata.json", "stewie/physics/column_state.py", "stewie/physics/worksite.py",
                   "stewie/specs/constants.py"],
                  {"bundle": name, "crop": list(COLUMN_CROP), "width": c1 - c0, "height": r1 - r0,
                   "cell_m": float(base.cell_m), "initial": initial, "steps": steps, "final": final,
                   "loose": loose_mask(cs).ravel().tolist(),
                   "after_set_height_mass": cs.mass_areal.ravel().tolist()})


def _real_crop_state():
    from stewie.physics.column_state import ColumnState
    from stewie.physics.worksite import coarse_base_from_bundle

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, r1, c0, c1 = COLUMN_CROP
    crop = lambda a: np.array(a[r0:r1, c0:c1], dtype=np.float64)                    # noqa: E731
    return ColumnState(c1 - c0, r1 - r0, base.cell_m, mass_areal=crop(base.mass_areal), density=crop(base.density),
                       state_label=np.array(base.state_label[r0:r1, c0:c1], dtype=np.uint8),
                       disturbance=crop(base.disturbance), datum=crop(base.datum))


def sandpile_runs() -> None:
    from stewie.physics.sandpile import Sandpile
    from stewie.specs import constants as K

    from stewie.physics.column_state import ColumnState

    runs = []
    for name, conn, coh_deg, tf, floor in (("eight", 8, 0.0, 0.5, False), ("four", 4, 0.0, 0.5, False),
                                           ("cohesive", 8, 5.0, 0.8, False), ("sintered_floor", 8, 0.0, 0.5, True),
                                           ("flat_synthetic", 8, 0.0, 0.5, False)):
        # flat_synthetic is a SYNTHETIC uniform layer (labelled): rest on a floor with no bedrock relief. The real
        # crop's bedrock is steeper than repose; its runs rest because drained cells stop donating (D-R52/D-R72).
        cs = ColumnState(32, 32, 5.0) if name == "flat_synthetic" else _real_crop_state()
        if floor:
            ring = np.zeros(cs.mass_areal.shape, dtype=bool)
            ring[10:22, 10:22] = True
            ring[14:18, 14:18] = False
            cs.sinter(ring, K.RHO_SINTERED)
        sp = Sandpile(cs, np.deg2rad(35.0), connectivity=conn, cohesion_steepening=np.deg2rad(coh_deg),
                      transfer_fraction=tf)
        sp.deposit(16, 16, 3.0e6, radius_cells=1, spoil_density=K.RHO_SPOIL)
        before = cs.grid_mass()
        steps, snaps = sp.relax_to_rest(400, capture=True, capture_every=4)
        runs.append({"name": name, "connectivity": conn, "cohesion_deg": coh_deg, "transfer_fraction": tf,
                     "sintered_floor": floor, "steps": steps, "n_snapshots": len(snaps),
                     "mid_snapshot": snaps[len(snaps) // 2].ravel().tolist(), "grid_kg_after_deposit": before,
                     "grid_kg_final": cs.grid_mass(), "mass_areal": cs.mass_areal.ravel().tolist(),
                     "density": cs.density.ravel().tolist(), "height": cs.derive_height().ravel().tolist()})
    write_fixture(ORACLE_FIXTURES, "sandpile_runs", "oracle/build_fixtures.py::sandpile_runs "
                  "(stewie.physics.sandpile.Sandpile on the real Haworth crop of column_ops)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/physics/sandpile.py",
                   "stewie/physics/column_state.py", "stewie/specs/constants.py"],
                  {"crop": list(COLUMN_CROP), "deposit": {"r": 16, "c": 16, "kg": 3.0e6, "radius": 1,
                   "spoil": K.RHO_SPOIL}, "theta_deg": 35.0, "max_steps": 400, "capture_every": 4,
                   "eps_deg": 0.5, "runs": runs})


def excavation_cases() -> None:
    """Grid inputs are synthetic (labelled); every output is the Python implementation's."""
    import itertools

    from stewie.physics import excavation as EX, material as MT

    factors = []
    for phi_deg, beta_deg, rake_deg, delta_deg in itertools.product((20.0, 30.0, 37.0, 45.0),
                                                                  (0.5, 10.0, 30.0, 50.0, 60.0, 89.0, 95.0),
                                                                  (45.0, 30.0), (None, 10.0)):
        phi = math.radians(phi_deg)
        delta = None if delta_deg is None else math.radians(delta_deg)
        try:
            out = list(EX.earthmoving_factors(phi, math.radians(beta_deg), rake_rad=math.radians(rake_deg),
                                              soil_tool_friction_rad=delta))
        except ValueError:
            out = None
        factors.append({"phi_deg": phi_deg, "beta_deg": beta_deg, "rake_deg": rake_deg,
                        "delta_rad": EX.SOIL_TOOL_FRICTION_FRAC * phi if delta is None else delta, "n": out})
    reports = []
    for d, w, c, rho, g, phi_deg, q in itertools.product((0.02, 0.1), (0.2, 0.5), (0.0, 170.0, 1000.0), (1300.0, 1750.0),
                                                       (1.62, 9.81), (30.0, 37.0, 50.0), (0.0, 100.0)):
        phi = math.radians(phi_deg)
        r = EX.earthmoving_report(depth_m=d, width_m=w, cohesion_pa=c, bulk_density_kg_m3=rho, gravity_ms2=g,
                                  phi_rad=phi, surcharge_pa=q)
        reports.append({"depth_m": d, "width_m": w, "c_pa": c, "rho": rho, "g": g, "phi_deg": phi_deg, "q_pa": q,
                        "rake_rad": EX.RAKE_ANGLE_RAD, "delta_rad": EX.SOIL_TOOL_FRICTION_FRAC * phi,
                        **{k: r[k] for k in ("draft_n", "n_gamma", "n_c", "n_q", "beta_rad", "specific_energy_j_per_kg")}})
    dens = [1000.0, 1300.0, 1455.8333740234375, 1600.0, 1920.0, 2300.0]
    mf = MT.material_fields(np.array(dens), normal_load_n=200.0, contact_area_m2=0.05)
    material = {"phi_loose_deg": MT.PHI_LOOSE_DEG, "phi_dense_deg": MT.PHI_DENSE_DEG,
                "cohesion_loose_pa": MT.COHESION_LOOSE_PA, "cohesion_dense_pa": MT.COHESION_DENSE_PA,
                "rho_surface": float(MT.K.RHO_SURFACE), "rho_deep": float(MT.K.RHO_DEEP), "normal_load_n": 200.0,
                "contact_area_m2": 0.05, "density": dens,
                "strength": [list(MT.cell_strength(x)) for x in dens],
                **{k: np.asarray(v).tolist() for k, v in mf.items()}}
    write_fixture(ORACLE_FIXTURES, "excavation_cases", "oracle/build_fixtures.py::excavation_cases "
                  "(stewie.physics.excavation, stewie.physics.material; synthetic input grid, labelled)",
                  ["stewie/physics/excavation.py", "stewie/physics/material.py", "stewie/specs/constants.py"],
                  {"n_beta": 900, "factors": factors, "reports": reports, "material": material})


def rover_ops() -> None:
    """SYNTHETIC grid (labelled); every output is the Python implementation's."""
    from stewie.physics import rover as RV
    from stewie.physics.column_state import ColumnState, StateLabel
    from stewie_forge import terramechanics as TM

    cs = ColumnState(64, 64, 0.05)
    cs.state_label[14:28, 14:30] = StateLabel.SPOIL
    initial_labels = cs.state_label.ravel().tolist()
    poses, pose, yaw = [], (20.0, 10.0), 0.3
    for k in range(30):
        omega = (0.0, 0.2, -0.4)[k // 10]
        pose, yaw = RV.step_pose(pose, yaw, 0.3, omega, 0.1, cell_m=cs.cell_m)
        poses.append([list(pose), yaw])
    first = RV.four_wheel_pass(cs, [(tuple(p), h) for p, h in poses[:15]], wheel_width_m=0.18, compaction=0.12)
    load = TM.static_wheel_load_n(payload_kg=10.0)
    slip = {"LF": 0.2, "RF": 0.0, "LB": 0.0, "RB": 0.0}
    second = RV.four_wheel_pass(cs, [(tuple(p), h) for p, h in poses[15:]], wheel_width_m=0.18, physical=True,
                                payload_kg=10.0, slip=slip)
    path = RV.straight_path(5, 5, 40, 50)
    RV.wheel_pass(cs, path, wheel_width_m=0.18, compaction=0.12)
    swath = [(float(r), float(c)) for r, c in RV.straight_path(50, 5, 50, 40)]
    dump = [(float(r), float(c)) for r, c in RV.straight_path(58, 5, 58, 40)]
    total0 = cs.total_mass()
    moved = RV.drum_pass(cs, swath, depth_m=0.03, width_m=0.2, dump_rc=dump)
    paths = {f"{a},{b},{c},{d},{e}": RV.straight_path(a, b, c, d, e)
             for a, b, c, d, e in ((0, 0, 3, 1, 1), (0, 0, 5, 2, 1), (2, 7, 9, 1, 2), (0, 0, 1, 3, 4), (4, 4, 4, 4, 1),
                                    (0, 0, 1, 2, 1), (0, 0, 3, 6, 1))}
    wraps = [[y, w, list(RV.step_pose((0.0, 0.0), y, 0.3, w, 0.5, cell_m=0.05)[0]), RV.step_pose((0.0, 0.0), y, 0.3, w, 0.5, cell_m=0.05)[1]]
             for y, w in ((3.1, 0.5), (-3.1, -0.5), (0.0, 0.0), (1.0, 1e-10))]
    targets = [[m, ld, sl, float(TM.physical_compaction_target_density(np.array([m]), ld, contact_width_m=0.18,
                                                                        slip=sl)[0])]
               for m in (0.0, 5.0, 156.0, 400.0) for ld in (0.0, 12.15, 150.0, 300.0) for sl in (0.0, 0.3)]
    write_fixture(ORACLE_FIXTURES, "rover_ops", "oracle/build_fixtures.py::rover_ops (stewie.physics.rover on a "
                  "SYNTHETIC 64x64 5 cm grid, labelled)",
                  ["stewie/physics/rover.py", "packages/stewie-forge/stewie_forge/terramechanics.py"],
                  {"synthetic": True, "width": 64, "height": 64, "cell_m": 0.05, "initial_labels": initial_labels,
                   "gauge_m": RV.WHEEL_GAUGE_M, "wheelbase_m": RV.WHEEL_BASE_M, "wheel_width_m": 0.18,
                   "compaction": 0.12, "poses": poses, "first_lines": first, "second_lines": second,
                   "physical_load_n": load, "slip": [slip[k] for k in ("LF", "RF", "LB", "RB")], "contact_len_m": 0.10,
                   "path": path, "swath": swath, "dump": dump, "drum_depth_m": 0.03, "drum_width_m": 0.2,
                   "drum_moved_kg": moved, "total_kg_before_drum": total0, "total_kg_after_drum": cs.total_mass(),
                   "mass_areal": cs.mass_areal.ravel().tolist(), "density": cs.density.ravel().tolist(),
                   "state_label": cs.state_label.ravel().tolist(), "disturbance": cs.disturbance.ravel().tolist(),
                   "paths": paths, "wraps": wraps, "targets": targets})


def conform_cases() -> None:
    from stewie.physics import rover as RV
    from stewie.specs import constants as K

    hm = _real_crop_state().derive_height()
    cell = 5.0
    cases = []
    for center in ((10.3, 12.7), (16.0, 16.0), (0.2, 31.5), (25.5, 5.5)):
        for heading in (0.0, 0.7, -2.0, 3.14):
            for payload in (0.0, 30.0):
                for rocks in ("none", "shoulder", "tall"):
                    clasts = []
                    if rocks != "none":
                        lf = RV.wheel_contact_points(center, heading, cell_m=cell)["LF"]
                        x, z = lf[1] * cell, lf[0] * cell
                        dem = RV._bilinear_height(hm, lf[0], lf[1])
                        r = 0.25 if rocks == "shoulder" else 0.9
                        clasts = [{"center_m": [x + 0.05, dem - 0.1, z - 0.05], "radius_m": r}]   # SYNTHETIC rock
                    out = RV.conform_pose(hm, center, heading, cell_m=cell, clasts=clasts, payload_kg=payload)
                    cases.append({"center": list(center), "heading": heading, "payload_kg": payload, "clasts": clasts,
                                  **out})
    # SYNTHETIC tilts (labelled) past the ~33.7 deg lift-off pitch, so the clamp-and-renormalise branch runs
    reactions = []
    for pitch in (-60.0, -35.0, 0.0, 20.0, 50.0):
        for roll in (-55.0, 0.0, 40.0):
            for weight in (48.6, 97.2):
                pr, rr = math.radians(pitch), math.radians(roll)
                cos_t = 1.0 / math.sqrt(1.0 + math.tan(pr) ** 2 + math.tan(rr) ** 2)
                out = RV._wheel_normal_reactions(weight, cos_t, pr, rr, wheelbase_m=RV.WHEEL_BASE_M,
                                                 gauge_m=RV.WHEEL_GAUGE_M, cg_height_m=K.CG_HEIGHT_M)
                reactions.append({"weight_n": weight, "cos_tilt": cos_t, "pitch_rad": pr, "roll_rad": rr,
                                  "loads": [out[k] for k in ("LF", "RF", "LB", "RB")]})
    write_fixture(ORACLE_FIXTURES, "conform_cases", "oracle/build_fixtures.py::conform_cases "
                  "(stewie.physics.rover.conform_pose on the real Haworth crop; rocks SYNTHETIC, labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/physics/rover.py", "stewie/specs/constants.py"],
                  {"width": hm.shape[1], "height": hm.shape[0], "cell_m": cell, "heightmap": hm.ravel().tolist(),
                   "climb_limit_m": RV.WHEEL_RADIUS_M, "min_grad_cells": 2.5, "gauge_m": RV.WHEEL_GAUGE_M,
                   "wheelbase_m": RV.WHEEL_BASE_M, "cg_height_m": K.CG_HEIGHT_M, "mass_dry_kg": K.ROVER_MASS_DRY_KG,
                   "g": float(K.g), "cases": cases, "reactions": reactions})


def drive_runs() -> None:
    from stewie.physics import drive as DR, stability as ST
    from stewie.physics.column_state import ColumnState
    from stewie.specs import constants as K
    from stewie_forge.terramechanics import TerramechanicsParams

    def run(name, cs, rc, yaw, twists, *, material=False, skid=False, payload=0.0, clasts=None, dig=None):
        start_kg = cs.total_mass()
        steps = []
        for i, (v, w) in enumerate(twists):
            rc, yaw, t = DR.drive_step(cs, rc, yaw, v, w, dt=0.1, payload_kg=payload, material=material,
                                       clasts=clasts, skid_steer=skid,
                                       dig_reaction_n=(dig(i) if dig else 0.0))
            steps.append({k: t[k] for k in ("rc", "yaw", "v_achieved", "omega_achieved", "slip", "entrapped",
                                            "slope_rad", "sinkage_m", "contact_len_m")}
                         | ({k: t[k] for k in ("slip_left", "slip_right", "v_left_ach", "v_right_ach", "scrub_factor") if k in t}
                            if skid else {}))
        return {"name": name, "width": cs.width, "height": cs.height, "cell_m": cs.cell_m, "material": material,
                "skid": skid, "payload_kg": payload, "clasts": clasts or [], "twists": twists,
                "dig_reaction": [dig(i) if dig else 0.0 for i in range(len(twists))], "steps": steps,
                "total_kg_start": start_kg, "total_kg_end": cs.total_mass(),
                "mass_areal": cs.mass_areal.ravel().tolist(), "density": cs.density.ravel().tolist(),
                "state_label": cs.state_label.ravel().tolist()}

    runs = []
    real = _real_crop_state()
    runs.append({**run("real_crop", real, (16.0, 16.0), 0.4, [(0.3, (0.0, 0.3, -0.2)[i // 14]) for i in range(40)],
                       payload=5.0), "start": "real"})
    # SYNTHETIC ramp (labelled): slope rises linearly 0 -> 40 deg along +col
    W = H = 64
    cell = 0.05
    slope = np.radians(np.linspace(0.0, 40.0, W))
    prof = np.concatenate([[0.0], np.cumsum(np.tan(slope[:-1]) * cell)])
    ramp = ColumnState(W, H, cell, datum=np.tile(prof, (H, 1)))
    runs.append({**run("synthetic_ramp", ramp, (32.0, 4.0), 0.0, [(0.3, 0.1)] * 120, material=True, skid=True,
                       dig=lambda i: 3.0 if 10 <= i < 20 else 0.0), "start": "ramp", "ramp_profile": prof.tolist()})
    # SYNTHETIC gentle tilt (labelled), 2 deg along +col and 1 deg along +row: exactly flat ground puts the
    # slope at numpy-lstsq noise (~1e-16), where slip_for_demand's 1e-6 bisection floor makes slip jump from 0
    # to 1e-6 (D-R57); a real tilt keeps both implementations off that discontinuity.
    tilt = (np.arange(W)[None, :] * np.tan(np.radians(2.0)) + np.arange(H)[:, None] * np.tan(np.radians(1.0))) * cell
    tilted = ColumnState(W, H, cell, datum=tilt)
    rocks = [{"center_m": [1.2, 0.08, 1.6], "radius_m": 0.12}, {"center_m": [1.9, 0.1, 1.45], "radius_m": 0.2}]
    for rk in rocks:
        rk["center_m"][1] += float(np.interp(rk["center_m"][0] / cell, np.arange(W), tilt[int(rk["center_m"][2] / cell)]))
    runs.append({**run("synthetic_rocks", tilted, (32.0, 10.0), 0.05, [(0.3, -0.15)] * 60, skid=True, payload=20.0,
                       clasts=rocks), "start": "tilted", "tilt_datum": tilt.ravel().tolist()})
    stab = []
    for pitch in (0.0, 20.0, 30.0, 40.0, -45.0, float("nan")):
        for roll in (0.0, 25.0, -50.0):
            for dx in (0.0, 0.1):
                r = ST.stability(pitch, roll, gauge_m=0.57, wheelbase_m=0.40, cg_height_m=0.30, cg_dx_m=dx)
                # JSON has no NaN/Infinity: the fail-closed NaN case records its non-finite outputs as null
                r = {k: (v if not isinstance(v, float) or math.isfinite(v) else None) for k, v in r.items()}
                stab.append({"pitch_deg": None if pitch != pitch else pitch, "roll_deg": roll, "cg_dx_m": dx, **r})
    base = TerramechanicsParams.from_constants()
    write_fixture(ORACLE_FIXTURES, "drive_runs", "oracle/build_fixtures.py::drive_runs (stewie.physics.drive "
                  "and stability; real Haworth crop plus SYNTHETIC ramp/rock grids, labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/physics/drive.py",
                   "stewie/physics/stability.py", "stewie/physics/rover.py", "stewie/physics/slip.py"],
                  {"soil": base.to_dict(), "g": float(K.g), "mass_kg": K.ROVER_MASS_DRY_KG, "n_wheels": K.N_WHEELS,
                   "cg_height_m": K.CG_HEIGHT_M, "wheel_radius_m": 0.18, "wheel_width_m": 0.18, "contact_len_m": 0.10,
                   "track_m": 0.5207, "gauge_m": 0.57, "wheelbase_m": 0.40, "runs": runs, "stability": stab,
                   "tip_limit_deg": ST.tip_tilt_limit_deg(gauge_m=0.57, wheelbase_m=0.40, cg_height_m=0.30)})


def world_log_cases() -> None:
    """SYNTHETIC commit inputs (labelled); every byte of the journal is the Python implementation's."""
    import tempfile

    from stewie.twin.envelope import TransactionLog

    commits = [
        {"authority_sha": "genesis", "twin_version": 0, "twin_hash": "genesis", "plan_id": "none", "belief": {},
         "mission": "none", "site": "haworth", "body": "moon", "mission_t_s": 0.0, "provenance": "boot",
         "uncertainty_m": 0.0, "packet_sha": "", "vehicle_sha": ""},
        {"authority_sha": "a" * 64, "twin_version": 3, "twin_hash": "b" * 64, "plan_id": "plan-7",
         "belief": {"pose": [1.5, -2.25, 1e-05], "ok": True, "n": 12, "nested": {"z": None, "a": 1e16}},
         "mission": "m1", "site": "shackleton_rim", "body": "moon", "mission_t_s": 123456789.123,
         "provenance": 'quote " back \\ nl \n tab \t ctl \x01 del \x7f e\u0301 \u00e9 \U0001f319',
         "uncertainty_m": 0.05, "packet_sha": "c" * 64, "vehicle_sha": ""},
        {"authority_sha": "d" * 64, "twin_version": 4, "twin_hash": "e" * 64, "plan_id": "plan-8",
         "belief": {"k": 0.1, "big": 1e15, "tiny": 0.0001, "neg": -0.0, "sub": 5e-324}, "mission": "m1",
         "site": "haworth", "body": "moon", "mission_t_s": 1e-07, "provenance": "resync",
         "uncertainty_m": 2.5, "packet_sha": "", "vehicle_sha": "f" * 64},
    ]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "world.journal")
        log = TransactionLog(journal_path=path)
        for c in commits:
            log.commit_snapshot(**c)
        journal = open(path, "rb").read().decode("utf-8")
    floats = [0.0, -0.0, 1.0, 0.1, 0.0001, 1e-05, 0.00012345, 1e15, 1e16, 1.5e16, 123456789.123, 5e-324,
              2.2250738585072014e-308, 1.7976931348623157e308, -1e-100, 3.141592653589793, 1e22, 9007199254740993.0,
              100.0, 1e-04 * 3, 2.0 ** 60]
    write_fixture(ORACLE_FIXTURES, "world_log_cases", "oracle/build_fixtures.py::world_log_cases "
                  "(stewie.twin.envelope.TransactionLog; SYNTHETIC commit inputs, labelled)",
                  ["stewie/twin/envelope.py", "stewie/twin/journal_io.py"],
                  {"synthetic": True, "commits": commits, "journal": journal,
                   "chain": [t.chain_hash for t in log.transactions],
                   "floats": [[x, repr(x)] for x in floats]})


def twin_store_cases() -> None:
    import tempfile

    from stewie.twin.versioned import TwinStore

    base = _real_crop_state().derive_height()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "twin.journal")
        tw = TwinStore(base, cell_m=5.0, journal_path=path)
        tw.apply_patch(base[4:10, 6:14], origin_rc=(4, 6), provenance="resync: unchanged real crop (not sensor evidence)")
        tw.apply_patch(base[12:15, 20:25] + 0.25, origin_rc=(12, 20), provenance="SYNTHETIC +0.25 m offset (labelled)")
        tw.undo()
        tw.apply_patch(np.full((2, 3), 1700.0), origin_rc=(0, 0), provenance="SYNTHETIC integral heights \u00e9")
        tw.apply_patch(base[29:32, 28:32] - 0.5, origin_rc=(29, 28), provenance="SYNTHETIC edge patch")
        tw.undo()
        tw.undo()
        journal = open(path, "rb").read().decode("utf-8")
        ver, ident = tw.identity()
        errors = {}
        for name, fn in (("out_of_bounds", lambda: tw.apply_patch(np.zeros((3, 3)), origin_rc=(30, 30), provenance="x")),
                         ("empty_provenance", lambda: tw.apply_patch(np.zeros((1, 1)), origin_rc=(0, 0), provenance="  ")),
                         ("nothing_to_undo", lambda: TwinStore(base, cell_m=5.0).undo())):
            try:
                fn()
                errors[name] = None
            except ValueError as e:
                errors[name] = str(e)
    write_fixture(ORACLE_FIXTURES, "twin_store_cases", "oracle/build_fixtures.py::twin_store_cases "
                  "(stewie.twin.versioned.TwinStore on the real Haworth crop; SYNTHETIC patches labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/twin/versioned.py",
                   "stewie/twin/journal_io.py"],
                  {"rows": int(base.shape[0]), "cols": int(base.shape[1]), "cell_m": 5.0, "base": base.ravel().tolist(),
                   "journal": journal, "version": ver, "identity_hash": ident, "verify": tw.verify_chain(),
                   "current": tw.current().ravel().tolist(), "observed": tw.observed_mask().ravel().tolist(),
                   "errors": errors})


ROUTE_WINDOW = (1000, 600, 100)   # real Haworth rows, cols, size: 85% passable incl. drop-offs, hazards to avoid


def route_layers(H: int, W: int) -> dict:
    """SYNTHETIC cost layers (labelled), integer-modulo formulas so the Rust test regenerates them exactly."""
    yy, xx = np.mgrid[0:H, 0:W]
    return {"illum_total": ((xx + 2 * yy) % 17) / 17.0, "shadow_hazard": (xx % 7) / 7.0, "saturation": (yy % 5) / 5.0,
            "map_uncertainty": ((xx * yy) % 11) / 11.0, "visibility": ((xx + yy) % 3) / 3.0,
            "map_unc": ((3 * xx + 5 * yy) % 13) / 13.0}


def route_cases() -> None:
    from scipy import ndimage

    from lode import planner_routing as PR
    from stewie.physics.worksite import coarse_base_from_bundle

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    cell, origin = 5.0, (100.0, 50.0)
    H, W = Z.shape
    L = route_layers(H, W)
    weights = {"shadow": 2.0, "saturation": 0.5, "visibility": 1.5}
    illum_terms = {k: L[k] for k in ("shadow_hazard", "saturation", "map_uncertainty", "visibility")} | {"weights": weights}
    _, passable = PR.slope_costmap(Z, cell, max_drop_m=PR.MAX_DROP_M)
    lab, _ = ndimage.label(passable, structure=np.ones((3, 3)))
    main = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
    rr, cc = np.nonzero(main)

    def site(fr, fc):        # the main-component cell nearest a fixed fraction of the window, as local (x, y)
        k = int(np.argmin((rr - fr * H) ** 2 + (cc - fc * W) ** 2))
        return (float(cc[k] * cell - origin[0] + 2.5), float(rr[k] * cell - origin[1] + 2.5))

    A, B, C, D = site(0.1, 0.1), site(0.9, 0.85), site(0.15, 0.9), site(0.85, 0.15)
    legs = []

    def leg(name, a, b, **kw):
        r = PR.route_leg((Z, cell), origin, a, b, return_terms=True, **kw)
        legs.append({"name": name, "a": list(a), "b": list(b),
                     "max_slope_deg": kw.get("max_slope_deg", 25.0), "margin_m": kw.get("margin_m", 20.0),
                     "keepouts": list(kw.get("keepouts", ())), "illum": kw.get("illum_cost") is not None,
                     "illum_terms": isinstance(kw.get("illum_cost"), dict), "map_unc": kw.get("map_unc_cost") is not None,
                     "illum_weight": kw.get("illum_weight", 1.0), "map_unc_weight": kw.get("map_unc_weight", 1.0),
                     "routed_m": r[0], "grid_straight_m": r[1], "reached": r[2],
                     "waypoints": [list(p) for p in r[3]], "breakdown": r[4]})

    leg("diag", A, B)
    leg("cross", C, D)
    leg("cap12", A, B, max_slope_deg=12.0)
    wp = legs[0]["waypoints"]
    mid = tuple(wp[len(wp) // 2])        # keep-outs sit ON the plain route, so each one must move it
    leg("circle", A, B, keepouts=[{"x": mid[0], "y": mid[1], "r": 40.0}])
    leg("rect", A, B, keepouts=[{"x0": mid[0] - 30, "y0": mid[1] - 60, "x1": mid[0] + 30, "y1": mid[1] + 60}])
    leg("poly", A, B, keepouts=[{"points": [[mid[0] - 50, mid[1] - 10], [mid[0] + 20, mid[1] - 70],
                                             [mid[0] + 60, mid[1] + 20], [mid[0] - 10, mid[1] + 50]]}])
    leg("wall", A, B, margin_m=2.0, keepouts=[{"x0": A[0] - 200, "y0": mid[1] - 5, "x1": B[0] + 10, "y1": mid[1] + 5}])
    leg("illum_total", A, B, illum_cost=L["illum_total"], illum_weight=3.0)
    leg("illum_terms", C, D, illum_cost=illum_terms, illum_weight=2.0, map_unc_cost=L["map_unc"], map_unc_weight=4.0)
    leg("off_dem", A, (5000.0, 40.0))
    k = 40
    cost, passable_k, terms = PR.slope_costmap(Z[:k, :k], cell, max_drop_m=PR.MAX_DROP_M,
                                               illum={kk: (v[:k, :k] if kk != "weights" else v) for kk, v in illum_terms.items()},
                                               illum_weight=2.0, map_unc=L["map_unc"][:k, :k], map_unc_weight=4.0,
                                               return_terms=True)
    write_fixture(ORACLE_FIXTURES, "route_cases", "oracle/build_fixtures.py::route_cases (lode.planner_routing on a "
                  "real Haworth window; cost layers SYNTHETIC integer formulas, labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "lode/planner_routing.py", "stewie/terrain/site_dem.py"],
                  {"window": list(ROUTE_WINDOW), "width": W, "height": H, "cell_m": cell, "origin": list(origin),
                   "z": Z.ravel().tolist(), "weights": weights, "max_drop_m": PR.MAX_DROP_M, "legs": legs,
                   "costmap": {"size": k, "cost": cost.ravel().tolist(), "passable": passable_k.ravel().tolist(),
                               "terms": {kk: v.ravel().tolist() for kk, v in terms.items()}}})


def route_extras() -> None:
    from lode import planner_routing as PR
    from stewie.physics.worksite import coarse_base_from_bundle

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    cell, origin = 5.0, (100.0, 50.0)
    legs_fx = json.load(open(os.path.join(ORACLE_FIXTURES, "route_cases.payload.json"), encoding="utf-8"))["legs"]
    A, B = tuple(legs_fx[0]["a"]), tuple(legs_fx[0]["b"])
    C, D = tuple(legs_fx[1]["a"]), tuple(legs_fx[1]["b"])
    inflated = []
    r6 = PR.route_leg_inflated((Z, cell), origin, A, B, footprint_radius_m=6.0)[3]
    mx, my = r6[len(r6) // 2]           # the keep-out sits ON the inflated route, so it must move it
    for name, a, b, rad, keep in (("r0", A, B, 0.0, []), ("r6", A, B, 6.0, []), ("r15", A, B, 15.0, []),
                                  ("r10_cross", C, D, 10.0, []),
                                  ("r6_rect", A, B, 6.0, [{"x0": mx - 25.0, "y0": my - 25.0, "x1": mx + 25.0, "y1": my + 25.0}])):
        r = PR.route_leg_inflated((Z, cell), origin, a, b, footprint_radius_m=rad, keepouts=keep)
        inflated.append({"name": name, "a": list(a), "b": list(b), "radius_m": rad, "keepouts": keep, "routed_m": r[0],
                         "grid_straight_m": r[1], "reached": r[2], "waypoints": [list(p) for p in r[3]]})
    diag = [tuple(p) for p in legs_fx[0]["waypoints"]]
    gains = [{"a": list(a), "b": list(b), "gain": PR.haul_elevation_gain_m((Z, cell), origin, a, b)}
             for a, b in ((A, B), (B, A), (C, D), (A, (5000.0, 0.0)))]
    ascents = [{"waypoints": [list(p) for p in w], "ascent": PR.haul_cumulative_ascent_m((Z, cell), origin, w)}
               for w in (diag, diag[::-1], [(-500.0, -500.0)] + diag[:20] + [(9000.0, 9000.0)])]
    spirals = []
    for bbox, swath, spacing, close in (((0.0, 0.0, 40.0, 40.0), 5.0, None, True), ((10.0, 20.0, 110.0, 50.0), 7.0, 3.0, True),
                                        ((0.0, 0.0, 30.0, 12.0), 5.0, None, False), ((150.0, 120.0, 260.0, 230.0), 12.5, None, True)):
        route = PR.coverage_spiral_route(bbox, swath_m=swath, spacing_m=spacing, close_loops=close)
        frac, flags = PR.coverage_route_feasible(route, (Z, cell), origin)
        spirals.append({"bbox": list(bbox), "swath_m": swath, "spacing_m": spacing, "close_loops": close,
                        "route": [list(p) for p in route], "feasible_frac": frac, "flags": flags})
    write_fixture(ORACLE_FIXTURES, "route_extras", "oracle/build_fixtures.py::route_extras (lode.planner_routing "
                  "inflated legs, haul gains, coverage spirals on the real route_cases window)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "lode/planner_routing.py"],
                  {"window": list(ROUTE_WINDOW), "cell_m": cell, "origin": list(origin), "inflated": inflated,
                   "gains": gains, "ascents": ascents, "spirals": spirals})


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
    polar_ldem_samples()
    pgda_avgvisib()
    terramechanics_cases()
    column_ops()
    sandpile_runs()
    excavation_cases()
    rover_ops()
    conform_cases()
    drive_runs()
    world_log_cases()
    twin_store_cases()
    route_cases()
    route_extras()


if __name__ == "__main__":
    main()
