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


def _ws_window(ws) -> dict:
    """A WorkSite's worked window, ledger and paging state (worksite oracles)."""
    f = ws.fine
    return {"origin": list(ws.window_world_origin), "region": list(ws.window_region_rc),
            "width": f.width, "height": f.height,
            **{n: getattr(f, n).ravel().tolist() for n in ("mass_areal", "density", "datum", "state_label",
                                                            "disturbance")},
            "inventory_kg": ws.inventory_kg, "peak_inventory_kg": ws.peak_inventory_kg,
            "cut_total_kg": ws.cut_total_kg, "placed_total_kg": ws.placed_total_kg,
            "total_mass": ws.total_mass(), "residual": ws.conservation_residual(),
            "recenters": ws.recenters,
            "store": sorted([[t[0], t[1], float(np.asarray(v["mass_areal"]).sum())]
                             for t, v in ws.worked_store.items()])}


def _ws_tick(ws, v, w) -> dict:
    """One WorkSite.step and the telemetry the worksite oracles keep."""
    t, dirty = ws.step(v, w, 0.1)
    return {k: t[k] for k in ("v_achieved", "omega_achieved", "slip", "entrapped", "sinkage_m",
                              "bounds_clamped", "recentered", "pose_xy")} | {"yaw": ws.yaw, "dirty": dirty}


def worksite_native() -> None:
    """WorkSite on the real Haworth 5 m bundle at its native cell (fine_cell_m=None, k=1): the streaming path
    (recenter, per-tick step, flatten, page out, dump, relax, page back, edge clamp) and the single-window path
    (open_window, drive, flatten, dump, relax). No clasts (D-R54: the Python climb radius differs)."""
    import math

    from stewie.physics.worksite import WorkSite
    from stewie.specs import constants as K
    from stewie_forge.terramechanics import TerramechanicsParams

    bundle = os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m")
    window, tick = _ws_window, _ws_tick

    ws = WorkSite.from_haworth_bundle(bundle, fine_cell_m=None)
    assert ws.k == 1 and not ws.smooth_datum
    start = ws.base_rc_to_xy((1000.0, 1000.0))
    far = ws.base_rc_to_xy((1000.0, 1012.0))
    ckpt, ticks = {}, []
    ws.recenter(start)
    ckpt["first"] = window(ws)
    ticks += [tick(ws, 0.25, 0.05) for _ in range(12)]
    h = ws.fine.derive_height()
    cut = np.zeros(h.shape, dtype=bool)
    cut[4:8, 4:8] = True
    cut_target = float(np.median(h[cut]))
    moved = ws.flatten(cut, cut_target)
    ckpt["flattened"] = window(ws)
    ws.recenter(far)
    ckpt["paged_out"] = window(ws)
    spot = np.zeros(ws.fine.derive_height().shape, dtype=bool)
    spot[5:7, 5:7] = True
    placed = ws.dump(spot, kg=0.5 * ws.inventory_kg)
    relax_steps, _ = ws.relax(max_steps=400, theta_r=K.THETA_R, transfer_fraction=0.6)
    ckpt["dumped"] = window(ws)
    ws.recenter(start)
    ckpt["returned"] = window(ws)
    virgin = ws.window_virgin_height().ravel().tolist()
    diff = ws.diff_field().ravel().tolist()
    edge_y = ws.base_rc_to_xy((1000.0, 0.0))[1]
    ws.set_pose((ws.world_x0 + 0.05, edge_y), yaw=math.pi)
    edge = [tick(ws, 0.25, 0.0) for _ in range(2)]
    ckpt["edge"] = window(ws)
    assert moved > 0 and placed > 0 and ws.recenters >= 4 and ws.worked_store
    assert edge[-1]["bounds_clamped"] and relax_steps < 400
    assert ckpt["dumped"]["residual"] < 1e-6 * ckpt["dumped"]["total_mass"]

    one = WorkSite.from_haworth_bundle(bundle, fine_cell_m=None)
    one.open_window((1000.0, 1000.0))
    twists = [(0.2, 0.0)] * 10
    drove = one.drive(twists, start_rc=(2.0, 2.0))
    oh = one.fine.derive_height()
    all_cells = np.ones(oh.shape, dtype=bool)
    one_target = float(oh.mean())
    one_moved = one.flatten(all_cells, one_target)
    corner = np.zeros(oh.shape, dtype=bool)
    corner[0, 0] = True
    one_placed = one.dump(corner)
    one_steps, _ = one.relax(max_steps=400, theta_r=K.THETA_R, transfer_fraction=0.6)
    single = window(one)
    assert one_moved > 0 and one_placed > 0
    write_fixture(ORACLE_FIXTURES, "worksite_native", "oracle/build_fixtures.py::worksite_native "
                  "(stewie.physics.worksite.WorkSite on the real Haworth 5 m bundle, fine_cell_m=None)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/physics/worksite.py",
                   "stewie/physics/drive.py", "stewie/physics/rover.py", "stewie/physics/sandpile.py",
                   "stewie/physics/column_state.py", "stewie/terrain/tiles_mosaic.py"],
                  {"bundle": "samples/lunar_dem/haworth_10km_5m", "tile_base_cells": ws.tile_base_cells,
                   "soil": TerramechanicsParams.from_constants().to_dict(), "g": float(K.g),
                   "mass_kg": K.ROVER_MASS_DRY_KG, "n_wheels": K.N_WHEELS, "cg_height_m": K.CG_HEIGHT_M,
                   "wheel_radius_m": 0.18, "wheel_width_m": 0.18, "contact_len_m": 0.10, "track_m": 0.5207,
                   "gauge_m": 0.57, "wheelbase_m": 0.40,
                   "v_max": ws.v_max, "omega_max": ws.omega_max, "theta_r": float(K.THETA_R),
                   "transfer_fraction": 0.6, "dt": 0.1,
                   "world": [ws.world_x0, ws.world_y0, ws.world_x1, ws.world_y1],
                   "start_xy": list(start), "far_xy": list(far), "tick_cmd": [0.25, 0.05], "ticks": ticks,
                   "cut_target_m": cut_target, "moved_kg": moved, "placed_kg": placed, "relax_steps": relax_steps,
                   "virgin_height": virgin, "diff": diff, "edge_pose": [ws.world_x0 + 0.05, edge_y, math.pi],
                   "edge_ticks": edge, "checkpoints": ckpt,
                   "single": {"base_rc": [1000.0, 1000.0], "twists": twists, "start_rc": [2.0, 2.0],
                              "drive": {k: drove[k] for k in ("commanded_dist_m", "achieved_dist_m", "final_rc",
                                                              "final_yaw", "any_entrapped")},
                              "target_m": one_target, "moved_kg": one_moved, "placed_kg": one_placed,
                              "relax_steps": one_steps, "window": single}})


def worksite_refined() -> None:
    """Interpolation-only refinement (D-R72 (1)): the Python overlay with its fbm off (``fbm_nu0`` 0) and bilinear
    thickness interpolation. (a) SYNTHETIC base blocks (labelled) with non-uniform thickness, one at zero so the
    negative-thickness clamp runs; (b) WorkSite at k=2 on the real Haworth 5 m bundle, streaming and single-window."""
    from stewie.physics.worksite import WorkSite
    from stewie.specs import constants as K
    from stewie.terrain import dem_overlay

    off = {"fbm_nu0": 0.0, "smooth": "bilinear"}
    names = ("mass_areal", "density", "datum", "state_label", "disturbance")
    blocks = []
    for k, (h, w) in ((3, (4, 5)), (4, (3, 3))):
        rr, cc = np.meshgrid(np.arange(h, dtype=np.float64), np.arange(w, dtype=np.float64), indexing="ij")
        density = 1300.0 + 40.0 * rr + 15.0 * cc
        thick = 0.12 + 0.05 * np.sin(rr + 0.7 * cc) + 0.02 * cc
        thick[1, 1] = 0.0                                 # a bare cell beside loose ones: the clamp path
        base = {"mass_areal": thick * density, "density": density, "datum": 3.0 * rr - 1.5 * cc + 0.25 * rr * cc,
                "state_label": ((rr + cc) % 3).astype(np.uint8), "disturbance": 0.1 * ((rr * w + cc) % 5)}
        fine = dem_overlay.overlay_residual(base, k, 0.0, 0.0, params=off, fine_cell_m=5.0 / k)
        blocks.append({"k": k, "height": h, "width": w, "base": {n: base[n].ravel().tolist() for n in names},
                       "fine": {n: fine[n].ravel().tolist() for n in names}})
    assert any((np.asarray(b["fine"]["mass_areal"]) == 0.0).any() for b in blocks), "clamp never ran"

    bundle = os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m")
    ws = WorkSite.from_haworth_bundle(bundle, fine_cell_m=2.5)
    ws.mosaic.overlay_params = off
    assert ws.k == 2 and ws.smooth_datum
    t = ws._virgin_tile_fields(250, 250)
    ws.mosaic.overlay_params = {"fbm_nu0": 0.0}            # bicubic: equal on uniform-thickness real terrain
    tb = ws._virgin_tile_fields(250, 250)
    ws.mosaic.overlay_params = off
    bicubic_gap = max(float(np.abs(t[n] - tb[n]).max()) for n in ("mass_areal", "density", "datum"))
    start = ws.base_rc_to_xy((1000.0, 1000.0))
    far = ws.base_rc_to_xy((1000.0, 1012.0))
    ckpt, ticks = {}, []
    ws.recenter(start)
    ckpt["first"] = _ws_window(ws)
    ticks += [_ws_tick(ws, 0.25, 0.05) for _ in range(6)]
    h = ws.fine.derive_height()
    cut = np.zeros(h.shape, dtype=bool)
    cut[8:16, 8:16] = True
    cut_target = float(np.median(h[cut]))
    moved = ws.flatten(cut, cut_target)
    ws.recenter(far)
    spot = np.zeros(ws.fine.derive_height().shape, dtype=bool)
    spot[10:14, 10:14] = True
    placed = ws.dump(spot, kg=0.5 * ws.inventory_kg)
    relax_steps, _ = ws.relax(max_steps=400, theta_r=K.THETA_R, transfer_fraction=0.6)
    ckpt["dumped"] = _ws_window(ws)
    ws.recenter(start)
    ckpt["returned"] = _ws_window(ws)
    virgin = ws.window_virgin_height().ravel().tolist()
    diff = ws.diff_field().ravel().tolist()
    assert moved > 0 and placed > 0 and relax_steps < 400 and ws.recenters == 3
    one = WorkSite.from_haworth_bundle(bundle, fine_cell_m=2.5)
    one.mosaic.overlay_params = off
    one.open_window((1000.0, 1000.0))
    single = _ws_window(one)
    write_fixture(ORACLE_FIXTURES, "worksite_refined", "oracle/build_fixtures.py::worksite_refined "
                  "(stewie.terrain.dem_overlay.overlay_residual with fbm off on SYNTHETIC blocks, labelled; "
                  "stewie.physics.worksite.WorkSite at k=2 on the real Haworth 5 m bundle)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/physics/worksite.py",
                   "stewie/terrain/dem_overlay.py", "stewie/terrain/tiles_mosaic.py", "stewie/physics/refinement.py",
                   "stewie/physics/drive.py", "stewie/physics/sandpile.py"],
                  {"overlay_params": off, "blocks": blocks, "bundle": "samples/lunar_dem/haworth_10km_5m",
                   "fine_cell_m": 2.5, "bicubic_gap": bicubic_gap, "start_xy": list(start), "far_xy": list(far),
                   "tick_cmd": [0.25, 0.05], "ticks": ticks, "cut_target_m": cut_target, "moved_kg": moved,
                   "placed_kg": placed, "relax_steps": relax_steps, "virgin_height": virgin, "diff": diff,
                   "checkpoints": ckpt, "single": {"base_rc": [1000.0, 1000.0], "window": single}})


def terrain_memory_cases() -> None:
    """TerrainMemory (RW-21c) over real worked terrain: each mission delta is a WorkSite diff on the real Haworth 5 m
    bundle (cut, then dump and relax), folded into a site grid, clipped, reverted and imprinted on a real DEM crop;
    a 1 m memory (WorkSite at k=5) imprints onto the 5 m DEM by volume-conserving block aggregation. Also pins
    numpy's pairwise float64 sum and Python round(x, 6) on real heights, which the chain hashes depend on."""
    from stewie.physics.worksite import WorkSite, coarse_base_from_bundle
    from stewie.twin.terrain_memory import TerrainMemory

    bundle = os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m")
    base, _ = coarse_base_from_bundle(bundle)
    heights = base.derive_height()

    def worked(fine_cell_m):
        ws = WorkSite.from_haworth_bundle(bundle, fine_cell_m=fine_cell_m)
        ws.mosaic.overlay_params = {"fbm_nu0": 0.0, "smooth": "bilinear"}
        ws.recenter(ws.base_rc_to_xy((1000.0, 1000.0)))
        h = ws.fine.derive_height()
        n = h.shape[0] // 3
        cut = np.zeros(h.shape, dtype=bool)
        cut[n:2 * n, n:2 * n] = True
        moved = ws.flatten(cut, float(np.median(h[cut])))
        d_cut = ws.diff_field().copy()
        spot = np.zeros(h.shape, dtype=bool)
        spot[2 * n:2 * n + n // 2, n:n + n // 2] = True
        ws.dump(spot)
        ws.relax(max_steps=400)
        return moved, d_cut, ws.diff_field() - d_cut

    moved, d1, d2 = worked(None)                              # 12 x 12 at 5 m
    tm = TerrainMemory(site="haworth", rows=20, cols=20, cell_m=5.0, origin=(10.0, -5.0))
    placed = [tm.apply_subgrid(d1, sub_origin=(20.0, 5.0), cell_m=5.0, mission="m1 cut", mass_moved_kg=moved),
              tm.apply_subgrid(d2, sub_origin=(70.0, 45.0), cell_m=5.0, mission="m2 dump", mass_moved_kg=0.5 * moved)]
    d3 = np.zeros((20, 20))
    d3[3:15, 3:15] = -0.25 * d1
    tm.apply(d3, mission="m3 trim", mass_moved_kg=0.0)
    assert placed[0]["clipped"] is False and placed[1]["clipped"] is True and placed[1]["placed_cells"] > 0
    assert tm.verify_chain()
    dem = heights[990:1030, 980:1020].copy()                  # 40 x 40 real DEM crop
    before_revert = {"chain": tm.chain, "summary": tm.summary(), "cumulative": tm.cumulative_delta().ravel().tolist(),
                     "delta_at": [tm.delta_at(v).ravel().tolist() for v in (1, 2, 3)],
                     "cumulative_at_2": tm.cumulative_delta_at(2).ravel().tolist(),
                     "height_at_1": tm.height_at(heights[0:20, 0:20], 1).ravel().tolist(),
                     "imprint": tm.imprint_on_dem(dem, dem_cell=5.0, dem_origin=(-5.0, 15.0)).ravel().tolist()}
    tm.save(os.path.join(ORACLE_FIXTURES, "terrain_memory_haworth.npz"))   # in the gate's fixture snapshot
    tm.revert_to(2)
    after_revert = {"chain": tm.chain, "summary": tm.summary(), "cumulative": tm.cumulative_delta().ravel().tolist()}

    fmoved, f1, _ = worked(1.0)                               # 60 x 60 at 1 m (k = 5)
    fine = TerrainMemory(site="haworth fine", rows=60, cols=60, cell_m=1.0, origin=(3.0, 2.0))
    fine.apply(f1, mission="fine cut", mass_moved_kg=fmoved)
    resampled = fine.imprint_on_dem_resampled(dem, dem_cell=5.0, dem_origin=(12.0, 7.0))
    assert abs((resampled - dem).sum() * 25.0 - f1.sum() * 1.0) < 1e-9 * max(1.0, abs(f1.sum()))

    # real heights carry at most 24 significant bits (f32 rasters), so their f64 sums are exact in any order;
    # scaled by 0.1 they are not, which makes the sum below depend on numpy's pairwise grouping
    flat = heights.ravel() * 0.1
    sums = [{"n": n, "sum": float(flat[:n].sum())} for n in (1, 7, 8, 9, 100, 128, 129, 1000, 8192, 8193, 100_000,
                                                              flat.size)]
    rounds = [{"x": x, "r": round(x, 6)} for x in [float(v) * 25.0 for v in flat[:200:7]] + [float(d1.sum()) * 25.0,
                                                                                             -1e-7, 2.5e-7, 1234.5678905]]
    write_fixture(ORACLE_FIXTURES, "terrain_memory_cases", "oracle/build_fixtures.py::terrain_memory_cases "
                  "(stewie.twin.terrain_memory.TerrainMemory with WorkSite deltas on the real Haworth 5 m bundle)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/twin/terrain_memory.py",
                   "stewie/physics/worksite.py"],
                  {"site": "haworth", "rows": 20, "cols": 20, "cell_m": 5.0, "origin": [10.0, -5.0],
                   "missions": [{"kind": "subgrid", "delta": d1.ravel().tolist(), "rows": 12, "cols": 12,
                                 "sub_origin": [20.0, 5.0], "mission": "m1 cut", "mass_moved_kg": moved},
                                {"kind": "subgrid", "delta": d2.ravel().tolist(), "rows": 12, "cols": 12,
                                 "sub_origin": [70.0, 45.0], "mission": "m2 dump", "mass_moved_kg": 0.5 * moved},
                                {"kind": "full", "delta": d3.ravel().tolist(), "mission": "m3 trim",
                                 "mass_moved_kg": 0.0}],
                   "placed": placed, "base_0_20": heights[0:20, 0:20].ravel().tolist(),
                   "dem": dem.ravel().tolist(), "dem_shape": [40, 40], "dem_origin": [-5.0, 15.0],
                   "before_revert": before_revert, "after_revert": after_revert,
                   "npz": "crates/stewie-oracle/fixtures/terrain_memory_haworth.npz",
                   "fine": {"rows": 60, "cols": 60, "cell_m": 1.0, "origin": [3.0, 2.0], "delta": f1.ravel().tolist(),
                            "mission": "fine cut", "mass_moved_kg": fmoved, "dem_origin": [12.0, 7.0],
                            "resampled": resampled.ravel().tolist(), "chain": fine.chain},
                   "pairwise_sums": sums, "rounds": rounds})


def traffic_memory_cases() -> None:
    """TrafficMemory (RW-21c-2) folding real drive traffic: two routed legs on the real Haworth route window
    (lode.planner_routing, as route_cases), rasterised by the server's own segment sampler, at the real IPEx
    static wheel loads (dry, then a 20 kg drum); a re-committed event is a no-op (H-09)."""
    from scipy import ndimage

    from lode import planner_routing as PR
    from stewie.physics import material as MT
    from stewie.physics.worksite import coarse_base_from_bundle
    from stewie.server.traffic_fold import _segment_cells
    from stewie.specs import constants as K
    from stewie.twin.traffic_memory import TrafficMemory
    from stewie_forge.terramechanics import TerramechanicsParams, static_wheel_load_n

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    cell, origin = 5.0, (100.0, 50.0)
    _, passable = PR.slope_costmap(Z, cell, max_drop_m=PR.MAX_DROP_M)
    lab, _ = ndimage.label(passable, structure=np.ones((3, 3)))
    rr, cc = np.nonzero(lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1)

    def site(fr, fc):        # the main-component cell nearest a fixed fraction of the window (as route_cases)
        k = int(np.argmin((rr - fr * n) ** 2 + (cc - fc * n) ** 2))
        return (float(cc[k] * cell - origin[0] + 2.5), float(rr[k] * cell - origin[1] + 2.5))

    routes = [PR.route_leg((Z, cell), origin, site(*a), site(*b))[3]
              for a, b in (((0.1, 0.1), (0.9, 0.85)), ((0.15, 0.9), (0.85, 0.15)))]
    assert all(len(r) > 10 for r in routes)

    def cells(route):
        out = set()
        for p, q in zip(route[:-1], route[1:]):
            out |= _segment_cells((p[0] + origin[0], p[1] + origin[1]), (q[0] + origin[0], q[1] + origin[1]),
                                  cell_m=cell, r0=0, c0=0, rows=n, cols=n)
        return sorted(out)

    dry, loaded = static_wheel_load_n(0.0), static_wheel_load_n(20.0)
    tm = TrafficMemory(site="haworth", rows=n, cols=n, cell_m=cell, origin=(0.0, 0.0))
    events = [("m1", "m1:leg0", cells(routes[0]), dry), ("m1", "m1:leg1", cells(routes[1]), dry),
              ("m1", "m1:leg0", cells(routes[0]), dry), ("m2", "m2:leg0", cells(routes[0]), loaded)]
    versions = [tm.apply_path(c, load, mission=m, event_id=e) for m, e, c, load in events]
    assert versions == [1, 2, 2, 3] and tm.verify_chain()
    tm.save(os.path.join(ORACLE_FIXTURES, "traffic_memory_haworth.npz"))
    p = TerramechanicsParams.from_constants()
    write_fixture(ORACLE_FIXTURES, "traffic_memory_cases", "oracle/build_fixtures.py::traffic_memory_cases "
                  "(stewie.twin.traffic_memory.TrafficMemory folding routed legs on the real Haworth window)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/twin/traffic_memory.py",
                   "stewie/server/traffic_fold.py", "stewie/physics/material.py",
                   "packages/stewie-forge/stewie_forge/terramechanics.py",
                   "packages/stewie-forge/stewie_forge/bearing.py"],
                  {"site": "haworth", "rows": n, "cols": n, "cell_m": cell, "mass_areal": tm.mass_areal,
                   "sigma_c_n": tm.sigma_c_n, "contact_width_m": tm.contact_width_m,
                   "soil": p.to_dict(), "contact_len_m": p.contact_len_m, "g": float(K.g),
                   "rho_surface": float(K.RHO_SURFACE), "rho_deep": float(K.RHO_DEEP),
                   "material": {"phi_loose_deg": MT.PHI_LOOSE_DEG, "phi_dense_deg": MT.PHI_DENSE_DEG,
                                "cohesion_loose_pa": MT.COHESION_LOOSE_PA, "cohesion_dense_pa": MT.COHESION_DENSE_PA,
                                "rho_surface": float(MT.K.RHO_SURFACE), "rho_deep": float(MT.K.RHO_DEEP)},
                   "events": [{"mission": m, "event_id": e, "cells": [list(x) for x in c], "load_n": load}
                              for m, e, c, load in events],
                   "versions": versions, "chain": tm.chain, "summary": tm.summary(),
                   "equilibrium": tm.equilibrium_density().ravel().tolist(),
                   "densified": tm.densified_density().ravel().tolist(),
                   "relative": tm.relative_density().ravel().tolist(),
                   "uplift": tm.bearing_uplift_pa().ravel().tolist(),
                   "npz": "crates/stewie-oracle/fixtures/traffic_memory_haworth.npz"})


def twin_ops_cases() -> None:
    """The twin's server-side operations (RW-21c-3) on real terrain: the composed terrain view over a real Haworth
    crop (as-built from the Terrain Memory fixture, observed from twin patches), a backup snapshot and a
    mission-time-stamped (compressed) snapshot written by the Python, and the version and time retention ladders
    and snapshot triggers on SYNTHETIC file names and times (labelled)."""
    import shutil
    import tempfile

    from stewie.physics.worksite import coarse_base_from_bundle
    from stewie.twin import backup, cadence
    from stewie.twin.terrain_memory import TerrainMemory
    from stewie.twin.terrain_view import compose_terrain_view
    from stewie.twin.versioned import TwinStore

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    dem = base.derive_height()[990:1030, 980:1020].copy()
    tm = TerrainMemory.load(os.path.join(ORACLE_FIXTURES, "terrain_memory_haworth.npz"))
    as_built = tm.imprint_on_dem(dem, dem_cell=5.0, dem_origin=(-5.0, 15.0))
    tw = TwinStore(dem, cell_m=5.0)
    tw.apply_patch(dem[2:6, 3:9] + 0.05, origin_rc=(2, 3), provenance="SYNTHETIC +0.05 m resync over the build (labelled)")
    tw.apply_patch(dem[30:33, 30:34] - 0.1, origin_rc=(30, 30), provenance="SYNTHETIC -0.1 m resync (labelled)")
    view = compose_terrain_view(dem, 5.0, as_built_z=as_built, as_built_version=tm.version,
                                observed_heights=tw.current(), observed_mask=tw.observed_mask(),
                                twin_version=tw.version)
    ignored = compose_terrain_view(dem, 5.0, as_built_z=as_built[:-1], as_built_version=tm.version,
                                   observed_heights=tw.current(), observed_mask=np.zeros(dem.shape, dtype=bool),
                                   twin_version=tw.version)
    assert {0, 1, 2} <= set(np.unique(view.source).tolist())
    # SR-17: the volume-conserving coarse imprint leaves sub-centimetre edge changes; they must count as built
    with open(os.path.join(ORACLE_FIXTURES, "terrain_memory_cases.payload.json")) as fh:
        tmc = json.load(fh)
    tmc = tmc.get("payload", tmc)
    coarse = np.array(tmc["fine"]["resampled"]).reshape(dem.shape)
    assert np.array_equal(np.array(tmc["dem"]).reshape(dem.shape), dem)
    assert np.count_nonzero((np.abs(coarse - dem) > 1e-4) & (np.abs(coarse - dem) < 1e-2)) > 0
    fine_view = compose_terrain_view(dem, 5.0, as_built_z=coarse, as_built_version=1)
    with tempfile.TemporaryDirectory() as d:
        shutil.copy(backup.snapshot(tw, os.path.join(d, "a")), os.path.join(ORACLE_FIXTURES, "twin_snapshot.npz"))
        stamped = cadence.snapshot_at(tw, os.path.join(d, "b"), mission_t_s=12345.5)
        shutil.copy(stamped, os.path.join(ORACLE_FIXTURES, "twin_snapshot_stamped.npz"))
        vdir = os.path.join(d, "v")
        os.makedirs(vdir)
        for v in range(1, 24):
            open(os.path.join(vdir, f"twin_v{v:06d}.npz"), "wb").close()
        kept_versions = backup.apply_retention(vdir, keep_recent=5, ladder=10)
    hour, day, week = 3600.0, 86400.0, 7 * 86400.0
    now = 100 * week
    ages = [0.0, 0.2 * hour, 0.9 * hour, 1.5 * hour, 23.9 * hour, 24.5 * hour, 30 * hour, 2.5 * day, 2.6 * day,
            8.9 * day, 9.5 * day, 3 * week, 3.1 * week, 5.5 * week, 9 * week, -60.0]
    times = {f"twin_v{i:06d}.npz": now - a for i, a in enumerate(ages)}
    times["twin_v000099.npz"] = times["twin_v000003.npz"]          # an exact tie: the smaller name wins
    retained = sorted(cadence.select_retained(times, now_t_s=now, keep_hourly=24, keep_daily=7, keep_weekly=4))
    sched = cadence.SnapshotScheduler(sol_seconds=cadence.SOL_SECONDS, every_n_events=50)
    due = [{"t": t, "n": n, "last_t": lt, "last_n": ln,
            "due": sched.due(mission_t_s=t, n_events=n, last_snap_t_s=lt, last_snap_events=ln)}
           for t, n, lt, ln in ((0.0, 0, 0.0, 0), (cadence.SOL_SECONDS - 1, 49, 0.0, 0), (cadence.SOL_SECONDS, 3, 0.0, 0),
                                (5000.0, 60, 100.0, 10), (5000.0, 59, 100.0, 10))]
    ver, ident = tw.identity()
    write_fixture(ORACLE_FIXTURES, "twin_ops_cases", "oracle/build_fixtures.py::twin_ops_cases (stewie.twin."
                  "{terrain_view, backup, cadence} on a real Haworth crop; retention names and times SYNTHETIC, labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "stewie/twin/terrain_view.py",
                   "crates/stewie-oracle/fixtures/terrain_memory_cases.payload.json", "stewie/twin/backup.py", "stewie/twin/cadence.py", "stewie/twin/versioned.py"],
                  {"rows": 40, "cols": 40, "cell_m": 5.0, "dem": dem.ravel().tolist(),
                   "as_built": as_built.ravel().tolist(), "as_built_version": tm.version,
                   "observed": tw.current().ravel().tolist(), "mask": tw.observed_mask().ravel().tolist(),
                   "twin_version": tw.version, "identity": [ver, ident], "events": tw.events,
                   "view": {"heights": view.heights.ravel().tolist(), "source": view.source.ravel().tolist(),
                            "as_built_version": view.as_built_version, "twin_version": view.twin_version,
                            "observed_fraction": view.observed_fraction},
                   "coarse_as_built": coarse.ravel().tolist(),
                   "coarse_view": {"heights": fine_view.heights.ravel().tolist(),
                                   "source": fine_view.source.ravel().tolist()},
                   "ignored": {"heights": ignored.heights.ravel().tolist(), "as_built_version": ignored.as_built_version,
                               "twin_version": ignored.twin_version},
                   "snapshot": "crates/stewie-oracle/fixtures/twin_snapshot.npz",
                   "stamped": "crates/stewie-oracle/fixtures/twin_snapshot_stamped.npz", "stamped_t": 12345.5,
                   "kept_versions": kept_versions, "now": now, "times": times, "retained": retained,
                   "sol_seconds": cadence.SOL_SECONDS, "every_n_events": 50, "due": due})


def mission_cases() -> None:
    """lode.planner_model.mission_from_dict (RW-33a) on the three committed sample missions and on SYNTHETIC variants
    of the first (labelled): one accepted case per optional block and one refused case per check. Each case
    records the Python's parsed Mission or its refusal."""
    import copy
    import dataclasses
    import glob

    from lode.planner_model import mission_from_dict

    samples = {os.path.basename(f)[:-5]: json.load(open(f)) for f in
               sorted(glob.glob(os.path.join(REPO, "stewie", "server", "sample_missions", "*.json")))}
    base = samples["01_flatten_pad"]

    def var(**kw):
        p = copy.deepcopy(base)
        for k, v in kw.items():
            if v is _DROP:
                p.pop(k, None)
            else:
                p[k] = v
        return p

    def orders(*extra):
        return copy.deepcopy(base["orders"]) + list(extra)

    def with_order(**kw):
        o = dict(base["orders"][0])
        o.update(kw)
        o = {k: v for k, v in o.items() if v is not _DROP}
        return var(orders=[o, base["orders"][1]])

    cut = {"action": "c2", "kind": "cut", "x": 5, "y": 5, "depth_m": 0.1}
    cases = dict(samples)
    cases.update({
        "versioned": var(schema_version="stewie_mission/1.0"),
        "vehicle_case_and_tool": var(vehicle="IPEx", tools=["Sinter"], orders=orders(
            {"action": "pave", "kind": "sinter", "x": 20, "y": 20, "footprint_m2": 4, "depth_m": 0.05})),
        "soil_same_as_body": var(soil=" Moon "),
        "soil_override": var(soil="mars"),
        "shapes": var(orders=orders(
            dict(cut, action="rect", shape={"kind": "rectangle", "w": 3, "h": 2, "theta_deg": 30}),
            dict(cut, action="circ", shape={"kind": "circle", "r": 1.5}),
            dict(cut, action="corr", shape={"kind": "corridor", "length": 10, "width": 0.5}),
            dict(cut, action="poly", shape={"kind": "polygon", "vertices": [[0, 0], [4, 0], [4, 3]]}))),
        "path_and_precedence": var(orders=orders({"action": "w1", "kind": "goto", "x": 1, "y": 1},
                                                 {"action": "w2", "kind": "goto", "x": 2, "y": 1},
                                                 {"action": "w3", "kind": "goto", "x": 3, "y": 2}),
                                   precedence=[["cut high spot", "fill pad"]]),
        "keepouts": var(keepouts=[{"x": 25, "y": 0, "r": 3}, {"x0": 30, "y0": 8, "x1": 28, "y1": 2},
                                  {"points": [[0, 20], [5, 20], [5, 25]]}]),
        "every_optional_block": var(
            objective_constraints={"max_time_s": 36000, "risk_weight": 0.5},
            mission_windows={"work": [[0, 3600], [7200, 9000]], "recharge": []},
            shared_resources=[{"id": "pit-a", "kind": "pit", "sites": [[10, 10]]},
                              {"id": "dump-b", "kind": "dump", "capacity": 2, "sites": [[40, 10], [41, 10]]}],
            observations=[{"vehicle": 0, "x": 5, "y": 5, "t_start": 10, "t_end": 20},
                          {"vehicle": 1, "x": 6, "y": 5, "t_start": 15, "t_end": 30, "kind": "solar"}],
            dig_energy_factor=1.4, accept_flatness_tol_m=0.03, lander=[2, 3], return_buffer_frac=0.3,
            charger_capacity=12, date="2027-01-15", name=42, physics_backend_id=" tier2_numpy "),
        "capacity_zero": var(charger_capacity=0),
        "capacity_fraction": var(charger_capacity=2.7),
        "insitu_density": with_order(insitu_density_kg_m3=1650.0, note="bank cut"),
        # refusals
        "not_an_object": [base],
        "body_case": var(body="Moon"),
        "unknown_schema": var(schema_version="stewie_mission/9"),
        "unknown_vehicle": var(vehicle="digger"),
        "unknown_tool": var(tools=["laser"]),
        "unknown_soil": var(soil="vulcan"),
        "unknown_backend": var(physics_backend_id="chrono"),
        "no_orders": var(orders=[]),
        "order_not_object": var(orders=["cut"]),
        "missing_field": with_order(depth_m=_DROP),
        "bad_kind": with_order(kind="drill"),
        "sinter_without_tool": var(orders=orders({"action": "pave", "kind": "sinter", "x": 1, "y": 1,
                                                  "footprint_m2": 1, "depth_m": 0.1})),
        "string_coordinate": with_order(x="10"),
        "negative_depth": with_order(depth_m=-0.1),
        "zero_footprint": with_order(footprint_m2=0),
        "bad_shape_kind": var(orders=orders(dict(cut, shape={"kind": "hexagon"}))),
        "degenerate_polygon": var(orders=orders(dict(cut, shape={"kind": "polygon", "vertices": [[0, 0], [1, 1], [2, 2]]}))),
        "precedence_unknown": var(precedence=[["cut high spot", "nowhere"]]),
        "precedence_shape": var(precedence=[["cut high spot"]]),
        "keepouts_not_list": var(keepouts={"x": 1}),
        "keepout_two_points": var(keepouts=[{"points": [[0, 0], [1, 1]]}]),
        "keepout_unknown": var(keepouts=[{"x": 1, "y": 2}]),
        "keepout_zero_radius": var(keepouts=[{"x": 1, "y": 2, "r": 0}]),
        "constraint_unknown": var(objective_constraints={"max_fun": 1}),
        "constraint_negative": var(objective_constraints={"max_time_s": -1}),
        "window_class": var(mission_windows={"sleep": [[0, 1]]}),
        "window_reversed": var(mission_windows={"work": [[10, 5]]}),
        "resource_duplicate": var(shared_resources=[{"id": "a", "kind": "pit", "sites": [[0, 0]]},
                                                    {"id": "a", "kind": "pit", "sites": [[1, 0]]}]),
        "resource_kind": var(shared_resources=[{"id": "a", "kind": "garage", "sites": [[0, 0]]}]),
        "resource_capacity_zero": var(shared_resources=[{"id": "a", "kind": "pit", "capacity": 0, "sites": [[0, 0]]}]),
        "resource_capacity_float": var(shared_resources=[{"id": "a", "kind": "pit", "capacity": 2.0, "sites": [[0, 0]]}]),
        "observation_vehicle": var(observations=[{"vehicle": -1, "x": 0, "y": 0, "t_start": 0, "t_end": 1}]),
        "observation_window": var(observations=[{"vehicle": 0, "x": 0, "y": 0, "t_start": 5, "t_end": 5}]),
        "observation_missing": var(observations=[{"vehicle": 0, "x": 0, "y": 0, "t_end": 1}]),
        "dig_factor_zero": var(dig_energy_factor=0),
        "flatness_negative": var(accept_flatness_tol_m=-1),
        "return_buffer_negative": var(return_buffer_frac=-0.1),
        "charger_shape": var(charger=[1]),
        "lander_shape": var(lander=[1, 2, 3]),
    })
    out = []
    for name, payload in cases.items():
        try:
            m = mission_from_dict(payload)
            out.append({"name": name, "payload": payload, "ok": True, "mission": dataclasses.asdict(m)})
        except (ValueError, KeyError, TypeError) as e:       # TypeError reaches the server as a 500, not a 400
            out.append({"name": name, "payload": payload, "ok": False, "error": f"{type(e).__name__}: {e}"})
    accepted = sum(c["ok"] for c in out)
    assert (accepted, len(out) - accepted) == (15, 38), (accepted, len(out))   # 14 planned + the string coordinate
    write_fixture(ORACLE_FIXTURES, "mission_cases", "oracle/build_fixtures.py::mission_cases (lode.planner_model."
                  "mission_from_dict on the committed sample missions and SYNTHETIC variants, labelled)",
                  ["lode/planner_model.py", "stewie/specs/vehicles.py", "stewie/server/sample_missions/01_flatten_pad.json",
                   "stewie/server/sample_missions/02_haul_around_hazard.json",
                   "stewie/server/sample_missions/03_blocked_infeasible.json"],
                  {"cases": out})


_DROP = object()


def balance_cases() -> None:
    """Cut-fill balance (RW-33b): the min-cost transportation solver on the P-03 docstring example and SYNTHETIC
    matrices (labelled), and lode.planner_balance.balance on missions routed over the real Haworth route window
    (sites picked as route_cases picks them): surplus, deficit, an unreachable fill, cuts only and fills only."""
    from scipy import ndimage

    from lode import planner_routing as PR
    from lode.planner_balance import _mincost_transport, balance
    from lode.planner_model import mission_from_dict
    from lode.planner_trips import _make_routes
    from stewie.physics.worksite import coarse_base_from_bundle

    inf = float("inf")
    transport = []
    for name, sup, dem, cost in (
            ("p03_doc", [10.0, 5.0], [5.0, 10.0], [[1.0, 2.0], [3.0, 9.0]]),
            ("unreachable_arcs", [8.0, 6.0, 4.0], [5.0, 9.0], [[2.0, inf], [inf, 3.0], [1.5, 4.0]]),
            ("excess_demand", [3.0], [5.0, 4.0], [[1.0, 2.0]]),
            ("no_arcs", [3.0, 2.0], [4.0], [[inf], [inf]]),
            ("cost_tie", [5.0, 5.0], [5.0, 5.0], [[1.0, 1.0], [1.0, 1.0]])):
        flow, unmet, left = _mincost_transport(sup, dem, cost)
        transport.append({"name": name, "supplies": sup, "demands": dem,
                          "cost": [[c if math.isfinite(c) else None for c in r] for r in cost],
                          "flow": flow, "unmet": unmet, "leftover": left})

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    cell, origin = 5.0, (100.0, 50.0)
    _, passable = PR.slope_costmap(Z, cell, max_drop_m=PR.MAX_DROP_M)
    lab, _ = ndimage.label(passable, structure=np.ones((3, 3)))
    main = lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1
    rr, cc = np.nonzero(main)

    def site(fr, fc):
        k = int(np.argmin((rr - fr * n) ** 2 + (cc - fc * n) ** 2))
        return [float(cc[k] * cell - origin[0] + 2.5), float(rr[k] * cell - origin[1] + 2.5)]

    br, bc = np.nonzero(~passable)          # an impassable cell: no route reaches it
    blocked = [float(bc[0] * cell - origin[0] + 2.5), float(br[0] * cell - origin[1] + 2.5)]

    def order(action, kind, xy, fp, depth, **kw):
        return {"action": action, "kind": kind, "x": xy[0], "y": xy[1], "footprint_m2": fp, "depth_m": depth, **kw}

    missions = {
        "surplus": [order("cut a", "cut", site(0.2, 0.2), 40, 0.3), order("cut b", "cut", site(0.7, 0.3), 30, 0.08,
                                                                             insitu_density_kg_m3=1650.0),
                    order("cut c", "cut", site(0.5, 0.8), 25, 0.5), order("fill d", "fill", site(0.4, 0.5), 36, 0.2),
                    order("fill e", "fill", site(0.8, 0.7), 20, 0.15)],
        "deficit": [order("cut a", "cut", site(0.3, 0.3), 10, 0.1), order("fill b", "fill", site(0.6, 0.6), 50, 0.3),
                    order("fill c", "fill", site(0.2, 0.8), 30, 0.2)],
        "unreachable_fill": [order("cut a", "cut", site(0.3, 0.3), 30, 0.2), order("fill b", "fill", blocked, 20, 0.2),
                             order("fill c", "fill", site(0.7, 0.4), 10, 0.2)],
        "cuts_only": [order("cut a", "cut", site(0.3, 0.3), 30, 0.2), order("cut b", "cut", site(0.6, 0.5), 12, 0.6)],
        "fills_only": [order("fill a", "fill", site(0.3, 0.3), 30, 0.2)],
    }
    out = []
    for name, orders in missions.items():
        payload = {"name": name, "body": "moon", "charger": site(0.5, 0.5), "orders": orders}
        m = mission_from_dict(payload)
        flows, surplus = balance(m, dem=(Z, cell), dem_origin=origin)
        idx = {id(o): i for i, o in enumerate(m.orders)}
        rd = _make_routes(m, (Z, cell), origin, 25.0)
        cuts = [o for o in m.orders if o.kind == "cut"]
        fills = [o for o in m.orders if o.kind == "fill"]
        cost = [[(lambda v: v if math.isfinite(v) else None)(rd((c.x, c.y), (f.x, f.y))) for f in fills] for c in cuts]
        out.append({"name": name, "payload": payload, "cost": cost, "surplus_kg": surplus,
                    "flows": [{"cut": None if c is None else idx[id(c)], "fill": None if f is None else idx[id(f)],
                               "mass_kg": mass, "dist_m": d} for c, f, mass, d in flows]})
    kinds = {name: {("routed" if f["cut"] is not None and f["fill"] is not None else
                     "import" if f["cut"] is None else "spoil") for f in r["flows"]} for name, r in
             ((r["name"], r) for r in out)}
    assert kinds["surplus"] >= {"routed", "spoil"} and "import" in kinds["deficit"]
    assert "import" in kinds["unreachable_fill"] and kinds["cuts_only"] == {"spoil"} and kinds["fills_only"] == {"import"}
    assert any(c is None for r in out for row in r["cost"] for c in row), "an unreachable arc"
    write_fixture(ORACLE_FIXTURES, "balance_cases", "oracle/build_fixtures.py::balance_cases (lode.planner_balance on "
                  "SYNTHETIC matrices, labelled, and on missions routed over the real Haworth route window)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "lode/planner_balance.py",
                   "lode/planner_routing.py", "lode/planner_trips.py", "lode/planner_model.py"],
                  {"window": list(ROUTE_WINDOW), "cell_m": cell, "origin": list(origin), "transport": transport,
                   "missions": out})


def trips_cases() -> None:
    """Trip construction (RW-33c1): lode.planner_trips._build_trips on missions routed over the real Haworth route
    window (sites picked as route_cases picks them; every mission free of cost ties, so the balance is unique),
    with the planning context, trip precedence and SYNTHETIC mission-clock window gates (labelled)."""
    import dataclasses

    from scipy import ndimage

    from lode import planner_constants as PC
    from lode import planner_routing as PR
    from lode.planner_model import mission_from_dict, mission_soil_params, plan_context
    from lode.planner_trips import _build_trips, _precedence_is_feasible, _window_gate, trip_precedence
    from stewie.physics.worksite import coarse_base_from_bundle
    from stewie.specs import ipex_specs as S

    base, _ = coarse_base_from_bundle(os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    cell, origin = 5.0, (100.0, 50.0)
    _, passable = PR.slope_costmap(Z, cell, max_drop_m=PR.MAX_DROP_M)
    lab, _ = ndimage.label(passable, structure=np.ones((3, 3)))
    rr, cc = np.nonzero(lab == np.argmax(np.bincount(lab.ravel())[1:]) + 1)

    def site(fr, fc):
        k = int(np.argmin((rr - fr * n) ** 2 + (cc - fc * n) ** 2))
        return [float(cc[k] * cell - origin[0] + 2.5), float(rr[k] * cell - origin[1] + 2.5)]

    br, bc = np.nonzero(~passable)
    blocked = [float(bc[0] * cell - origin[0] + 2.5), float(br[0] * cell - origin[1] + 2.5)]

    def order(action, kind, xy, fp=None, depth=None, **kw):
        o = {"action": action, "kind": kind, "x": xy[0], "y": xy[1], **kw}
        if kind != "goto":
            o.update(footprint_m2=fp, depth_m=depth)
        return o

    missions = {
        "haul_two_pairs": {"orders": [order("cut a", "cut", site(0.2, 0.2), 40, 0.3),
                                      order("cut b", "cut", site(0.7, 0.3), 30, 0.08, insitu_density_kg_m3=1650.0),
                                      order("fill c", "fill", site(0.4, 0.5), 36, 0.2),
                                      order("fill d", "fill", site(0.85, 0.75), 10, 0.15),
                                      order("w1", "goto", site(0.5, 0.2)), order("w2", "goto", site(0.6, 0.2))],
                           "precedence": [["cut a", "fill d"]]},
        "deficit": {"orders": [order("cut a", "cut", site(0.3, 0.3), 10, 0.1), order("fill b", "fill", site(0.6, 0.6), 50, 0.3)]},
        "unreachable_fill": {"orders": [order("cut a", "cut", site(0.3, 0.3), 30, 0.2), order("fill b", "fill", blocked, 20, 0.2),
                                        order("fill c", "fill", site(0.7, 0.4), 10, 0.2)]},
        "cuts_only": {"orders": [order("cut a", "cut", site(0.3, 0.3), 30, 0.2), order("cut b", "cut", site(0.6, 0.5), 12, 0.6)]},
        "heavy_rassor": {"orders": [order("cut a", "cut", site(0.25, 0.6), 60, 0.4), order("fill b", "fill", site(0.6, 0.35), 50, 0.3)],
                         "vehicle": "rassor2", "dig_energy_factor": 1.3},
    }
    out = []
    for name, extra in missions.items():
        payload = {"name": name, "body": "moon", "charger": site(0.5, 0.5), **extra}
        m = mission_from_dict(payload)
        ctx = plan_context(m)
        trips, flows, surplus, meta = _build_trips(m, (Z, cell), origin, 25.0)
        prec = trip_precedence(trips, m)
        idx = {id(o): i for i, o in enumerate(m.orders)}
        keep = ("kind", "site", "dest", "label", "mass", "dig_e", "dig_t", "haul_m", "haul_e", "drive_e", "slip_e", "lift_e",
                "offload_e", "offload_t", "shape")
        out.append({"name": name, "payload": payload, "context": dataclasses.asdict(ctx), "soil": mission_soil_params(m).to_dict(),
                    "trips": [{**{k: (list(t[k]) if isinstance(t.get(k), tuple) else t.get(k, 0.0 if k not in ("shape",) else None))
                                  for k in keep}, "actions": sorted(t["actions"])} for t in trips],
                    "flows": [{"cut": None if c is None else idx[id(c)], "fill": None if f is None else idx[id(f)], "mass_kg": mm}
                              for c, f, mm, _d in flows],
                    "surplus_kg": surplus, "precedence": [list(p) for p in prec],
                    "precedence_feasible": _precedence_is_feasible(len(trips), prec),
                    "meta": {k: meta[k] for k in ("straight_haul_m", "routed_haul_m", "blocked_legs", "traverse_cap_deg", "feasible")},
                    "routes": [{"from": list(r["from_xy"]), "to": list(r["to_xy"]), "reached": r["reached"],
                                "waypoints": r["waypoints"]} for r in meta["routes"]]})
    kinds = {t["kind"] for r in out for t in r["trips"]}
    assert kinds == {"goto", "import", "dig", "cutfill"}, kinds
    assert any(r["meta"]["blocked_legs"] for r in out) and any(r["precedence"] for r in out)
    assert any(t["kind"] == "cutfill" and t["haul_m"] > 0 and t["slip_e"] > 0 for r in out for t in r["trips"])
    windows = {"work": [[100.0, 200.0], [0.0, 50.0]], "drive": []}
    gates = [{"class": c, "t": t, "result": list(_window_gate(windows, c, t))}
             for c, t in (("work", 10.0), ("work", 60.0), ("work", 150.0), ("work", 250.0), ("drive", 5.0), ("recharge", 5.0))]
    gates.append({"class": "work", "t": 7.0, "result": list(_window_gate(None, "work", 7.0)), "no_windows": True})
    write_fixture(ORACLE_FIXTURES, "trips_cases", "oracle/build_fixtures.py::trips_cases (lode.planner_trips on missions "
                  "routed over the real Haworth route window; window gates SYNTHETIC, labelled)",
                  ["samples/lunar_dem/haworth_10km_5m/metadata.json", "lode/planner_trips.py", "lode/planner_model.py",
                   "lode/planner_endurance.py", "lode/planner_balance.py", "stewie/physics/slip.py", "stewie/specs/ipex_specs.py",
                   "stewie/specs/vehicles.py"],
                  {"window": list(ROUTE_WINDOW), "cell_m": cell, "origin": list(origin),
                   "params": {"reserve_frac": PC.RESERVE_FRAC, "charge_w": PC.CHARGE_W, "dig_rate_kg_s": PC.DIG_RATE_KG_S,
                              "drive_speed_ms": PC.DRIVE_SPEED_MS, "rolling_resistance": S.ROLLING_RESISTANCE_COEFF,
                              "drivetrain_efficiency": S.DRIVETRAIN_EFFICIENCY, "gravity_ms2": 1.62},
                   "slip": {"n_wheels": 4, "contact_len_m": 0.10, "contact_width_m": 0.18, "z_entrap_m": 0.36},
                   "windows": windows, "gates": gates, "missions": out})


def sim_cases() -> None:
    """The battery-aware trip simulation (RW-33c2): lode.planner_sim._simulate over the trips_cases missions on the
    real Haworth route window, in build order, reversed, and under SYNTHETIC mission-clock windows (labelled) that
    force drive, work and recharge waits and a closed window."""
    import copy

    from lode.planner_model import mission_from_dict
    from lode.planner_sim import _simulate
    from lode.planner_trips import _build_trips, _make_routes

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    runs = []

    def run(name, payload, reverse=False):
        m = mission_from_dict(payload)
        trips, _flows, _surplus, _meta = _build_trips(m, dem, origin, 25.0)
        order = list(range(len(trips)))[::-1] if reverse else list(range(len(trips)))
        tl, per, core = _simulate(m, [trips[i] for i in order], routes=_make_routes(m, dem, origin, 25.0))
        runs.append({"name": name, "payload": payload, "order": order,
                     "timeline": [{k: s[k] for k in ("t0", "t1", "kind", "batt0", "batt1", "mass", "speed", "x0", "y0", "x1", "y1")}
                                  for s in tl],
                     "per_trip": [{"t_start": p["t_start"], "t_end": p["t_end"]} for p in per], "core": core})

    for mc in tc["missions"]:
        run(mc["name"], mc["payload"])
    main = next(mc["payload"] for mc in tc["missions"] if mc["name"] == "haul_two_pairs")
    run("haul_two_pairs_reversed", main, reverse=True)
    windowed = copy.deepcopy(main)
    windowed["mission_windows"] = {"drive": [[600.0, 1.0e9]], "work": [[2000.0, 6.0e5], [7.0e5, 9.0e5]],
                                   "recharge": [[0.0, 5.0e4], [3.0e5, 1.0e9]]}
    run("haul_two_pairs_windowed", windowed)
    closed = copy.deepcopy(main)
    closed["mission_windows"] = {"work": [[0.0, 100.0]]}
    run("work_window_closes", closed)
    stranded = copy.deepcopy(main)
    stranded["mission_windows"] = {"recharge": [[0.0, 1000.0]]}   # the first mid-dig recharge finds it closed
    run("recharge_window_closes_mid_work", stranded)
    kinds = {s["kind"] for r in runs for s in r["timeline"]}
    assert {"drive", "charge", "dig", "offload", "wait"} <= kinds, kinds
    assert any(not r["core"]["feasible"] for r in runs) and any(r["core"]["charges"] > 1 for r in runs)
    last = runs[-1]                                          # stranded mid-dig: some, not all, mass credited
    assert "recharge window closed" in last["core"]["infeasible_reasons"][0] and last["core"]["mass_kg"] > 0
    write_fixture(ORACLE_FIXTURES, "sim_cases", "oracle/build_fixtures.py::sim_cases (lode.planner_sim._simulate on the "
                  "trips_cases missions over the real Haworth route window; mission windows SYNTHETIC, labelled)",
                  ["lode/planner_sim.py", "lode/planner_trips.py", "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"runs": runs})


def sequencing_cases() -> None:
    """Sequencing (RW-33d1): lode.planner_optimize.optimize_sequence for every algorithm and several objectives on
    missions routed over the real Haworth route window (tie-free balances), including a mission large enough for
    auto's Held-Karp + LK path and a budgeted one whose constraint penalty bites; objective parsing and the
    optimality labels. Mission layouts beyond trips_cases are SYNTHETIC placements on the real terrain (labelled)."""
    import copy

    from lode.planner_model import mission_from_dict
    from lode.planner_optimize import (_objective_optimality, effective_algorithm, optimize_sequence,
                                       parse_objective)
    from lode.planner_trips import _build_trips, _make_routes, trip_precedence

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    main = payloads["haul_two_pairs"]
    many = copy.deepcopy(main)
    reachable = [(o["x"], o["y"]) for name in ("deficit", "cuts_only", "heavy_rassor") for o in payloads[name]["orders"]]
    many["orders"] = [o for o in main["orders"]] + [
        {"action": f"g{k}", "kind": "goto", "x": x, "y": y} for k, (x, y) in enumerate(reachable[:4], 1)]
    budget = copy.deepcopy(main)
    budget["objective_constraints"] = {"max_time_s": 1.0e6, "risk_weight": 50.0}
    cases = []

    def run(name, payload, algos, objectives):
        m = mission_from_dict(payload)
        trips, _f, _s, _meta = _build_trips(m, dem, origin, 25.0)
        prec = trip_precedence(trips, m)
        rd = _make_routes(m, dem, origin, 25.0)
        for algo in algos:
            for obj in objectives:
                order = optimize_sequence(trips, m, algorithm=algo, objective=obj, precedence=prec, routes=rd)
                resolved = effective_algorithm(algo, len(trips))
                label = _objective_optimality(resolved, obj)
                cases.append({"mission": name, "payload": payload, "n_trips": len(trips), "algorithm": algo,
                              "objective": obj, "order": list(order), "resolved": resolved,
                              "label": list(label)})

    algos = ["nearest", "greedy", "two_opt", "or_opt", "lk", "brute", "held_karp", "auto"]
    run("haul_two_pairs", main, algos, ["time", "energy", "distance", "charges", "time:0.6,energy:0.4", "mass"])
    run("heavy_rassor", payloads["heavy_rassor"], algos, ["time", "distance"])
    run("many", many, ["auto", "brute", "held_karp", "lk", "nearest", "two_opt", "or_opt", "greedy"], ["time", "distance"])
    run("budget", budget, ["brute", "two_opt"], ["time", "energy:1,charges:1"])
    assert any(c["resolved"] == "held_karp_lk" for c in cases) and any(c["algorithm"] == "brute" and c["resolved"] == "lk"
                                                                          for c in cases)
    assert len({tuple(c["order"]) for c in cases if c["mission"] == "haul_two_pairs"}) > 1, "orders differ by solver"
    parses = []
    for spec in ("time", "time:0.6,energy:0.4", "energy:1,charges:1", "distance:", "time:-1", "time:nan",
                 "time:0", "time,time", "time:abc", "speed", "power:2,mass:2"):
        try:
            parses.append({"spec": spec, "weights": [[k, v] for k, v in parse_objective(spec).items()]})
        except ValueError as e:
            parses.append({"spec": spec, "error": str(e)})
    write_fixture(ORACLE_FIXTURES, "sequencing_cases", "oracle/build_fixtures.py::sequencing_cases (lode.planner_optimize "
                  "on missions over the real Haworth route window; extra placements SYNTHETIC, labelled)",
                  ["lode/planner_optimize.py", "lode/planner_sim.py", "lode/planner_trips.py",
                   "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases, "parses": parses})


def fleet_cases() -> None:
    """Fleet allocation and deconfliction (RW-33d2a): lode.planner_multivehicle's site-exclusive allocation and
    every resolver plan_multi runs, on fleets planned over the real Haworth route window (trips_cases missions,
    each rover sequenced by optimize_sequence and simulated by _simulate exactly as plan_multi does). The
    declared shared resources, observations and the multi-site layouts are SYNTHETIC placements on the real
    terrain (labelled). Also SYNTHETIC per-vehicle timelines (labelled) for the branches a real fleet here does not
    reach: a capacity-2 resource, chained cross-vehicle precedence and the observation refusals."""
    import copy

    import lode.planner_multivehicle as MV
    from lode.planner_model import mission_from_dict
    from lode.planner_optimize import optimize_sequence
    from lode.planner_sim import _simulate
    from lode.planner_trips import _build_trips, _make_routes, trip_precedence

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}

    def spans(tl):
        return [{"kind": s["kind"], "t0": s["t0"], "t1": s["t1"], "batt0": s["batt0"], "batt1": s["batt1"],
                 "from": [s["x0"], s["y0"]], "to": [s["x1"], s["y1"]]} for s in tl]

    cases = []

    def run(name, payload, vehicles, algo="nearest", obj="time"):
        m = mission_from_dict(payload)
        trips, _f, _s, _meta = _build_trips(m, dem, origin, 25.0)
        rd = _make_routes(m, dem, origin, 25.0)
        prec = trip_precedence(trips, m)
        alloc = MV._allocate_trips(trips, vehicles)
        per, orders = [], []
        for v, idxs in enumerate(alloc):
            vtrips = [trips[i] for i in idxs]
            gorder = []
            if vtrips:
                li = {g: k for k, g in enumerate(idxs)}
                lp = [(li[i], li[j]) for i, j in prec if i in li and j in li]
                order = optimize_sequence(vtrips, m, algorithm=algo, objective=obj, precedence=(lp or None),
                                          routes=rd)
                vtrips = [vtrips[k] for k in order]
                gorder = [idxs[k] for k in order]
            tl, per_trip, core = _simulate(m, vtrips, rd)
            per.append({"vehicle": v, "trips": vtrips, "tl": tl, "per_trip": per_trip, "core": core})
            orders.append(gorder)
        jd, jbd = MV._resolve_joint_resources(per, charger_capacity=m.charger_capacity,
                                              shared_resources=m.shared_resources)
        od, obd = MV._resolve_observation_vantages(len(per), m.observations)
        cases.append({
            "name": name, "payload": payload, "vehicles": vehicles, "algorithm": algo, "objective": obj,
            "alloc": alloc, "orders": orders, "precedence": [list(p) for p in prec],
            "tl": [spans(pv["tl"]) for pv in per],
            "times": [[[float(pt["t_start"]), float(pt["t_end"])] for pt in pv["per_trip"]] for pv in per],
            "core_time_s": [pv["core"]["time_s"] for pv in per],
            "joint": {"delay": jd, "charger_delay": jbd["charger_delay"], "resource_delay": jbd["resource_delay"],
                      "resource_waits": [[k, w] for k, w in jbd["resource_waits"].items()]},
            "crowd": MV._resolve_spacetime_crowding(per),
            "precedence_delay": MV._resolve_cross_vehicle_precedence(per, alloc, prec, trips),
            "observation": {"delay": od, "vantages": [[k, v] for k, v in obd.get("vantages", {}).items()]},
            "vehicle_conflicts": MV._vehicle_conflicts(per), "charger_conflicts": MV._charger_conflicts(per, m),
            "temporal_conflicts": MV._temporal_conflicts(per), "haul_path_conflicts": MV._haul_path_conflicts(per),
            "health": [MV._rover_health(pv) for pv in per]})

    main = payloads["haul_two_pairs"]
    run("two_pairs_x2", main, 2)
    run("two_pairs_x3", main, 3)
    run("two_pairs_x4_greedy", main, 4, algo="greedy", obj="energy")
    shared = copy.deepcopy(main)
    shared["shared_resources"] = [
        {"id": "dump", "kind": "dump", "capacity": 1, "sites": [[152.5, 152.5], [277.5, 377.5]]},
        {"id": "pit", "kind": "pit", "capacity": 1, "sites": [[2.5, 52.5], [52.5, 302.5]]}]
    shared["observations"] = [
        {"vehicle": 0, "x": 150.0, "y": 150.0, "t_start": 0.0, "t_end": 600.0, "kind": "solar"},
        {"vehicle": 1, "x": 155.0, "y": 152.0, "t_start": 100.0, "t_end": 400.0, "kind": "meerkat"},
        {"vehicle": 1, "x": 300.0, "y": 300.0, "t_start": 50.0, "t_end": 90.0, "kind": "solar"}]
    run("shared_resources_x2", shared, 2)
    capped = copy.deepcopy(shared)
    capped["charger_capacity"] = 2
    run("charger_cap2_x3", capped, 3)
    prec = copy.deepcopy(main)
    prec["precedence"] = [[main["orders"][0]["action"], main["orders"][1]["action"]]]
    run("precedence_x2", prec, 2)
    run("deficit_x2", payloads["deficit"], 2)
    twin = copy.deepcopy(payloads["heavy_rassor"])
    twin["orders"] = list(twin["orders"]) + [dict(o, action=o["action"] + "_east", x=o["x"] + 5.0)
                                             for o in payloads["heavy_rassor"]["orders"]]
    run("heavy_twin_x2", twin, 2)
    run("heavy_rassor_x2", payloads["heavy_rassor"], 2)
    assert any(max(c["joint"]["charger_delay"]) > 0 for c in cases), "vacuity: a charger wait"
    assert any(c["joint"]["resource_waits"] for c in cases), "vacuity: a resource wait"
    assert any(max(c["crowd"]) > 0 for c in cases), "vacuity: a crowding wait"
    assert any(max(c["observation"]["delay"]) > 0 for c in cases), "vacuity: an observation wait"
    assert any(c["haul_path_conflicts"] for c in cases) and any(c["temporal_conflicts"] for c in cases)

    # SYNTHETIC timelines (labelled): branches the real fleets above do not reach
    def seg(kind, t0, t1, a, b=None, batt=(100.0, 90.0)):
        b = b or a
        return dict(t0=t0, t1=t1, kind=kind, batt0=batt[0], batt1=batt[1], mass=0.0, speed=0.0,
                    x0=a[0], y0=a[1], x1=b[0], y1=b[1])

    sites = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
    synth_trips = [{"site": list(s), "kind": "dig", "dig_e": 1.0, "haul_e": 0.0} for s in sites]
    syn_per = [
        {"vehicle": 0, "tl": [seg("charge", 0.0, 100.0, (0, 0)), seg("dig", 100.0, 300.0, (0, 0), batt=(100.0, 10.0))],
         "per_trip": [{"trip": synth_trips[0], "t_start": 0.0, "t_end": 300.0}],
         "core": {"feasible": True, "charges": 1, "infeasible_reasons": []}},
        {"vehicle": 1, "tl": [seg("charge", 50.0, 150.0, (0, 0)), seg("drive", 150.0, 200.0, (0, 0), (50, 0))],
         "per_trip": [{"trip": synth_trips[1], "t_start": 50.0, "t_end": 250.0}],
         "core": {"feasible": False, "charges": 1, "infeasible_reasons": ["a", "b", "c", "d"]}},
        {"vehicle": 2, "tl": [seg("charge", 60.0, 120.0, (0, 0)), seg("dig", 120.0, 400.0, (100, 0))],
         "per_trip": [{"trip": synth_trips[2], "t_start": 10.0, "t_end": 400.0}],
         "core": {"feasible": True, "charges": 1, "infeasible_reasons": []}},
    ]
    syn_alloc = [[0], [1], [2]]
    res2 = [{"id": "yard", "kind": "dump", "capacity": 2, "sites": [[0.0, 0.0], [50.0, 0.2], [100.0, 0.0]]}]
    synthetic = []
    for cap in (1, 2):
        jd, jbd = MV._resolve_joint_resources(syn_per, charger_capacity=cap, shared_resources=res2)
        synthetic.append({"charger_capacity": cap, "resources": res2,
                          "joint": {"delay": jd, "charger_delay": jbd["charger_delay"],
                                    "resource_delay": jbd["resource_delay"],
                                    "resource_waits": [[k, w] for k, w in jbd["resource_waits"].items()]}})
    # a charge and a resource visit arriving together: the charger is placed first (kind before id, and the id
    # "alpha" sorts before "charger"); rover 0 already holds the charger and later the resource, so the order
    # decides who waits
    tie_per = [
        {"vehicle": 0, "tl": [seg("charge", 0.0, 100.0, (0, 0))],
         "per_trip": [{"trip": synth_trips[0], "t_start": 50.0, "t_end": 150.0}], "core": {}},
        {"vehicle": 1, "tl": [seg("charge", 0.0, 40.0, (0, 0))],
         "per_trip": [{"trip": synth_trips[1], "t_start": 0.0, "t_end": 80.0}], "core": {}}]
    tie_res = [{"id": "alpha", "kind": "pit", "capacity": 1, "sites": [[0.0, 0.0], [50.0, 0.0]]}]
    tjd, tjbd = MV._resolve_joint_resources(tie_per, charger_capacity=1, shared_resources=tie_res)
    tie = {"tl": [spans(pv["tl"]) for pv in tie_per],
           "times": [[[pt["t_start"], pt["t_end"]] for pt in pv["per_trip"]] for pv in tie_per],
           "resources": tie_res, "delay": tjd, "charger_delay": tjbd["charger_delay"],
           "resource_delay": tjbd["resource_delay"]}
    chain = [(0, 1), (1, 2)]
    syn = {"tl": [spans(pv["tl"]) for pv in syn_per],
           "times": [[[pt["t_start"], pt["t_end"]] for pt in pv["per_trip"]] for pv in syn_per],
           "sites": [list(s) for s in sites], "alloc": syn_alloc,
           "core": [{"feasible": pv["core"]["feasible"], "charges": pv["core"]["charges"],
                     "infeasible_reasons": pv["core"]["infeasible_reasons"]} for pv in syn_per],
           "joint": synthetic, "chain": [list(p) for p in chain],
           "chain_delay": MV._resolve_cross_vehicle_precedence(syn_per, syn_alloc, chain, synth_trips),
           "crowd": MV._resolve_spacetime_crowding(syn_per),
           "health": [MV._rover_health(pv) for pv in syn_per], "tie": tie}
    refusals = []
    for obs in ([{"vehicle": 3, "x": 0, "y": 0, "t_start": 0, "t_end": 1, "kind": "solar"}],
                [{"vehicle": 0, "x": 0, "y": 0, "t_start": 5, "t_end": 5, "kind": "solar"}]):
        try:
            MV._resolve_observation_vantages(3, obs)
        except ValueError as e:
            refusals.append({"observations": obs, "error": str(e)})
    assert len(refusals) == 2
    segs = []
    for a0, a1, b0, b1 in [((0, 0), (10, 0), (5, 5), (5, -5)), ((0, 0), (0, 0), (3, 4), (3, 4)),
                           ((0, 0), (0, 0), (-5, 1), (5, 1)), ((0, 0), (10, 0), (12, 3), (12, 3)),
                           ((0, 0), (10, 0), (0, 2), (10, 2)), ((0, 0), (10, 0), (-3, 4), (-1, 9)),
                           ((0, 0), (10, 0), (14, 1), (20, 7))]:
        segs.append({"a0": a0, "a1": a1, "b0": b0, "b1": b1, "d": MV._seg_seg_min_dist(a0, a1, b0, b1)})
    write_fixture(ORACLE_FIXTURES, "fleet_cases", "oracle/build_fixtures.py::fleet_cases (lode.planner_multivehicle "
                  "on fleets over the real Haworth route window; placements and the timeline cases SYNTHETIC, labelled)",
                  ["lode/planner_multivehicle.py", "lode/fleet_resources.py", "lode/planner_optimize.py",
                   "lode/planner_sim.py", "lode/planner_trips.py", "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases, "synthetic": syn, "refusals": refusals, "segments": segs})


def plan_cases() -> None:
    """Plan assembly (RW-33d2a): lode.planner_assembly.plan_and_simulate for one rover and for fleets, on the
    trips_cases missions over the real Haworth route window -- visit order, rover tags, the core totals, the
    optimality labels and warnings, every fleet figure, and the report totals and energy ledger (RW-33d2c) with the
    Python's report constants. The multi-site layouts, declared resources and observations, the closing recharge
    windows that strand a rover, the 12 W idle draw, the dig-energy factor, the lander and the keep-out are
    SYNTHETIC (labelled) settings on the real terrain."""
    import copy
    import warnings as W

    import lode.mission_planner as MP
    from lode.planner_assembly import plan_and_simulate

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    from lode.planner_model import mission_from_dict

    fleet_keys = ("makespan_parallel_s", "charger_wait_s", "crowd_wait_s", "precedence_wait_s",
                  "temporal_conflicts", "haul_path_conflicts", "fleet_needs_replan", "fleet_replanned",
                  "unreallocatable_trips")
    report_keys = ("cut_kg", "fill_kg", "sinter_kg", "surplus_kg", "waypoint_sequence", "deficit_kg", "import_kg",
                   "offload_energy_J", "drum_cycles", "cut_passes", "dig_energy_bounds_MJ", "plan_uncertainty",
                   "lift_energy_J", "routed_haul", "traverse_cap_deg", "haul_detour_frac", "n_keepouts",
                   "keepout_conflicts", "return_to_lander", "relocalization")
    cases = []

    def run(name, payload, vehicles=1, algo="nearest", obj="time", idle=0.0):
        m = mission_from_dict(payload)
        saved = MP.IDLE_POWER_W
        MP.IDLE_POWER_W = idle
        try:
            with W.catch_warnings(record=True) as caught:
                W.simplefilter("always")
                trips, _flows, per_trip, _tl, t = plan_and_simulate(
                    m, dem=dem, dem_origin=origin, max_traverse_slope_deg=25.0,
                    algorithm=algo, objective=obj, vehicles=vehicles)
        finally:
            MP.IDLE_POWER_W = saved
        case = {"name": name, "payload": payload, "vehicles": vehicles, "algorithm": algo, "objective": obj,
                "idle_power_w": idle,
                "sites": [list(tr["site"]) for tr in trips], "vehicle": [int(tr.get("vehicle", 0)) for tr in trips],
                "times": [[float(p["t_start"]), float(p["t_end"])] for p in per_trip],
                "warnings": [str(w.message) for w in caught if issubclass(w.category, UserWarning)],
                "totals": {k: t[k] for k in ("time_s", "mass_kg", "energy_J", "charges", "distance_m", "avg_power_w",
                                             "survival_energy_J", "feasible", "infeasible_reasons",
                                             "resolved_algorithm", "optimality", "objective_exact", "solved_metric",
                                             "n_precedence", "makespan_s", "vehicle_conflicts", "charger_conflicts",
                                             "blocked_legs")}}
        case["report"] = {k: t[k] for k in report_keys}
        case["ledger"] = t["energy_ledger"]
        if vehicles > 1:
            case["fleet"] = {k: t[k] for k in fleet_keys}
            case["fleet"]["resource_wait_s"] = t.get("resource_wait_s", 0.0)
            case["fleet"]["observation_wait_s"] = t.get("observation_wait_s", 0.0)
            case["fleet"]["resource_waits"] = [[k, w] for k, w in t.get("resource_waits", {}).items()]
            case["fleet"]["detail"] = [
                {k: d[k] for k in ("vehicle", "n_trips", "time_s", "energy_J", "distance_m", "charges",
                                   "charger_wait_s", "crowd_wait_s", "precedence_wait_s", "track", "health")}
                for d in t["vehicles_detail"]]
        cases.append(case)
        return case

    main = payloads["haul_two_pairs"]
    for algo in ("nearest", "auto", "two_opt"):
        run(f"two_pairs_{algo}", main, algo=algo)
    run("two_pairs_energy_idle", main, obj="energy", idle=12.0)
    many = copy.deepcopy(main)
    reachable = [(o["x"], o["y"]) for nm in ("deficit", "cuts_only", "heavy_rassor") for o in payloads[nm]["orders"]]
    many["orders"] = list(main["orders"]) + [
        {"action": f"g{k}", "kind": "goto", "x": x, "y": y} for k, (x, y) in enumerate(reachable[:4], 1)]
    run("many_brute_degrades", many, algo="brute")
    for nm in ("deficit", "unreachable_fill", "cuts_only", "heavy_rassor"):
        run(nm, payloads[nm])
    run("two_pairs_x2", main, vehicles=2)
    run("two_pairs_x3_idle", main, vehicles=3, idle=12.0)
    shared = copy.deepcopy(main)
    shared["shared_resources"] = [
        {"id": "dump", "kind": "dump", "capacity": 1, "sites": [[152.5, 152.5], [277.5, 377.5]]},
        {"id": "pit", "kind": "pit", "capacity": 1, "sites": [[2.5, 52.5], [52.5, 302.5]]}]
    shared["observations"] = [
        {"vehicle": 0, "x": 150.0, "y": 150.0, "t_start": 0.0, "t_end": 600.0, "kind": "solar"},
        {"vehicle": 1, "x": 155.0, "y": 152.0, "t_start": 100.0, "t_end": 400.0, "kind": "meerkat"}]
    run("shared_x2", shared, vehicles=2)
    prec = copy.deepcopy(main)
    prec["precedence"] = [[main["orders"][0]["action"], main["orders"][1]["action"]]]
    run("precedence_x2", prec, vehicles=2)
    run("precedence_single", prec)
    factored = copy.deepcopy(main)
    factored["dig_energy_factor"] = 1.3
    factored["lander"] = [60.0, 210.0]
    factored["return_buffer_frac"] = 0.35
    run("factor_lander", factored)
    walled = copy.deepcopy(main)
    walled["keepouts"] = [{"x": 7.5, "y": 202.5, "r": 3.0}]
    run("keepout_over_waypoint", walled)
    # one short look-around beside the charger: no cuts, no drum cycles, a traverse shorter than one fix interval,
    # and a lander whose furthest plan point is the charger itself
    run("short_look", {"body": "moon", "charger": [152.5, 197.5], "lander": [149.0, 194.0],
                       "orders": [{"action": "look", "kind": "goto", "x": 150.0, "y": 195.0}]})
    unordered = copy.deepcopy(main)
    # reallocation runs only when no precedence spans the fleet; consecutive gotos chain automatically
    unordered["precedence"] = []
    unordered["orders"] = [o for o in main["orders"] if o["kind"] != "goto"]
    free = run("unordered_x2", unordered, vehicles=2)
    times = sorted(d["time_s"] for d in free["fleet"]["detail"])
    closing = copy.deepcopy(unordered)
    closing["mission_windows"] = {"recharge": [[0.0, (times[0] + times[-1]) / 2.0]]}
    stranded = run("window_strands_x2", closing, vehicles=2)
    assert stranded["fleet"]["fleet_replanned"], "vacuity: the closing window strands a rover and reallocates"
    early = copy.deepcopy(unordered)
    early["mission_windows"] = {"recharge": [[0.0, times[0] * 1.05]]}
    dropped = run("window_drops_x2", early, vehicles=2)
    assert dropped["fleet"]["unreallocatable_trips"] > 0 and dropped["totals"]["feasible"], \
        "vacuity: work no lone rover finishes is dropped while the Python still calls the fleet feasible"
    assert any(c["warnings"] for c in cases), "vacuity: a degraded solver warns"
    assert any(not c["totals"]["feasible"] for c in cases if c["vehicles"] == 1), "vacuity: a blocked route"
    assert any(c["report"]["keepout_conflicts"] for c in cases), "vacuity: an order inside a keep-out"
    import lode.lander_return as LR
    import lode.planner_assembly as PA
    import lode.planner_constants as PC
    import lode.relocalization as REL
    from stewie.physics import rassor_mass_model as RM
    from stewie.specs import ipex_specs as S
    lo, hi = S.dig_energy_bounds_j_per_kg()
    report_params = {"drum_rate_ratio": lo / hi, "ipex_dig_j_per_kg": hi, "max_cut_per_pass_m": S.max_cut_per_pass_m(),
                     "fill_mpe_frac": RM.FDC_MPE_HALF_FULL, "localization_margin_m": PC.LOCALIZATION_MARGIN_M,
                     "relocalize_drift_tol_m": PA.RELOCALIZE_DRIFT_TOL_M, "drift_frac": REL.DEFAULT_DRIFT_FRAC,
                     "fix_maneuver_s": REL.DEFAULT_FIX_MANEUVER_S, "arm_lift_height_m": RM.ARM_LIFT_HEIGHT_M,
                     "arm_lift_efficiency": RM.ARM_LIFT_EFFICIENCY, "ipex_rover_mass_kg": PC.ROVER_MASS_KG,
                     "default_return_buffer_frac": LR.DEFAULT_RETURN_BUFFER_FRAC}
    refusals = []
    cyc = copy.deepcopy(main)
    a0, a1 = main["orders"][0]["action"], main["orders"][1]["action"]
    cyc["precedence"] = [[a0, a1], [a1, a0]]
    for vehicles in (1, 2):
        try:
            plan_and_simulate(mission_from_dict(cyc), dem=dem, dem_origin=origin, vehicles=vehicles)
        except (RuntimeError, ValueError) as e:
            refusals.append({"payload": cyc, "vehicles": vehicles, "error": str(e)})
    assert len(refusals) == 2
    write_fixture(ORACLE_FIXTURES, "plan_cases", "oracle/build_fixtures.py::plan_cases (lode.planner_assembly."
                  "plan_and_simulate over the real Haworth route window; layouts, resources, observations, the "
                  "closing window and the idle draw SYNTHETIC, labelled)",
                  ["lode/planner_assembly.py", "lode/planner_multivehicle.py", "lode/planner_optimize.py",
                   "lode/planner_sim.py", "lode/planner_trips.py", "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases, "refusals": refusals, "report_params": report_params})


def plan_ir_cases() -> None:
    """Executable plan IR (RW-33d2b): lode.planner_views.plan_ir for one rover and fleets over the real Haworth route
    window -- every action, precondition, waypoint polyline, the precedence DAG, the headline expectations and the
    content-hash plan_id. Each case also records the mission vehicle's planning context: the Python IR prices drive
    legs and the reserve with the IPEx module constants whatever the vehicle (D-R95). Multi-site layouts and the
    footprint shape are SYNTHETIC placements on the real terrain (labelled). The Rust IR splits an action one charge
    cannot finish into per-charge parts (D-R96); the Python IR here is the unsplit reference."""
    import copy

    from lode.planner_model import mission_from_dict, plan_context
    from lode.planner_views import plan_ir

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    cases = []

    def run(name, payload, vehicles=1, algo="nearest", obj="time"):
        m = mission_from_dict(payload)
        ir = plan_ir(m, dem=dem, dem_origin=origin, max_traverse_slope_deg=25.0, algorithm=algo, objective=obj,
                     vehicles=vehicles)
        ir.pop("provenance")                                 # hashes the Python object dump; RW-33f defines Rust's
        ctx = plan_context(m)
        cases.append({"name": name, "payload": payload, "vehicles": vehicles, "algorithm": algo, "objective": obj,
                      "vehicle": m.vehicle, "ctx": {"drive_j_per_m": ctx.drive_j_per_m,
                                                    "drive_speed_ms": ctx.drive_speed_ms,
                                                    "battery_j": ctx.battery_j,
                                                    "reserve_j": ctx.reserve_frac * ctx.battery_j},
                      "ir": ir})

    main = payloads["haul_two_pairs"]
    run("two_pairs", main)
    run("two_pairs_auto_energy", main, algo="auto", obj="energy")
    for nm in ("deficit", "unreachable_fill", "cuts_only", "heavy_rassor"):
        run(nm, payloads[nm])
    shaped = copy.deepcopy(main)
    shaped["orders"][0] = dict(shaped["orders"][0], shape={"kind": "rectangle", "w": 4.0, "h": 2.5, "theta_deg": 30.0})
    run("shaped_footprint", shaped)
    small = copy.deepcopy(main)
    small["orders"] = [dict(o, footprint_m2=1.0, depth_m=0.05) if o["kind"] != "goto" else o for o in main["orders"]]
    run("small_orders", small)
    run("small_orders_x2", small, vehicles=2)
    walled = copy.deepcopy(small)
    walled["orders"] = list(small["orders"]) + [{"action": "probe", "kind": "goto", "x": 142.5, "y": -47.5}]
    run("blocked_waypoint", walled)
    run("two_pairs_x2", main, vehicles=2)
    run("two_pairs_x3", main, vehicles=3)
    assert any(not c["ir"]["feasible"] for c in cases), "vacuity: a blocked leg makes the IR infeasible"
    assert any(a.get("footprint") for c in cases for a in c["ir"]["actions"]), "vacuity: a footprint view"
    assert any(c["ir"]["precedence"] for c in cases), "vacuity: a precedence DAG"
    assert any(c["vehicle"] != "ipex" for c in cases), "vacuity: a non-IPEx vehicle"
    assert any(all(a["pre"]["battery_J_min"] <= c["ctx"]["battery_j"] for a in c["ir"]["actions"]) for c in cases), \
        "vacuity: an IR whose every action fits one charge (no split, so identical to the Rust IR)"
    write_fixture(ORACLE_FIXTURES, "plan_ir_cases", "oracle/build_fixtures.py::plan_ir_cases (lode.planner_views.plan_ir "
                  "over the real Haworth route window; layouts and the footprint shape SYNTHETIC, labelled)",
                  ["lode/planner_views.py", "lode/planner_assembly.py", "lode/planner_routing.py",
                   "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases})


def acceptance_cases() -> None:
    """Pooled plan acceptance (RW-33e1): lode.planner_acceptance.validate_plan on missions over the real Haworth route
    window -- material realizability on the conserved column, slope and off-DEM siting, as-built flatness, berm rise,
    repose and bearing capacity -- for every footprint shape. Each case records the stock Python result AND the result
    with the acceptance column built at bank density (D-R98): the stock column takes ColumnState's default surface
    density, so its 10 m mantle stands 14.8 m tall and a cut drops the surface 1.48x its depth. The two differ only in
    the repose (flank-slope) figures. Multi-site layouts, shapes, the edge order and the design load are SYNTHETIC
    (labelled) settings on the real terrain."""
    import copy
    import inspect

    import lode.planner_acceptance as PA
    from lode.planner_model import mission_from_dict

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    stock_cs = PA.ColumnState

    def bank_density_column(**kw):
        # the mantle at the density its mass was loaded at (mass_areal = rho_bank * 10 m)
        kw.setdefault("density", kw["mass_areal"] / 10.0)
        return stock_cs(**kw)

    def clean(r):
        return {k: v for k, v in r.items() if k != "terrain_grids"}

    cases = []

    def run(name, payload, **kw):
        m = mission_from_dict(payload)
        stock = clean(PA.validate_plan(m, dem=dem, dem_origin=origin, **kw))
        PA.ColumnState = bank_density_column
        try:
            fixed = clean(PA.validate_plan(m, dem=dem, dem_origin=origin, **kw))
        finally:
            PA.ColumnState = stock_cs
        def near(a, b):
            if isinstance(a, float) and isinstance(b, float):
                return abs(a - b) <= 1e-9 * max(1.0, abs(b))
            if isinstance(a, dict) and isinstance(b, dict):
                return a.keys() == b.keys() and all(near(a[k], b[k]) for k in a)
            if isinstance(a, list) and isinstance(b, list):
                return len(a) == len(b) and all(near(x, y) for x, y in zip(a, b))
            return a == b

        for k in fixed:
            if k not in ("repose", "repose_pass"):
                assert near(fixed[k], stock[k]), f"{name}: D-R98 changed {k}"
        sig = inspect.signature(PA.validate_plan).parameters
        params = {k: v.default for k, v in sig.items()
                  if v.default is not inspect.Parameter.empty and k not in ("dem", "dem_origin", "return_grids")}
        params.update(kw)
        cases.append({"name": name, "payload": payload, "params": params, "stock": stock, "result": fixed})

    main = payloads["haul_two_pairs"]
    run("two_pairs", main)
    for nm in ("deficit", "cuts_only", "heavy_rassor", "unreachable_fill"):
        run(nm, payloads[nm])
    shaped = copy.deepcopy(main)
    shaped["orders"][0] = dict(shaped["orders"][0], shape={"kind": "rectangle", "w": 4.0, "h": 2.5, "theta_deg": 30.0})
    shaped["orders"][1] = dict(shaped["orders"][1], shape={"kind": "corridor", "length": 20.0, "width": 2.0,
                                                           "theta_deg": 45.0})
    shaped["orders"][2] = dict(shaped["orders"][2], shape={"kind": "circle", "r": 3.0})
    shaped["orders"][3] = dict(shaped["orders"][3], shape={"kind": "polygon",
                                                           "vertices": [[-3, -2], [4, -2], [5, 3], [-2, 4]]})
    run("shaped", shaped, bearing_load_pa=20000.0, accept_flatness_tol_m=0.05)
    run("shaped_heavy_load", shaped, bearing_load_pa=200000.0, bearing_fs=2.0, max_slope_deg=25.0)
    small = copy.deepcopy(main)
    small["orders"] = [dict(o, footprint_m2=1.0, depth_m=0.05) if o["kind"] != "goto" else o for o in main["orders"]]
    run("small_orders", small, max_slope_deg=30.0)
    edge = copy.deepcopy(main)
    far = n * 5.0 - origin[0] + 3.0                          # just past the window's far side
    edge["orders"] = list(main["orders"]) + [{"action": "edge cut", "kind": "cut", "x": -103.0, "y": 0.0,
                                              "footprint_m2": 40.0, "depth_m": 0.1},
                                             {"action": "far fill", "kind": "fill", "x": far, "y": 60.0,
                                              "footprint_m2": 40.0, "depth_m": 0.1}]
    run("off_dem", edge)
    deep = copy.deepcopy(payloads["cuts_only"])
    deep["orders"][0] = dict(deep["orders"][0], depth_m=12.0)
    run("below_the_mantle", deep, max_slope_deg=90.0)     # siting passes, so only the datum floor can fail it
    assert any(len(c["result"]["off_dem_orders"]) == 2 for c in cases), "vacuity: orders off both DEM edges"
    floor = [c for c in cases if c["name"] == "below_the_mantle"][0]["result"]
    assert not floor["feasible"] and not floor["slope_violations"], "vacuity: the datum floor alone fails a plan"
    assert any(c["result"]["slope_violations"] for c in cases), "vacuity: a slope violation"
    assert any(not c["result"]["feasible"] for c in cases) and any(c["result"]["feasible"] for c in cases)
    assert any(b.get("firming_recommended") for c in cases for b in c["result"]["bearing"]), "vacuity: firming"
    assert any(c["result"]["repose"] != c["stock"]["repose"] for c in cases), "vacuity: D-R98 changes repose"
    write_fixture(ORACLE_FIXTURES, "acceptance_cases", "oracle/build_fixtures.py::acceptance_cases (lode.planner_"
                  "acceptance.validate_plan over the real Haworth route window, stock and at bank density; layouts, "
                  "shapes, the edge order and the design loads SYNTHETIC, labelled)",
                  ["lode/planner_acceptance.py", "stewie/physics/column_state.py", "lode/gis_export.py",
                   "forge/bearing.py", "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases})


def replay_cases() -> None:
    """Ordered replay acceptance (RW-33e2): lode.planner_acceptance.execute_plan_acceptance walks each plan's trips in
    order through the capacity-bounded drum, on missions over the real Haworth route window planned by
    plan_and_simulate. Like acceptance_cases, each case records the stock Python result and the bank-density column
    (D-R98); the as-built surface is recorded as its change from the untouched column (every changed cell's index and
    height change), with the untouched surface taken from a replay of no trips. Layouts are SYNTHETIC placements on
    the real terrain (labelled)."""
    import copy

    import lode.planner_acceptance as PA
    from lode.planner_assembly import plan_and_simulate
    from lode.planner_model import mission_from_dict

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    stock_cs = PA.ColumnState

    def bank_density_column(**kw):
        kw.setdefault("density", kw["mass_areal"] / 10.0)
        return stock_cs(**kw)

    def replay(m, trips):
        r = PA.execute_plan_acceptance(m, trips, dem=dem, dem_origin=origin)
        surface = r.pop("as_built")
        untouched = PA.execute_plan_acceptance(m, [], dem=dem, dem_origin=origin)["as_built"]
        delta = (surface - untouched).ravel()
        changed = np.nonzero(np.abs(delta) > 1e-12)[0]
        r["changed"] = [[int(i), float(delta[i])] for i in changed]
        return r

    cases = []

    def run(name, payload, vehicles=1):
        m = mission_from_dict(payload)
        trips = plan_and_simulate(m, dem=dem, dem_origin=origin, vehicles=vehicles)[0]
        stock = replay(m, trips)
        PA.ColumnState = bank_density_column
        try:
            fixed = replay(m, trips)
        finally:
            PA.ColumnState = stock_cs
        for k in ("feasible", "mass_conserved", "shuttle_cycles", "placed_kg", "max_simultaneous_drum_kg"):
            assert abs(fixed[k] - stock[k]) <= 1e-9 * max(1.0, abs(stock[k])), f"{name}: D-R98 changed {k}"
        cases.append({"name": name, "payload": payload, "vehicles": vehicles, "stock": stock, "result": fixed})

    main = payloads["haul_two_pairs"]
    run("two_pairs", main)
    run("two_pairs_x2", main, vehicles=2)
    for nm in ("deficit", "cuts_only", "heavy_rassor", "unreachable_fill"):
        run(nm, payloads[nm])
    small = copy.deepcopy(main)
    small["orders"] = [dict(o, footprint_m2=1.0, depth_m=0.05) if o["kind"] != "goto" else o for o in main["orders"]]
    run("small_orders", small)
    overlap = copy.deepcopy(payloads["deficit"])
    overlap["orders"] = list(overlap["orders"]) + [
        {"action": "regrade", "kind": "cut", "x": 204.5, "y": 252.5, "footprint_m2": 16.0, "depth_m": 0.05},
        {"action": "berm", "kind": "fill", "x": 54.5, "y": 104.5, "footprint_m2": 9.0, "depth_m": 0.1}]
    run("overlapping_footprints", overlap)
    assert any(c["result"]["feasible"] for c in cases) and any(not c["result"]["feasible"] for c in cases)
    assert any(c["result"]["changed"] != c["stock"]["changed"] for c in cases), "vacuity: D-R98 moves the surface"
    write_fixture(ORACLE_FIXTURES, "replay_cases", "oracle/build_fixtures.py::replay_cases (lode.planner_acceptance."
                  "execute_plan_acceptance over the real Haworth route window, stock and at bank density; layouts "
                  "SYNTHETIC, labelled)",
                  ["lode/planner_acceptance.py", "lode/planner_assembly.py", "stewie/physics/column_state.py",
                   "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases})


def build_cases() -> None:
    """LEAP construction (RW-34a): leap.structures.decompose for every template (defaults, custom sizes including a
    half-metre side that pins Python's round-half-even note formatting, and the refusals) and leap.siteplan.
    analyze_siteplan over base layouts. Every placement and size is a SYNTHETIC authored layout (labelled); the
    densities are the soil baseline's."""
    from leap import siteplan as SP
    from leap import structures as ST

    templates = []
    for name in sorted(ST.STRUCTURES):
        templates.append({"name": name, "x": 10.0, "y": -4.0, "params": {}, "orders": ST.decompose(name, 10.0, -4.0)})
    custom = [("landing_pad", {"side_m": 6.5, "cut_depth_m": 0.08}), ("haul_road", {"length_m": 42.5, "width_m": 2.5}),
              ("crater_fill", {"radius_m": 3.0, "depth_m": 0.25}), ("blast_berm", {"height_m": 0.9}),
              ("habitat_foundation", {"side_m": 7.0, "fill_height_m": 0.1}), ("trench", {"depth_m": 1.2})]
    for name, params in custom:
        templates.append({"name": name, "x": -3.0, "y": 7.5, "params": params,
                          "orders": ST.decompose(name, -3.0, 7.5, **params)})
    refusals = []
    for name, params in [("moon_base", {}), ("landing_pad", {"side_m": 0.0}), ("trench", {"depth_m": -1.5}),
                         ("crater_fill", {"radius_m": 0})]:
        try:
            accepted = ST.decompose(name, 0.0, 0.0, **params)
            # the cut-only templates skip the positivity check (D-R101: the Rust refuses these too)
            refusals.append({"name": name, "params": params, "error": None, "python_accepted": accepted})
        except ValueError as e:
            refusals.append({"name": name, "params": params, "error": str(e)})
    assert any(r["error"] is None for r in refusals), "vacuity: a non-positive size the Python accepts"
    layouts = {
        "balanced_pair": [("landing_pad", 0.0, 0.0, {}), ("habitat_foundation", 60.0, 0.0, {})],
        "surplus": [("borrow_pit", 0.0, 0.0, {}), ("haul_road", 40.0, 10.0, {}), ("blast_berm", 90.0, 0.0, {})],
        "mixed": [("crater_fill", 0.0, 0.0, {"radius_m": 12.0}), ("blast_berm", 50.0, 30.0, {}),
                    ("solar_pad", -40.0, 5.0, {})],
        "overlapping": [("landing_pad", 0.0, 0.0, {}), ("solar_pad", 4.0, 1.0, {}), ("trench", 30.0, -2.0, {})],
        "close_but_clear": [("solar_pad", 0.0, 0.0, {}), ("borrow_pit", 9.5, 0.0, {})],
        # the berm's borrow pit sits beside the crater, so the larger crater fill drains it first
        "shared_source": [("crater_fill", 0.0, 0.0, {}), ("blast_berm", 12.0, 0.0, {"length_m": 6.0})],
        "base": [("landing_pad", 0.0, 0.0, {}), ("habitat_foundation", 40.0, 25.0, {}),
                 ("blast_berm", -30.0, 10.0, {"length_m": 20.0}), ("borrow_pit", 15.0, -35.0, {"depth_m": 0.5}),
                 ("crater_fill", 70.0, -20.0, {"radius_m": 5.0}), ("solar_pad", -60.0, -40.0, {})],
    }
    plans = []
    for name, layout in layouts.items():
        placed = [SP.PlacedStructure(n, x, y, p) for n, x, y, p in layout]
        plans.append({"name": name, "placed": [{"name": n, "x": x, "y": y, "params": p} for n, x, y, p in layout],
                      "min_gap_m": 2.0, "report": SP.analyze_siteplan(placed).to_dict()})
    assert any("overlap" in a for p in plans for a in p["report"]["advisories"]), "vacuity: an overlap"
    assert any("surplus" in a for p in plans for a in p["report"]["advisories"])
    # every template balances its own fills, so no template layout can be in deficit
    close = [p for p in plans if p["name"] == "close_but_clear"][0]["report"]["clearances"][0]
    assert 0.0 <= close["gap_m"] < 2.0 and not close["overlap"], "vacuity: a sub-minimum gap the Python does not advise"
    write_fixture(ORACLE_FIXTURES, "build_cases", "oracle/build_fixtures.py::build_cases (leap.structures + "
                  "leap.siteplan; layouts and sizes SYNTHETIC, labelled)",
                  ["leap/structures.py", "leap/siteplan.py", "stewie/specs/constants.py"],
                  {"rho_bank": ST.RHO_BANK, "rho_loose": ST.RHO_LOOSE, "templates": templates,
                   "refusals": refusals, "plans": plans})


def record_cases() -> None:
    """Conserved as-built record (RW-34b): lode.planner_acceptance.mission_terrain_delta and record_mission into a
    stewie.twin.terrain_memory.TerrainMemory, and the moved-regolith estimate (lode.regolith_volume.
    estimate_moved_regolith, stewie.contracts.RegolithVolumeEstimate.from_delta), for missions over the real
    Haworth route window, on the bank-density acceptance column (D-R98). Two missions are recorded into one site
    memory in turn. Layouts, the estimate's error envelopes and the drum readings are SYNTHETIC (labelled)."""
    import copy
    import math

    import lode.planner_acceptance as PA
    from lode.planner_model import mission_from_dict
    from lode.regolith_volume import estimate_moved_regolith
    from stewie.contracts import RegolithVolumeEstimate
    from stewie.physics import rassor_mass_model as RM
    from stewie.twin.terrain_memory import TerrainMemory

    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    base, _ = __import__("stewie.physics.worksite", fromlist=["coarse_base_from_bundle"]).coarse_base_from_bundle(
        os.path.join(REPO, "samples", "lunar_dem", "haworth_10km_5m"))
    r0, c0, n = ROUTE_WINDOW
    Z = np.array(base.derive_height()[r0:r0 + n, c0:c0 + n], dtype=np.float64)
    dem, origin = (Z, 5.0), (100.0, 50.0)
    payloads = {mc["name"]: mc["payload"] for mc in tc["missions"]}
    stock_cs = PA.ColumnState

    def bank_density_column(**kw):
        kw.setdefault("density", kw["mass_areal"] / 10.0)
        return stock_cs(**kw)

    def changed(grid):
        flat = np.asarray(grid, dtype=float).ravel()
        idx = np.nonzero(np.abs(flat) > 1e-12)[0]
        return [[int(i), float(flat[i])] for i in idx]

    main = payloads["haul_two_pairs"]
    small = copy.deepcopy(main)
    small["orders"] = [dict(o, footprint_m2=1.0, depth_m=0.05) if o["kind"] != "goto" else o for o in main["orders"]]
    missions = [("deficit", payloads["deficit"]), ("cuts_only", payloads["cuts_only"]), ("small_orders", small),
                ("two_pairs", main)]
    PA.ColumnState = bank_density_column
    try:
        deltas = {name: PA.mission_terrain_delta(mission_from_dict(p), dem=dem, dem_origin=origin)
                  for name, p in missions}
        # one site memory per cell size, covering every mission on that cell plus a 6-cell rim (deficit and
        # cuts_only share the 0.5 m cell, so the second records on top of the first)
        memories = {}
        for key in {round(d["cell_m"], 12) for d in deltas.values()}:
            ds = [d for d in deltas.values() if round(d["cell_m"], 12) == key]
            cell = ds[0]["cell_m"]
            x0, y0 = min(d["x0"] for d in ds) - 6 * cell, min(d["y0"] for d in ds) - 6 * cell
            x1 = max(d["x0"] + d["cols"] * cell for d in ds) + 6 * cell
            y1 = max(d["y0"] + d["rows"] * cell for d in ds) + 6 * cell
            memories[key] = TerrainMemory(site="haworth", rows=int(math.ceil((y1 - y0) / cell)),
                                          cols=int(math.ceil((x1 - x0) / cell)), cell_m=cell, origin=(x0, y0))
        cases = []
        for name, payload in missions:
            m = mission_from_dict(payload)
            d = deltas[name]
            rho_bank = m.density * __import__("lode.planner_balance", fromlist=["SWELL"]).SWELL
            mem = memories[round(d["cell_m"], 12)]
            placement = PA.record_mission(mem, m, dem=dem, dem_origin=origin)
            estimates = []
            # drum readings above half full (the published 2.56 %) and below it (the blended over-range band)
            for rmse, frac, drum in ((0.0, 0.0, None), (0.01, 0.05, 0.97), (0.0, 0.02, 1.4), (0.0, 0.0, 0.4)):
                kw = dict(density_kg_m3=rho_bank, spoil_density_kg_m3=m.density, height_rmse_m=rmse,
                          density_frac=frac, conserved_mass_kg=d["mass_moved_kg"],
                          drum_inferred_kg=None if drum is None else drum * min(d["mass_moved_kg"], 30.0))
                raw = estimate_moved_regolith(d["base"], d["as_built"], d["cell_m"], **kw)
                ev = RegolithVolumeEstimate.from_delta(d["base"], d["as_built"], d["cell_m"],
                                                       work_order_id=f"wo-{name}", before_source="conserved:base",
                                                       after_source="conserved:as_built",
                                                       transaction_id=f"tx-{name}", **{
                                                           k: v for k, v in kw.items() if k != "spoil_density_kg_m3"})
                estimates.append({"inputs": kw, "estimate": raw, "evidence": ev.model_dump()})
            cases.append({"name": name, "payload": payload, "x0": d["x0"], "y0": d["y0"], "cell_m": d["cell_m"],
                          "rows": d["rows"], "cols": d["cols"], "mass_moved_kg": d["mass_moved_kg"],
                          "rho_bank": rho_bank, "delta": changed(d["delta"]), "placement": placement,
                          "memory": {"rows": mem.rows, "cols": mem.cols, "origin": list(mem.origin),
                                     "summary": mem.summary(), "head": mem.chain[-1]["hash"]},
                          "estimates": estimates})
    finally:
        PA.ColumnState = stock_cs
    assert any(c["placement"]["version"] > 1 for c in cases), "vacuity: a second mission on one site memory"
    assert any(e["evidence"]["acceptance"] == "accepted" for c in cases for e in c["estimates"])
    assert any(e["evidence"]["acceptance"] == "review" for c in cases for e in c["estimates"])
    drum = {"mpe_all": RM.FDC_MPE_ALL, "mpe_with_outliers": RM.FDC_MPE_WITH_OUTLIERS,
            "mpe_half_full": RM.FDC_MPE_HALF_FULL, "half_full_kg": RM.HALF_FULL_KG}
    write_fixture(ORACLE_FIXTURES, "record_cases", "oracle/build_fixtures.py::record_cases (mission terrain delta, "
                  "Terrain Memory record and moved-regolith evidence over the real Haworth route window at bank "
                  "density; layouts, error envelopes and drum readings SYNTHETIC, labelled)",
                  ["lode/planner_acceptance.py", "lode/regolith_volume.py", "stewie/contracts/__init__.py",
                   "stewie/twin/terrain_memory.py", "stewie/physics/rassor_mass_model.py",
                   "crates/stewie-oracle/fixtures/trips_cases.payload.json"],
                  {"cases": cases, "drum": drum})


def illumination_cases() -> None:
    """Illumination route cost (RW-15a): dart.illumination_cost.illumination_cost (cast shadows, grazing-Sun
    saturation, map uncertainty, anchor line of sight) on a real 60x60 window of the Haworth route window, under the
    apparent Sun at real Haworth epochs (the SPICE vectors of ephem_topocentric, turned to topocentric azimuth and
    elevation here) and under fixed Sun angles that reach every branch (Sun down, grazing, high). The anchor
    positions and the map-uncertainty field are SYNTHETIC (labelled)."""
    from dart.illumination_cost import (GRAZING_EL_DEG, W_MAP_UNCERTAINTY, W_SATURATION, W_SHADOW, W_VISIBILITY,
                                        illumination_cost)
    from dart.visibility import viewshed

    with open(os.path.join(ORACLE_FIXTURES, "route_cases.payload.json")) as fh:
        rc = json.load(fh)
    rc = rc.get("payload", rc)
    with open(os.path.join(ORACLE_FIXTURES, "trips_cases.payload.json")) as fh:
        tc = json.load(fh)
    tc = tc.get("payload", tc)
    side = int(tc["window"][2])
    Z = np.asarray(rc["z"], dtype=np.float64).reshape(side, side)
    r0, c0, n = 40, 40, 60
    window = Z[r0:r0 + n, c0:c0 + n]
    cell = 5.0
    with open(os.path.join(ORACLE_FIXTURES, "ephem_topocentric.payload.json")) as fh:
        eph = json.load(fh)
    eph = eph.get("payload", eph)
    site = eph["sites"]["haworth"]
    lat, lon = np.radians(site["lat_deg"]), np.radians(site["lon_deg"])
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    north = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
    up = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])

    def azel(v):
        v = np.asarray(v, dtype=float)
        e, nn, u = float(v @ east), float(v @ north), float(v @ up)
        return math.degrees(math.atan2(e, nn)) % 360.0, math.degrees(math.atan2(u, math.hypot(e, nn)))

    suns = []
    for s in eph["samples"]:
        if s["site"] != "haworth":
            continue
        az, el = azel(s["sun_m"])
        if el > 0.0 and len([x for x in suns if x["utc"]]) < 3:
            suns.append({"utc": s["utc"], "az_deg": az, "el_deg": el})
        if el <= 0.0 and not any(x["utc"] and x["el_deg"] <= 0.0 for x in suns):
            suns.append({"utc": s["utc"], "az_deg": az, "el_deg": el})
    suns += [{"utc": None, "az_deg": 135.0, "el_deg": 2.0}, {"utc": None, "az_deg": 300.0, "el_deg": 1.0},
             {"utc": None, "az_deg": 45.0, "el_deg": 30.0}, {"utc": None, "az_deg": 210.0, "el_deg": -3.0}]
    anchors = [(60.0, 75.0), (230.0, 120.0)]                     # world metres within the window (SYNTHETIC)
    los = viewshed((window, cell), (0.0, 0.0), anchors)
    yy, xx = np.mgrid[0:n, 0:n]
    mu = np.clip(np.hypot(xx - 30, yy - 30) / 42.0, 0.0, 1.0)  # SYNTHETIC coverage gradient
    cases = []
    for sun in suns:
        for variant in ("plain", "anchors", "los_and_mu"):
            kw = {}
            if variant == "anchors":
                kw["anchors"] = anchors
            elif variant == "los_and_mu":
                kw["los"] = los
                kw["map_uncertainty"] = mu
            r = illumination_cost(window, cell_m=cell, sun_az_deg=sun["az_deg"], sun_el_deg=sun["el_deg"], **kw)
            sat = r["saturation"].ravel()
            lit = r["shadow_hazard"].ravel() == 0.0
            assert np.all(sat[~lit] == 0.0) and (not lit.any() or np.all(sat[lit] == sat[lit][0]))
            case = {"sun": sun, "variant": variant,
                    "shadowed": np.nonzero(~lit)[0].tolist(),            # compact: the shadowed cells
                    "saturation_lit": float(sat[lit][0]) if lit.any() else 0.0,
                    "blind": np.nonzero(r["visibility"].ravel() > 0.0)[0].tolist()}
            if variant == "los_and_mu":
                case["total"] = r["total"].ravel().tolist()
            cases.append(case)
    lit_counts = [n * n - len(c["shadowed"]) for c in cases]
    assert 0 < max(lit_counts) and min(lit_counts) == 0, "vacuity: lit cells under some Sun, none with the Sun down"
    assert any(0 < x < n * n for x in lit_counts), "vacuity: a partly shadowed window"
    assert 0 < int(np.count_nonzero(los)) < n * n, "vacuity: some cells see an anchor, some do not"
    write_fixture(ORACLE_FIXTURES, "illumination_cases", "oracle/build_fixtures.py::illumination_cases (dart."
                  "illumination_cost on a real Haworth window; Sun from the SPICE vectors of ephem_topocentric and fixed "
                  "angles; anchors and the map-uncertainty field SYNTHETIC, labelled)",
                  ["dart/illumination_cost.py", "dart/shadow_predict.py", "dart/visibility.py", "dart/illumination.py",
                   "crates/stewie-oracle/fixtures/route_cases.payload.json",
                   "crates/stewie-oracle/fixtures/ephem_topocentric.payload.json"],
                  {"window": [r0, c0, n], "cell_m": cell, "anchors": [list(a) for a in anchors],
                   "los": los.ravel().tolist(), "map_uncertainty": mu.ravel().tolist(),
                   "weights": {"shadow": W_SHADOW, "saturation": W_SATURATION, "map_uncertainty": W_MAP_UNCERTAINTY,
                               "visibility": W_VISIBILITY, "grazing_el_deg": GRAZING_EL_DEG},
                   "cases": cases})


def solar_cases() -> None:
    """Solar observation contract (RW-15b): dart.solar_observation.ephemeris_fallback at the lit Haworth epochs of
    illumination_cases (the SPICE-derived Sun), azimuth wrapping, and every refusal. The sigmas, the sample ids and
    the out-of-range angles are SYNTHETIC inputs (labelled)."""
    import dataclasses

    from dart.solar_observation import ephemeris_fallback

    with open(os.path.join(ORACLE_FIXTURES, "illumination_cases.payload.json")) as fh:
        ic = json.load(fh)
    ic = ic.get("payload", ic)
    lit = [c["sun"] for c in ic["cases"] if c["variant"] == "plain" and c["sun"]["utc"] and c["sun"]["el_deg"] > 0]
    cases = []
    for k, sun in enumerate(lit):
        o = ephemeris_fallback(sun["az_deg"], sun["el_deg"], sample_id=f"haworth-{k}", sigma_azimuth_deg=0.5,
                               sigma_elevation_deg=0.25)
        cases.append({"sun": sun, "sample_id": f"haworth-{k}", "sigmas": [0.5, 0.25], "calibrated": False,
                      "observation": dataclasses.asdict(o)})
    o = ephemeris_fallback(370.0, 12.0, sample_id="wrap", sigma_azimuth_deg=0.0, sigma_elevation_deg=1.0,
                           covariance_calibrated=True)
    cases.append({"sun": {"utc": None, "az_deg": 370.0, "el_deg": 12.0}, "sample_id": "wrap", "sigmas": [0.0, 1.0],
                  "calibrated": True, "observation": dataclasses.asdict(o)})
    refusals = []
    for az, el, sid, sa, se in ((10.0, 0.0, "a", 0.1, 0.1), (10.0, 95.0, "a", 0.1, 0.1), (10.0, 20.0, "", 0.1, 0.1),
                                (10.0, 20.0, "a", -0.5, 0.1), (10.0, 20.0, "a", 0.1, -1.0)):
        try:
            ephemeris_fallback(az, el, sample_id=sid, sigma_azimuth_deg=sa, sigma_elevation_deg=se)
        except ValueError as e:
            refusals.append({"az_deg": az, "el_deg": el, "sample_id": sid, "sigmas": [sa, se], "error": str(e)})
    assert len(lit) >= 2 and len(refusals) == 5
    write_fixture(ORACLE_FIXTURES, "solar_cases", "oracle/build_fixtures.py::solar_cases (dart.solar_observation; "
                  "Sun from illumination_cases' SPICE epochs; sigmas, ids and out-of-range angles SYNTHETIC, labelled)",
                  ["dart/solar_observation.py", "crates/stewie-oracle/fixtures/illumination_cases.payload.json"],
                  {"cases": cases, "refusals": refusals})


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


def flattest_cases() -> None:
    """The flattest buildable anchor (RW-55b3; stewie.terrain.site_dem.flattest_anchor): the cell minimising the
    mean slope over a window (SciPy uniform_filter, mode nearest) on every real bundled DEM at the default 20 m
    window, and on Haworth at windows giving odd and even and unit kernels. Real data only; the windows are the
    planner's own parameter values."""
    cases = []
    for name in _bundled_dems():
        dem = site_dem.load_haworth_dem(bundle_dir=os.path.join(REPO, "samples", "lunar_dem", name))
        # 12.5 m and 22.5 m put the kernel on a half (2.5, 4.5): Python's round is half-to-even
        for window_m in ((20.0, 15.0, 5.0, 33.0, 12.5, 22.5) if name == "haworth_10km_5m" else (20.0,)):
            x, y = site_dem.flattest_anchor(dem, window_m=window_m)
            cases.append({"bundle": name, "window_m": window_m, "cell_m": float(dem[1]), "x": x, "y": y})
    write_fixture(ORACLE_FIXTURES, "flattest_cases", "oracle/build_fixtures.py::flattest_cases "
                  "(stewie.terrain.site_dem.flattest_anchor on every bundled DEM; real data)",
                  ["stewie/terrain/site_dem.py"], {"cases": cases})


def auth_cases() -> None:
    """Server auth core (RW-55a1): stewie.server.auth (session tokens, revocation, roles, proxy trust) and
    stewie.server.operators (the account store) driven through one scripted scenario in a temporary data dir. The
    clock is pinned and the store's randomness (salts, invite tokens, token ids) comes from a seeded generator, so
    every result, every token and the final store are reproducible; the Rust port replays the same script with the
    same clock and bytes. Emails, passwords, keys and the scenario are SYNTHETIC test inputs (labelled)."""
    import copy
    import hashlib
    import tempfile
    import uuid as _uuid

    import stewie.server.auth as A
    import stewie.server.operators as O

    seed = hashlib.sha256(b"stewie-auth-oracle").digest()
    stream = {"n": 0}

    def det_bytes(n: int) -> bytes:                         # SYNTHETIC deterministic randomness (labelled)
        out = b""
        while len(out) < n:
            out += hashlib.sha256(seed + stream["n"].to_bytes(8, "big")).digest()
            stream["n"] += 1
        return out[:n]

    clock = {"t": 1_800_000_000.0}
    env = {"STEWIE_API_KEY": "automation-key-0123456789", "STEWIE_SESSION_SECRET": "session-secret-abcdef",
           "STEWIE_ALLOWED_OPERATORS": "alice@example.org,bob@example.org,carol@example.org",
           "STEWIE_DIRECTORS": "alice@example.org", "STEWIE_GIS_ANON_KEY": "anon-key-xyz",
           "STEWIE_TRUST_TAILSCALE": "1", "STEWIE_TRUSTED_PROXIES": "100.64.0.1,10.0.0.0/8,testclient"}
    saved = {k: os.environ.get(k) for k in list(env) + ["STEWIE_DATA_DIR", "STEWIE_TOKEN_AUD", "STEWIE_TLS_TERMINATED"]}
    patched = {"os_urandom": O.os.urandom, "token_urlsafe": O.secrets.token_urlsafe, "clock": O._clock,
               "uuid4": A.uuid.uuid4, "time": A.time.time}
    steps = []

    def rec(op, args, fn):
        try:
            out = fn()
            steps.append({"op": op, "args": args, "ok": out})
        except Exception as e:                              # noqa: BLE001 -- the error text is the oracle
            steps.append({"op": op, "args": args, "error": f"{type(e).__name__}: {e}"})

    with tempfile.TemporaryDirectory() as d:
        try:
            os.environ.update(env)
            os.environ["STEWIE_DATA_DIR"] = d
            os.environ.pop("STEWIE_TOKEN_AUD", None)
            os.environ.pop("STEWIE_TLS_TERMINATED", None)
            O.os.urandom = det_bytes
            O.secrets.token_urlsafe = lambda n: __import__("base64").urlsafe_b64encode(det_bytes(n)).decode().rstrip("=")
            O._clock = lambda: clock["t"]
            A.uuid.uuid4 = lambda: _uuid.UUID(bytes=det_bytes(16), version=4)
            A.time.time = lambda: clock["t"]
            # the account store
            rec("register", ["Alice@Example.org", "correct horse battery"],
                lambda: O.register("Alice@Example.org", "correct horse battery"))
            rec("register", ["bob@example.org", "short"], lambda: O.register("bob@example.org", "short"))
            rec("register", ["<img src=x>@x.co", "long enough pw"], lambda: O.register("<img src=x>@x.co", "long enough pw"))
            rec("register", ["alice@example.org", "another password"], lambda: O.register("alice@example.org", "another password"))
            rec("verify_credentials", ["alice@example.org", "correct horse battery", "1.2.3.4"],
                lambda: O.verify_credentials("alice@example.org", "correct horse battery", client_ip="1.2.3.4"))
            rec("approve", ["alice@example.org", "boot", "director"], lambda: O.approve("alice@example.org", "boot", role="director"))
            for k in range(6):
                clock["t"] += 1.0
                rec("verify_credentials", ["alice@example.org", f"wrong {k}", "6.6.6.6"],
                    lambda k=k: O.verify_credentials("alice@example.org", f"wrong {k}", client_ip="6.6.6.6"))
                rec("is_locked", ["alice@example.org", "6.6.6.6"], lambda: O.is_locked("alice@example.org", client_ip="6.6.6.6"))
            rec("is_locked", ["alice@example.org", "6.6.6.6"], lambda: O.is_locked("alice@example.org", client_ip="6.6.6.6"))
            rec("is_locked", ["alice@example.org", "1.2.3.4"], lambda: O.is_locked("alice@example.org", client_ip="1.2.3.4"))
            rec("verify_credentials", ["alice@example.org", "correct horse battery", "1.2.3.4"],
                lambda: O.verify_credentials("alice@example.org", "correct horse battery", client_ip="1.2.3.4"))
            rec("verify_credentials", ["alice@example.org", "correct horse battery", "6.6.6.6"],
                lambda: O.verify_credentials("alice@example.org", "correct horse battery", client_ip="6.6.6.6"))
            clock["t"] += 15 * 60 + 1
            rec("verify_credentials", ["alice@example.org", "correct horse battery", "6.6.6.6"],
                lambda: O.verify_credentials("alice@example.org", "correct horse battery", client_ip="6.6.6.6"))
            rec("create_active", ["carol@example.org", "carol password 1", "trainee"],
                lambda: O.create_active("carol@example.org", "carol password 1", role="trainee", by="alice@example.org"))
            rec("set_password", ["carol@example.org", "carol password 2"], lambda: O.set_password("carol@example.org", "carol password 2"))
            rec("verify_old_password", ["carol@example.org", "carol password 1"], lambda: O.verify_old_password("carol@example.org", "carol password 1"))
            rec("verify_old_password", ["carol@example.org", "carol password 2"], lambda: O.verify_old_password("carol@example.org", "carol password 2"))
            rec("set_role", ["carol@example.org", "pilot", "alice@example.org"], lambda: O.set_role("carol@example.org", "pilot", "alice@example.org"))
            invite = {}
            rec("create_invite", ["alice@example.org", "operator", 3600, 1],
                lambda: invite.setdefault("t", O.create_invite("alice@example.org", role="operator", ttl_s=3600, max_uses=1)))
            rec("redeem_invite", ["<invite>", "dave@example.org", "weak"], lambda: O.redeem_invite(invite["t"], "dave@example.org", "weak"))
            rec("redeem_invite", ["<invite>", "dave@example.org", "dave password 1"],
                lambda: O.redeem_invite(invite["t"], "dave@example.org", "dave password 1"))
            rec("redeem_invite", ["<invite>", "erin@example.org", "erin password 1"],
                lambda: O.redeem_invite(invite["t"], "erin@example.org", "erin password 1"))
            rec("revoke", ["bob@example.org", "alice@example.org"], lambda: O.revoke("bob@example.org", "alice@example.org"))
            rec("revoke", ["dave@example.org", "alice@example.org"], lambda: O.revoke("dave@example.org", "alice@example.org"))
            for who in ("api-key", "desktop-local", "gis-anon", "alice@example.org", "carol@example.org",
                        "dave@example.org", "bob@example.org", "zed@example.org"):
                rec("role_of", [who], lambda who=who: A.role_of(who))
            rec("list_all", [], O.list_all)
            store = json.load(open(os.path.join(d, "operators.json")))
            # session tokens: issued, verified, revoked
            tok = {}
            rec("issue_token", ["alice@example.org"], lambda: tok.setdefault("a", A.issue_token("alice@example.org")))
            rec("verify_token", ["<alice>"], lambda: A.verify_token(tok["a"]))
            rec("decode_claims", ["<alice>"], lambda: A.decode_claims(tok["a"]))
            rec("verify_token", ["<alice>", "expired"], lambda: A.verify_token(tok["a"], now=clock["t"] + 12 * 3600 + 1))
            tampered = tok["a"][:-2] + ("A" if tok["a"][-2] != "A" else "B") + tok["a"][-1]
            rec("verify_token", ["<alice tampered>"], lambda: A.verify_token(tampered))
            rec("issue_token", ["zed@example.org"], lambda: tok.setdefault("z", A.issue_token("zed@example.org")))
            rec("verify_token", ["<zed, not allowlisted>"], lambda: A.verify_token(tok["z"]))
            os.environ["STEWIE_TOKEN_AUD"] = "other-audience"
            rec("issue_token", ["alice@example.org", "other-audience"], lambda: tok.setdefault("o", A.issue_token("alice@example.org")))
            os.environ.pop("STEWIE_TOKEN_AUD")
            rec("verify_token", ["<other audience>"], lambda: A.verify_token(tok["o"]))
            rec("revoke_jti", ["<alice jti>"], lambda: A.revoke_jti(A.decode_claims(tok["a"])["jti"]))
            rec("verify_token", ["<alice revoked>"], lambda: A.verify_token(tok["a"]))
            revoked_store = json.load(open(os.path.join(d, "revoked_jti.json")))
            open(os.path.join(d, "revoked_jti.json"), "w").write("{not json")
            rec("is_revoked", ["<anything>", "corrupt store"], lambda: A.is_revoked("0" * 32))
            os.environ.pop("STEWIE_SESSION_SECRET")
            rec("issue_token", ["alice@example.org", "derived secret"], lambda: tok.setdefault("d", A.issue_token("alice@example.org")))
            derived = A._signing_secret().hex()
            os.environ["STEWIE_SESSION_SECRET"] = env["STEWIE_SESSION_SECRET"]
            # proxy trust and the Tailscale identity
            for peer in ("100.64.0.1", "10.9.8.7", "11.0.0.1", "testclient", None, "not-an-ip"):
                rec("peer_trusted", [peer], lambda peer=peer: A._peer_trusted(peer, A.trusted_proxies()))
            for peer, login in (("100.64.0.1", "Alice@Example.org"), ("11.0.0.1", "alice@example.org"),
                                ("10.1.1.1", "zed@example.org")):
                rec("tailscale_identity", [peer, login],
                    lambda peer=peer, login=login: A.tailscale_identity({"tailscale-user-login": login}, peer_ip=peer))
            for addr in ("user.name+tag@host.tld", "a..b@x.co", ".a@x.co", "a@x", "a@-x.co", "a@x.c0", "a b@x.co",
                         "x" * 65 + "@x.co", "ok@sub.domain.museum"):
                rec("validate_email", [addr], lambda addr=addr: O._validate_email(addr))
        finally:
            O.os.urandom = patched["os_urandom"]
            O.secrets.token_urlsafe = patched["token_urlsafe"]
            O._clock = patched["clock"]
            A.uuid.uuid4 = patched["uuid4"]
            A.time.time = patched["time"]
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    assert any("error" in s for s in steps) and any(s.get("ok") is None for s in steps if "ok" in s)
    write_fixture(ORACLE_FIXTURES, "auth_cases", "oracle/build_fixtures.py::auth_cases (stewie.server.auth + operators "
                  "through one scripted scenario; pinned clock, seeded randomness; every input SYNTHETIC, labelled)",
                  ["stewie/server/auth.py", "stewie/server/operators.py"],
                  {"env": env, "seed_sha256_of": "stewie-auth-oracle", "clock0": 1_800_000_000.0, "steps": steps,
                   "store": store, "revoked": revoked_store, "tokens": {k: v for k, v in tok.items()},
                   "derived_secret_hex": derived})


def services_cases() -> None:
    """Server services (RW-55a2a): stewie.server.services (the audit ledger: durable append, redaction,
    correlation ids, size rotation, visible failure, the fail-closed critical path, revocation health) and
    stewie.server.ratelimit.RateLimiter, driven through one scripted scenario in a temporary data dir with a
    pinned clock. Actors, actions, field values and the clock are SYNTHETIC test inputs (labelled)."""
    import tempfile

    import stewie.server.auth as A
    import stewie.server.services as S
    from stewie.server.ratelimit import RateLimiter

    clock = {"t": 1_800_000_000.25}
    saved_env = {k: os.environ.get(k) for k in ("STEWIE_DATA_DIR", "STEWIE_AUDIT_MAX_BYTES")}
    saved_time = S.time.time
    steps = []

    def rec(op, args, fn):
        try:
            out = fn()
            steps.append({"op": op, "args": args, "ok": out})
        except Exception as e:                              # noqa: BLE001 -- the error class is the oracle
            steps.append({"op": op, "args": args, "error": type(e).__name__})

    def ledger(d):
        names = sorted(os.listdir(d))
        live = os.path.join(d, "events.jsonl")
        lines = [json.loads(x) for x in open(live)] if os.path.exists(live) else []
        return {"rotated": [n for n in names if n.startswith("events.jsonl.")], "live": lines}

    with tempfile.TemporaryDirectory() as d:
        try:
            os.environ["STEWIE_DATA_DIR"] = d
            os.environ.pop("STEWIE_AUDIT_MAX_BYTES", None)
            S.time.time = lambda: clock["t"]
            S.reset_audit_health()
            S.reset_revocation_health()
            S.set_correlation_id(None)
            # redaction and fingerprints
            for obj in ({"user": "a", "Password": "p", "nested": {"api_key": "k", "keep": [1, {"Token": "t"}]}},
                        [{"cookie": "c"}, "x", 3.5], "plain", {"SESSION": {"x": 1}, "sessions": 2}):
                rec("redact", [obj], lambda obj=obj: S.redact(obj))
            for obj in ({"b": 1, "a": [1.5, "é", None, True]}, [], "text", {"z": {"y": 1e-7, "x": 1e20}}):
                rec("hash_payload", [obj], lambda obj=obj: S.hash_payload(obj))
            for a in ("rc.goto", "rc.gotox", "rc.go", "operator.approve", "operators", "twin.publish.site",
                      "twin.pub", "auth.login", "admin.", "release.x", "executive.release"):
                rec("is_critical_action", [a], lambda a=a: S.is_critical_action(a))
            # the ledger: plain, with a correlation id, with fields (redacted; an explicit correlation id and a
            # field named like a record key override)
            rec("log_event", ["alice", "auth.login", "password"], lambda: S.log_event("alice", "auth.login", "password"))
            clock["t"] += 0.0004
            S.set_correlation_id("cid-0001")
            rec("log_event", ["bob", "plan.run", "", {"status": 200, "token": "secret-ish", "latency_ms": 12.5}],
                lambda: S.log_event("bob", "plan.run", "", status=200, token="secret-ish", latency_ms=12.5))
            rec("log_event", ["bob", "plan.run", "t", {"correlation_id": "cid-override", "ts": 1.5}],
                lambda: S.log_event("bob", "plan.run", "t", correlation_id="cid-override", ts=1.5))
            S.set_correlation_id(None)
            clock["t"] += 1.0
            rec("critical_event", ["alice", "operator.approve", "carol", {"role": "trainee"}],
                lambda: S.critical_event("alice", "operator.approve", "carol", role="trainee"))
            rec("audit_health", [], S.audit_health)
            before_rotation = ledger(d)
            # rotation: a tiny cap rolls the live file before the next append
            os.environ["STEWIE_AUDIT_MAX_BYTES"] = "64"
            clock["t"] += 1.0
            rec("log_event", ["alice", "after.rotation", ""], lambda: S.log_event("alice", "after.rotation", ""))
            os.environ.pop("STEWIE_AUDIT_MAX_BYTES")
            after_rotation = ledger(d)
            # a failed write: plain events degrade visibly and return; a critical one is refused
            blocked = os.path.join(d, "blocked")
            open(blocked, "w").write("a file where the data dir should be")
            os.environ["STEWIE_DATA_DIR"] = os.path.join(blocked, "sub")
            rec("log_event", ["alice", "lost", ""], lambda: S.log_event("alice", "lost", ""))
            rec("critical_event", ["alice", "rc.goto", "rover-1"], lambda: S.critical_event("alice", "rc.goto", "rover-1"))
            h = S.audit_health()
            rec("audit_health", [], lambda: {"degraded": h["degraded"], "failures": h["failures"],
                                             "has_error": h["last_error"] is not None})
            os.environ["STEWIE_DATA_DIR"] = d
            # revocation health: a corrupt revocation store denies, degrades, and is audited
            open(os.path.join(d, "revoked_jti.json"), "w").write("[not json")
            clock["t"] += 1.0
            rec("is_revoked", ["0" * 32], lambda: A.is_revoked("0" * 32))
            r = S.revocation_health()
            rec("revocation_health", [], lambda: {"degraded": r["degraded"], "failures": r["failures"],
                                                  "has_error": r["last_error"] is not None})
            final = ledger(d)
            for line in final["live"]:
                if line["action"] == "revocation.read_failed":
                    line["target"] = "<the read error>"          # the error text is each language's own
            # the fixed-window rate limiter
            rl = RateLimiter(3, 10.0)
            for key, now, cost in (("ip1", 0.0, 1), ("ip1", 1.0, 1), ("ip2", 1.5, 1), ("ip1", 2.0, 1), ("ip1", 3.0, 1),
                                   ("ip1", 9.99, 1), ("ip1", 10.0, 1), ("ip1", 10.5, 2), ("ip1", 11.0, 1),
                                   ("ip3", 0.0, 4), ("ip3", 0.1, 0), ("ip3", 0.2, -5), ("ip3", 0.3, 1),
                                   ("ip3", 0.4, 1)):
                rec("rate_allow", [key, now, cost], lambda key=key, now=now, cost=cost: rl.allow(key, now=now, cost=cost))
        finally:
            S.time.time = saved_time
            S.set_correlation_id(None)
            S.reset_audit_health()
            S.reset_revocation_health()
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    write_fixture(ORACLE_FIXTURES, "services_cases", "oracle/build_fixtures.py::services_cases (stewie.server.services "
                  "audit ledger + revocation health + ratelimit.RateLimiter through one scripted scenario; pinned "
                  "clock; every input SYNTHETIC, labelled)",
                  ["stewie/server/services.py", "stewie/server/ratelimit.py"],
                  {"clock0": 1_800_000_000.25, "steps": steps, "before_rotation": before_rotation,
                   "after_rotation": after_rotation, "final": final})


def http_auth_cases() -> None:
    """The server's HTTP surface for identity (RW-55a2b): the real FastAPI app (stewie.server.server) driven by
    the Starlette TestClient through one scripted session against /auth/{config,login,logout,register,me,password},
    /healthz, the catch-all 404, the validation and body-size envelopes and the response middleware. Every
    response's status, JSON body, hardening headers and parsed Set-Cookie attributes are recorded, then the
    account store and the audit ledger. The clock is pinned, the randomness (token ids, CSRF tokens, salts,
    correlation ids) is a seeded stream, the client is 127.0.0.1, and the rate limiters start empty. Emails,
    passwords, keys and the scenario are SYNTHETIC test inputs (labelled)."""
    import hashlib
    import importlib
    import tempfile
    import uuid as _uuid

    from fastapi.testclient import TestClient

    import stewie.server.auth as A
    import stewie.server.operators as O
    import stewie.server.routers.auth as R
    import stewie.server.services as S

    seed = hashlib.sha256(b"stewie-http-auth-oracle").digest()
    stream = {"n": 0}

    def det_bytes(n: int) -> bytes:                         # SYNTHETIC deterministic randomness (labelled)
        out = b""
        while len(out) < n:
            out += hashlib.sha256(seed + stream["n"].to_bytes(8, "big")).digest()
            stream["n"] += 1
        return out[:n]

    clock = {"t": 1_800_000_000.0}
    env = {"STEWIE_API_KEY": "automation-key-0123456789", "STEWIE_SESSION_SECRET": "session-secret-abcdef",
           "STEWIE_ALLOWED_OPERATORS": "alice@example.org,bob@example.org",
           "STEWIE_DIRECTORS": "alice@example.org", "STEWIE_GIS_ANON_KEY": "anon-key-xyz",
           "STEWIE_TRUST_TAILSCALE": "1", "STEWIE_TRUSTED_PROXIES": "10.0.0.0/8",
           "STEWIE_REGISTRATION": "1", "STEWIE_MAX_BODY_BYTES": "2048"}
    unset = ("STEWIE_TOKEN_AUD", "STEWIE_TLS_TERMINATED", "STEWIE_DESKTOP", "STEWIE_OPERATOR_LOGIN",
             "STEWIE_TRUST_PROXY", "STEWIE_CORS_ORIGINS", "STEWIE_DEV_OPEN", "STEWIE_AUDIT_MAX_BYTES")
    saved = {k: os.environ.get(k) for k in list(env) + list(unset) + ["STEWIE_DATA_DIR"]}
    patched = {"urandom": O.os.urandom, "token_urlsafe": O.secrets.token_urlsafe, "token_hex": S.secrets.token_hex,
               "clock": O._clock, "uuid4": A.uuid.uuid4, "a_time": A.time.time, "s_time": S.time.time}
    keep_headers = ("content-type", "x-correlation-id", "x-content-type-options", "referrer-policy",
                    "permissions-policy", "cache-control", "access-control-allow-origin")
    steps = []

    def cookies_of(resp):
        out = []
        for line in resp.headers.get_list("set-cookie"):
            parts = [p.strip() for p in line.split(";")]
            name, _, value = parts[0].partition("=")
            c = {"name": name, "value": value.strip('"')}
            for p in parts[1:]:
                k, eq, v = p.partition("=")
                c[k.lower()] = v if eq else True
            out.append(c)
        return out

    with tempfile.TemporaryDirectory() as d:
        try:
            os.environ.update(env)
            os.environ["STEWIE_DATA_DIR"] = d
            for k in unset:
                os.environ.pop(k, None)
            O.os.urandom = det_bytes
            O.secrets.token_urlsafe = lambda n: __import__("base64").urlsafe_b64encode(det_bytes(n)).decode().rstrip("=")
            S.secrets.token_hex = lambda n: det_bytes(n).hex()
            O._clock = lambda: clock["t"]
            A.uuid.uuid4 = lambda: _uuid.UUID(bytes=det_bytes(16), version=4)
            A.time.time = lambda: clock["t"]
            S.time.time = lambda: clock["t"]
            S.reset_audit_health()
            S.reset_revocation_health()
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            import stewie.server.server as srv
            importlib.reload(srv)
            client = TestClient(srv.app, client=("127.0.0.1", 50000))
            n = {"i": 0}

            def call(method, path, *, headers=None, cookies=None, json_body=None, raw=None, cid=True):
                n["i"] += 1
                h = dict(headers or {})
                if cid:
                    h["X-Correlation-Id"] = f"cid-{n['i']:03d}"
                if cookies:
                    h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
                client.cookies.clear()
                kw = {}
                if json_body is not None:
                    kw["json"] = json_body
                if raw is not None:
                    kw["content"] = raw
                    h.setdefault("Content-Type", "application/json")
                r = client.request(method, path, headers=h, **kw)
                try:
                    body = r.json()
                except ValueError:
                    body = r.text
                if isinstance(body, dict) and "uptime_s" in body:
                    body["uptime_s"] = "<uptime>"
                steps.append({"request": {"method": method, "path": path, "headers": h,
                                          "json": json_body, "raw": raw},
                              "status": r.status_code, "body": body,
                              "headers": {k: r.headers[k] for k in keep_headers if k in r.headers},
                              "cookies": cookies_of(r)})
                return r

            key = {"X-API-Key": env["STEWIE_API_KEY"]}
            call("GET", "/healthz")
            call("GET", "/auth/config")
            call("GET", "/auth/me")
            call("GET", "/auth/me", headers=key)
            call("GET", "/auth/me", headers={"X-Stewie-Anon-Key": "anon-key-xyz"})
            call("GET", "/auth/me", headers={"X-API-Key": "wrong-key"})
            call("GET", "/auth/me", headers={"Tailscale-User-Login": "alice@example.org"})   # untrusted peer
            call("GET", "/auth/me", headers=key, cid=False)                                    # a minted id
            call("POST", "/auth/register", json_body={"email": "carol@example.org", "password": "carol password 1"})
            call("POST", "/auth/register", json_body={"email": "<b>@x.co", "password": "long enough pw"})
            call("POST", "/auth/register", json_body={"email": "dave@example.org", "password": "short"})
            r = call("POST", "/auth/login", json_body={"email": "Alice@Example.org"}, headers=key)
            alice = r.json()["token"]
            call("GET", "/auth/me", headers={"Authorization": f"Bearer {alice}"})
            call("POST", "/auth/login", json_body={"email": "bob@example.org"},
                 headers={"Authorization": f"Bearer {alice}"})                                   # no cross-identity
            clock["t"] += 1.0
            call("POST", "/auth/password", json_body={"new_password": "alice password 1"},
                 headers={"Authorization": f"Bearer {alice}"})
            call("POST", "/auth/password", json_body={"new_password": "x"}, headers=key)        # automation: no pw
            call("POST", "/auth/login", json_body={"email": "alice@example.org", "password": "wrong password"})
            clock["t"] += 1.0
            r = call("POST", "/auth/login", json_body={"email": "alice@example.org", "password": "alice password 1"})
            jar = {c["name"]: c["value"] for c in cookies_of(r)}
            call("POST", "/auth/password", json_body={"new_password": "alice password 2"},
                 cookies={"stewie_session": jar["stewie_session"]})                               # no CSRF
            call("POST", "/auth/password", json_body={"new_password": "alice password 2"},
                 cookies=jar, headers={"X-CSRF-Token": "not-the-cookie"})
            call("POST", "/auth/password", json_body={"old_password": "wrong", "new_password": "alice password 2"},
                 cookies=jar, headers={"X-CSRF-Token": jar["stewie_csrf"]})
            call("POST", "/auth/password", json_body={"old_password": "alice password 1",
                                                      "new_password": "alice password 2"},
                 cookies=jar, headers={"X-CSRF-Token": jar["stewie_csrf"]})
            call("GET", "/auth/me", cookies={"stewie_session": jar["stewie_session"]})           # GET: no CSRF
            clock["t"] += 1.0
            call("POST", "/auth/logout", cookies=jar)
            call("GET", "/auth/me", cookies={"stewie_session": jar["stewie_session"]})           # revoked
            call("POST", "/auth/logout")
            call("POST", "/auth/login", json_body={"email": "zed@example.org"}, headers=key)
            call("POST", "/auth/login", json_body={"email": "alice@example.org"}, headers=key)  # has a password
            call("POST", "/auth/login", raw="{not json")
            call("POST", "/auth/login", json_body={"email": "x" * 300})
            call("POST", "/auth/login", json_body={"email": 5, "password": ["a"]})
            call("POST", "/auth/register", raw="x" * 3000)
            call("GET", "/no/such/route")
            call("POST", "/no/such/route", json_body={})
            call("GET", "/auth/login")                                                           # GET catch-all
            call("PUT", "/auth/login", json_body={})
            call("DELETE", "/no/such/route")
            call("POST", "/auth/login", raw="")
            call("POST", "/auth/login", raw="[1, 2]")
            call("POST", "/auth/login", json_body={"email": "a@b.co", "password": "p" * 257, "extra": 1})
            call("POST", "/auth/register", json_body={"email": None, "password": None})
            call("POST", "/auth/password", json_body={"new_password": 7}, headers=key)
            for k in range(9):                                                                   # the per-IP cap
                call("POST", "/auth/login", json_body={"email": "bob@example.org", "password": f"wrong {k}"})
            # an unreadable revocation store: the token is denied and /healthz reports the degradation
            store = json.load(open(os.path.join(d, "operators.json")))
            open(os.path.join(d, "revoked_jti.json"), "w").write("[not json")
            call("GET", "/auth/me", headers={"Authorization": f"Bearer {alice}"})
            call("GET", "/healthz")
            ledger = [json.loads(x) for x in open(os.path.join(d, "events.jsonl"))]
            for line in ledger:
                if line["action"] == "revocation.read_failed":
                    line["target"] = "<the read error>"                     # the error text is each language's own
            for st in steps:
                if isinstance(st["body"], dict) and isinstance(st["body"].get("revocation"), dict) \
                        and st["body"]["revocation"]["last_error"] is not None:
                    st["body"]["revocation"]["last_error"] = "<the read error>"
        finally:
            O.os.urandom = patched["urandom"]
            O.secrets.token_urlsafe = patched["token_urlsafe"]
            S.secrets.token_hex = patched["token_hex"]
            O._clock = patched["clock"]
            A.uuid.uuid4 = patched["uuid4"]
            A.time.time = patched["a_time"]
            S.time.time = patched["s_time"]
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            importlib.reload(srv)
    write_fixture(ORACLE_FIXTURES, "http_auth_cases", "oracle/build_fixtures.py::http_auth_cases (the FastAPI app's "
                  "identity routes, /healthz and middleware through one scripted TestClient session; pinned clock, "
                  "seeded randomness; every input SYNTHETIC, labelled)",
                  ["stewie/server/server.py", "stewie/server/deps.py", "stewie/server/routers/auth.py",
                   "stewie/server/routers/health.py"],
                  {"env": env, "seed_sha256_of": "stewie-http-auth-oracle", "clock0": 1_800_000_000.0,
                   "client": "127.0.0.1", "steps": steps, "store": store, "ledger": ledger})


def http_admin_cases() -> None:
    """The account-administration surface (RW-55b1): the real FastAPI app driven by the Starlette TestClient through
    /admin/operators (list, create, approve, revoke, role, reset, delete) with the last-director guard, /admin/invite
    and /auth/invite/redeem, and the director-only /events ledger view, including the role gates and the request
    validation envelopes. Same harness as http_auth_cases: pinned clock, seeded randomness, client 127.0.0.1, the
    store and ledger recorded at the end. Emails, passwords, keys and the scenario are SYNTHETIC test inputs."""
    import hashlib
    import importlib
    import tempfile
    import uuid as _uuid

    from fastapi.testclient import TestClient

    import stewie.server.auth as A
    import stewie.server.operators as O
    import stewie.server.routers.auth as R
    import stewie.server.services as S

    seed = hashlib.sha256(b"stewie-http-admin-oracle").digest()
    stream = {"n": 0}

    def det_bytes(n: int) -> bytes:                         # SYNTHETIC deterministic randomness (labelled)
        out = b""
        while len(out) < n:
            out += hashlib.sha256(seed + stream["n"].to_bytes(8, "big")).digest()
            stream["n"] += 1
        return out[:n]

    clock = {"t": 1_800_000_000.0}
    env = {"STEWIE_API_KEY": "automation-key-0123456789", "STEWIE_SESSION_SECRET": "session-secret-abcdef",
           "STEWIE_ALLOWED_OPERATORS": "alice@example.org,bob@example.org",
           "STEWIE_DIRECTORS": "alice@example.org", "STEWIE_REGISTRATION": "1"}
    unset = ("STEWIE_TOKEN_AUD", "STEWIE_TLS_TERMINATED", "STEWIE_DESKTOP", "STEWIE_OPERATOR_LOGIN",
             "STEWIE_TRUST_PROXY", "STEWIE_CORS_ORIGINS", "STEWIE_DEV_OPEN", "STEWIE_AUDIT_MAX_BYTES",
             "STEWIE_GIS_ANON_KEY", "STEWIE_TRUST_TAILSCALE", "STEWIE_TRUSTED_PROXIES", "STEWIE_MAX_BODY_BYTES")
    saved = {k: os.environ.get(k) for k in list(env) + list(unset) + ["STEWIE_DATA_DIR"]}
    patched = {"urandom": O.os.urandom, "token_urlsafe": O.secrets.token_urlsafe, "token_hex": S.secrets.token_hex,
               "clock": O._clock, "uuid4": A.uuid.uuid4, "a_time": A.time.time, "s_time": S.time.time}
    steps = []

    with tempfile.TemporaryDirectory() as d:
        try:
            os.environ.update(env)
            os.environ["STEWIE_DATA_DIR"] = d
            for k in unset:
                os.environ.pop(k, None)
            O.os.urandom = det_bytes
            O.secrets.token_urlsafe = lambda n: __import__("base64").urlsafe_b64encode(det_bytes(n)).decode().rstrip("=")
            S.secrets.token_hex = lambda n: det_bytes(n).hex()
            O._clock = lambda: clock["t"]
            A.uuid.uuid4 = lambda: _uuid.UUID(bytes=det_bytes(16), version=4)
            A.time.time = lambda: clock["t"]
            S.time.time = lambda: clock["t"]
            S.reset_audit_health()
            S.reset_revocation_health()
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            import stewie.server.server as srv
            importlib.reload(srv)
            client = TestClient(srv.app, client=("127.0.0.1", 50000))
            n = {"i": 0}

            def call(method, path, *, headers=None, json_body=None, raw=None):
                n["i"] += 1
                h = dict(headers or {})
                h["X-Correlation-Id"] = f"cid-{n['i']:03d}"
                client.cookies.clear()
                kw = {}
                if json_body is not None:
                    kw["json"] = json_body
                if raw is not None:
                    kw["content"] = raw
                    h.setdefault("Content-Type", "application/json")
                r = client.request(method, path, headers=h, **kw)
                try:
                    body = r.json()
                except ValueError:
                    body = r.text
                steps.append({"request": {"method": method, "path": path, "headers": h, "json": json_body,
                                          "raw": raw}, "clock": clock["t"], "status": r.status_code, "body": body})
                return r

            key = {"X-API-Key": env["STEWIE_API_KEY"]}
            alice = {"Authorization": "Bearer " + call("POST", "/auth/login", json_body={"email": "alice@example.org"},
                                                      headers=key).json()["token"]}
            bob = {"Authorization": "Bearer " + call("POST", "/auth/login", json_body={"email": "bob@example.org"},
                                                    headers=key).json()["token"]}
            clock["t"] += 1.0
            call("POST", "/auth/password", json_body={"new_password": "alice password 1"}, headers=alice)
            # the role gates
            call("GET", "/admin/operators", headers=alice)
            call("GET", "/admin/operators", headers=bob)
            call("GET", "/admin/operators")
            call("GET", "/admin/operators", headers=key)
            # create
            clock["t"] += 1.0
            call("POST", "/admin/operators/create", headers=key,
                 json_body={"email": "Carol@Example.org", "password": "carol password 1", "role": "director"})
            call("POST", "/admin/operators/create", headers=key,
                 json_body={"email": "carol@example.org", "password": "carol password 1"})
            call("POST", "/admin/operators/create", headers=key,
                 json_body={"email": "erin@example.org", "password": "erin password 1", "role": "pilot"})
            call("POST", "/admin/operators/create", headers=key, json_body={"email": 5, "password": True})
            call("POST", "/admin/operators/create", headers=key, json_body={"email": None, "password": [1, "a"]})
            call("POST", "/admin/operators/create", headers=key, raw="[1, 2]")
            call("POST", "/admin/operators/create", headers=key, raw="")
            call("POST", "/admin/operators/create", headers=key, raw="{bad")
            call("POST", "/admin/operators/create", headers=bob, json_body={"email": "x@example.org"})
            # approve a registered account
            call("POST", "/auth/register", json_body={"email": "dave@example.org", "password": "dave password 1"})
            clock["t"] += 1.0
            call("POST", "/admin/operators/approve", headers=alice, json_body={"email": "dave@example.org"})
            call("POST", "/admin/operators/approve", headers=key, json_body={"email": "nobody@example.org"})
            call("POST", "/admin/operators/approve", headers=key, json_body={"email": "dave@example.org", "role": "boss"})
            # roles and the last-director guard
            call("POST", "/admin/operators/role", headers=key, json_body={"email": "carol@example.org", "role": "trainee"})
            call("POST", "/admin/operators/role", headers=key, json_body={"email": "alice@example.org", "role": "operator"})
            call("POST", "/admin/operators/role", headers=key, json_body={"email": "carol@example.org", "role": "director"})
            call("POST", "/admin/operators/role", headers=key, json_body={"email": "alice@example.org", "role": "operator"})
            call("POST", "/admin/operators/revoke", headers=key, json_body={"email": "carol@example.org"})
            call("DELETE", "/admin/operators/carol%40example.org", headers=key)
            call("POST", "/admin/operators/role", headers=key, json_body={"email": "alice@example.org", "role": "director"})
            call("DELETE", "/admin/operators/Carol@Example.org", headers=key)
            call("DELETE", "/admin/operators/nobody@example.org", headers=key)
            call("POST", "/admin/operators/revoke", headers=key, json_body={"email": "dave@example.org"})
            call("POST", "/admin/operators/revoke", headers=key, json_body={"email": "nobody@example.org"})
            call("POST", "/admin/operators/reset", headers=key, json_body={"email": "dave@example.org", "new_password": "short"})
            call("POST", "/admin/operators/reset", headers=key,
                 json_body={"email": "dave@example.org", "new_password": "dave password 2"})
            call("POST", "/admin/operators/reset", headers=key, json_body={"email": "x@example.org",
                                                                          "new_password": "long enough pw"})
            call("GET", "/admin/operators/dave@example.org", headers=key)
            # invites
            clock["t"] += 1.0
            r = call("POST", "/admin/invite", headers=key, json_body={})
            one = r.json()["token"]
            r = call("POST", "/admin/invite", headers=alice, json_body={"role": "trainee", "ttl_s": 60, "max_uses": 2})
            two = r.json()["token"]
            call("POST", "/admin/invite", headers=key, json_body={"role": "pilot"})
            call("POST", "/admin/invite", headers=key, json_body={"ttl_s": 0})
            call("POST", "/admin/invite", headers=key, json_body={"ttl_s": 7776001, "max_uses": 0})
            call("POST", "/admin/invite", headers=key, json_body={"max_uses": 2.5})
            call("POST", "/admin/invite", headers=key, json_body={"max_uses": 2.0, "ttl_s": "30"})
            call("POST", "/admin/invite", headers=key, json_body={"max_uses": "x", "ttl_s": "abc", "role": 3})
            call("POST", "/admin/invite", headers=key, json_body={"extra": 1})
            call("POST", "/admin/invite", headers=key, json_body={"z": 1, "ttl_s": 0, "max_uses": None})
            call("POST", "/admin/invite", headers=key, json_body={"ttl_s": True, "max_uses": " 3 "})
            call("POST", "/admin/invite", headers=key, json_body={"ttl_s": "1e3", "max_uses": "2.0", "role": "guest"})
            call("POST", "/admin/invite", headers=key, json_body={"ttl_s": None, "max_uses": [1]})
            call("POST", "/admin/invite", headers=bob, json_body={})
            call("POST", "/auth/invite/redeem", json_body={"token": "short", "email": "ab", "password": ""})
            call("POST", "/auth/invite/redeem", json_body={"token": one})
            call("POST", "/auth/invite/redeem", json_body={"token": one, "email": "erin@example.org",
                                                          "password": "erin password 1", "x": 1})
            clock["t"] += 1.0
            call("POST", "/auth/invite/redeem", json_body={"token": one, "email": "erin@example.org",
                                                          "password": "erin password 1"})
            call("POST", "/auth/invite/redeem", json_body={"token": one, "email": "fay@example.org",
                                                          "password": "fay password 1"})
            call("POST", "/auth/invite/redeem", json_body={"token": two, "email": "gus@example.org", "password": "weak"})
            call("POST", "/auth/invite/redeem", json_body={"token": two, "email": "gus@example.org",
                                                          "password": "gus password 1"})
            clock["t"] += 61.0
            call("POST", "/auth/invite/redeem", json_body={"token": two, "email": "hal@example.org",
                                                          "password": "hal password 1"})
            # the ledger view
            call("GET", "/events?n=3", headers=key)
            call("GET", "/events?actor=Alice@Example.org", headers=key)
            call("GET", "/events?action=admin.operator.role&n=2", headers=key)
            call("GET", "/events?n=0", headers=alice)
            call("GET", "/events?n=abc", headers=key)
            call("GET", "/events", headers=bob)
            call("GET", "/admin/operators", headers=key)
            store = json.load(open(os.path.join(d, "operators.json")))
            ledger = [json.loads(x) for x in open(os.path.join(d, "events.jsonl"))]
        finally:
            O.os.urandom = patched["urandom"]
            O.secrets.token_urlsafe = patched["token_urlsafe"]
            S.secrets.token_hex = patched["token_hex"]
            O._clock = patched["clock"]
            A.uuid.uuid4 = patched["uuid4"]
            A.time.time = patched["a_time"]
            S.time.time = patched["s_time"]
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            importlib.reload(srv)
    write_fixture(ORACLE_FIXTURES, "http_admin_cases", "oracle/build_fixtures.py::http_admin_cases (the FastAPI app's "
                  "account administration, invites and /events through one scripted TestClient session; pinned clock, "
                  "seeded randomness; every input SYNTHETIC, labelled)",
                  ["stewie/server/routers/operators_admin.py", "stewie/server/routers/invites.py",
                   "stewie/server/deps.py", "stewie/server/operators.py"],
                  {"env": env, "seed_sha256_of": "stewie-http-admin-oracle", "clock0": 1_800_000_000.0,
                   "client": "127.0.0.1", "steps": steps, "store": store, "ledger": ledger})


def http_build_cases() -> None:
    """The construction surface (RW-55b2): the real FastAPI app's /construction (the build catalog and acceptance
    criteria, operator+) and /siteplan/analyze (validate-and-advise over a placed layout, any auth) through one
    scripted TestClient session, with the role gates and Pydantic's nested-list validation. Same harness as
    http_admin_cases. Layouts, sizes, emails and keys are SYNTHETIC test inputs (labelled); the templates and
    densities are the real ones."""
    import hashlib
    import importlib
    import tempfile
    import uuid as _uuid

    from fastapi.testclient import TestClient

    import stewie.server.auth as A
    import stewie.server.operators as O
    import stewie.server.routers.auth as R
    import stewie.server.services as S

    seed = hashlib.sha256(b"stewie-http-build-oracle").digest()
    stream = {"n": 0}

    def det_bytes(n: int) -> bytes:                         # SYNTHETIC deterministic randomness (labelled)
        out = b""
        while len(out) < n:
            out += hashlib.sha256(seed + stream["n"].to_bytes(8, "big")).digest()
            stream["n"] += 1
        return out[:n]

    clock = {"t": 1_800_000_000.0}
    env = {"STEWIE_API_KEY": "automation-key-0123456789", "STEWIE_SESSION_SECRET": "session-secret-abcdef",
           "STEWIE_ALLOWED_OPERATORS": "alice@example.org,bob@example.org",
           "STEWIE_DIRECTORS": "alice@example.org", "STEWIE_GIS_ANON_KEY": "anon-key-xyz"}
    unset = ("STEWIE_TOKEN_AUD", "STEWIE_TLS_TERMINATED", "STEWIE_DESKTOP", "STEWIE_OPERATOR_LOGIN",
             "STEWIE_TRUST_PROXY", "STEWIE_CORS_ORIGINS", "STEWIE_DEV_OPEN", "STEWIE_AUDIT_MAX_BYTES",
             "STEWIE_REGISTRATION", "STEWIE_TRUST_TAILSCALE", "STEWIE_TRUSTED_PROXIES", "STEWIE_MAX_BODY_BYTES")
    saved = {k: os.environ.get(k) for k in list(env) + list(unset) + ["STEWIE_DATA_DIR"]}
    patched = {"urandom": O.os.urandom, "token_urlsafe": O.secrets.token_urlsafe, "token_hex": S.secrets.token_hex,
               "clock": O._clock, "uuid4": A.uuid.uuid4, "a_time": A.time.time, "s_time": S.time.time}
    steps = []

    with tempfile.TemporaryDirectory() as d:
        try:
            os.environ.update(env)
            os.environ["STEWIE_DATA_DIR"] = d
            for k in unset:
                os.environ.pop(k, None)
            O.os.urandom = det_bytes
            O.secrets.token_urlsafe = lambda n: __import__("base64").urlsafe_b64encode(det_bytes(n)).decode().rstrip("=")
            S.secrets.token_hex = lambda n: det_bytes(n).hex()
            O._clock = lambda: clock["t"]
            A.uuid.uuid4 = lambda: _uuid.UUID(bytes=det_bytes(16), version=4)
            A.time.time = lambda: clock["t"]
            S.time.time = lambda: clock["t"]
            S.reset_audit_health()
            S.reset_revocation_health()
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            import stewie.server.server as srv
            importlib.reload(srv)
            client = TestClient(srv.app, client=("127.0.0.1", 50000))
            n = {"i": 0}

            def call(method, path, *, headers=None, json_body=None, raw=None):
                n["i"] += 1
                h = dict(headers or {})
                h["X-Correlation-Id"] = f"cid-{n['i']:03d}"
                client.cookies.clear()
                kw = {}
                if json_body is not None:
                    kw["json"] = json_body
                if raw is not None:
                    kw["content"] = raw
                    h.setdefault("Content-Type", "application/json")
                r = client.request(method, path, headers=h, **kw)
                try:
                    body = r.json()
                except ValueError:
                    body = r.text
                steps.append({"request": {"method": method, "path": path, "headers": h, "json": json_body,
                                          "raw": raw}, "clock": clock["t"], "status": r.status_code, "body": body})
                return r

            key = {"X-API-Key": env["STEWIE_API_KEY"]}
            bob = {"Authorization": "Bearer " + call("POST", "/auth/login", json_body={"email": "bob@example.org"},
                                                    headers=key).json()["token"]}
            guest = {"X-Stewie-Anon-Key": "anon-key-xyz"}
            call("GET", "/construction", headers=key)
            call("GET", "/construction", headers=bob)
            call("GET", "/construction", headers=guest)
            call("GET", "/construction")
            pl = lambda n, x, y, p=None: {"name": n, "x": x, "y": y, **({"params": p} if p is not None else {})}
            call("POST", "/siteplan/analyze", headers=guest,
                 json_body={"placements": [pl("landing_pad", 0, 0), pl("habitat_foundation", 60, 0)]})
            call("POST", "/siteplan/analyze", headers=bob,
                 json_body={"placements": [pl("landing_pad", 0, 0), pl("solar_pad", 4, 1), pl("trench", 30, -2)],
                            "min_gap_m": 5})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": [
                pl("landing_pad", 0.0, 0.0), pl("habitat_foundation", 40.0, 25.0),
                pl("blast_berm", -30.0, 10.0, {"length_m": 20.0}), pl("borrow_pit", 15.0, -35.0, {"depth_m": 0.5}),
                pl("crater_fill", 70.0, -20.0, {"radius_m": 5.0}), pl("solar_pad", -60.0, -40.0)]})
            call("POST", "/siteplan/analyze", headers=key,
                 json_body={"placements": [pl("solar_pad", "0", True), pl("borrow_pit", 9.5, 0.0)], "min_gap_m": "0"})
            call("POST", "/siteplan/analyze", headers=key,
                 json_body={"placements": [pl("solar_pad", 0.0, 0.0), pl("borrow_pit", 9.5, 0.0)]})   # 1.65 m < 2 m
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": [pl("moon_base", 0, 0)]})
            call("POST", "/siteplan/analyze", headers=key,
                 json_body={"placements": [pl("landing_pad", 0, 0, {"side_m": 0.0})]})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": []})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": 5})
            call("POST", "/siteplan/analyze", headers=key,
                 json_body={"placements": [{"x": "q", "y": None, "params": [1]}], "min_gap_m": -1})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": [{"name": 5, "x": 1, "y": 2}, 7]})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": [pl("trench", 0, 0)], "min_gap_m": -1})
            call("POST", "/siteplan/analyze", headers=key, json_body={"placements": [pl("trench", 0, 0)] * 501})
            call("POST", "/siteplan/analyze", headers=key, json_body={})
            call("POST", "/siteplan/analyze", json_body={"placements": [pl("trench", 0, 0)]})
            store = json.load(open(os.path.join(d, "operators.json"))) if os.path.exists(os.path.join(d, "operators.json")) else None
            ledger = [json.loads(x) for x in open(os.path.join(d, "events.jsonl"))]
        finally:
            O.os.urandom = patched["urandom"]
            O.secrets.token_urlsafe = patched["token_urlsafe"]
            S.secrets.token_hex = patched["token_hex"]
            O._clock = patched["clock"]
            A.uuid.uuid4 = patched["uuid4"]
            A.time.time = patched["a_time"]
            S.time.time = patched["s_time"]
            for lim in (R._login_ip_limiter, R._login_acct_limiter, R._register_ip_limiter):
                lim.reset()
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            importlib.reload(srv)
    write_fixture(ORACLE_FIXTURES, "http_build_cases", "oracle/build_fixtures.py::http_build_cases (the FastAPI app's "
                  "/construction and /siteplan/analyze through one scripted TestClient session; layouts SYNTHETIC, "
                  "labelled)",
                  ["stewie/server/routers/construction.py", "stewie/server/routers/siteplan.py",
                   "leap/structures.py", "leap/siteplan.py", "lode/planner_acceptance.py"],
                  {"env": env, "seed_sha256_of": "stewie-http-build-oracle", "clock0": 1_800_000_000.0,
                   "client": "127.0.0.1", "steps": steps, "store": store, "ledger": ledger})


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
    worksite_native()
    worksite_refined()
    terrain_memory_cases()
    traffic_memory_cases()
    twin_ops_cases()
    mission_cases()
    world_log_cases()
    twin_store_cases()
    route_cases()
    route_extras()
    balance_cases()
    trips_cases()
    sim_cases()
    sequencing_cases()
    fleet_cases()
    plan_cases()
    plan_ir_cases()
    acceptance_cases()
    replay_cases()
    build_cases()
    record_cases()
    illumination_cases()
    solar_cases()
    flattest_cases()
    auth_cases()
    services_cases()
    http_auth_cases()
    http_admin_cases()
    http_build_cases()


if __name__ == "__main__":
    main()
